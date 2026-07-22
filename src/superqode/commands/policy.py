"""Inspect, initialize, and simulate layered governance policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from superqode.governance import POLICY_PHASES, PolicyRequest, load_governance, write_project_policy


@click.group()
def policy() -> None:
    """Explain contextual policy and credential-safe execution controls."""


@policy.command("init")
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
)
@click.option("--force", is_flag=True, help="Replace an existing project policy")
def policy_init(repo: Path, force: bool) -> None:
    """Create .superqode/policy.yaml with secure builder defaults."""
    try:
        path = write_project_policy(repo, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Governance policy: {path}")


@policy.command("show")
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def policy_show(repo: Path, json_output: bool) -> None:
    """Show merged layers, redacted credential bindings, and guardrails."""
    try:
        payload = load_governance(repo).to_public_dict()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    guardrails = payload["guardrails"]
    click.echo(f"layers: {len(payload['policy']['layers'])}")
    for layer in payload["policy"]["layers"]:
        click.echo(
            f"- {layer['name']}: {layer['source']} "
            f"({len(layer['rules'])} rule(s))"
        )
    click.echo(
        f"shell_env={guardrails['shell_env']} "
        f"network_strict={str(guardrails['network_strict']).lower()} "
        f"block_model_credentials={str(guardrails['block_model_credentials']).lower()}"
    )
    click.echo(f"credential bindings: {len(payload['credentials']['bindings'])}")


@policy.command("explain")
@click.argument("phase", type=click.Choice(list(POLICY_PHASES)))
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
)
@click.option("--tool", default="")
@click.option("--tool-group", default="")
@click.option("--host", default="")
@click.option("--risk", default="")
@click.option("--provider", default="")
@click.option("--runtime", default="")
@click.option("--arg", "arguments", multiple=True, help="Projected key=value argument")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def policy_explain(
    phase: str,
    repo: Path,
    tool: str,
    tool_group: str,
    host: str,
    risk: str,
    provider: str,
    runtime: str,
    arguments: tuple[str, ...],
    json_output: bool,
) -> None:
    """Explain a read-only projected policy decision."""
    try:
        bundle = load_governance(repo)
        request = PolicyRequest(
            phase=phase,
            tool=tool,
            tool_group=tool_group,
            host=host,
            risk=risk,
            provider=provider,
            runtime=runtime,
            arguments=_arguments(arguments),
        )
        decision = bundle.engine.evaluate(request)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload: dict[str, Any] = {
        "request": request.to_dict(),
        "decision": decision.to_dict(),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"{decision.action.upper()}  phase={phase} tool={tool or '-'}")
    click.echo(decision.reason)
    for match in decision.matches:
        click.echo(f"- {match.layer}/{match.rule_id}: {match.action} ({match.source})")


def _arguments(values: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"policy argument must use key=value: {value}")
        key, item = value.split("=", 1)
        if not key.strip():
            raise ValueError("policy argument key cannot be empty")
        result[key.strip()] = item
    return result


__all__ = ["policy"]
