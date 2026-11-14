"""Run typed decision packs and inspect recorded SystemOne evidence."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("decision-providers")
def decision_providers():
    """List supported decision engines without making network requests."""
    from superqode.systemone.providers import provider_rows

    click.echo(json.dumps(provider_rows(), indent=2))


@harness.command("decision")
@click.option(
    "--provider",
    type=click.Choice(["typesafe", "google", "openai"]),
    default="typesafe",
    show_default=True,
)
@click.option("--model", default=None)
@click.option("--pack", default="factory_route", show_default=True)
@click.option(
    "--prompt",
    "-p",
    required=True,
    help="Text or JSON state. This explicit command makes a metered decision request.",
)
@click.option("--timeout-ms", type=click.IntRange(min=1, max=60000), default=5000)
@click.option(
    "--record-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Opt in to private, redacted API records, including failures and retries",
)
def decision(provider, model, pack, prompt, timeout_ms, record_dir):
    """Evaluate a decision pack using your selected provider's API key."""
    import asyncio
    from types import SimpleNamespace
    from superqode.systemone.config import build_client, resolve_systemone, SELECTION_ENV
    from superqode.systemone.providers import get_provider
    from superqode.systemone.pack import load_pack
    from superqode.systemone.decision import evaluate_decision, parse_state
    from superqode.systemone.client import SystemOneError

    try:
        definition = get_provider(provider)
        import os

        settings = resolve_systemone(
            explicit=SimpleNamespace(
                enabled=True,
                client="live",
                provider=provider,
                model=model or definition.model,
                timeout_ms=timeout_ms,
                record_dir=str(record_dir or ""),
            ),
            environ={key: value for key, value in os.environ.items() if key not in SELECTION_ENV},
        )
        client = build_client(settings)
        if client is None:
            raise ValueError(
                f"Decision engine unavailable ({settings.skip_reason}); set {settings.api_key_env}"
            )
        questions = load_pack(pack)
        result = asyncio.run(evaluate_decision(client, parse_state(prompt, questions), questions))
        click.echo(result.model_dump_json(indent=2))
    except (ValueError, OSError, SystemOneError) as exc:
        raise click.ClickException(str(exc)) from exc


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
