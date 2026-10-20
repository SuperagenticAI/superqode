"""Explicit compaction of a completed built-in session using the shared engine."""

from dataclasses import replace
from pathlib import Path


async def compact(request, emit):
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.backends.base import HarnessBackendRequest
    from superqode.harness.backends.runtime import _create_runtime_for_request

    definition = resolve_harness(request["harness"], root=request["cwd"])
    if definition.digest != request["expected_digest"]:
        raise ValueError("Harness changed since this conversation; compaction was not started")
    spec = replace(
        definition.spec,
        context=replace(
            definition.spec.context,
            session_storage=str(Path(request["state_root"]) / "native-sessions"),
        ),
    )
    _, runtime = _create_runtime_for_request(
        HarnessBackendRequest(
            spec=spec,
            prompt="",
            provider=request["provider"],
            model=request["model"],
            working_directory=Path(request["cwd"]),
            session_id=request["session_id"],
        ),
        "builtin",
    )
    result = await runtime.loop.compact_now(str(request.get("instructions") or ""))
    emit("answer", {"text": result.get("message", "Compaction finished")})
    emit(
        "result",
        {
            **result,
            "status": "completed" if result.get("success") else "failed",
            "session_id": request["session_id"],
            "harness_digest": definition.digest,
            "source_job": request["source_job"],
            "native_continuity": bool(result.get("success")),
        },
    )
