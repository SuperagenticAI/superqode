"""Protocol adapters for routing OpenAI-compatible tool request bodies."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from ..providers.gateway.base import ToolDefinition
from ..systemone.tool_router import ToolRouter, TurnToolPlan


@dataclass(frozen=True)
class RoutingEvent:
    """Sanitized routing metadata suitable for local logs and response headers."""

    turn_id: str
    status: str
    mode: str
    original_count: int
    selected_count: int
    original_schema_bytes: int = 0
    selected_schema_bytes: int = 0
    dropped: tuple[str, ...] = ()
    latency_ms: int = 0
    cached: bool = False


class TurnPlanCache:
    """Small TTL/LRU cache that holds one immutable plan across a turn."""

    def __init__(self, *, ttl_seconds: int = 1800, max_entries: int = 512) -> None:
        self.ttl_seconds = max(int(ttl_seconds), 1)
        self.max_entries = max(int(max_entries), 1)
        self._items: OrderedDict[str, tuple[float, TurnToolPlan]] = OrderedDict()

    def get(self, key: str) -> TurnToolPlan | None:
        item = self._items.get(key)
        if item is None:
            return None
        created, plan = item
        if time.monotonic() - created > self.ttl_seconds:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return plan

    def put(self, key: str, plan: TurnToolPlan) -> None:
        self._items[key] = (time.monotonic(), plan)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


class ToolRequestRouter:
    """Filter OpenAI and Anthropic tool arrays without other request mutation."""

    def __init__(self, router: ToolRouter, *, cache: TurnPlanCache | None = None) -> None:
        self.router = router
        self.cache = cache or TurnPlanCache()

    async def route(
        self,
        body: Mapping[str, Any],
        *,
        turn_id: str = "",
    ) -> tuple[dict[str, Any], RoutingEvent | None]:
        output = dict(body)
        raw_tools = body.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools:
            return output, None

        gemini_declarations = _gemini_declarations(raw_tools)
        if gemini_declarations:
            return await self._route_gemini(
                body,
                output,
                raw_tools,
                gemini_declarations,
                turn_id=turn_id,
            )

        definitions, names = _tool_definitions(raw_tools)
        if not definitions:
            return output, None
        request_text = _latest_user_text(body)
        key = turn_id.strip() or _fallback_turn_id(body, request_text, names)
        plan = self.cache.get(key)
        cached = plan is not None
        if plan is None:
            plan = await self.router.plan(request_text, definitions)
            self.cache.put(key, plan)

        allowed = set(plan.effective)
        forced = _forced_tool_names(body)
        allowed.update(forced)
        output["tools"] = [
            raw
            for raw, name in zip(raw_tools, names, strict=True)
            if name is None or name in allowed
        ]
        recommended = set(plan.selected) | forced
        selected_names = {name for name in names if name is not None and name in recommended}
        recommended_tools = [
            raw
            for raw, name in zip(raw_tools, names, strict=True)
            if name is None or name in recommended
        ]
        event = RoutingEvent(
            turn_id=key,
            status=plan.status,
            mode=plan.mode,
            original_count=len(raw_tools),
            # In shadow mode report the recommendation, not the unchanged
            # forwarded list, so developers can measure the prospective win.
            selected_count=len(selected_names) + sum(name is None for name in names),
            original_schema_bytes=_json_size(raw_tools),
            selected_schema_bytes=_json_size(recommended_tools),
            dropped=tuple(name for name in plan.dropped if name not in forced),
            latency_ms=plan.latency_ms,
            cached=cached,
        )
        return output, event

    async def _route_gemini(
        self,
        body: Mapping[str, Any],
        output: dict[str, Any],
        raw_tools: list[Any],
        declarations: list[Mapping[str, Any]],
        *,
        turn_id: str,
    ) -> tuple[dict[str, Any], RoutingEvent | None]:
        definitions, names = _tool_definitions(declarations)
        if not definitions:
            return output, None
        request_text = _latest_user_text(body)
        key = turn_id.strip() or _fallback_turn_id(body, request_text, names)
        plan = self.cache.get(key)
        cached = plan is not None
        if plan is None:
            plan = await self.router.plan(request_text, definitions)
            self.cache.put(key, plan)

        forced = _forced_tool_names(body)
        effective = set(plan.effective) | forced
        recommended = set(plan.selected) | forced
        output["tools"] = _filter_gemini_tools(raw_tools, effective)
        recommended_tools = _filter_gemini_tools(raw_tools, recommended)
        event = RoutingEvent(
            turn_id=key,
            status=plan.status,
            mode=plan.mode,
            original_count=len(declarations),
            selected_count=sum(name in recommended for name in names if name is not None),
            original_schema_bytes=_json_size(raw_tools),
            selected_schema_bytes=_json_size(recommended_tools),
            dropped=tuple(name for name in plan.dropped if name not in forced),
            latency_ms=plan.latency_ms,
            cached=cached,
        )
        return output, event


def _tool_definitions(
    raw_tools: Sequence[Any],
) -> tuple[list[ToolDefinition], list[str | None]]:
    definitions: list[ToolDefinition] = []
    names: list[str | None] = []
    for raw in raw_tools:
        name, description, parameters = _tool_parts(raw)
        names.append(name)
        if name is not None:
            definitions.append(
                ToolDefinition(name=name, description=description, parameters=parameters)
            )
    return definitions, names


def _tool_parts(raw: Any) -> tuple[str | None, str, dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None, "", {}
    function = raw.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        return (
            str(name) if name else None,
            str(function.get("description") or ""),
            dict(function.get("parameters") or {}),
        )
    # Responses API function tools are flat. Provider-hosted tools such as
    # web_search have only a type; use that type as their stable catalogue id.
    name = raw.get("name") or raw.get("type")
    return (
        str(name) if name else None,
        str(raw.get("description") or ""),
        dict(raw.get("parameters") or raw.get("input_schema") or {}),
    )


def _gemini_declarations(raw_tools: Sequence[Any]) -> list[Mapping[str, Any]]:
    declarations: list[Mapping[str, Any]] = []
    for group in raw_tools:
        if not isinstance(group, Mapping):
            continue
        raw = group.get("functionDeclarations")
        if raw is None:
            raw = group.get("function_declarations")
        if not isinstance(raw, list):
            continue
        declarations.extend(item for item in raw if isinstance(item, Mapping))
    return declarations


def _filter_gemini_tools(raw_tools: Sequence[Any], allowed: set[str]) -> list[Any]:
    filtered: list[Any] = []
    for group in raw_tools:
        if not isinstance(group, Mapping):
            filtered.append(group)
            continue
        declaration_key = next(
            (key for key in ("functionDeclarations", "function_declarations") if key in group),
            None,
        )
        if declaration_key is None or not isinstance(group[declaration_key], list):
            # Provider-hosted tools such as googleSearch are not function
            # declarations and remain available rather than being guessed at.
            filtered.append(group)
            continue
        kept = [
            declaration
            for declaration in group[declaration_key]
            if not isinstance(declaration, Mapping) or str(declaration.get("name") or "") in allowed
        ]
        if kept:
            clone = dict(group)
            clone[declaration_key] = kept
            filtered.append(clone)
    return filtered


def _latest_user_text(body: Mapping[str, Any]) -> str:
    candidates = body.get("messages")
    if not isinstance(candidates, list):
        candidates = body.get("input")
    if not isinstance(candidates, list):
        candidates = body.get("contents")
    if isinstance(candidates, str):
        return candidates
    if not isinstance(candidates, list):
        return ""
    for item in reversed(candidates):
        if isinstance(item, Mapping) and item.get("role") == "user":
            text = _content_text(item.get("content") or item.get("parts"))
            if text:
                return text
    return ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type not in {None, "text", "input_text"}:
            continue
        value = item.get("text") or item.get("content")
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _forced_tool_names(body: Mapping[str, Any]) -> set[str]:
    choice = body.get("tool_choice")
    if isinstance(choice, Mapping):
        # Anthropic: {"type": "tool", "name": "..."}
        name = choice.get("name")
        if name:
            return {str(name)}
        # OpenAI Chat Completions: {"type": "function", "function": {"name": "..."}}
        function = choice.get("function")
        if isinstance(function, Mapping) and function.get("name"):
            return {str(function["name"])}
    tool_config = body.get("toolConfig") or body.get("tool_config")
    if isinstance(tool_config, Mapping):
        calling = tool_config.get("functionCallingConfig") or tool_config.get(
            "function_calling_config"
        )
        if isinstance(calling, Mapping):
            allowed = calling.get("allowedFunctionNames") or calling.get("allowed_function_names")
            if isinstance(allowed, list):
                return {str(item) for item in allowed}
    return set()


def _fallback_turn_id(
    body: Mapping[str, Any], request_text: str, names: Sequence[str | None]
) -> str:
    identity: MutableMapping[str, Any] = {
        "model": body.get("model"),
        # If a client sends only tool outputs and no stable turn header, use
        # the changing input rather than accidentally sharing a plan across
        # unrelated turns. Exact multi-step stability requires the header or
        # a request that retains its latest user message.
        "request": request_text or body.get("input") or body.get("messages"),
        "tools": list(names),
    }
    for key in ("conversation_id", "session_id", "prompt_cache_key"):
        if body.get(key):
            identity[key] = body[key]
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "auto-" + hashlib.sha256(encoded).hexdigest()[:24]


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str).encode())


# Backward-compatible name from the initial OpenAI-only gateway slice.
OpenAIToolRequestRouter = ToolRequestRouter


__all__ = [
    "OpenAIToolRequestRouter",
    "RoutingEvent",
    "ToolRequestRouter",
    "TurnPlanCache",
]
