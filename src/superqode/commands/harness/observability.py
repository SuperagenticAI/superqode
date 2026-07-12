"""Harness observability commands."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.group("observability")
def harness_observability():
    """Inspect and export harness observability artifacts."""


@harness_observability.command("status")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_observability_status(spec_path, json_output):
    """Show local and optional external observability sink status."""
    from superqode.harness import (
        load_harness_spec,
        observability_status,
        render_observability_status,
    )

    spec = load_harness_spec(spec_path) if spec_path else None
    rows = observability_status(spec)
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(render_observability_status(rows))


@harness_observability.command("export")
@click.argument("run_id")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for JSON/JSONL observability artifacts",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_observability_export(run_id, spec_path, store_path, output_dir, json_output):
    """Export a harness run tree to local JSONL and optional configured sinks."""
    from superqode.harness import (
        FileHarnessStore,
        export_harness_observability,
        load_harness_spec,
        render_observability_export,
    )

    store = FileHarnessStore(store_path)
    spec = load_harness_spec(spec_path) if spec_path else None
    try:
        payload = export_harness_observability(
            store,
            run_id,
            output_dir=output_dir,
            spec=spec,
        )
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_observability_export(payload))
