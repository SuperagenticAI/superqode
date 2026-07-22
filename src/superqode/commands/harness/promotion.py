"""Guarded HarnessSpec promotion, canary, activation, and rollback commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ._group import harness


@harness.group("promote")
def harness_promote() -> None:
    """Stage, canary, activate, inspect, or roll back HarnessSpecs."""


@harness_promote.command("stage")
@click.option("--base", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option(
    "--candidate", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True
)
@click.option(
    "--tasks", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    required=True,
)
@click.option(
    "--ledger",
    type=click.Path(path_type=Path),
    default=Path(".superqode/self-improve/candidates.jsonl"),
    show_default=True,
)
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option("--actor", required=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_stage(
    base: Path,
    candidate: Path,
    tasks: Path,
    eval_results: tuple[Path, ...],
    ledger: Path,
    registry: Path,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Require audit and held-out gates, then stage a rollback-safe candidate."""
    from superqode.harness import (
        audit_harness_candidate,
        record_candidate_audit,
        stage_harness_promotion,
    )

    try:
        audit = audit_harness_candidate(
            base_spec_path=base,
            candidate_spec_path=candidate,
            tasks_path=tasks,
            eval_result_paths=eval_results,
            ledger_path=ledger,
            require_heldout=True,
        )
        record = record_candidate_audit(
            audit,
            ledger_path=ledger,
            notes=f"promotion stage by {actor}: {reason}",
        )
        if not audit["accepted"]:
            raise ValueError("candidate failed its promotion audit")
        promotion = stage_harness_promotion(
            base_spec=base,
            candidate_spec=candidate,
            audit=audit,
            registry_path=registry,
            actor=actor,
            reason=reason,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {"audit": audit, "candidate_record": record, "promotion": promotion}
    _emit(payload, json_output, f"Staged {promotion['candidate_id']}")


@harness_promote.command("canary")
@click.argument("candidate_id")
@click.option("--percent", type=click.IntRange(1, 99), required=True)
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option("--actor", required=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_canary(
    candidate_id: str,
    percent: int,
    registry: Path,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Route a deterministic percentage of WorkOrders to the candidate."""
    from superqode.harness import start_harness_canary

    try:
        payload = start_harness_canary(
            candidate_id,
            percent=percent,
            registry_path=registry,
            actor=actor,
            reason=reason,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, json_output, f"Canary {candidate_id}: {percent}%")


@harness_promote.command("activate")
@click.argument("candidate_id")
@click.option(
    "--evidence",
    "evidence_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    required=True,
    help="Live held-out HarnessBench scorecard",
)
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
)
@click.option("--actor", required=True)
@click.option("--reason", default="")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_activate(
    candidate_id: str,
    evidence_paths: tuple[Path, ...],
    registry: Path,
    repo: Path,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Activate only after live held-out evidence and contextual policy approval."""
    from superqode.harness import activate_harness_promotion

    try:
        payload = activate_harness_promotion(
            candidate_id,
            evidence_paths=evidence_paths,
            registry_path=registry,
            actor=actor,
            repository=repo,
            reason=reason,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, json_output, f"Activated {candidate_id}")


@harness_promote.command("rollback")
@click.argument("candidate_id")
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option("--actor", required=True)
@click.option("--reason", required=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_rollback(
    candidate_id: str,
    registry: Path,
    actor: str,
    reason: str,
    json_output: bool,
) -> None:
    """Stop a canary or restore the verified pre-promotion snapshot."""
    from superqode.harness import rollback_harness_promotion

    try:
        payload = rollback_harness_promotion(
            candidate_id,
            registry_path=registry,
            actor=actor,
            reason=reason,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, json_output, f"Rolled back {candidate_id}")


@harness_promote.command("status")
@click.argument("candidate_id")
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_status(candidate_id: str, registry: Path, json_output: bool) -> None:
    """Show current promotion state and its append-only history."""
    from superqode.harness import harness_promotion_state

    try:
        payload = harness_promotion_state(candidate_id, registry_path=registry)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, json_output, f"{candidate_id}: {payload['status']}")


@harness_promote.command("select")
@click.argument("base_spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--key", required=True, help="Stable WorkOrder/session routing key")
@click.option(
    "--registry",
    type=click.Path(path_type=Path),
    default=Path(".superqode/harnesses/promotions.jsonl"),
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_promote_select(base_spec: Path, key: str, registry: Path, json_output: bool) -> None:
    """Explain deterministic canary selection for a routing key."""
    from superqode.harness import select_harness_promotion

    try:
        payload = select_harness_promotion(base_spec, key=key, registry_path=registry)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, json_output, f"Selected {payload.get('selected') or 'stable'}")


def _emit(payload: dict, json_output: bool, summary: str) -> None:
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(summary)


__all__ = ["harness_promote"]
