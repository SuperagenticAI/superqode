"""Sequential, host-driven Monty programs with optional WorkOrder continuation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sysconfig
from contextlib import suppress
from pathlib import Path

from superqode.execution_recovery import (
    active_recovery,
    input_fingerprint,
    check_recovery_workspace,
)
from superqode.workorders.programs import ProgramJournal, MAX_RESULT_BYTES
from superqode.workorders.recovery import workspace_fingerprint
from .monty_tool import _load_monty


def runtime_identity(module):
    """Pin the actual worker bytes as well as the Python API version."""
    binary = os.getenv("MONTY_BIN")
    if not binary:
        candidate = Path(sysconfig.get_path("scripts")) / (
            "monty.exe" if os.name == "nt" else "monty"
        )
        binary = str(candidate) if candidate.is_file() else shutil.which("monty")
    if not binary:
        raise RuntimeError("Monty worker is missing; install superqode[monty]")
    path = Path(binary).resolve(strict=True)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"api": module.__version__, "worker_sha256": digest}, path


def bounded_json(value):
    payload = json.dumps(value, allow_nan=False, ensure_ascii=True)
    if len(payload.encode()) > MAX_RESULT_BYTES:
        raise ValueError("Program host result exceeds 64,000 bytes")
    return json.loads(payload)


async def run_program(program_id, code, host, *, cwd, signal=None):
    """Run or restore a program. Host prepares, dispatches and guards results.

    No host coroutine or OS access is supplied to Monty. Every external call is
    explicitly journaled before dispatch and answered only after result commit.
    """
    module = _load_monty()
    if module is None:
        raise RuntimeError("Monty is not installed; install superqode[monty]")
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > MAX_RESULT_BYTES:
        raise ValueError("Program code must contain 1–64,000 bytes")
    runtime, binary = await asyncio.to_thread(runtime_identity, module)
    if hasattr(host, "begin_program"):
        await host.begin_program(program_id)
    scope = active_recovery()
    journal = None
    if scope:
        await check_recovery_workspace(scope)
        workspace = await asyncio.to_thread(
            workspace_fingerprint, Path(cwd), exclude_paths=(scope.store.path,)
        )
        journal = ProgramJournal(
            scope,
            program_id,
            input_fingerprint(
                {
                    "code": code,
                    "runtime": runtime,
                    "capabilities": host.identity(),
                    "contract": 1,
                    "limits": {"calls": 32, "memory": 32 * 1024 * 1024, "compute_seconds": 2},
                }
            ),
            workspace,
        )
    saved = journal.load() if journal else None
    revision = saved["revision"] if saved else 0
    metadata = saved["metadata"] if saved else {"history": [], "printed": "", "runtime": runtime}

    def check():
        if signal:
            signal.throw_if_aborted()

    async def check_workspace():
        check()
        if journal:
            current = await asyncio.to_thread(
                workspace_fingerprint, Path(cwd), exclude_paths=(scope.store.path,)
            )
            if current != workspace:
                raise ValueError(
                    "Workspace changed during the read-only program; reconciliation required"
                )

    # Re-check authority on all data already present in the interpreter, not
    # just the pending call. A changed hook/result projection invalidates reuse.
    if saved:
        records = {
            r["invocation_id"]: r
            for r in scope.store.invocations(scope.work_order_id, scope.task_id)
        }
        for entry in metadata["history"]:
            check()
            prepared = await host.prepare(**entry["request"], call_id=entry["id"])
            if input_fingerprint(prepared) != entry["prepared_sha256"]:
                raise ValueError("Recovered program authority or effective arguments changed")
            record = records.get(entry["id"])
            if record and record["status"] == "completed":
                await host.check_result(prepared, record["result"]["value"])
        if saved["state"] == "completed":
            await check_workspace()
            if hasattr(host, "check_final"):
                await host.check_final(saved["result"])
            if hasattr(host, "commit_program"):
                await host.commit_program(saved["result"])
            return {**saved["result"], "recovery": "reused"}

    def printed(_stream, text):
        # The retained prefix is checkpointed alongside the VM. Printing does
        # not create a separate external side effect during recovery.
        remaining = 20_000 - len(metadata["printed"])
        if remaining > 0:
            metadata["printed"] += text[:remaining]
        if len(text) > remaining:
            metadata["printed_truncated"] = True

    async with module.AsyncMonty(binary_path=binary, max_processes=1, request_timeout=4) as pool:
        async with pool.checkout(
            script_name="superqode_program.py",
            limits=module.ResourceLimits(max_feed_duration_secs=2, max_memory=32 * 1024 * 1024),
        ) as session:
            snapshot = (
                await session.load_snapshot(saved["checkpoint"], print_callback=printed)
                if saved
                else await session.feed_start(code, print_callback=printed)
            )
            restoring = bool(saved)
            suspensions = 0
            while not isinstance(snapshot, module.MontyComplete):
                check()
                suspensions += 1
                if suspensions > 256:
                    raise ValueError("Program suspension budget exceeded")
                if isinstance(snapshot, module.AsyncNameLookupSnapshot):
                    if snapshot.object_id is not None or snapshot.variable_name not in {
                        "tool_call",
                        "tool_search",
                        "tool_parallel",
                        "store",
                        "load",
                    }:
                        snapshot = await snapshot.resume()
                    else:
                        # Register only a callable marker. It is never invoked
                        # by the host; FunctionSnapshot routes the eventual call.
                        snapshot = await snapshot.resume(value=lambda *a, **k: None)
                    continue
                if (
                    not isinstance(snapshot, module.AsyncFunctionSnapshot)
                    or snapshot.is_os_function
                    or snapshot.object_id is not None
                ):
                    raise ValueError(
                        "Program supports sequential tool calls only; direct OS access and host futures are unavailable"
                    )
                request = {
                    "function": str(snapshot.function_name),
                    "args": list(snapshot.args),
                    "kwargs": snapshot.kwargs,
                }
                if len(json.dumps(request).encode()) > MAX_RESULT_BYTES:
                    raise ValueError("Program host arguments exceed 64,000 bytes")
                if restoring:
                    entry = metadata["history"][-1]
                    if request != entry["request"]:
                        raise ValueError(
                            "Restored checkpoint does not match its recorded invocation"
                        )
                    call_id = entry["id"]
                else:
                    if len(metadata["history"]) >= 32:
                        raise ValueError("Program call budget exceeded")
                    call_id = f"program/{program_id}/call-{len(metadata['history']) + 1}"
                prepared = await host.prepare(**request, call_id=call_id)
                units = (
                    len(prepared.get("calls", [])) if request["function"] == "tool_parallel" else 1
                )
                if not restoring:
                    spent = metadata.get("call_units", len(metadata["history"]))
                    if spent + units > 32:
                        raise ValueError("Program call budget exceeded")
                    metadata["call_units"] = spent + units
                await check_workspace()
                inputs = {"program": program_id, "prepared": prepared}
                safe = prepared["replay_safe"]
                if restoring:
                    decision = journal.admit(invocation_id=call_id, inputs=inputs, replay_safe=safe)
                else:
                    metadata["history"].append(
                        {
                            "id": call_id,
                            "request": request,
                            "prepared_sha256": input_fingerprint(prepared),
                        }
                    )
                    decision = (
                        journal.stage(
                            revision=revision,
                            checkpoint=await session.dump(),
                            metadata=metadata,
                            invocation_id=call_id,
                            inputs=inputs,
                            replay_safe=safe,
                        )
                        if journal
                        else {"action": "execute"}
                    )
                    revision += 1
                check()
                if decision["action"] == "reuse":
                    value = decision["result"]["value"]
                    await host.check_result(prepared, value)
                else:
                    try:
                        value = bounded_json(await host.execute(prepared, call_id, signal))
                        await check_workspace()
                        if journal:
                            journal.finish_call(call_id, {"value": value})
                    except BaseException:
                        if journal:
                            with suppress(Exception):
                                journal.uncertain(call_id)
                        raise
                # Never supply a value before its successful journal commit.
                usage = metadata.setdefault(
                    "usage", {"tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "cost_usd": 0.0}
                )
                if prepared.get("name") == "mcp_call":
                    reported = value.get("usage")
                    for key, reported_key in (
                        ("tokens_in", "input"),
                        ("tokens_out", "output"),
                        ("total_tokens", "total_tokens"),
                    ):
                        usage[key] = (
                            usage[key] + reported[reported_key]
                            if reported and usage[key] is not None
                            else None
                        )
                    usage["cost_usd"] = (
                        usage["cost_usd"] + reported["cost"]["total"]
                        if reported and usage["cost_usd"] is not None
                        else None
                    )
                snapshot = await snapshot.resume({"return_value": value})
                restoring = False
            check()
            await check_workspace()
            text = metadata["printed"].rstrip()
            final = repr(snapshot.output)
            output = (
                (text + "\n" + final if text else final).encode()[:8_000].decode(errors="ignore")
            )
            result = {
                "output": output,
                "program_id": program_id,
                "calls": metadata.get("call_units", len(metadata["history"])),
                "recovery": "continued" if saved else "fresh",
                "checkpointed": bool(journal),
                "output_truncated": len((text + "\n" + final if text else final).encode()) > 8_000,
                "printed_truncated": metadata.get("printed_truncated", False),
                **(
                    {"program_state": host.program_state()}
                    if hasattr(host, "program_state")
                    else {}
                ),
                "usage": {
                    **metadata.get(
                        "usage",
                        {"tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "cost_usd": 0.0},
                    ),
                    "tool_calls": journal.dispatch_count({e["id"] for e in metadata["history"]})
                    if journal
                    else len(metadata["history"]),
                },
            }
            if hasattr(host, "check_final"):
                await host.check_final(result)
            if journal:
                journal.complete(revision, result, metadata)
            if hasattr(host, "commit_program"):
                await host.commit_program(result)
            return result


async def cancellable_program(*args, signal=None, **kwargs):
    task = asyncio.create_task(run_program(*args, signal=signal, **kwargs))
    unsubscribe = signal.add_listener(task.cancel) if signal else lambda: None
    try:
        async with asyncio.timeout(30):
            return await task
    finally:
        unsubscribe()
