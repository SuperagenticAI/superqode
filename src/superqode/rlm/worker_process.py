"""Detached child-process transport for live native RLM agents."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from superqode.pipy.coding_session import CodingSessionOptions

from .supervisor import AgentRecord, AgentSupervisor


async def run_durable_child(
    record: AgentRecord,
    *,
    options: CodingSessionOptions,
    supervisor: AgentSupervisor,
) -> str:
    """Launch a detached worker once, or reattach to its result files."""
    process: subprocess.Popen[bytes] | None = None
    result_path = Path(record.worker_result_path) if record.worker_result_path else None
    if result_path is None:
        job_dir = _job_dir(supervisor, record.id)
        request_path = job_dir / "request.json"
        result_path = job_dir / "result.json"
        control_path = job_dir / "control.jsonl"
        log_path = job_dir / "worker.log"
        job_dir.mkdir(parents=True, exist_ok=True)
        model = options.model
        provider = str(getattr(model, "provider", "") or "")
        model_id = str(getattr(model, "id", "") or "")
        if record.model:
            selected_provider, separator, selected_model = record.model.partition("/")
            provider = selected_provider if separator else ""
            model_id = selected_model if separator else selected_provider
        request = {
            "agent_id": record.id,
            "prompt": record.prompt,
            "cwd": str(Path(options.cwd).expanduser().resolve()),
            "provider": provider,
            "model": model_id,
            "thinking_level": str(options.thinking_level),
            "session_root": str(job_dir / "sessions"),
            "result_path": str(result_path),
            "control_path": str(control_path),
            "max_depth": max(0, supervisor.max_depth - supervisor.depth(record.id)),
            "max_children": supervisor.max_children,
            "max_parallel": supervisor.max_parallel,
        }
        _atomic_json(request_path, request)
        with log_path.open("ab") as log:
            process = subprocess.Popen(  # noqa: S603 - fixed module invocation
                [sys.executable, "-m", "superqode.rlm.worker", str(request_path)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        request["worker_pid"] = process.pid
        _atomic_json(request_path, request)
        supervisor.mark_worker(
            record.id,
            pid=process.pid,
            request_path=request_path,
            result_path=result_path,
            control_path=control_path,
        )

    while True:
        result = _read_json(result_path)
        if result is not None:
            if process is not None:
                try:
                    await asyncio.to_thread(process.wait, 5)
                except subprocess.TimeoutExpired:
                    pass
            record.worker_pid = None
            record.usage = (
                dict(result.get("usage") or {}) if isinstance(result.get("usage"), dict) else {}
            )
            status = str(result.get("status") or "failed")
            if status == "completed":
                return str(result.get("result") or "")
            if status == "cancelled":
                raise asyncio.CancelledError(f"Detached RLM worker {record.id} was cancelled")
            raise RuntimeError(str(result.get("error") or "Detached RLM worker failed"))
        locally_exited = process is not None and process.poll() is not None
        if locally_exited or (record.worker_pid and not _process_alive(record.worker_pid)):
            record.worker_pid = None
            raise RuntimeError(
                f"Detached RLM worker {record.id} exited without writing a result; "
                f"inspect {_job_dir(supervisor, record.id) / 'worker.log'}"
            )
        await asyncio.sleep(0.2)


def _job_dir(supervisor: AgentSupervisor, agent_id: str) -> Path:
    journal = supervisor.journal_path
    base = journal.parent if journal is not None else Path.cwd() / ".superqode-rlm"
    stem = journal.stem.removesuffix(".agents") if journal is not None else "session"
    return base / f"{stem}.workers" / agent_id


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _process_alive(pid: int) -> bool:
    import os

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


__all__ = ["run_durable_child"]
