"""Harness candidate audit and ledger commands."""

import json
from pathlib import Path

import click

from ._group import harness
from .evaluation import _csv_tuple


@harness.command("audit-candidate")
@click.option("--base", "base_spec", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--candidate",
    "candidate_spec",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Candidate `harness eval --json` result for held-in/held-out gates",
)
@click.option("--surfaces", default=None, help="Comma-separated editable surfaces")
@click.option("--protected-surfaces", default=None, help="Comma-separated protected surfaces")
@click.option("--max-candidate-edits", default=None, type=int)
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--require-heldout", is_flag=True, help="Require a passing held-out eval gate")
@click.option(
    "--allow-protected-changes",
    is_flag=True,
    help="Do not reject solely because protected surfaces changed",
)
@click.option("--allow-ungated", is_flag=True, help="Allow apply decisions without eval gates")
@click.option("--record", is_flag=True, help="Append the audit decision to the candidate ledger")
@click.option("--notes", default="", help="Notes to store when --record is used")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_audit_candidate(
    base_spec,
    candidate_spec,
    tasks_path,
    eval_results,
    surfaces,
    protected_surfaces,
    max_candidate_edits,
    ledger_path,
    require_heldout,
    allow_protected_changes,
    allow_ungated,
    record,
    notes,
    json_output,
):
    """Audit a candidate HarnessSpec before accepting it."""
    from superqode.harness import (
        audit_harness_candidate,
        record_candidate_audit,
        render_candidate_audit,
    )

    try:
        audit = audit_harness_candidate(
            base_spec_path=base_spec,
            candidate_spec_path=candidate_spec,
            tasks_path=tasks_path,
            eval_result_paths=eval_results,
            editable_surfaces=_csv_tuple(surfaces),
            protected_surfaces=_csv_tuple(protected_surfaces),
            max_candidate_edits=max_candidate_edits,
            ledger_path=ledger_path,
            require_heldout=require_heldout,
            allow_protected_changes=allow_protected_changes,
            allow_ungated=allow_ungated,
        )
        recorded = (
            record_candidate_audit(audit, ledger_path=ledger_path, notes=notes) if record else None
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**audit, "recorded": recorded}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_candidate_audit(audit))
    if recorded:
        click.echo(f"Recorded: {recorded['ledger_path']}")


@harness.group("candidates")
def harness_candidates():
    """Manage native self-improvement candidate attempts."""


@harness_candidates.command("list")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_candidates_list(ledger_path, json_output):
    """List recorded self-improvement candidates."""
    from superqode.harness import read_candidate_ledger, render_candidate_ledger

    try:
        ledger = read_candidate_ledger(ledger_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(ledger, indent=2))
        return
    click.echo(render_candidate_ledger(ledger))


@harness_candidates.command("show")
@click.argument("candidate_id")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_candidates_show(candidate_id, ledger_path, json_output):
    """Show one recorded self-improvement candidate."""
    from superqode.harness import read_candidate_ledger

    try:
        ledger = read_candidate_ledger(ledger_path)
        matches = [
            item
            for item in ledger.get("candidates") or []
            if item.get("candidate_id") == candidate_id or item.get("attempt_id") == candidate_id
        ]
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if not matches:
        raise click.ClickException(f"Candidate not found: {candidate_id}")
    payload = matches[-1]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Candidate: {payload.get('candidate_id') or '-'}")
    click.echo(f"Decision: {payload.get('decision') or '-'}")
    click.echo(f"Surfaces: {', '.join(payload.get('changed_surfaces') or []) or '-'}")
    for violation in payload.get("violations") or []:
        click.echo(f"- {violation.get('code')}: {violation.get('message')}")


@harness_candidates.command("export")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
def harness_candidates_export(ledger_path, output_path):
    """Export candidate history as optimizer trace-evidence markdown."""
    from superqode.harness import candidate_ledger_to_markdown, read_candidate_ledger

    try:
        markdown = candidate_ledger_to_markdown(read_candidate_ledger(ledger_path))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path:
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        click.echo(f"Wrote: {target}")
        return
    click.echo(markdown.rstrip())
