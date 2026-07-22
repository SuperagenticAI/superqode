"""Reproducible HarnessBench command surface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click

from ._group import harness


@harness.command("bench")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="New directory for manifest, raw runs, scorecard, and checksums",
)
@click.option("--live/--dry-run", default=None, help="Override the manifest live setting")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_bench(
    manifest_path: Path,
    output_dir: Path | None,
    live: bool | None,
    json_output: bool,
) -> None:
    """Run a fixed-model, multi-harness reproducibility benchmark."""
    from superqode.harness.bench import (
        default_harness_bench_output,
        load_harness_bench_manifest,
        run_harness_bench,
    )

    try:
        manifest = load_harness_bench_manifest(manifest_path)
        destination = output_dir or default_harness_bench_output(manifest.bench_id)
        payload = asyncio.run(run_harness_bench(manifest, output_dir=destination, live=live))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"HarnessBench: {payload['status']}")
    click.echo(f"Winner: {payload['winner'] or '-'}")
    click.echo(f"Fingerprint: {payload['fingerprint']}")
    click.echo(f"Scorecard: {payload['scorecard']}")


@harness.command("bench-verify")
@click.argument(
    "output_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_bench_verify(output_dir: Path, json_output: bool) -> None:
    """Verify a HarnessBench package without executing its model calls."""
    from superqode.harness.bench import verify_harness_bench

    try:
        payload = verify_harness_bench(output_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(
            f"HarnessBench {'VALID' if payload['valid'] else 'INVALID'}  "
            f"checked={payload['checked']} fingerprint={payload['fingerprint']}"
        )
        for failure in payload["failures"]:
            click.echo(f"- {failure['path']}: {failure['error']}")
    if not payload["valid"]:
        raise click.exceptions.Exit(1)


__all__ = ["harness_bench", "harness_bench_verify"]
