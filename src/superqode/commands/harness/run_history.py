"""Harness execution and run-history commands."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("run")
@click.argument("reference", required=False)
@click.argument("task", required=False)
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--prompt", "-p", help="Prompt to run")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--session", "session_id", default=None, help="Reuse a harness session id")
@click.option(
    "--store",
    "store_kind",
    type=click.Choice(["memory", "file", "sqlite"]),
    default=None,
    help="Override observability.run_store",
)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--stream", is_flag=True, help="Print normalized stream events")
@click.option(
    "--single-step",
    is_flag=True,
    help="Force one prompt through the harness kernel, ignoring non-single workflow topology",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_run(
    reference,
    task,
    spec_path,
    prompt,
    provider,
    model_name,
    runtime_name,
    session_id,
    store_kind,
    working_dir,
    sandbox_backend,
    stream,
    single_step,
    json_output,
):
    """Run a HarnessSpec or installed Python harness."""
    import asyncio

    from superqode.harness import (
        WorkflowMode,
        create_harness_store,
        init_harness,
        load_harness_spec,
        run_workflow,
        workflow_steps_from_spec,
    )

    if reference and spec_path:
        raise click.UsageError("Pass either a harness name/path or --spec, not both")
    if task and prompt and task != prompt:
        raise click.UsageError("Pass the task as an argument or --prompt, not both")
    prompt = prompt or task
    if reference and Path(reference).is_file():
        spec_path = Path(reference)
        reference = None
    if not prompt:
        raise click.UsageError("A task is required; pass it as an argument or --prompt")
    if not reference and spec_path is None:
        raise click.UsageError("A harness name/path or --spec is required")

    async def _run_spec():
        spec = load_harness_spec(spec_path)
        store = create_harness_store(
            store_kind or spec.observability.run_store,
            (
                Path(spec.context.session_storage) / "store.sqlite3"
                if (store_kind or spec.observability.run_store) == "sqlite"
                else Path(spec.context.session_storage)
            ),
        )
        kernel = await init_harness(spec, store=store)
        run_as_workflow = (not single_step) and spec.workflow.mode != WorkflowMode.SINGLE
        if run_as_workflow and stream:
            raise click.ClickException(
                "--stream is only available for single-step harness runs; "
                "omit --stream or pass --single-step."
            )
        if run_as_workflow:
            steps = workflow_steps_from_spec(spec, prompt)
            workflow_result = await run_workflow(
                kernel,
                steps,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                session_id=session_id,
            )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "content": workflow_result.content,
                            "session_id": workflow_result.session_id,
                            "run_id": workflow_result.run_id,
                            "harness": spec.name,
                            "workflow": {
                                "mode": workflow_result.mode.value,
                                "result_count": len(workflow_result.results),
                                "result_run_ids": [item.run_id for item in workflow_result.results],
                                "failures": list(workflow_result.failures),
                            },
                            "results": [
                                {
                                    "content": item.content,
                                    "session_id": item.session_id,
                                    "run_id": item.run_id,
                                    "tool_calls_made": item.tool_calls_made,
                                    "iterations": item.iterations,
                                    "stopped_reason": item.response.stopped_reason,
                                }
                                for item in workflow_result.results
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(workflow_result.content)
                click.echo(
                    f"\nWorkflow run: {workflow_result.run_id} "
                    f"({workflow_result.mode.value}, {len(workflow_result.results)} result(s))"
                )
            return workflow_result
        session_obj = await kernel.session(session_id)
        if stream:
            events = []
            async for event in session_obj.stream(
                prompt,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
            ):
                item = {
                    "type": event.type,
                    "data": event.data,
                    "session_id": event.session_id,
                    "run_id": event.run_id,
                }
                events.append(item)
                if json_output:
                    click.echo(json.dumps(item))
                elif event.type == "delta":
                    click.echo(event.data.get("text", ""), nl=False)
            if json_output:
                return None
            click.echo()
            return {"events": events}
        result = await session_obj.prompt(
            prompt,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_directory=working_dir,
            sandbox_backend=sandbox_backend,
        )
        pending_approvals = list(session_obj.pending_approvals())
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "content": result.content,
                        "session_id": result.session_id,
                        "run_id": result.run_id,
                        "tool_calls_made": result.tool_calls_made,
                        "iterations": result.iterations,
                        "harness": result.spec.name,
                        "stopped_reason": result.response.stopped_reason,
                        "pending_approvals": pending_approvals,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(result.content)
            if result.response.stopped_reason == "needs_approval" and pending_approvals:
                click.echo("Approval required:")
                for entry in pending_approvals:
                    tool = entry.get("tool_name") or "<unknown>"
                    args_preview = str(entry.get("arguments", {}))
                    if len(args_preview) > 120:
                        args_preview = args_preview[:117] + "..."
                    click.echo(f"  [{entry.get('index', 0)}] {tool} {args_preview}")
                click.echo("Use the TUI to approve or reject the paused tool call.")
        return result

    async def _run_adapter():
        from superqode.harness import (
            HarnessCreateRequest,
            HarnessProtocolController,
            create_harness_store,
            load_harness_adapter,
        )

        adapter = load_harness_adapter(reference)
        resolved_store_kind = store_kind or "file"
        store_path = (
            Path(".superqode/sessions/store.sqlite3")
            if resolved_store_kind == "sqlite"
            else Path(".superqode/sessions")
        )
        store = create_harness_store(resolved_store_kind, store_path)
        controller = HarnessProtocolController([adapter], store=store)
        if session_id and store.get_session(session_id) is not None:
            session = await controller.resume(session_id)
        else:
            session = await controller.create(
                HarnessCreateRequest(
                    harness_id=adapter.descriptor.id,
                    provider=provider,
                    model=model_name,
                    working_directory=working_dir,
                    session_id=session_id,
                )
            )
        events = []
        async for event in controller.send(session, prompt):
            events.append(event)
            if stream:
                if json_output:
                    click.echo(json.dumps(event.to_dict()))
                elif event.type == "message.delta":
                    click.echo(event.data.get("text", ""), nl=False)
        terminal = events[-1] if events else None
        if terminal is None or terminal.type != "run.completed":
            detail = terminal.data.get("error") if terminal is not None else "no events"
            raise RuntimeError(f"Harness run failed: {detail}")
        assistant = next(
            (
                event
                for event in reversed(events)
                if event.type == "message.created" and event.data.get("role") == "assistant"
            ),
            None,
        )
        content = str(assistant.data.get("content") or "") if assistant else ""
        if stream:
            if not json_output:
                click.echo()
            return events
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "content": content,
                        "session_id": session.session_id,
                        "run_id": terminal.run_id,
                        "harness": adapter.descriptor.id,
                        "events": [event.to_dict() for event in events],
                    },
                    indent=2,
                )
            )
        else:
            click.echo(content)
            click.echo(f"\nRun: {terminal.run_id}  Session: {session.session_id}")
        return events

    try:
        asyncio.run(_run_adapter() if reference else _run_spec())
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc), "success": False}, indent=2))
        else:
            click.echo(f"Error: {exc}", err=True)
        raise click.Abort() from exc


@harness.command("events")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--after", type=int, default=0, show_default=True, help="First event index")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_events(run_id, store_path, after, json_output):
    """Show normalized events for a harness run."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        events = store.get_events(run_id, after=after)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = [event.to_dict() for event in events]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for index, event in enumerate(events, start=after):
        preview = (
            event.data.get("text") or event.data.get("status") or event.data.get("error") or ""
        )
        preview = str(preview).replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        suffix = f"  {preview}" if preview else ""
        click.echo(f"{index:04d}  {event.type}{suffix}")


@harness.command("runs")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by session id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_runs(store_path, session_id, json_output):
    """List persisted harness runs."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    runs = store.list_runs(session_id=session_id)
    payload = [run.to_dict() for run in runs]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not runs:
        click.echo("No harness runs found.")
        return
    for run in runs[:25]:
        workflow = " workflow" if run.metadata.get("workflow") else ""
        click.echo(
            f"{run.run_id}  {run.status:<14}  {run.harness:<22}  "
            f"{run.runtime:<14}  {run.prompt_preview}{workflow}"
        )
