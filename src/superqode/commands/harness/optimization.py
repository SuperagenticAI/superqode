"""Harness improvement and optimization commands."""

import json
from pathlib import Path

import click

from ._group import harness
from .evaluation import _csv_tuple


@harness.command("improve")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--from-failures",
    "failure_reports",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Failure report from `harness mine-failures`",
)
@click.option(
    "--logbook-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option(
    "--candidate-ledger",
    "candidate_ledger",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
    help="JSONL ledger for accepted and rejected harness candidates",
)
@click.option(
    "--surfaces",
    default=None,
    help="Comma-separated harness surfaces the optimizer may edit",
)
@click.option(
    "--protected-surfaces",
    default=None,
    help="Comma-separated surfaces requiring explicit human review",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Self-improvement meta-harness project directory to create",
)
@click.option("--backend", default="fake", show_default=True, help="Meta-harness backend")
@click.option("--budget", default=1, show_default=True, type=int, help="Proposal budget")
@click.option("--run-name", default="superqode-improve", show_default=True)
@click.option("--metaharness-bin", default="metaharness", show_default=True)
@click.option("--export-only", is_flag=True, help="Only create the meta-harness project")
@click.option("--apply", "apply_best", is_flag=True, help="Apply the best candidate harness.yaml")
@click.option(
    "--allow-protected-changes",
    is_flag=True,
    help="Allow audited protected-surface changes during --apply",
)
@click.option(
    "--allow-ungated-apply",
    is_flag=True,
    help="Allow --apply without a passing held-out eval gate",
)
@click.option(
    "--output",
    "output_spec",
    type=click.Path(path_type=Path),
    default=None,
    help="Where --apply writes the improved spec (default: --spec path)",
)
@click.option("--force", is_flag=True, help="Overwrite project dir or output spec when needed")
@click.option("--trace-evidence", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to include as trace evidence",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to include as trace evidence",
)
@click.option("--objective", default=None, help="Override the meta-harness objective")
@click.option(
    "--hosted", is_flag=True, help="Pass --hosted to metaharness backends that support it"
)
@click.option("--oss", is_flag=True, help="Pass --oss to metaharness backends that support it")
@click.option("--local-provider", type=click.Choice(["ollama", "lmstudio"]), default=None)
@click.option("--model", "model_name", default=None)
@click.option("--proposal-timeout", type=float, default=None)
@click.option("--search-mode", type=click.Choice(["hill-climb", "frontier"]), default="hill-climb")
@click.option("--proposal-batch-size", default=1, show_default=True, type=int)
@click.option("--selection-policy", type=click.Choice(["single", "pareto"]), default="single")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_improve(
    spec_path,
    tasks_path,
    failure_reports,
    logbook_dir,
    candidate_ledger,
    surfaces,
    protected_surfaces,
    project_dir,
    backend,
    budget,
    run_name,
    metaharness_bin,
    export_only,
    apply_best,
    allow_protected_changes,
    allow_ungated_apply,
    output_spec,
    force,
    trace_evidence,
    test_results,
    eval_results,
    objective,
    hosted,
    oss,
    local_provider,
    model_name,
    proposal_timeout,
    search_mode,
    proposal_batch_size,
    selection_policy,
    json_output,
):
    """Improve a HarnessSpec using mined failures, logbook memory, and regression gates."""
    from superqode.harness import (
        append_self_improve_evidence,
        apply_metaharness_best_spec,
        audit_harness_candidate,
        export_metaharness_project,
        load_eval_tasks,
        load_harness_spec,
        record_candidate_audit,
        render_optimize_payload,
        run_metaharness_project,
        summarize_metaharness_run,
    )

    if hosted and oss:
        raise click.ClickException("--hosted cannot be combined with --oss")
    try:
        source_spec = load_harness_spec(spec_path)
        task_file = load_eval_tasks(tasks_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    editable = _csv_tuple(surfaces) or source_spec.optimization.editable_surfaces
    protected = _csv_tuple(protected_surfaces) or source_spec.optimization.protected_surfaces
    optimization_policy = {
        "enabled": source_spec.optimization.enabled,
        "require_human_apply": source_spec.optimization.require_human_apply,
        "editable_surfaces": list(editable),
        "protected_surfaces": list(protected),
        "heldout_fraction": source_spec.optimization.heldout_fraction,
        "max_candidate_edits": source_spec.optimization.max_candidate_edits,
    }
    resolved_project_dir = project_dir or (
        Path(".superqode") / "self-improve" / Path(spec_path).stem
    )
    try:
        export = export_metaharness_project(
            spec_path=spec_path,
            tasks_path=tasks_path,
            project_dir=resolved_project_dir,
            backend=backend,
            budget=budget,
            objective=objective
            or (
                "Improve this SuperQode HarnessSpec using the supplied mined "
                "failures and logbook. Keep the candidate valid and do not "
                "regress the eval task contract."
            ),
            model=model_name,
            hosted=hosted,
            oss=oss,
            local_provider=local_provider,
            proposal_timeout=proposal_timeout,
            search_mode=search_mode,
            proposal_batch_size=proposal_batch_size,
            selection_policy=selection_policy,
            trace_evidence_path=trace_evidence,
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            force=force,
        )
        self_improve = append_self_improve_evidence(
            evidence_path=export.trace_evidence_path,
            failure_report_paths=failure_reports,
            logbook_dir=logbook_dir,
            candidate_ledger_path=candidate_ledger,
            editable_surfaces=editable,
            protected_surfaces=protected,
            optimization_policy=optimization_policy,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "export": export.to_dict(),
        "self_improve": self_improve,
        "optimization_policy": optimization_policy,
        "task_split_counts": task_file.get("split_counts") or {},
        "run": None,
        "summary": None,
        "candidate_audit": None,
        "candidate_record": None,
        "applied": None,
        "next_steps": [
            f"Inspect evidence: {export.trace_evidence_path}",
            f"Run regression gate: superqode harness eval --spec {spec_path} --tasks {tasks_path}",
            "Audit candidate: "
            f"superqode harness audit-candidate --base {spec_path} "
            f"--candidate <candidate.yaml> --tasks {tasks_path} --require-heldout",
            f"Inspect candidates: {metaharness_bin} inspect {Path(export.project_dir) / 'runs' / run_name}",
        ],
    }
    if int((task_file.get("split_counts") or {}).get("held-out") or 0) > 0:
        payload["next_steps"].insert(
            2,
            "Gate held-out candidate: "
            f"superqode harness eval --spec {spec_path} --variant <candidate.yaml> "
            f"--tasks {tasks_path} --split held-out",
        )
    if not export_only:
        try:
            run = run_metaharness_project(
                project_dir=export.project_dir,
                backend=backend,
                budget=budget,
                run_name=run_name,
                metaharness_bin=metaharness_bin,
                trace_evidence_path=export.trace_evidence_path,
                hosted=hosted,
                oss=oss,
                local_provider=local_provider,
                model=model_name,
                proposal_timeout=proposal_timeout,
                search_mode=search_mode,
                proposal_batch_size=proposal_batch_size,
                selection_policy=selection_policy,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload["run"] = run
        if not run["ok"]:
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(render_optimize_payload(payload))
                if run.get("stderr"):
                    click.echo(run["stderr"], err=True)
            raise click.exceptions.Exit(1)
        try:
            payload["summary"] = summarize_metaharness_run(run["run_dir"])
        except Exception as exc:
            raise click.ClickException(
                f"Meta-harness run completed but summary failed: {exc}"
            ) from exc
        if apply_best:
            best_spec_path = payload["summary"].get("best_spec_path")
            if not best_spec_path:
                raise click.ClickException("No best candidate harness.yaml found to audit/apply.")
            try:
                payload["candidate_audit"] = audit_harness_candidate(
                    base_spec_path=spec_path,
                    candidate_spec_path=best_spec_path,
                    tasks_path=tasks_path,
                    eval_result_paths=eval_results,
                    editable_surfaces=editable,
                    protected_surfaces=protected,
                    max_candidate_edits=source_spec.optimization.max_candidate_edits,
                    ledger_path=candidate_ledger,
                    require_heldout=bool(
                        int((task_file.get("split_counts") or {}).get("held-out") or 0)
                    ),
                    allow_protected_changes=allow_protected_changes,
                    allow_ungated=allow_ungated_apply,
                )
                payload["candidate_record"] = record_candidate_audit(
                    payload["candidate_audit"],
                    ledger_path=candidate_ledger,
                    notes=f"recorded by harness improve run {run_name}",
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
            if not payload["candidate_audit"]["accepted"]:
                if json_output:
                    click.echo(json.dumps(payload, indent=2))
                    raise click.exceptions.Exit(1)
                raise click.ClickException(
                    "Best candidate failed self-improvement audit; "
                    "inspect candidate_audit or rerun with explicit overrides."
                )
            try:
                payload["applied"] = apply_metaharness_best_spec(
                    run_dir=run["run_dir"],
                    output_spec=output_spec or spec_path,
                    force=force or output_spec is None,
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_optimize_payload(payload))


@harness.command("optimize")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Meta-harness project directory to create",
)
@click.option("--backend", default="fake", show_default=True, help="Meta-harness backend")
@click.option("--budget", default=1, show_default=True, type=int, help="Proposal budget")
@click.option("--run-name", default="superqode-optimize", show_default=True)
@click.option("--metaharness-bin", default="metaharness", show_default=True)
@click.option("--export-only", is_flag=True, help="Only create the meta-harness project")
@click.option("--apply", "apply_best", is_flag=True, help="Apply the best candidate harness.yaml")
@click.option(
    "--output",
    "output_spec",
    type=click.Path(path_type=Path),
    default=None,
    help="Where --apply writes the optimized spec (default: --spec path)",
)
@click.option("--force", is_flag=True, help="Overwrite project dir or output spec when needed")
@click.option("--trace-evidence", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to include as trace evidence",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to include as trace evidence",
)
@click.option("--objective", default=None, help="Override the meta-harness objective")
@click.option(
    "--hosted", is_flag=True, help="Pass --hosted to metaharness backends that support it"
)
@click.option("--oss", is_flag=True, help="Pass --oss to metaharness backends that support it")
@click.option("--local-provider", type=click.Choice(["ollama", "lmstudio"]), default=None)
@click.option("--model", "model_name", default=None)
@click.option("--proposal-timeout", type=float, default=None)
@click.option("--search-mode", type=click.Choice(["hill-climb", "frontier"]), default="hill-climb")
@click.option("--proposal-batch-size", default=1, show_default=True, type=int)
@click.option("--selection-policy", type=click.Choice(["single", "pareto"]), default="single")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize(
    spec_path,
    tasks_path,
    project_dir,
    backend,
    budget,
    run_name,
    metaharness_bin,
    export_only,
    apply_best,
    output_spec,
    force,
    trace_evidence,
    test_results,
    eval_results,
    objective,
    hosted,
    oss,
    local_provider,
    model_name,
    proposal_timeout,
    search_mode,
    proposal_batch_size,
    selection_policy,
    json_output,
):
    """Optimize a HarnessSpec through an optional meta-harness project."""
    from superqode.harness import (
        apply_metaharness_best_spec,
        export_metaharness_project,
        render_optimize_payload,
        run_metaharness_project,
        summarize_metaharness_run,
    )

    if hosted and oss:
        raise click.ClickException("--hosted cannot be combined with --oss")
    resolved_project_dir = project_dir or (
        Path(".superqode") / "metaharness" / Path(spec_path).stem
    )
    try:
        export = export_metaharness_project(
            spec_path=spec_path,
            tasks_path=tasks_path,
            project_dir=resolved_project_dir,
            backend=backend,
            budget=budget,
            objective=objective,
            model=model_name,
            hosted=hosted,
            oss=oss,
            local_provider=local_provider,
            proposal_timeout=proposal_timeout,
            search_mode=search_mode,
            proposal_batch_size=proposal_batch_size,
            selection_policy=selection_policy,
            trace_evidence_path=trace_evidence,
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            force=force,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "export": export.to_dict(),
        "run": None,
        "summary": None,
        "applied": None,
        "next_steps": [
            f"Run: superqode harness optimize --spec {spec_path} --tasks {tasks_path} --backend codex",
            f"Inspect: {metaharness_bin} inspect {Path(export.project_dir) / 'runs' / run_name}",
        ],
    }
    if not export_only:
        try:
            run = run_metaharness_project(
                project_dir=export.project_dir,
                backend=backend,
                budget=budget,
                run_name=run_name,
                metaharness_bin=metaharness_bin,
                trace_evidence_path=export.trace_evidence_path,
                hosted=hosted,
                oss=oss,
                local_provider=local_provider,
                model=model_name,
                proposal_timeout=proposal_timeout,
                search_mode=search_mode,
                proposal_batch_size=proposal_batch_size,
                selection_policy=selection_policy,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload["run"] = run
        if not run["ok"]:
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(render_optimize_payload(payload))
                if run.get("stderr"):
                    click.echo(run["stderr"], err=True)
            raise click.exceptions.Exit(1)
        try:
            payload["summary"] = summarize_metaharness_run(run["run_dir"])
        except Exception as exc:
            raise click.ClickException(
                f"Meta-harness run completed but summary failed: {exc}"
            ) from exc
        if apply_best:
            try:
                payload["applied"] = apply_metaharness_best_spec(
                    run_dir=run["run_dir"],
                    output_spec=output_spec or spec_path,
                    force=force or output_spec is None,
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_optimize_payload(payload))


@harness.command("optimize-inspect")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize_inspect(run_dir, json_output):
    """Inspect a meta-harness optimization run summary."""
    from superqode.harness import render_metaharness_summary, summarize_metaharness_run

    try:
        summary = summarize_metaharness_run(run_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(summary, indent=2))
        return
    click.echo(render_metaharness_summary(summary))


@harness.command("optimize-ledger")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize_ledger(run_dir, json_output):
    """Show the candidate ledger from a meta-harness optimization run."""
    from superqode.harness import metaharness_candidate_ledger, render_metaharness_ledger

    try:
        rows = metaharness_candidate_ledger(run_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(render_metaharness_ledger(rows))
