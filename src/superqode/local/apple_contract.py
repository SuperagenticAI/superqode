"""Validate Apple's deliberately bounded text/schema/tool protocol before IPC.

The native helper only proposes calls. All effects go through the normal host
tool executor and its permissions. Unsupported schemas fail rather than losing
constraints silently; the original schema also validates completed output.
"""

from dataclasses import asdict
import json
import math
import re

from jsonschema import Draft202012Validator, ValidationError


def schema(value, depth=0):
    if not isinstance(value, dict) or depth > 8:
        raise ValueError("Apple schemas must be objects nested at most eight levels")
    allowed = {
        "type",
        "description",
        "title",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
    }
    if set(value) - allowed or value.get("type") not in {
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
    }:
        raise ValueError(
            "Apple guided generation supports simple object, array and scalar schemas; references, unions and other schema keywords need another model"
        )
    Draft202012Validator.check_schema(value)
    if "enum" in value and (
        value["type"] != "string"
        or not value["enum"]
        or not all(isinstance(v, str) for v in value["enum"])
    ):
        raise ValueError("Apple guided generation supports nonempty string enums")
    if value["type"] == "object":
        properties = value.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 32:
            raise ValueError("Use at most 32 properties per Apple object schema")
        if set(value.get("required", [])) - set(properties):
            raise ValueError("Apple schema required fields must have property definitions")
        if value.get("additionalProperties") not in (None, False):
            raise ValueError("Apple guided generation needs explicitly named properties")
        for child in properties.values():
            schema(child, depth + 1)
    elif value["type"] == "array":
        schema(value.get("items"), depth + 1)
    return value


def normalized_temperature(value):
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("Apple temperature must be a finite number")
    return min(1.0, max(0.0, value))


def request(messages, tools, max_tokens, temperature, response_format):
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
        raise ValueError("Apple output limit must be a positive integer")
    normalized_temperature(temperature)
    definitions = [asdict(t) for t in tools or []]
    if len(definitions) > 5 or len({t["name"] for t in definitions}) != len(definitions):
        raise ValueError(
            "Use at most five distinct Apple tools; select the Apple on-device configuration for three file tools"
        )
    for tool in definitions:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", tool["name"]):
            raise ValueError("Apple tool names must be short function identifiers")
        schema(tool["parameters"])
        if tool["parameters"]["type"] != "object":
            raise ValueError("Apple tool arguments must have an object schema")
    output_schema = None
    if response_format not in (None, {"type": "text"}):
        if not isinstance(response_format, dict) or response_format.get("type") != "json_schema":
            raise ValueError(
                "Apple structured output needs response_format=json_schema with an explicit simple schema"
            )
        output_schema = schema((response_format.get("json_schema") or {}).get("schema"))
        if definitions:
            raise ValueError(
                "Use separate Apple requests for tool calling and structured final output"
            )
    raw, pending, seen = [], {}, set()
    for message in messages:
        row = {
            k: v for k, v in asdict(message).items() if v is not None and k != "reasoning_content"
        }
        if row.get("role") not in {
            "system",
            "developer",
            "user",
            "assistant",
            "tool",
        } or not isinstance(row.get("content", ""), str):
            raise ValueError("Apple on-device accepts text conversations without images")
        row.setdefault("content", "")
        calls = row.get("tool_calls") or []
        if calls and row["role"] != "assistant":
            raise ValueError("Only assistant messages can request Apple tools")
        if pending and row["role"] != "tool":
            raise ValueError("Complete the pending Apple tool results before continuing")
        for call in calls:
            identity = call.get("id")
            function = call.get("function", {})
            if (
                not isinstance(identity, str)
                or not identity
                or identity in seen
                or not isinstance(function.get("name"), str)
            ):
                raise ValueError("Apple tool calls need distinct IDs and function names")
            arguments = function.get("arguments", {})
            if not isinstance(
                json.loads(arguments) if isinstance(arguments, str) else arguments, dict
            ):
                raise ValueError("Apple tool arguments must be JSON objects")
            seen.add(identity)
            pending[identity] = function["name"]
        if row["role"] == "tool":
            identity = row.get("tool_call_id")
            if identity not in pending:
                raise ValueError("Apple tool result has no matching pending call")
            row["name"] = pending.pop(identity)
        raw.append(row)
    if pending or not raw or raw[-1]["role"] not in {"user", "tool"}:
        raise ValueError("Apple requests must end with a user message or completed tool results")
    return raw, definitions, output_schema


def tool_calls(calls, definitions):
    by_name = {t["name"]: t for t in definitions}
    if not isinstance(calls, list) or not 1 <= len(calls) <= 5:
        raise ValueError("Invalid Apple tool handoff")
    seen = set()
    for call in calls:
        function = call.get("function", {})
        name, identity = function.get("name"), call.get("id")
        if name not in by_name or not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError("Apple requested an unknown tool or duplicate call")
        seen.add(identity)
        arguments = function.get("arguments")
        value = json.loads(arguments) if isinstance(arguments, str) else arguments
        try:
            Draft202012Validator(by_name[name]["parameters"]).validate(value)
        except ValidationError:
            raise ValueError(
                "Apple produced invalid arguments for " + name + "; no tool was executed"
            ) from None
        call["type"] = "function"
        function["arguments"] = json.dumps(value, ensure_ascii=False)
    return calls
