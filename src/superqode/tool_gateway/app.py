"""ASGI reverse proxy for local, protocol-level tool routing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx

from .routing import RoutingEvent, ToolRequestRouter

_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_ROUTED_PATHS = {
    "/chat/completions",
    "/messages",
    "/responses",
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/responses",
}


def _is_routed_path(path: str) -> bool:
    if path in _ROUTED_PATHS:
        return True
    if not path.startswith(("/v1/models/", "/v1beta/models/")):
        return False
    return path.endswith(":generateContent") or path.endswith(":streamGenerateContent")


def _catalogue_count(raw_tools: Any) -> int:
    if not isinstance(raw_tools, list):
        return 0
    count = 0
    for group in raw_tools:
        if isinstance(group, dict):
            declarations = group.get("functionDeclarations") or group.get("function_declarations")
            if isinstance(declarations, list):
                count += len(declarations)
                continue
        count += 1
    return count


@dataclass(frozen=True)
class GatewayConfig:
    upstream: str
    upstream_api_key: str = ""
    upstream_api_key_header: str = "auto"
    timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("upstream must be an absolute http(s) URL")
        if self.upstream_api_key_header not in {
            "auto",
            "authorization",
            "x-api-key",
            "x-goog-api-key",
        }:
            raise ValueError(
                "upstream_api_key_header must be auto, authorization, x-api-key, or x-goog-api-key"
            )


@dataclass
class GatewayMetrics:
    """Non-sensitive, in-memory routing totals for the current process."""

    model_requests: int = 0
    catalogue_requests: int = 0
    tool_entries_received: int = 0
    unroutable_catalogues: int = 0
    routed_requests: int = 0
    original_tools: int = 0
    selected_tools: int = 0
    original_schema_bytes: int = 0
    selected_schema_bytes: int = 0
    cache_hits: int = 0
    fail_open_errors: int = 0
    decision_latency_ms: int = 0
    last_request_shape: dict[str, Any] | None = None

    def record(self, event: RoutingEvent) -> None:
        self.routed_requests += 1
        self.original_tools += event.original_count
        self.selected_tools += event.selected_count
        self.original_schema_bytes += event.original_schema_bytes
        self.selected_schema_bytes += event.selected_schema_bytes
        self.cache_hits += int(event.cached)
        self.decision_latency_ms += event.latency_ms

    def as_dict(self) -> dict[str, Any]:
        saved = max(self.original_tools - self.selected_tools, 0)
        percent = round(saved * 100 / self.original_tools, 1) if self.original_tools else 0.0
        schema_saved = max(self.original_schema_bytes - self.selected_schema_bytes, 0)
        schema_percent = (
            round(schema_saved * 100 / self.original_schema_bytes, 1)
            if self.original_schema_bytes
            else 0.0
        )
        return {
            "model_requests": self.model_requests,
            "catalogue_requests": self.catalogue_requests,
            "tool_entries_received": self.tool_entries_received,
            "unroutable_catalogues": self.unroutable_catalogues,
            "routed_requests": self.routed_requests,
            "original_tools": self.original_tools,
            "selected_tools": self.selected_tools,
            "tool_entries_avoided": saved,
            "tool_entry_reduction_percent": percent,
            "original_schema_bytes": self.original_schema_bytes,
            "selected_schema_bytes": self.selected_schema_bytes,
            "schema_bytes_avoided": schema_saved,
            "schema_byte_reduction_percent": schema_percent,
            "cache_hits": self.cache_hits,
            "fail_open_errors": self.fail_open_errors,
            "decision_latency_ms": self.decision_latency_ms,
            "last_request_shape": self.last_request_shape,
        }


def create_tool_gateway_app(
    config: GatewayConfig,
    request_router: ToolRequestRouter | None,
    *,
    http: httpx.AsyncClient | None = None,
):
    """Create the local proxy app; injection keeps all tests offline."""
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, StreamingResponse
        from starlette.routing import Route
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise RuntimeError("Tool gateway dependencies are missing; reinstall superqode.") from exc

    owns_http = http is None
    client = http or httpx.AsyncClient(timeout=config.timeout_seconds)
    metrics = GatewayMetrics()

    @asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        yield
        if owns_http:
            await client.aclose()

    async def healthz(_request: Request):
        return JSONResponse({"status": "ok", "routing": request_router is not None})

    async def status(_request: Request):
        return JSONResponse(metrics.as_dict())

    async def proxy(request: Request):
        incoming_path = "/" + request.path_params["path"]
        body = await request.body()
        body_rewritten = False
        event: RoutingEvent | None = None
        if request.method == "POST" and _is_routed_path(incoming_path) and request_router:
            metrics.model_requests += 1
            try:
                payload = await request.json()
            except ValueError:
                return JSONResponse({"error": "request body must be JSON"}, status_code=400)
            if not isinstance(payload, dict):
                return JSONResponse(
                    {"error": "request body must be a JSON object"}, status_code=400
                )
            original_payload = payload
            raw_tools = payload.get("tools")
            metrics.last_request_shape = {
                "path": incoming_path,
                "top_level_keys": sorted(str(key) for key in payload),
                "tools_container": type(raw_tools).__name__,
                "tool_count": _catalogue_count(raw_tools),
            }
            if isinstance(raw_tools, list) and raw_tools:
                metrics.catalogue_requests += 1
                metrics.tool_entries_received += _catalogue_count(raw_tools)
            try:
                payload, event = await request_router.route(
                    payload,
                    turn_id=request.headers.get("x-superqode-turn-id", ""),
                )
            except Exception:
                # Optimization must never make the underlying model endpoint
                # less available. The unmodified catalogue is the safe path.
                payload = original_payload
                metrics.fail_open_errors += 1
            if isinstance(raw_tools, list) and raw_tools and event is None:
                metrics.unroutable_catalogues += 1
            import json

            body = json.dumps(payload, separators=(",", ":")).encode()
            body_rewritten = True

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_HEADERS and key.lower() != "x-superqode-turn-id"
        }
        if body_rewritten:
            headers.pop("content-encoding", None)
        if config.upstream_api_key:
            headers.pop("authorization", None)
            headers.pop("x-api-key", None)
            headers.pop("x-goog-api-key", None)
            key_header = _api_key_header(config)
            headers[key_header] = (
                f"Bearer {config.upstream_api_key}"
                if key_header == "authorization"
                else config.upstream_api_key
            )
        upstream_request = client.build_request(
            request.method,
            _upstream_url(config.upstream, incoming_path, request.url.query),
            headers=headers,
            content=body,
        )
        try:
            response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            return JSONResponse({"error": "upstream connection failed"}, status_code=502)

        response_headers = {
            key: value for key, value in response.headers.items() if key.lower() not in _HOP_HEADERS
        }
        if event is not None:
            metrics.record(event)
            response_headers.update(_event_headers(event))
            logging.getLogger("uvicorn.error").info(
                "JEV tools %d->%d (%s, %s, %dms)",
                event.original_count,
                event.selected_count,
                event.mode,
                "cache hit" if event.cached else event.status,
                event.latency_ms,
            )

        async def content() -> AsyncIterator[bytes]:
            try:
                # Preserve the upstream Content-Encoding and its raw bytes;
                # downstream SDKs perform their normal decoding.
                if response.is_stream_consumed:
                    # MockTransport and already-buffered error responses have
                    # no live raw stream left, but their content is complete.
                    yield response.content
                else:
                    async for chunk in response.aiter_raw():
                        yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            content(),
            status_code=response.status_code,
            headers=response_headers,
            media_type=None,
        )

    async def proxy_route(request: Request):
        return await proxy(request)

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/superqode/status", status, methods=["GET"]),
            Route(
                "/{path:path}",
                proxy_route,
                methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            ),
        ],
        lifespan=lifespan,
    )


def _upstream_url(upstream: str, path: str, query: str) -> str:
    base = upstream.rstrip("/")
    if (
        base.endswith("/v1")
        or base.endswith("/backend-api/codex")
        or base.endswith("/v1beta/openai")
    ) and path.startswith("/v1/"):
        path = path[3:]
    url = base + path
    return f"{url}?{query}" if query else url


def _api_key_header(config: GatewayConfig) -> str:
    if config.upstream_api_key_header != "auto":
        return config.upstream_api_key_header
    hostname = (urlsplit(config.upstream).hostname or "").lower()
    if hostname == "generativelanguage.googleapis.com":
        return "x-goog-api-key"
    return "x-api-key" if hostname == "api.anthropic.com" else "authorization"


def _event_headers(event: RoutingEvent) -> dict[str, str]:
    return {
        "x-superqode-routing": event.status,
        "x-superqode-routing-mode": event.mode,
        "x-superqode-tools": f"{event.original_count}->{event.selected_count}",
        "x-superqode-schema-bytes": (
            f"{event.original_schema_bytes}->{event.selected_schema_bytes}"
        ),
        "x-superqode-routing-cache": "hit" if event.cached else "miss",
        "x-superqode-routing-ms": str(event.latency_ms),
    }


__all__ = ["GatewayConfig", "GatewayMetrics", "create_tool_gateway_app"]
