"""Native Harness² task refinement commands."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from uuid import uuid4

import click

from ._group import harness


@harness.group("refine", invoke_without_command=True)
@click.option("--spec", default="codegem", show_default=True, help="Harness name or YAML path")
@click.option("--task-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--prompt", default=None, help="Task text instead of --task-file")
@click.option(
    "--source", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path(".")
)
@click.option("--output", type=click.Path(path_type=Path))
@click.option("--provider", default="ollama", show_default=True)
@click.option(
    "--model", default=None, help="Explicit solver/editor model, or the harness primary model"
)
@click.option("--method", type=click.Choice(["harness2"]), default="harness2")
@click.option("--mode", type=click.Choice(["parallel", "sequential"]), default=None)
@click.option("--k", type=click.IntRange(1, 4), default=None)
@click.option("--max-parallel", type=click.IntRange(1, 4), default=None)
@click.option("--max-seconds", type=click.FloatRange(min=0.1), default=None)
@click.option("--max-sessions", type=click.IntRange(min=1), default=None)
@click.option("--max-turns", type=click.IntRange(1, 128), default=None)
@click.option("--max-output-tokens", type=click.IntRange(128, 32768), default=None)
@click.option(
    "--check", multiple=True, help="Explicit public check command; parsed as argv without a shell"
)
@click.option("--protect", multiple=True, help="Relative source file the solver must not change")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_context
def harness_refine(
    ctx,
    spec,
    task_file,
    prompt,
    source,
    output,
    provider,
    model,
    method,
    mode,
    k,
    max_parallel,
    max_seconds,
    max_sessions,
    max_turns,
    max_output_tokens,
    check,
    protect,
    dry_run,
    json_output,
):
    """Refine a task harness; inspect/cancel/resume/apply saved jobs with subcommands."""
    if ctx.invoked_subcommand:
        return
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.refinement import RefinementCoordinator, RefinementRequest
    from superqode.harness.refinement.models import refinement_options

    try:
        if bool(task_file) == bool(prompt):
            raise ValueError("Supply exactly one of --task-file or --prompt")
        source = source.expanduser().resolve()
        selected = resolve_harness(spec, root=source).spec
        settings = refinement_options(selected)
        settings.update(
            {
                key: value
                for key, value in {
                    "mode": mode,
                    "k": k,
                    "max_parallel": max_parallel,
                    "max_wall_seconds": max_seconds,
                    "max_sessions": max_sessions,
                    "max_turns": max_turns,
                    "max_output_tokens": max_output_tokens,
                }.items()
                if value is not None
            }
        )
        if not model:
            primary = selected.model_policy.primary or ""
            if "/" in primary:
                provider, model = primary.split("/", 1)
            else:
                raise ValueError("Supply --model for the local Gemma or configured model route")
        request = RefinementRequest(
            task=task_file.read_text() if task_file else prompt,
            source=source,
            output=(output or source / ".superqode" / "refinements" / uuid4().hex[:12]).resolve(),
            spec=selected,
            provider=provider,
            model=model,
            **settings,
            checks=tuple(tuple(shlex.split(value)) for value in check),
            protected_paths=tuple(protect),
        )
        if dry_run:
            payload = request.plan()
        else:

            def progress(event):
                if not json_output and event["type"] in {
                    "stage.started",
                    "stage.completed",
                    "stage.reused",
                    "candidate.rejected",
                }:
                    click.echo(f"{event['type']}: {event['data'].get('label', '')}", err=True)

            payload = asyncio.run(RefinementCoordinator(request, callback=progress).run())
        click.echo(
            json.dumps(payload, indent=2) if json_output or dry_run else render_result(payload)
        )
        if payload.get("status") not in {None, "succeeded"}:
            raise click.exceptions.Exit(1)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


def render_result(result):
    usage = result.get("usage", {})
    cost = usage.get("cost_usd")
    return (
        f"Harness²: {result.get('status', 'unknown')}\n"
        f"Validation: {result.get('validation', 'not completed')}\n"
        f"Selected: {result.get('chosen_label', '-')}\n"
        f"New sessions: {result.get('new_sessions', 0)}; cost USD: {cost if cost is not None else 'unknown'}\n"
        f"Output: {result.get('output', '')}\n{result.get('error', '')}"
    ).rstrip()


@harness_refine.command("inspect")
@click.argument("output", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def refine_inspect(output, json_output):
    from superqode.harness.refinement import inspect_refinement

    try:
        payload = inspect_refinement(output)
        click.echo(
            json.dumps(payload, indent=2) if json_output else render_result(payload["result"])
        )
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc


@harness_refine.command("cancel")
@click.argument("output", type=click.Path(exists=True, file_okay=False, path_type=Path))
def refine_cancel(output):
    from superqode.harness.refinement import cancel_refinement

    try:
        cancel_refinement(output)
        click.echo("Cancellation requested")
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@harness_refine.command("resume")
@click.argument("output", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--retry-interrupted",
    is_flag=True,
    help="Retry only after reconciling uncertain prior tool effects",
)
@click.option("--max-seconds", type=click.FloatRange(min=0.1), default=900)
@click.option("--max-sessions", type=click.IntRange(min=1), default=64)
@click.option("--json", "json_output", is_flag=True)
def refine_resume(output, retry_interrupted, max_seconds, max_sessions, json_output):
    from superqode.harness.refinement import RefinementCoordinator
    from superqode.harness.refinement.models import resume_request

    try:
        request = resume_request(
            output.resolve(),
            retry_interrupted=retry_interrupted,
            max_wall_seconds=max_seconds,
            max_sessions=max_sessions,
        )
        result = asyncio.run(RefinementCoordinator(request).run())
        click.echo(json.dumps(result, indent=2) if json_output else render_result(result))
        if result["status"] != "succeeded":
            raise click.exceptions.Exit(1)
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc


@harness_refine.command("apply")
@click.argument("output", type=click.Path(exists=True, file_okay=False, path_type=Path))
def refine_apply(output):
    """Explicitly apply the checked patch to its unchanged original source."""
    from superqode.harness.refinement import apply_refinement

    try:
        click.echo(json.dumps(apply_refinement(output), indent=2))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
