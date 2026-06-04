"""Tool-call parsing for in-process MLX generation.

Local MLX models emit tool calls as *text* (there's no provider that hands us a
structured ``tool_calls`` field). This module turns that text into OpenAI-shaped
tool calls, with a small registry of family-specific parsers:

- ``qwen``   — Qwen / Hermes style ``<tool_call>{json}</tool_call>``
- ``gemma``  — Gemma 4 style (```tool_call / ```json fences, or ``[func(args)]``)
- ``json``   — generic: any ``{"name", "arguments"|"parameters"}`` object / ```json fence

The format is chosen by :func:`resolve_format`, which honours the harness
``model_policy.tool_call_format`` knob (``native`` → family default, ``*-json`` →
the generic JSON parser) and otherwise detects from the model id. This is what
finally makes ``tool_call_format`` do something.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Tuple

ToolCall = Dict[str, Any]

# --- format resolution --------------------------------------------------------

_QWEN_FAMILIES = ("qwen", "hermes", "mistral", "deepseek")
_GEMMA_FAMILIES = ("gemma",)


def resolve_format(model: str, policy_format: str | None = None) -> str:
    """Pick a parser format for ``model``.

    Honours an explicit harness ``tool_call_format`` first:
      * ``strict-json`` / ``compact-json`` / ``json`` -> ``"json"``
      * ``native``                                    -> family default
    Otherwise detects from the model id. Falls back to ``"json"``.
    """
    fmt = (policy_format or "").strip().lower()
    if fmt in ("strict-json", "compact-json", "json"):
        return "json"
    if fmt in ("qwen", "gemma"):
        return fmt
    # native / unset -> detect by family
    m = model.lower()
    if any(f in m for f in _GEMMA_FAMILIES):
        return "gemma"
    if any(f in m for f in _QWEN_FAMILIES):
        return "qwen"
    return "json"


# --- low-level JSON extraction ------------------------------------------------


def _balanced_json_objects(text: str) -> List[str]:
    """Return top-level ``{...}`` substrings, brace-balanced (string-aware)."""
    out: List[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
                    start = -1
    return out


def _as_tool_call(name: str, arguments: Any) -> ToolCall:
    """Build an OpenAI-shaped tool call (arguments serialized to a JSON string)."""
    if isinstance(arguments, (dict, list)):
        args_str = json.dumps(arguments)
    elif arguments is None:
        args_str = "{}"
    else:
        args_str = str(arguments)
    return {
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": name, "arguments": args_str},
    }


def _tool_call_from_obj(obj: Dict[str, Any]) -> ToolCall | None:
    """Map a parsed dict to a tool call if it looks like one."""
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    if isinstance(name, dict):  # {"function": {"name": ..., "arguments": ...}}
        inner = name
        name = inner.get("name")
        args = inner.get("arguments", inner.get("parameters", {}))
    else:
        args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
    if not name or not isinstance(name, str):
        return None
    # arguments may itself be a JSON string
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    return _as_tool_call(name, args)


# --- per-format parsers -------------------------------------------------------

_QWEN_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FENCE = re.compile(r"```(?:tool_call|tool_code|json)?\s*(.*?)```", re.DOTALL)


def _parse_qwen(text: str) -> Tuple[str, List[ToolCall]]:
    calls: List[ToolCall] = []
    for body in _QWEN_BLOCK.findall(text):
        for obj_str in _balanced_json_objects(body) or [body]:
            try:
                tc = _tool_call_from_obj(json.loads(obj_str))
            except Exception:
                tc = None
            if tc:
                calls.append(tc)
    clean = _QWEN_BLOCK.sub("", text).strip()
    if calls:
        return clean, calls
    # Fall back to generic if no <tool_call> blocks matched.
    return _parse_json(text)


def _parse_gemma(text: str) -> Tuple[str, List[ToolCall]]:
    calls: List[ToolCall] = []
    # Gemma 4 commonly emits fenced ```tool_call / ```json blocks.
    for body in _FENCE.findall(text):
        for obj_str in _balanced_json_objects(body):
            try:
                tc = _tool_call_from_obj(json.loads(obj_str))
            except Exception:
                tc = None
            if tc:
                calls.append(tc)
    if calls:
        return _FENCE.sub("", text).strip(), calls
    # Also handle Qwen-style tags and bare JSON as a fallback.
    return _parse_qwen(text)


def _parse_json(text: str) -> Tuple[str, List[ToolCall]]:
    """Generic: any balanced JSON object that looks like a tool call."""
    calls: List[ToolCall] = []
    consumed: List[str] = []
    # Prefer fenced blocks, then bare objects.
    candidates = _FENCE.findall(text)
    candidates.extend(_balanced_json_objects(text))
    for cand in candidates:
        for obj_str in _balanced_json_objects(cand) or [cand]:
            try:
                obj = json.loads(obj_str)
            except Exception:
                continue
            tc = _tool_call_from_obj(obj)
            if tc:
                calls.append(tc)
                consumed.append(obj_str)
    clean = text
    for c in consumed:
        clean = clean.replace(c, "")
    clean = _FENCE.sub("", clean).strip()
    return clean, calls


_PARSERS = {"qwen": _parse_qwen, "gemma": _parse_gemma, "json": _parse_json}


def parse_tool_calls(text: str, fmt: str = "json") -> Tuple[str, List[ToolCall]]:
    """Parse ``text`` into ``(clean_text, tool_calls)`` using format ``fmt``.

    ``tool_calls`` are OpenAI-shaped dicts with a serialized ``arguments`` string.
    ``clean_text`` has the tool-call markup removed (the model's natural-language
    remainder, if any).
    """
    parser = _PARSERS.get(fmt, _parse_json)
    try:
        return parser(text or "")
    except Exception:
        return (text or "").strip(), []


__all__ = ["resolve_format", "parse_tool_calls", "ToolCall"]
