"""Persistent approval memory for HarnessSpec tool gates.

This stores user decisions from ``:approve always`` / ``:reject always`` as
ordinary ``PermissionRuleSpec`` entries so future runs can reuse the same
``permission_request`` policy path as declarative harness rules.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .spec import HarnessSpec, PermissionRuleSpec

_VERSION = 1
_PREFERRED_ARGUMENTS = ("command", "path", "file_path", "url")


def approval_memory_path(spec: HarnessSpec) -> Path:
    """Return the file used for persistent approval decisions for ``spec``."""
    return Path(spec.context.session_storage) / "approval_memory.json"


def load_approval_memory_rules(spec: HarnessSpec) -> tuple[PermissionRuleSpec, ...]:
    """Load remembered allow/deny decisions as permission rules."""
    data = _read_memory(spec)
    rules: list[PermissionRuleSpec] = []
    for item in data.get("rules", []):
        if not isinstance(item, dict):
            continue
        if item.get("harness") not in ("", None, spec.name):
            continue
        action = str(item.get("action") or "").lower()
        if action not in {"allow", "deny"}:
            continue
        rules.append(
            PermissionRuleSpec(
                tool=str(item.get("tool") or "*"),
                argument=str(item.get("argument") or ""),
                pattern=str(item.get("pattern") or "*"),
                action=action,
            )
        )
    return tuple(rules)


def remember_approval_decision(
    spec: HarnessSpec,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    action: str,
) -> PermissionRuleSpec:
    """Persist an always-allow or always-deny decision and return its rule."""
    normalized = action.strip().lower()
    if normalized not in {"allow", "deny"}:
        raise ValueError("Persistent approval decisions must be 'allow' or 'deny'")
    argument, pattern = _rule_target(arguments)
    rule = PermissionRuleSpec(
        tool=tool_name or "*",
        argument=argument,
        pattern=pattern,
        action=normalized,
    )
    data = _read_memory(spec)
    entries = [
        item
        for item in data.get("rules", [])
        if not (
            isinstance(item, dict)
            and item.get("harness") == spec.name
            and item.get("tool") == rule.tool
            and item.get("argument", "") == rule.argument
            and item.get("pattern", "*") == rule.pattern
        )
    ]
    entries.append(
        {
            "harness": spec.name,
            "tool": rule.tool,
            "argument": rule.argument,
            "pattern": rule.pattern,
            "action": rule.action,
            "created_at": time.time(),
            "source": "approval_always",
        }
    )
    _write_memory(spec, {"version": _VERSION, "rules": entries})
    return rule


def _rule_target(arguments: dict[str, Any]) -> tuple[str, str]:
    for key in _PREFERRED_ARGUMENTS:
        value = arguments.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value):
            return key, _glob_literal(str(value))
    return "", "*"


def _glob_literal(value: str) -> str:
    """Escape fnmatch metacharacters so remembered decisions are exact."""
    out = []
    for char in value:
        if char == "[":
            out.append("[[]")
        elif char == "]":
            out.append("[]]")
        elif char == "*":
            out.append("[*]")
        elif char == "?":
            out.append("[?]")
        else:
            out.append(char)
    return "".join(out)


def _read_memory(spec: HarnessSpec) -> dict[str, Any]:
    path = approval_memory_path(spec)
    if not path.exists():
        return {"version": _VERSION, "rules": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _VERSION, "rules": []}
    if not isinstance(data, dict):
        return {"version": _VERSION, "rules": []}
    rules = data.get("rules")
    if not isinstance(rules, list):
        data["rules"] = []
    return data


def _write_memory(spec: HarnessSpec, data: dict[str, Any]) -> None:
    path = approval_memory_path(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


__all__ = [
    "approval_memory_path",
    "load_approval_memory_rules",
    "remember_approval_decision",
]
