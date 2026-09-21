"""HTTP and MCP service surfaces for Jev Tool Routing."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any, Mapping, Sequence

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from superqode.systemone.live import LiveSystemOneClient
from superqode.systemone.tool_router import (
    SystemOneToolDecisionProvider,
    ToolRouter,
    ToolRoutingSettings,
)

from .sdk import JevToolRouting, RoutingResult

MAX_TOOLS = 256
MAX_REQUEST_CHARS = 100_000
MAX_BODY_BYTES = 2 * 1024 * 1024


class RoutingCoordinator:
    """Share one Jev client and turn caches across HTTP and MCP transports."""

    def __init__(self, *, api_key: str | None = None, timeout_ms: int = 1500) -> None:
        key = (api_key if api_key is not None else os.getenv("TYPESAFE_API_KEY", "")).strip()
        if not key:
            raise RuntimeError("TYPESAFE_API_KEY is required")
        self.timeout_ms = max(int(timeout_ms), 1)
        self._provider = SystemOneToolDecisionProvider(
            LiveSystemOneClient(api_key=key, timeout_ms=self.timeout_ms)
        )
        self._routers: dict[tuple[str, float], JevToolRouting] = {}

    async def route(
        self,
        request: str,
        tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
        mode: str = "enforce",
        threshold: float = 0.30,
    ) -> RoutingResult:
        _validate_route_input(request, tools, mode, threshold)
        key = (mode, round(float(threshold), 6))
        router = self._routers.get(key)
        if router is None:
            core = ToolRouter(
                self._provider,
                ToolRoutingSettings(
                    mode=mode,
                    threshold=threshold,
                    timeout_ms=self.timeout_ms,
                ),
            )
            router = JevToolRouting(router=core)
            self._routers[key] = router
        return await router.route(request, tools, turn_id=turn_id)


class BearerTokenMiddleware:
    """Require an application bearer token while leaving health checks open."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or ())
        supplied = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {self.token}"
        if not self.token or not secrets.compare_digest(supplied, expected):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_jev_service_app(
    *,
    coordinator: RoutingCoordinator | None = None,
    token: str | None = None,
) -> Starlette:
    """Create a stateless HTTP API with a Streamable HTTP MCP endpoint."""
    shared = coordinator or RoutingCoordinator()
    service_token = (
        token if token is not None else os.getenv("SUPERQODE_JEV_SERVICE_TOKEN", "")
    ).strip()

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "superqode-jev-tool-routing"})

    async def route_tools(request: Request) -> Response:
        content_length = int(request.headers.get("content-length") or 0)
        if content_length > MAX_BODY_BYTES:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
            prompt = str(payload.get("request") or "")
            tools = payload.get("tools") or ()
            mode = str(payload.get("mode") or "enforce")
            threshold = float(payload.get("threshold", 0.30))
            _validate_route_input(prompt, tools, mode, threshold)
            result = await shared.route(
                prompt,
                tools,
                turn_id=str(payload.get("turn_id") or ""),
                mode=mode,
                threshold=threshold,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(result.as_dict())

    from superqode.mcp.jev_router_server import build_jev_mcp_server

    mcp_server = build_jev_mcp_server(shared)
    mcp_app = mcp_server.http_app(path="/mcp", stateless_http=True, json_response=True)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    routes = [
        Route("/healthz", health, methods=["GET"]),
        Route("/v1/route-tools", route_tools, methods=["POST"]),
        *mcp_app.routes,
    ]
    middleware = [Middleware(BearerTokenMiddleware, token=service_token)] if service_token else []
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


def _validate_route_input(
    request: str,
    tools: Sequence[Mapping[str, Any]],
    mode: str,
    threshold: float,
) -> None:
    if not request.strip():
        raise ValueError("request is required")
    if len(request) > MAX_REQUEST_CHARS:
        raise ValueError("request is too large")
    if mode not in {"shadow", "enforce"}:
        raise ValueError("mode must be shadow or enforce")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise TypeError("tools must be an array")
    if len(tools) > MAX_TOOLS:
        raise ValueError(f"at most {MAX_TOOLS} tools are allowed")
    if any(not isinstance(tool, Mapping) for tool in tools):
        raise TypeError("each tool must be an object")
    if len(json.dumps(tools, separators=(",", ":"), default=str).encode()) > MAX_BODY_BYTES:
        raise ValueError("tool catalogue is too large")


__all__ = [
    "BearerTokenMiddleware",
    "RoutingCoordinator",
    "create_jev_service_app",
]
