"""`sq gauge` — emit and check Agent Quality Records.

The record format is published at github.com/SuperagenticAI/supergauge. These
commands project state SuperQode already holds into it; `gauge gate` is the verb
that belongs in a pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from superqode.gauge import LEVELS, check_levels, highest_level


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    import yaml

    class RecordLoader(yaml.SafeLoader):
        """Keeps RFC 3339 timestamps as strings; the record carries them as text."""

    RecordLoader.yaml_implicit_resolvers = {
        key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return yaml.load(text, Loader=RecordLoader)


def _dump(record: dict, path: Path | None, as_json: bool) -> str:
    if as_json or (path and path.suffix == ".json"):
        return json.dumps(record, indent=2)
    import yaml

    return yaml.safe_dump(record, sort_keys=False, default_flow_style=False, width=100)


@click.group()
def gauge() -> None:
    """Emit and check Agent Quality Records."""


@gauge.command("run")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--tasks", "tasks_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--provider", default="ollama", show_default=True)
@click.option("--model", default="", help="Model id; falls back to the spec's model policy.")
@click.option(
    "--repeat",
    "repeat",
    default=1,
    show_default=True,
    help="Independent attempts per task. Values above 1 produce pass^k and pass@k.",
)
@click.option("--profile", "profile_id", default="sg/coding-agent", show_default=True)
@click.option("--tier", type=click.Choice(["T0", "T1", "T2"]), default="T1", show_default=True)
@click.option(
    "--sealed/--unsealed",
    default=False,
    help="Assert the held-out split was closed to anything that tunes.",
)
@click.option("--canary", "canary_ids", multiple=True, help="Contamination probe task ids.")
@click.option(
    "--evaluator-independent",
    is_flag=True,
    help="Assert the grader saw only the artifact and resulting state.",
)
@click.option(
    "--ledger",
    "ledger_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Event ledger to reference. Defaults to .superqode/harness-protocol.",
)
@click.option(
    "--candidate",
    "candidate_id",
    default="",
    help="Promotion candidate id; the record takes its actor and rollback target from it.",
)
@click.option("--no-sources", is_flag=True, help="Skip the promotion, policy and ledger readers.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.option("--live/--dry-run", default=False, show_default=True)
def gauge_run(
    spec_path: Path,
    tasks_path: Path,
    provider: str,
    model: str,
    repeat: int,
    profile_id: str,
    tier: str,
    sealed: bool,
    canary_ids: tuple[str, ...],
    evaluator_independent: bool,
    ledger_dir: Path | None,
    candidate_id: str,
    no_sources: bool,
    out_path: Path | None,
    as_json: bool,
    live: bool,
) -> None:
    """Evaluate a harness and emit a record.

    Measures appear only where the run produced them. A run without --repeat
    carries no reliability measure and stops at L2, which is the honest result.
    """
    import asyncio

    from superqode.gauge.record import record_from_eval
    from superqode.harness.eval import load_eval_tasks, run_harness_eval
    from superqode.harness.loader import load_harness_spec

    spec = load_harness_spec(spec_path)
    task_file = load_eval_tasks(tasks_path)
    tasks = task_file["tasks"]

    resolved_model = model or getattr(getattr(spec, "model_policy", None), "model", "") or ""

    runs = []
    for attempt in range(max(1, repeat)):
        runs.append(
            asyncio.run(
                run_harness_eval(
                    spec_paths=[spec_path],
                    tasks_path=tasks_path,
                    provider=provider,
                    model=resolved_model,
                    live=live,
                )
            )
        )
        if not live:
            break  # a dry run is deterministic; repeating it measures nothing

    from superqode.gauge import sources as gauge_sources

    promotion: dict = {}
    decisions: list[dict] = []
    ledger: dict = {}
    if not no_sources:
        promotion = gauge_sources.promotion_evidence(base_spec=spec_path, candidate_id=candidate_id)
        decisions = gauge_sources.policy_decisions_from_ledger(
            ledger_dir or gauge_sources.DEFAULT_LEDGER_DIR
        ) or gauge_sources.policy_decisions(repository=".")
        ledger = gauge_sources.ledger_evidence(ledger_dir or gauge_sources.DEFAULT_LEDGER_DIR)

    record = record_from_eval(
        eval_result=runs[0],
        tasks=tasks,
        spec=spec,
        spec_path=spec_path,
        profile_id=profile_id,
        tier=tier,
        sealed=sealed,
        canary_ids=list(canary_ids),
        evaluator_independent=evaluator_independent,
        policy_decisions=decisions or None,
        ledger=ledger.get("ledger"),
        ledger_events=ledger.get("events"),
        actor=promotion.get("actor"),
    )

    # A promotion supplies the way back, which is what L4 asks for.
    if promotion.get("rolls_back_to"):
        record.decision["rolls_back_to"] = promotion["rolls_back_to"]

    if live and len(runs) > 1:
        _add_reliability(record, runs)

    payload = record.to_dict()
    text = _dump(payload, out_path, as_json)
    if out_path:
        out_path.write_text(text, encoding="utf-8")
        click.echo(f"record written: {out_path}")
        click.echo(f"highest level met: {highest_level(payload) or 'none'}")
    else:
        click.echo(text)


def _add_reliability(record, runs: list[dict]) -> None:
    """Add pass^k and pass@k across independent attempts."""
    per_task: dict[str, list[bool]] = {}
    for run in runs:
        variant = (run.get("variants") or [{}])[0]
        for task in variant.get("tasks") or []:
            if task.get("status") in {"passed", "failed"}:
                per_task.setdefault(str(task["id"]), []).append(task["status"] == "passed")

    complete = {tid: results for tid, results in per_task.items() if len(results) == len(runs)}
    if not complete:
        return

    k = len(runs)
    all_pass = sum(1 for r in complete.values() if all(r))
    any_pass = sum(1 for r in complete.values() if any(r))
    n = len(complete)
    record.add_measure("reliability.pass_hat_k", round(all_pass / n, 3), k=k, n=n)
    record.add_measure("reliability.pass_at_k", round(any_pass / n, 3), k=k, n=n)


@gauge.command("gate")
@click.argument("record_path", type=click.Path(exists=True, path_type=Path))
@click.option("--level", type=click.Choice(list(LEVELS)), default="L2", show_default=True)
@click.option("--quiet", is_flag=True)
def gauge_gate(record_path: Path, level: str, quiet: bool) -> None:
    """Exit non-zero when the record does not reach LEVEL. The CI verb."""
    record = _load(record_path)
    failures = check_levels(record)
    reached = highest_level(record)

    if not quiet:
        for lv in LEVELS:
            click.echo(f"{lv}  {'pass' if not failures[lv] else 'fail'}")
            for problem in failures[lv]:
                click.echo(f"      {problem}")
        click.echo(f"\nhighest level met: {reached or 'none'}")

    if reached is None or LEVELS.index(reached) < LEVELS.index(level):
        raise SystemExit(1)


@gauge.command("show")
@click.argument("record_path", type=click.Path(exists=True, path_type=Path))
def gauge_show(record_path: Path) -> None:
    """Print the record as a scorecard."""
    record = _load(record_path)
    subject = record.get("subject") or {}
    profile = record.get("profile") or {}
    decision = record.get("decision") or {}
    task_set = record.get("task_set") or {}

    click.echo(f"\n  {subject.get('agent', 'unknown')}")
    click.echo(
        f"  profile {profile.get('id')}@{profile.get('version')}  tier {profile.get('tier')}"
    )
    click.echo(f"  harness {str(subject.get('harness_digest', ''))[:23]}...")

    authority = subject.get("authority") or {}
    if authority:
        bits = [f"{k}={v}" for k, v in authority.items() if k != "capabilities"]
        click.echo(f"  authority {' '.join(bits) or 'recorded'}")

    click.echo(
        f"\n  task set  held-in {task_set.get('held_in', 0)}  "
        f"held-out {task_set.get('held_out', 0)}  "
        f"sealed {'yes' if task_set.get('sealed') else 'no'}"
    )

    click.echo("\n  measures")
    for measure in record.get("measures") or []:
        extra = " ".join(f"{k}={v}" for k, v in measure.items() if k not in {"id", "value"})
        click.echo(f"    {measure['id']:<38} {measure['value']!s:<8} {extra}")

    gates = record.get("gates") or []
    if gates:
        click.echo("\n  gates")
        for gate in gates:
            mark = "PASS" if gate.get("result") == "pass" else "FAIL"
            floor = f" floor={gate['floor']}" if gate.get("floor") is not None else ""
            click.echo(f"    [{mark}] {gate['id']}{floor}")

    click.echo(
        f"\n  verdict {decision.get('verdict', 'none')}  by {decision.get('actor', 'unknown')}"
    )
    click.echo(f"  level   {highest_level(record) or 'none'}\n")


@gauge.command("verify")
@click.argument("record_path", type=click.Path(exists=True, path_type=Path))
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
def gauge_verify(record_path: Path, spec_path: Path | None) -> None:
    """Recompute what can be recomputed without re-running the agent."""
    from superqode.gauge.record import sha256_file

    record = _load(record_path)
    subject = record.get("subject") or {}
    problems: list[str] = []

    if spec_path:
        actual = sha256_file(spec_path)
        recorded = str(subject.get("harness_digest") or "")
        if actual != recorded:
            problems.append(
                f"harness digest differs\n    recorded {recorded}\n    actual   {actual}"
            )
        else:
            click.echo("harness digest matches")

    evidence = (record.get("assurance") or {}).get("evidence") or {}
    ledger = evidence.get("ledger")
    if ledger:
        if Path(ledger).exists():
            click.echo(f"ledger present: {ledger}")
        else:
            problems.append(f"ledger absent: {ledger}")

    for problem in problems:
        click.echo(f"FAIL {problem}")
    if problems:
        raise SystemExit(1)
    click.echo("verified what is checkable offline; replay the ledger for L4")
