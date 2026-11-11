"""Bounded, schema-checked local tool repair and the small-model lean profile."""

import copy
import json
import re
import uuid
from dataclasses import dataclass

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .tool_args import parse_tool_arguments

LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "lm_studio", "local-openai"})
# Scoped harness registries use read/write/edit; only registered tools are exposed.
LEAN_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "read",
        "write",
        "edit",
        "bash",
        "glob",
        "grep",
        "shell_session",
        "request_permissions",
        "get_context_remaining",
        "read_context_chunk",
        "run_test",
        "submit_json",
    }
)
LEAN_INSTRUCTIONS = (
    "Work in small steps. Use only the listed tools with JSON object arguments. "
    "Read before editing, check the result, and never claim an unrun test passed."
)
_ALIASES = (
    frozenset({"path", "file_path", "filename", "file"}),
    frozenset({"command", "cmd", "shell_command"}),
    frozenset({"content", "text", "file_content"}),
    frozenset({"old_text", "old_string", "search"}),
    frozenset({"new_text", "new_string", "replacement"}),
)


def lean_profile(provider, model, context):
    if (provider or "").lower() not in LOCAL_PROVIDERS:
        return False
    from superqode.local.context_contract import LM_STARTERS, STARTERS

    canonical = LM_STARTERS.get(model, model)
    size = STARTERS.get(canonical, (None,))[0]
    if size is None:
        match = re.search(r"(?:^|[^\d.])(\d+(?:\.\d+)?)b(?:[^a-z]|$)", model.lower())
        size = float(match.group(1)) if match else None
    return bool((size is not None and size <= 9) or (0 < context <= 8192))


def compact_schema(schema):
    """Shorten schema prose only, never const/default/enum instance data."""
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    result = copy.deepcopy(schema)
    if isinstance(result.get("description"), str):
        result["description"] = result["description"].split("\n")[0][:96]
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        if isinstance(result.get(key), dict):
            result[key] = {name: compact_schema(value) for name, value in result[key].items()}
    for key in (
        "items",
        "additionalProperties",
        "additionalItems",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
    ):
        if key in result:
            result[key] = (
                [compact_schema(value) for value in result[key]]
                if isinstance(result[key], list)
                else compact_schema(result[key])
            )
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(result.get(key), list):
            result[key] = [compact_schema(value) for value in result[key]]
    return result


def repair_arguments(raw, schema):
    """No guessing of values, coercion, dropped keys or ambiguous renaming."""
    args, error = parse_tool_arguments(raw)
    repaired = False
    if error:
        return args, error, repaired
    if isinstance(raw, str):
        try:
            repaired = json.loads(raw) != args
        except ValueError:
            repaired = True
    try:
        json.dumps(args, allow_nan=False)
    except (TypeError, ValueError):
        return {}, "Tool arguments must contain only finite JSON values.", repaired
    if not isinstance(schema, dict):
        return args, "Tool schema is not a JSON object.", repaired
    properties = schema.get("properties", {})
    args = dict(args)
    for key in list(args):
        if key in properties:
            continue
        matches = {
            target for group in _ALIASES if key in group for target in properties if target in group
        }
        if len(matches) == 1:
            target = matches.pop()
            if target in args:
                return args, "Conflicting argument names; use the tool schema exactly.", repaired
            args[target] = args.pop(key)
            repaired = True
        elif schema.get("additionalProperties") is not True and not isinstance(
            schema.get("additionalProperties"), dict
        ):
            return args, f"Unknown or ambiguous argument '{key}'; use the listed schema.", repaired
    try:
        error = next(Draft202012Validator(schema, registry=Registry()).iter_errors(args), None)
    except (TypeError, ValueError, RecursionError, SchemaError, Unresolvable):
        return args, "Tool schema could not validate these arguments.", repaired
    if error is not None:
        return args, str(error.message)[:180], repaired
    return args, None, repaired


def _whole_object(text):
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index == len(text) - 1
    return False


def extract_local_calls(content):
    """Accept explicit blocks or a whole-response call, never examples in prose.

    Malformed explicit blocks stay invalid so they receive corrective feedback;
    they must not silently become an empty-argument executable call.
    """
    content = content or ""
    blocks = list(re.finditer(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL))
    payloads = [match.group(1) for match in blocks]
    if not payloads:
        text = content.strip()
        if not (text.startswith("{") or text.startswith("```")):
            return content, []
        # Strip a whole fence, but refuse a partial JSON object in prose.
        if text.startswith("```"):
            match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if not match:
                return content, []
            text = match.group(1).strip()
        if not (text.startswith("{") and text.endswith("}") and _whole_object(text)):
            return content, []
        payload, error = parse_tool_arguments(text)
        if error or not isinstance(payload, dict):
            return content, []
        envelope = payload.get("function", payload)
        if not isinstance(envelope, dict) or not ("name" in envelope or "tool" in envelope):
            return content, []
        if not ("arguments" in envelope or "parameters" in envelope):
            return content, []
        payloads = [text]
    calls = []
    for text in payloads:
        payload, error = parse_tool_arguments(text)
        envelope = payload.get("function", payload) if not error else {}
        if not isinstance(envelope, dict):
            envelope = {}
        name = envelope.get("name", envelope.get("tool", ""))
        arguments = envelope.get("arguments", envelope.get("parameters", text))
        calls.append(
            {
                "id": "local-" + uuid.uuid4().hex[:12],
                "type": "function",
                "function": {
                    "name": name if isinstance(name, str) else "",
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                },
            }
        )
    cleaned = (
        re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
        if blocks
        else ""
    )
    return cleaned, calls


@dataclass
class ToolRetryBudget:
    """Two corrective sends in total per user run, not two per tool or iteration."""

    used: int = 0

    def correction(self):
        if self.used >= 2:
            return False
        self.used += 1
        return True
