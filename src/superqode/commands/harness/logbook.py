"""Harness failure-logbook commands."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.group("logbook")
def harness_logbook():
    """Manage the file-backed self-improvement logbook."""


@harness_logbook.command("update")
@click.option(
    "--from-failures",
    "failure_reports",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Failure report from `harness mine-failures`",
)
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_update(failure_reports, logbook_dir, json_output):
    """Merge mined failures into the self-improvement logbook."""
    from superqode.harness import update_logbook_from_failures

    if not failure_reports:
        raise click.ClickException("Pass at least one --from-failures report.")
    try:
        payload = update_logbook_from_failures(
            failure_report_paths=failure_reports,
            logbook_dir=logbook_dir,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(
        "Logbook updated: "
        f"patterns={payload['patterns']} added={payload['added']} updated={payload['updated']}"
    )
    click.echo(f"Wrote: {payload['failure_patterns_path']}")


@harness_logbook.command("show")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_show(logbook_dir, json_output):
    """Show the self-improvement logbook."""
    from superqode.harness import read_logbook, render_logbook

    try:
        payload = read_logbook(logbook_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_logbook(payload))


@harness_logbook.command("export")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write markdown evidence to this file instead of stdout",
)
def harness_logbook_export(logbook_dir, output_path):
    """Export the logbook as optimizer trace-evidence markdown."""
    from superqode.harness import logbook_to_markdown, read_logbook

    try:
        markdown = logbook_to_markdown(read_logbook(logbook_dir))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path:
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        click.echo(f"Wrote: {target}")
        return
    click.echo(markdown.rstrip())


@harness_logbook.command("prune")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--min-count", default=1, show_default=True, type=int)
@click.option("--max-patterns", default=None, type=int)
@click.option(
    "--keep-status",
    "keep_statuses",
    multiple=True,
    default=("active", "pinned"),
    show_default=True,
    help="Status to retain; repeatable",
)
@click.option("--dry-run", is_flag=True, help="Report pruning without writing")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_prune(
    logbook_dir, min_count, max_patterns, keep_statuses, dry_run, json_output
):
    """Prune stale or low-confidence self-improvement memory."""
    from superqode.harness import prune_logbook

    try:
        payload = prune_logbook(
            logbook_dir=logbook_dir,
            min_count=min_count,
            max_patterns=max_patterns,
            keep_statuses=tuple(keep_statuses),
            dry_run=dry_run,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    action = "Would prune" if dry_run else "Pruned"
    click.echo(f"{action}: {payload['pruned']} pattern(s); kept {payload['after']}.")
