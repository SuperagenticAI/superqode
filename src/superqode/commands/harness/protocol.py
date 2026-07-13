"""Harness Protocol v1 discovery and offline conformance commands."""

import asyncio
import json
from pathlib import Path

import click

from ._group import harness


@harness.group("protocol")
def harness_protocol():
    """Inspect and validate the Harness Protocol v1 control plane."""


@harness_protocol.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_protocol_list(json_output):
    """List built-in and installed Python harnesses."""
    from superqode.harness import discover_harness_adapters

    rows = [entry.to_dict() for entry in discover_harness_adapters()]
    if json_output:
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    click.echo(f"{'ID':<22} {'SOURCE':<24} STATUS")
    for row in rows:
        status = "ready" if row["available"] else str(row["issue"] or "unavailable")
        click.echo(f"{str(row['id']):<22} {str(row['source']):<24} {status}")


@harness_protocol.command("describe")
@click.argument("adapter_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_protocol_describe(adapter_id, json_output):
    """Describe the protocol or one of its reference adapter types."""
    from superqode.harness import (
        ACPHarnessProtocolAdapter,
        CANONICAL_EVENT_TYPES,
        HARNESS_PROTOCOL_VERSION,
        CoreHarnessProtocolAdapter,
        DirectPythonHarnessAdapter,
        get_harness_template,
        load_harness_adapter,
    )

    async def handler(message, session):
        del session
        return message.content

    adapters = (
        CoreHarnessProtocolAdapter(get_harness_template("coding")),
        DirectPythonHarnessAdapter("python", handler, name="Direct Python harness"),
        ACPHarnessProtocolAdapter("<agent command>"),
    )
    descriptors = {adapter.descriptor.id: adapter.descriptor for adapter in adapters}
    if adapter_id and adapter_id not in descriptors:
        try:
            adapter = load_harness_adapter(adapter_id)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        descriptors = {adapter.descriptor.id: adapter.descriptor}
    payload = {
        "protocol_version": HARNESS_PROTOCOL_VERSION,
        "canonical_event_types": sorted(CANONICAL_EVENT_TYPES),
        "adapters": [
            descriptor.to_dict()
            for key, descriptor in descriptors.items()
            if not adapter_id or key == adapter_id
        ],
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    click.echo(f"Harness Protocol v{HARNESS_PROTOCOL_VERSION}")
    click.echo(f"Canonical events: {len(payload['canonical_event_types'])}")
    for descriptor in payload["adapters"]:
        enabled = [name for name, supported in descriptor["capabilities"].items() if supported]
        click.echo(f"{descriptor['id']}: {descriptor['name']}")
        click.echo(f"  capabilities: {', '.join(enabled) or 'none'}")


@harness_protocol.command("conformance")
@click.argument("harness_id", required=False)
@click.option("--provider", default="conformance", show_default=True)
@click.option("--model", default="deterministic", show_default=True)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=".",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_protocol_conformance(harness_id, provider, model, working_dir, json_output):
    """Check the reference adapter or a named installed harness."""
    from superqode.harness import (
        DirectPythonHarnessAdapter,
        load_harness_adapter,
        render_harness_conformance,
        run_harness_conformance,
    )

    async def handler(message, session):
        del message, session
        return "protocol-ok"

    adapter = (
        load_harness_adapter(harness_id)
        if harness_id
        else DirectPythonHarnessAdapter(
            "reference-python",
            handler,
            name="Reference Python harness",
        )
    )
    report = asyncio.run(
        run_harness_conformance(
            adapter,
            provider=provider,
            model=model,
            working_directory=working_dir,
        )
    )
    if json_output:
        click.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(render_harness_conformance(report))
    if not report.passed:
        raise click.ClickException("Harness Protocol conformance failed")
