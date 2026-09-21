"""Harness-neutral local and remote Jev Tool Routing clients.

The SDK intentionally accepts tools as JSON-like mappings.  That keeps it
usable with OpenAI Responses/Chat Completions, Anthropic Messages, Codex
app-server dynamic tools, and custom harness schemas without importing any of
their SDKs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

from superqode.systemone.tool_router import (
    ToolRouter,
    ToolRoutingSettings,
    build_tool_router,
)
from superqode.tool_gateway.routing import ToolRequestRouter, TurnPlanCache


@dataclass(frozen=True)
class RoutingResult:
    """A routed catalogue plus privacy-safe decision metadata."""

    tools: tuple[dict[str, Any], ...]
    original_count: int
    selected_count: int
    dropped: tuple[str, ...]
    status: str
    mode: str
    latency_ms: int
    cached: bool = False
    original_schema_bytes: int = 0
    selected_schema_bytes: int = 0

    @property
    def reduction_percent(self) -> float:
        if not self.original_count:
            return 0.0
        return round(
            (self.original_count - self.selected_count) * 100 / self.original_count,
            1,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "tools": list(self.tools),
            "original_count": self.original_count,
            "selected_count": self.selected_count,
            "dropped": list(self.dropped),
            "status": self.status,
            "mode": self.mode,
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "original_schema_bytes": self.original_schema_bytes,
            "selected_schema_bytes": self.selected_schema_bytes,
            "reduction_percent": self.reduction_percent,
        }


class JevToolRouting:
    """In-process Jev router for Python harnesses.

    Construct once per process and pass a stable ``turn_id`` for all model
    steps belonging to the same user turn.  Failures preserve the full tool
    catalogue.
    """

    def __init__(
        self,
        *,
        mode: str = "enforce",
        threshold: float = 0.30,
        timeout_ms: int = 1500,
        turn_ttl: int = 1800,
        router: ToolRouter | None = None,
    ) -> None:
        settings = ToolRoutingSettings(
            mode=mode,
            threshold=threshold,
            timeout_ms=timeout_ms,
        )
        resolved = router or build_tool_router(settings)
        if resolved is None:
            raise RuntimeError("TYPESAFE_API_KEY is required for local Jev Tool Routing")
        self._router = ToolRequestRouter(
            resolved,
            cache=TurnPlanCache(ttl_seconds=turn_ttl),
        )

    async def route(
        self,
        request: str,
        tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
    ) -> RoutingResult:
        catalogue = [_copy_tool(tool) for tool in tools]
        body, event = await self._router.route(
            {
                "input": [{"role": "user", "content": request}],
                "tools": catalogue,
            },
            turn_id=turn_id,
        )
        if event is None:
            return RoutingResult(
                tools=tuple(catalogue),
                original_count=len(catalogue),
                selected_count=len(catalogue),
                dropped=(),
                status="empty" if not catalogue else "unroutable",
                mode=self._router.router.settings.mode,
                latency_ms=0,
            )
        return RoutingResult(
            tools=tuple(body["tools"]),
            original_count=event.original_count,
            selected_count=event.selected_count,
            dropped=event.dropped,
            status=event.status,
            mode=event.mode,
            latency_ms=event.latency_ms,
            cached=event.cached,
            original_schema_bytes=event.original_schema_bytes,
            selected_schema_bytes=event.selected_schema_bytes,
        )

    def route_sync(
        self,
        request: str,
        tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
    ) -> RoutingResult:
        """Synchronous convenience method for non-async harnesses."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.route(request, tools, turn_id=turn_id))
        raise RuntimeError("route_sync cannot run inside an event loop; await route instead")


class JevToolRoutingClient:
    """Async client for a local or Cloud Run Jev Tool Routing service."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout: float = 5.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._http = http

    async def route(
        self,
        request: str,
        tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
        mode: str = "enforce",
        threshold: float = 0.30,
    ) -> RoutingResult:
        owns_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=self.timeout)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = await client.post(
                f"{self.base_url}/v1/route-tools",
                headers=headers,
                json={
                    "request": request,
                    "tools": [_copy_tool(tool) for tool in tools],
                    "turn_id": turn_id,
                    "mode": mode,
                    "threshold": threshold,
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        return RoutingResult(
            tools=tuple(payload["tools"]),
            original_count=int(payload["original_count"]),
            selected_count=int(payload["selected_count"]),
            dropped=tuple(payload.get("dropped", ())),
            status=str(payload["status"]),
            mode=str(payload["mode"]),
            latency_ms=int(payload.get("latency_ms", 0)),
            cached=bool(payload.get("cached", False)),
            original_schema_bytes=int(payload.get("original_schema_bytes", 0)),
            selected_schema_bytes=int(payload.get("selected_schema_bytes", 0)),
        )


def _copy_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(tool, Mapping):
        raise TypeError("each tool must be a mapping")
    return dict(tool)


__all__ = ["JevToolRouting", "JevToolRoutingClient", "RoutingResult"]
