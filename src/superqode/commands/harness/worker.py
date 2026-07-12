"""Harness inbox drain and worker commands."""

import json
import os
import time
from pathlib import Path

import click

from ._group import harness
from .inbox import _execute_claimed_harness_input


@harness.command("drain")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--session", "session_id", required=True, help="Harness session id to drain")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--limit", default=1, show_default=True, type=int, help="Maximum inputs to drain")
@click.option("--owner-id", default=None, help="Drain worker owner id")
@click.option(
    "--lease-seconds", default=300, show_default=True, type=int, help="Claim lease duration"
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_drain(
    spec_path,
    session_id,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    store_path,
    limit,
    owner_id,
    lease_seconds,
    json_output,
):
    """Execute pending durable inputs for one harness session."""
    import asyncio

    from superqode.harness import (
        FileHarnessStore,
        init_harness,
        load_harness_spec,
    )

    async def _drain():
        spec = load_harness_spec(spec_path)
        store = FileHarnessStore(store_path)
        kernel = await init_harness(spec, store=store)
        owner = owner_id or f"drain-{os.getpid()}-{int(time.time() * 1000)}"
        drained = []
        for _ in range(max(0, limit)):
            item = store.claim_next_input(
                session_id=session_id,
                owner_id=owner,
                lease_seconds=lease_seconds,
            )
            if item is None:
                break
            drained.append(
                await _execute_claimed_harness_input(
                    item=item,
                    spec=spec,
                    kernel=kernel,
                    store=store,
                    owner=owner,
                    provider=provider,
                    model_name=model_name,
                    runtime_name=runtime_name,
                    working_dir=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                    lease_seconds=lease_seconds,
                )
            )
        return drained

    payload = asyncio.run(_drain())
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No pending harness inbox inputs to drain.")
        return
    for item in payload:
        if item["status"] == "done":
            click.echo(f"drained {item['input_id']} -> {item['run_id']}")
        else:
            click.echo(f"failed {item['input_id']}: {item['error']}")


@harness.command("worker")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--session", "session_id", required=True, help="Harness session id to drain")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--owner-id", default=None, help="Worker owner id")
@click.option(
    "--lease-seconds", default=300, show_default=True, type=int, help="Claim lease duration"
)
@click.option(
    "--concurrency", default=1, show_default=True, type=int, help="Concurrent worker loops"
)
@click.option("--poll-seconds", default=2.0, show_default=True, type=float, help="Idle poll delay")
@click.option("--max-runs", default=None, type=int, help="Stop after this many claimed inputs")
@click.option("--once", is_flag=True, help="Exit when no pending input is available")
@click.option("--recover-stale/--no-recover-stale", default=True, show_default=True)
@click.option(
    "--stale-after",
    "stale_after_seconds",
    default=300,
    show_default=True,
    type=int,
    help="Recover running inputs older than this many seconds on startup",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON when the worker exits")
def harness_worker(
    spec_path,
    session_id,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    store_path,
    owner_id,
    lease_seconds,
    concurrency,
    poll_seconds,
    max_runs,
    once,
    recover_stale,
    stale_after_seconds,
    json_output,
):
    """Run a durable harness inbox worker."""
    import asyncio

    from superqode.harness import FileHarnessStore, init_harness, load_harness_spec

    async def _worker():
        spec = load_harness_spec(spec_path)
        store = FileHarnessStore(store_path)
        recovered = (
            store.recover_stale_inputs(
                session_id=session_id,
                stale_after_seconds=stale_after_seconds,
            )
            if recover_stale
            else []
        )
        kernel = await init_harness(spec, store=store)
        owner = owner_id or f"worker-{os.getpid()}-{int(time.time() * 1000)}"
        processed = []
        claim_lock = asyncio.Lock()
        processed_lock = asyncio.Lock()
        claimed_count = 0

        async def _claim_one():
            nonlocal claimed_count
            async with claim_lock:
                if max_runs is not None and claimed_count >= max(0, max_runs):
                    return None, True
                item = store.claim_next_input(
                    session_id=session_id,
                    owner_id=owner,
                    lease_seconds=lease_seconds,
                )
                if item is None:
                    return None, once
                claimed_count += 1
                return item, False

        async def _loop(worker_index):
            while True:
                item, should_stop = await _claim_one()
                if item is None:
                    if should_stop:
                        return
                    await asyncio.sleep(max(0.0, poll_seconds))
                    continue
                result = await _execute_claimed_harness_input(
                    item=item,
                    spec=spec,
                    kernel=kernel,
                    store=store,
                    owner=owner,
                    provider=provider,
                    model_name=model_name,
                    runtime_name=runtime_name,
                    working_dir=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                    lease_seconds=lease_seconds,
                )
                result["worker_index"] = worker_index
                async with processed_lock:
                    processed.append(result)

        await asyncio.gather(*(_loop(index) for index in range(max(1, concurrency))))
        return {
            "owner_id": owner,
            "session_id": session_id,
            "recovered": [item.to_dict() for item in recovered],
            "processed": processed,
        }

    payload = asyncio.run(_worker())
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if payload["recovered"]:
        click.echo(f"Recovered {len(payload['recovered'])} stale inbox input(s).")
    if not payload["processed"]:
        click.echo("No harness inbox inputs processed.")
        return
    for item in payload["processed"]:
        if item["status"] == "done":
            click.echo(f"worker drained {item['input_id']} -> {item['run_id']}")
        else:
            click.echo(f"worker failed {item['input_id']}: {item['error']}")
