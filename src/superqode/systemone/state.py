"""Bounded state sent to a System One evaluation.

The token budget is shared by state and questions. Never dump the repo;
send the tool call, grant, policy, task, and a short diff. Secret-looking
keys and query values are redacted with the same name matcher used for
spawned-shell environments.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..tools.env_policy import is_secret_name

TASK_CHARS = 2000
DIFF_CHARS = 4000
ARG_CHARS = 4000
REDACTED = "[redacted]"

_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]{1,128})=(\"[^\"]*\"|'[^']*'|[^\s&]+)")
_HEADER = re.compile(
    r"(?i)((?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+)[^\s\"']+"
)
_SECRET_FIELD = re.compile(
    r"(?i)([\"']?([\w.-]{0,128}(?:token|secret|password|api[_-]?key)[\w.-]{0,128})[\"']?\s*:\s*)(\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
_SECRET_FLAG = re.compile(
    r"(?i)(--[\w-]*(?:token|secret|password|api-key)[\w-]*\s+)(\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_URL_AUTH = re.compile(r"(https?://)[^/\s:@]+:[^/@\s]+@", re.I)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S
)


def _clip(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _redact_string(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        name, _value = match.group(1), match.group(2)
        if is_secret_name(name):
            return f"{name}={REDACTED}"
        return match.group(0)

    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _HEADER.sub(lambda m: m[1] + REDACTED, text)
    text = _SECRET_FIELD.sub(lambda m: m[1] + REDACTED, text)
    text = _SECRET_FLAG.sub(lambda m: m[1] + REDACTED, text)
    text = _URL_AUTH.sub(lambda m: m[1] + REDACTED + "@", text)
    return _ASSIGNMENT.sub(_replace, text)


def _redact(value: Any, *, key: str = "") -> Any:
    if key and is_secret_name(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key=key) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _cap_arguments(arguments: Any) -> Any:
    blob = json.dumps(arguments, default=str)
    if len(blob) <= ARG_CHARS:
        return arguments
    return {"_truncated": True, "preview": blob[: ARG_CHARS - 1] + "…"}


def prepare_decision_state(state: Any, schema: dict[str, Any] | None = None) -> Any:
    if not isinstance(state, (str, dict, list)):
        raise ValueError("Decision state must be text, an object, or an array")
    if len(json.dumps(state, ensure_ascii=False)) > 32000:
        raise ValueError("Decision state exceeds the 32000-character limit")
    if schema is not None:
        from jsonschema import Draft202012Validator

        error = next(Draft202012Validator(schema).iter_errors(state), None)
        if error is not None:
            # Do not echo input values (which may contain credentials).
            raise ValueError(
                f"Decision state does not satisfy {error.validator} in the pack schema"
            )
    payload = _redact(state)
    if len(json.dumps(payload, ensure_ascii=False)) > 32000:
        raise ValueError("Decision state exceeds the 32000-character limit")
    return payload


class ToolGateState(BaseModel):
    """State for the tool_gate pack. Keep it small and secret-free."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    grant: list[str] = Field(default_factory=list)
    policy: str = ""
    task: str = ""
    last_diff: str | None = None

    def to_payload(self) -> dict[str, Any]:
        arguments = _cap_arguments(_redact(json.loads(json.dumps(self.arguments, default=str))))
        payload: dict[str, Any] = {
            "tool": self.tool,
            "arguments": arguments,
            "grant": list(self.grant),
            "policy": self.policy,
            "task": _clip(_redact_string(self.task), TASK_CHARS),
        }
        if self.last_diff:
            payload["last_diff"] = _clip(_redact_string(self.last_diff), DIFF_CHARS)
        return payload


__all__ = ["ARG_CHARS", "DIFF_CHARS", "REDACTED", "TASK_CHARS", "ToolGateState"]
