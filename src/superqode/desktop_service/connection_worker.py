"""Run vendor-owned subscriptions and remote protocols without inventing a model route."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import uuid


APPROVAL_LOCK = threading.Lock()


def approval(emit, name, arguments):
    with APPROVAL_LOCK:
        identity = uuid.uuid4().hex
        emit("approval", {"request_id": identity, "tool": {"name": name, "arguments": arguments}})
        from .controls import _router

        if _router is None:
            raise RuntimeError("Runtime control channel is unavailable")
        return _router.decision(identity).get("allow") is True


async def run_connection(request, directory, emit, secrets):
    route = request["_desktop_connection"]
    kind = route["kind"]
    config = json.loads(os.environ.pop("SUPERQODE_DESKTOP_REMOTE", "{}"))
    if kind in {"a2a", "uhp"}:
        from .remote_worker import run_remote

        return await run_remote(request, route, config, emit, secrets)
    vendor = route.get("subscription_vendor")
    if vendor:
        from superqode.providers.subscription_env import subscription_child_env

        _, removed = subscription_child_env(vendor)
        for name in removed:
            os.environ.pop(name, None)
        emit(
            "billing",
            {
                "requested": "subscription",
                "ignored_api_key_variables": removed,
                "verified": False,
                "owner": vendor,
            },
        )
    from superqode.agent.loop import AgentConfig
    from superqode.runtime.registry import create_runtime
    from superqode.tools.base import ToolRegistry
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    runtime = create_runtime(
        route["runtime"],
        config=AgentConfig(
            provider="agent",
            model=request.get("model") or "",
            working_directory=Path(request["cwd"]),
            session_storage_dir=str(Path(request["state_root"]) / "vendor-sessions"),
        ),
        tools=ToolRegistry.for_profile("coding"),
        gateway=LiteLLMGateway(),
        approval_callback=lambda name, args: approval(emit, name, args),
        billing_requested="subscription"
        if vendor
        else "byok"
        if route.get("auth") == "byok"
        else "agent-managed",
    )
    from .controls import inbox

    inbox(emit).bind(runtime)
    try:
        if request.get("session_id"):
            import inspect

            resume = runtime.resume_thread(request["session_id"])
            if inspect.isawaitable(resume):
                await resume
        emit("stage", {"message": "Starting the connected agent and sending your prompt"})
        if hasattr(runtime, "run_harness_events"):
            async for event in runtime.run_harness_events(request["prompt"]):
                emit("harness_event", {"event": event.type, "payload": dict(event.data)})
                if event.type in {"error", "run.failed"} or (
                    event.type == "model_result"
                    and event.data.get("stopped_reason") in {"error", "cancelled"}
                ):
                    raise RuntimeError(
                        str(event.data.get("error") or "Vendor agent did not complete")
                    )
        else:
            response = await runtime.run(request["prompt"])
            if response.stopped_reason in {"error", "cancelled"}:
                raise RuntimeError(response.error or response.content or "Agent did not complete")
            emit("answer", {"text": response.content})
        session_id = getattr(runtime, "thread_id", None) or getattr(runtime, "session_id", None)
        emit(
            "result",
            {
                "status": "completed",
                "route": route["id"],
                "native_continuity": False,
                "vendor_continuity": bool(session_id and hasattr(runtime, "resume_thread")),
                "session_id": session_id,
                "harness_digest": route["digest"],
            },
        )
    finally:
        if hasattr(runtime, "aclose"):
            await runtime.aclose()
