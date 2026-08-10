"""Internal entry point for one detached native RLM child."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any


async def run_worker(request_path: str | Path) -> int:
    request = _read_required_json(Path(request_path))
    result_path = Path(str(request["result_path"]))
    try:
        from superqode.pipy.ai.models import resolve_model
        from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions
        from superqode.rlm.sandbox import RLMSandboxConfig

        options = RLMCodingSessionOptions(
            cwd=Path(str(request["cwd"])),
            model=resolve_model(
                str(request.get("model") or ""), provider=str(request.get("provider") or "")
            ),
            thinking_level=str(request.get("thinking_level") or "off"),  # type: ignore[arg-type]
            session_root=Path(str(request["session_root"])),
            max_depth=int(request.get("max_depth") or 3),
            max_children=int(request.get("max_children") or 8),
            max_parallel=int(request.get("max_parallel") or 4),
            durable_children=True,
            sandbox=RLMSandboxConfig.from_config(request.get("sandbox")),
            sandbox_session=str(request.get("sandbox_session") or ""),
        )
        session = await RLMCodingSession.create(options)
        prompt_task = asyncio.create_task(session.prompt(str(request["prompt"])))
        control_task = asyncio.create_task(
            _watch_control(Path(str(request["control_path"])), session, prompt_task)
        )
        try:
            message = await prompt_task
        finally:
            control_task.cancel()
            await asyncio.gather(control_task, return_exceptions=True)
        _atomic_json(
            result_path,
            {
                "status": "completed",
                "result": message.text,
                "usage": _usage_dict(getattr(message, "usage", None)),
                "completed_at": time.time(),
            },
        )
        return 0
    except asyncio.CancelledError:
        _atomic_json(
            result_path,
            {"status": "cancelled", "error": "Worker cancelled", "completed_at": time.time()},
        )
        return 2
    except BaseException as error:  # noqa: BLE001 - durable worker must report every failure
        _atomic_json(
            result_path,
            {
                "status": "failed",
                "error": str(error),
                "error_type": type(error).__name__,
                "completed_at": time.time(),
            },
        )
        return 1


async def _watch_control(path: Path, session: Any, prompt_task: asyncio.Task[Any]) -> None:
    offset = 0
    while not prompt_task.done():
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                lines = handle.readlines()
                offset = handle.tell()
            for line in lines:
                try:
                    command = json.loads(line)
                except ValueError:
                    continue
                operation = str(command.get("operation") or "")
                message = str(command.get("message") or "")
                if operation == "steer":
                    await session.steer(message)
                elif operation == "follow_up":
                    await session.follow_up(message)
                elif operation == "cancel":
                    await session.abort()
                    prompt_task.cancel()
                    return
        await asyncio.sleep(0.1)


def _read_required_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("RLM worker request must be a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _usage_dict(usage: Any) -> dict[str, int | float]:
    if usage is None:
        return {}
    cost = getattr(usage, "cost", None)
    return {
        "input_tokens": int(getattr(usage, "input", 0) or 0),
        "output_tokens": int(getattr(usage, "output", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read", 0) or 0),
        "cache_write_tokens": int(getattr(usage, "cache_write", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cost_usd": float(getattr(cost, "total", 0.0) or 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal native RLM child worker")
    parser.add_argument("request")
    arguments = parser.parse_args()
    return asyncio.run(run_worker(arguments.request))


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())


__all__ = ["main", "run_worker"]
