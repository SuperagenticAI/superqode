"""Harness replay, fork, and graph commands."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("replay")
@click.argument("run_id")
@click.option(
    "--execute", is_flag=True, help="Re-run the prompt instead of only showing the replay plan"
)
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--prompt", default=None, help="Exact prompt to replay when the run did not store one"
)
@click.option("--provider", default=None, help="Provider override for --execute")
@click.option("--model", "model_name", default=None, help="Model override for --execute")
@click.option("--runtime", "runtime_name", default=None, help="Runtime override for --execute")
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_replay(
    run_id,
    execute,
    spec_path,
    prompt,
    provider,
    model_name,
    runtime_name,
    sandbox_backend,
    working_dir,
    store_path,
    json_output,
):
    """Show a replay plan for a persisted harness run."""
    import asyncio

    from superqode.harness import (
        FileHarnessStore,
        build_harness_replay_plan,
        create_harness_store,
        init_harness,
        load_harness_spec,
        render_harness_replay_plan,
    )

    store = FileHarnessStore(store_path)
    try:
        plan = build_harness_replay_plan(store, run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if execute:
        if spec_path is None:
            raise click.ClickException("--execute requires --spec <harness.yaml>")
        exact_prompt = prompt or plan.get("prompt") or ""
        if not exact_prompt:
            raise click.ClickException(
                "No full prompt is stored for this run. Pass --prompt or use context.prompt_persistence: full."
            )

        async def _execute():
            spec = load_harness_spec(spec_path)
            replay_store = create_harness_store(
                spec.observability.run_store,
                (
                    Path(spec.context.session_storage) / "store.sqlite3"
                    if spec.observability.run_store == "sqlite"
                    else Path(spec.context.session_storage)
                ),
            )
            kernel = await init_harness(spec, store=replay_store)
            session_obj = await kernel.session()
            run = plan["run"]
            result = await session_obj.prompt(
                exact_prompt,
                provider=provider or run["provider"],
                model=model_name or run["model"],
                runtime=runtime_name or run["runtime"],
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                metadata={"replay_of": run_id},
            )
            payload = {
                "replay_of": run_id,
                "run_id": result.run_id,
                "session_id": result.session_id,
                "content": result.content,
                "stopped_reason": result.response.stopped_reason,
                "tool_calls_made": result.tool_calls_made,
                "iterations": result.iterations,
            }
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(result.content)
                click.echo(f"Replayed {run_id} -> {result.run_id}")

        asyncio.run(_execute())
        return
    if json_output:
        click.echo(json.dumps(plan, indent=2))
        return
    click.echo(render_harness_replay_plan(plan))


@harness.command("fork")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--after", type=int, default=None, help="Copy events through this event index")
@click.option("--session", "session_id", default=None, help="Session id for the forked run")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_fork(run_id, store_path, after, session_id, json_output):
    """Fork a persisted harness run by copying its event prefix."""
    from superqode.harness import FileHarnessStore, fork_harness_run

    store = FileHarnessStore(store_path)
    try:
        fork = fork_harness_run(store, run_id, after=after, session_id=session_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(fork, indent=2))
        return
    click.echo(f"Forked {run_id} -> {fork['run_id']}")
    click.echo(f"Events copied: {fork['events']}")
    click.echo(f"Next: superqode harness events {fork['run_id']}")


@harness.command("graph")
@click.argument("run_id", required=False)
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_graph(run_id, spec_path, store_path, json_output):
    """Show a planned HarnessSpec graph or persisted event graph for a run."""
    from superqode.harness import (
        FileHarnessStore,
        load_harness_spec,
        plan_harness_graph,
        render_harness_graph,
    )

    if spec_path is not None:
        graph = plan_harness_graph(load_harness_spec(spec_path))
        if json_output:
            click.echo(json.dumps(graph.to_dict(), indent=2))
            return
        click.echo("Planned graph:")
        click.echo(render_harness_graph(graph))
        return

    if not run_id:
        raise click.ClickException("Pass a run_id or --spec <harness.yaml>.")

    store = FileHarnessStore(store_path)
    try:
        graph = store.get_event_graph(run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(graph.to_dict(), indent=2))
        return

    click.echo(f"Run: {graph.run_id}")
    click.echo(render_harness_graph(graph))
