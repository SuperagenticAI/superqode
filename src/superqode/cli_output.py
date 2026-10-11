"""Machine output and safe diagnostics for non-interactive invocations."""

from __future__ import annotations

import io
import json
import os
import time
from contextvars import ContextVar
from typing import Callable

machine_events = ContextVar("superqode_machine_events", default=None)


def sanitize_diagnostic(value):
    from superqode.app.feedback_bundle import redact_feedback
    from superqode.tools.env_policy import is_secret_name

    secrets = [value for key, value in os.environ.items() if is_secret_name(key)]
    # Stored credentials can be opaque strings that do not match token regexes.
    # Resolve them only for redaction; they never enter an output payload.
    try:
        from superqode.auth import all as stored_credentials

        for credential in stored_credentials().values():
            secrets.extend(
                str(getattr(credential, name, ""))
                for name in ("key", "token", "access", "refresh")
                if getattr(credential, name, "")
            )
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return redact_feedback(value, secrets=secrets)


def public_error(error: Exception | str, *, usage: bool = False) -> dict:
    """Keep SDK payloads out of the public error contract."""
    if usage:
        return {"error_code": "invalid_request", "error": sanitize_diagnostic(str(error))}
    from superqode.runtime.errors import (
        HeadlessSetupError,
        RuntimeNotInstalledError,
        RuntimeNotImplementedError,
        RuntimePolicyError,
        UnknownRuntimeError,
    )

    if isinstance(error, (HeadlessSetupError, UnknownRuntimeError)):
        return {"error_code": "invalid_request", "error": sanitize_diagnostic(str(error))}
    if isinstance(error, (RuntimeNotInstalledError, RuntimeNotImplementedError)):
        return {"error_code": "runtime_unavailable", "error": sanitize_diagnostic(str(error))}
    if isinstance(error, RuntimePolicyError):
        return {"error_code": "policy_unsupported", "error": sanitize_diagnostic(str(error))}
    from superqode.providers.connection_diagnostics import failure_message

    code, message = failure_message(error if isinstance(error, Exception) else Exception())
    if code == "error":
        text = str(error).lower()
        if any(
            word in text for word in ("authentication", "unauthorized", "api key", "api_key", "401")
        ):
            code, message = (
                "auth_error",
                "Authentication failed. Check your credential with superqode auth check.",
            )
        elif any(word in text for word in ("rate limit", "quota", "429")):
            code, message = (
                "rate_limited",
                "The account is rate limited or out of quota. Retry later or check your plan.",
            )
        elif "timeout" in text or "timed out" in text:
            code, message = "timeout", "The request timed out. Check the connection and retry."
        else:
            message = "The request failed. Run superqode doctor and check the selected provider, model, and harness."
    return {"error_code": code, "error": message}


class DiagnosticStream(io.TextIOBase):
    """Redact complete diagnostic lines, including writes split across chunks."""

    def __init__(self, destination, log=None):
        self.destination = destination
        self.log = log
        self.pending = ""

    def write(self, value):
        self.pending += str(value)
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self._emit(line + "\n")
        return len(value)

    def _emit(self, value):
        safe = sanitize_diagnostic(value)
        import logging

        logging.getLogger("superqode.headless").debug(safe.rstrip())
        self.destination.write(safe)
        self.destination.flush()
        if self.log:
            self.log.write(safe)
            self.log.flush()

    def flush(self):
        if self.pending:
            self._emit(self.pending)
            self.pending = ""


class EventWriter:
    """One flushed JSON object per line, with monotonically ordered events."""

    def __init__(self, output, *, clock: Callable = time.time):
        self.output = output
        self.sequence = 0
        self.clock = clock

    def __call__(self, event_type, data=None):
        self.sequence += 1
        payload = {
            "type": f"superqode.{event_type}",
            "sequence": self.sequence,
            "timestamp": self.clock(),
            **(data or {}),
        }
        self.output.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.output.flush()
