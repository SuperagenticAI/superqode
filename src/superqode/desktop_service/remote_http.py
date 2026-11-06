"""Loopback-only HTTP adapter for private Tailscale Serve. No public bind option."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
import json
import socket
import threading
import time
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

MAX_BODY = 160 * 1024
MAX_RESPONSE = 8 * 1024 * 1024


def application(access):
    buckets = defaultdict(deque)
    gate = asyncio.Semaphore(8)

    async def endpoint(request: Request):
        origin = access.config.get("private_url", "")
        host = urlsplit(origin).netloc
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        }

        def response(value, status=200):
            return JSONResponse(value, status_code=status, headers=headers)

        # Do not trust X-Forwarded-* for authorization or peer identity.
        if request.client and request.client.host not in {"127.0.0.1", "::1"}:
            return response({"error": "Use this Mac's private connection"}, 403)
        if not host or request.headers.get("host", "").lower() != host:
            return response({"error": "Use the Mac's configured private HTTPS address"}, 403)
        if request.headers.get("origin") not in (None, origin):
            return response({"error": "This origin is not authorized"}, 403)
        # Serve strips client-supplied identity headers; Funnel supplies none.
        # Require an untagged signed-in device, then independently authenticate it.
        principal = request.headers.get("tailscale-user-login", "")
        if not principal or len(principal) > 320:
            return response(
                {
                    "error": "Use private Tailscale Serve from a signed-in personal device; public Funnel and tagged clients are not supported."
                },
                403,
            )
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            return response({"error": "Send application/json"}, 415)
        if not access.config.get("enabled") or access.service._closing or access.stopping:
            return response({"error": "Remote access is disabled on the Mac"}, 503)
        now = time.monotonic()
        bucket = buckets[request.url.path]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        limit = 10 if request.url.path == "/v1/pair" else 1200
        if len(bucket) >= limit:
            return response({"error": "Too many requests. Wait a minute and retry."}, 429)
        bucket.append(now)
        try:
            async with asyncio.timeout(10):
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return response({"error": "Request is too large"}, 413)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Send a JSON object")
            async with gate:
                if request.url.path == "/v1/pair":
                    if set(payload) != {"code", "name"}:
                        raise ValueError("Provide a pairing code and device name")
                    result = await asyncio.to_thread(
                        access.request_pairing, payload["code"], payload["name"], principal
                    )
                elif request.url.path == "/v1/pair/claim":
                    if set(payload) != {"id", "claim"} or not all(
                        isinstance(v, str) for v in payload.values()
                    ):
                        raise ValueError("Provide the pairing request and claim")
                    result = await asyncio.to_thread(
                        access.claim_pairing, payload["id"], payload["claim"], principal
                    )
                else:
                    authorization = request.headers.get("authorization", "")
                    credential = authorization[7:] if authorization.startswith("Bearer ") else ""
                    device = await asyncio.to_thread(access.authenticate, credential, principal)
                    device_bucket = buckets[device["id"]]
                    while device_bucket and device_bucket[0] < now - 60:
                        device_bucket.popleft()
                    if len(device_bucket) >= 240:
                        return response(
                            {
                                "error": "This device is sending requests too quickly. Wait a minute and retry."
                            },
                            429,
                        )
                    device_bucket.append(now)
                    if (
                        set(payload) - {"method", "params"}
                        or not isinstance(payload.get("method"), str)
                        or not isinstance(payload.get("params", {}), dict)
                    ):
                        raise ValueError("Provide a method and object parameters")
                    result = await asyncio.to_thread(
                        access.rpc,
                        device,
                        payload["method"],
                        payload.get("params", {}),
                        request.headers.get("idempotency-key", ""),
                    )
            result = {"result": result}
            if len(json.dumps(result, default=str).encode()) > MAX_RESPONSE:
                return response(
                    {"error": "Result is too large. Inspect this operation on the Mac."}, 413
                )
            return response(result)
        except PermissionError as exc:
            return response({"error": str(exc)}, 403)
        except (ValueError, KeyError, TypeError) as exc:
            # Keep provider errors and paths out of the API; only known boundary text is returned.
            message = str(exc) if type(exc) is ValueError else "Invalid companion request"
            return response({"error": access.clean(message)[:500]}, 400)
        except TimeoutError:
            return response(
                {"error": "Request timed out. Check activity before retrying an action."}, 408
            )
        except Exception:
            return response(
                {
                    "error": "The Mac could not complete this request. Check its activity and connection."
                },
                500,
            )

    return Starlette(
        routes=[
            Route(path, endpoint, methods=["POST"])
            for path in ("/v1/pair", "/v1/pair/claim", "/v1/rpc")
        ]
    )


class RemoteServer:
    def __init__(self, access, port):
        self.access = access
        self.port = port
        self.thread = None
        self.server = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and self.server and self.server.started)

    def start(self):
        import uvicorn

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", self.port))
            listener.listen(16)
            self.port = listener.getsockname()[1]
            self.server = uvicorn.Server(
                uvicorn.Config(
                    application(self.access),
                    host="127.0.0.1",
                    access_log=False,
                    log_level="error",
                    proxy_headers=False,
                    timeout_keep_alive=5,
                    timeout_graceful_shutdown=5,
                    limit_concurrency=16,
                    ws="none",
                )
            )
            self.thread = threading.Thread(
                target=self.server.run,
                kwargs={"sockets": [listener]},
                name="superqode-private-access",
                daemon=True,
            )
            self.thread.start()
            deadline = time.monotonic() + 5
            while (
                self.thread.is_alive() and not self.server.started and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            if not self.running:
                self.stop()
                raise RuntimeError("The private remote listener did not start")
        except BaseException:
            listener.close()
            raise

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                raise RuntimeError(
                    "Remote access is still closing; wait before stopping the engine"
                )
