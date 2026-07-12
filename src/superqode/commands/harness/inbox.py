"""Harness inbox commands and claimed-input execution."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.group("inbox")
def harness_inbox():
    """Manage durable harness session inputs."""


@harness_inbox.command("add")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", required=True, help="Harness session id")
@click.option("--prompt", required=True, help="Prompt to admit")
@click.option(
    "--delivery",
    type=click.Choice(["queue", "steer", "admit-only"]),
    default="queue",
    show_default=True,
    help="How the input should be delivered by a future drain",
)
@click.option("--id", "input_id", default=None, help="Stable input id for exact retry")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_add(store_path, session_id, prompt, delivery, input_id, json_output):
    """Admit a prompt to a durable harness session inbox."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        record = store.admit_input(
            session_id=session_id,
            input_id=input_id,
            prompt=prompt,
            delivery=delivery,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = record.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Admitted {record.input_id} to {record.session_id} ({record.delivery})")


@harness_inbox.command("list")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by harness session id")
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(["pending", "running", "done", "failed"]),
    default=None,
    help="Filter by input status",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_list(store_path, session_id, status_filter, json_output):
    """List durable harness session inputs."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    inputs = store.list_inputs(session_id=session_id, status=status_filter)
    payload = [item.to_dict() for item in inputs]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not inputs:
        click.echo("No harness inbox inputs found.")
        return
    for item in inputs[:50]:
        preview = " ".join(item.prompt.split())
        if len(preview) > 80:
            preview = preview[:77] + "..."
        run = f" run={item.run_id}" if item.run_id else ""
        click.echo(
            f"{item.input_id}  {item.status:<8}  {item.delivery:<10}  "
            f"{item.session_id}  {preview}{run}"
        )


@harness_inbox.command("recover")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by harness session id")
@click.option(
    "--stale-after",
    "stale_after_seconds",
    default=300,
    show_default=True,
    type=int,
    help="Recover running inputs older than this many seconds",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_recover(store_path, session_id, stale_after_seconds, json_output):
    """Recover stale running inbox inputs back to pending."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    recovered = store.recover_stale_inputs(
        session_id=session_id,
        stale_after_seconds=stale_after_seconds,
    )
    payload = [item.to_dict() for item in recovered]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not recovered:
        click.echo("No stale running harness inbox inputs found.")
        return
    for item in recovered:
        click.echo(f"recovered {item.input_id} for {item.session_id}")


async def _execute_claimed_harness_input(
    *,
    item,
    spec,
    kernel,
    store,
    owner,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    session_id,
    lease_seconds,
):
    import asyncio
    import contextlib

    from superqode.harness import WorkflowMode, run_workflow, workflow_steps_from_spec

    async def _heartbeat(stop_event):
        interval = max(1.0, lease_seconds / 2)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                with contextlib.suppress(Exception):
                    store.renew_input_lease(
                        item.input_id,
                        owner_id=owner,
                        lease_seconds=lease_seconds,
                    )

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(stop))
    try:
        try:
            if spec.workflow.mode != WorkflowMode.SINGLE:
                workflow_result = await run_workflow(
                    kernel,
                    workflow_steps_from_spec(spec, item.prompt),
                    provider=provider,
                    model=model_name,
                    runtime=runtime_name,
                    working_directory=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                )
                store.mark_input_done(
                    item.input_id,
                    run_id=workflow_result.run_id,
                    owner_id=owner,
                )
                return {
                    "input_id": item.input_id,
                    "status": "done",
                    "run_id": workflow_result.run_id,
                    "owner_id": owner,
                    "content": workflow_result.content,
                }
            session_obj = await kernel.session(session_id)
            result = await session_obj.prompt(
                item.prompt,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                metadata={"admitted_input_id": item.input_id},
            )
            store.mark_input_done(item.input_id, run_id=result.run_id, owner_id=owner)
            return {
                "input_id": item.input_id,
                "status": "done",
                "run_id": result.run_id,
                "owner_id": owner,
                "content": result.content,
            }
        except Exception as exc:  # noqa: BLE001
            store.mark_input_failed(item.input_id, error=str(exc), owner_id=owner)
            return {
                "input_id": item.input_id,
                "status": "failed",
                "owner_id": owner,
                "error": str(exc),
            }
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            await heartbeat
