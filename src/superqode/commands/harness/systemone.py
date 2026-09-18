"""Inspect Jev shadow evidence without live model calls."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("decision-report")
@click.argument("trace_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--reference", type=click.Choice(["policyAction", "humanAction"]), default="policyAction"
)
@click.option(
    "--allow-confidence",
    multiple=True,
    type=click.FloatRange(0, 1),
    help="Recompose recorded answers at this confidence threshold; repeat to compare.",
)
def harness_decision_report(
    trace_dir: Path, reference: str, allow_confidence: tuple[float, ...]
) -> None:
    """Compare intended decisions with policy or explicit human labels (JSON)."""
    from superqode.systemone.audit import confidence_sweep, disagreement_report

    try:
        events = [json.loads(path.read_text()) for path in sorted(trace_dir.glob("*.json"))]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("trace must be a JSON object")
        report = disagreement_report(events, reference)
        if allow_confidence:
            report["confidence_sweep"] = confidence_sweep(events, allow_confidence, reference)
        click.echo(json.dumps(report, indent=2))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise click.ClickException(f"Invalid decision traces: {exc}") from exc
