"""Harness evidence command."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("evidence")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_evidence(run_id, store_path, json_output):
    """Show a readable evidence report for a harness run."""
    from superqode.harness import (
        FileHarnessStore,
        build_harness_evidence,
        render_harness_evidence,
    )

    store = FileHarnessStore(store_path)
    try:
        evidence = build_harness_evidence(store, run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(evidence, indent=2))
        return
    click.echo(render_harness_evidence(evidence))
