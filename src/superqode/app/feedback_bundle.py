"""Allowlisted, bounded diagnostics that can be reviewed before local export."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version
import os
from pathlib import Path
import platform
import re

from superqode import __version__, design_system as ds
from superqode.systemone.state import redact_evidence
from superqode.tools.env_policy import is_secret_name

_TOKEN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_[A-Za-z0-9_]{15,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
_BEARER = re.compile(r"(?i)(\bbearer\s+)[^\s\"',}]+")
_URL = re.compile(r"https?://[^\s<>\"']+")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)", re.S
)
_CONTROL = re.compile(
    r"\x1b(?:\]|P)[^\x07\x1b]*(?:\x07|\x1b\\|$)|\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)


def redact_feedback(value, *, secrets=(), paths=()):
    """Sanitize whole strings before clipping so a cut token cannot escape."""
    from urllib.parse import urlsplit, urlunsplit

    def sanitize(text):
        text = _CONTROL.sub("", text)
        text = _PRIVATE_KEY.sub("[redacted]", text)
        for secret in sorted(set(secrets), key=len, reverse=True):
            if isinstance(secret, str) and len(secret) >= 4:
                text = text.replace(secret, "[redacted]")
        text = _TOKEN.sub("[redacted]", text)
        text = _BEARER.sub(lambda match: match[1] + "[redacted]", text)

        def clean_url(match):
            try:
                parsed = urlsplit(match[0])
                return urlunsplit(
                    (parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")
                )
            except ValueError:
                return "[redacted URL]"

        text = _URL.sub(clean_url, text)
        for path in sorted(set(paths), key=len, reverse=True):
            if path and path not in {"/", "\\"}:
                text = text.replace(path, "[local path]")
        return _CONTROL.sub("", text)

    if isinstance(value, dict):
        return redact_evidence(
            {
                sanitize(str(key)): redact_feedback(item, secrets=secrets, paths=paths)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return [redact_feedback(item, secrets=secrets, paths=paths) for item in value]
    return redact_evidence(sanitize(value)) if isinstance(value, str) else value


def _detection_source() -> str:
    from superqode import theming

    return str(theming.DETECTION_SOURCE)


def feedback_bundle(app, description="", *, include_errors=True, include_route=True) -> dict:
    """No prompts, source files, tool arguments, config dumps or session IDs."""
    secrets = [
        value for key, value in os.environ.items() if is_secret_name(key) and len(value) >= 4
    ]
    paths = [str(Path.home()), str(Path.cwd())]
    kind, provider, model = app._connection_target()
    try:
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.dynamic import resolve_provider_def

        definition = resolve_provider_def(provider) if provider else None
        key = provider_api_key(definition) if definition else None
        if key:
            secrets.append(key)
    except (OSError, ValueError, KeyError):
        pass
    terminal = {
        "term": os.environ.get("TERM", "unknown"),
        "color": os.environ.get("COLORTERM", "unknown"),
        "program": os.environ.get("TERM_PROGRAM", "unknown"),
        "width": app.size.width,
        "height": app.size.height,
        "ssh": bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY")),
        "tmux": bool(os.environ.get("TMUX")),
        "screen": bool(os.environ.get("STY")),
    }
    bundle = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "superqode_version": __version__,
        "textual_version": version("textual"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "terminal": terminal,
        "appearance": {
            "theme": str(app._current_theme),
            "active_theme": ds.get_theme().name,
            "light_or_dark": ds.get_theme().appearance,
            "detection_source": _detection_source(),
            **{key: getattr(app._appearance, key) for key in ("density", "motion", "icons")},
        },
        "description": str(description),
    }
    if include_route:
        pure = getattr(app, "_pure_mode", None)
        session = getattr(pure, "session", None)
        bundle["route"] = {
            "kind": kind,
            "provider": provider,
            "model": model,
            "runtime": str(
                getattr(pure, "runtime_name", "") or getattr(session, "harness_runtime", "")
            ),
            "harness": str(getattr(session, "harness_name", "") or "core"),
        }
    if include_errors:
        from superqode.app.widgets import ConversationLog
        from superqode.app.outcomes import OutcomeSeverity

        errors = []
        for outcome in app._outcome_store().list():
            if outcome.severity == OutcomeSeverity.ERROR:
                errors.append({"source": outcome.source, "message": outcome.summary})
        for message in reversed(
            getattr(app.query_one("#log", ConversationLog), "_diagnostic_errors", [])
        ):
            errors.append({"source": "TUI", "message": message})
        bundle["recent_errors"] = errors[:10]
    bundle = redact_feedback(bundle, secrets=secrets, paths=paths)
    bundle["description"] = bundle["description"][:4000]
    for key in ("term", "color", "program"):
        bundle["terminal"][key] = bundle["terminal"][key][:128]
    for error in bundle.get("recent_errors", []):
        error["message"] = error["message"][:2000]
        error["source"] = error["source"][:128]
    for key, value in bundle.get("route", {}).items():
        bundle["route"][key] = str(value)[:128]
    for section in ("appearance", "platform"):
        for key, value in bundle[section].items():
            bundle[section][key] = str(value)[:193]
    return bundle
