"""Harness tests, evaluations, benchmarks, and failure mining."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.command("test")
@click.argument("spec_arg", required=False, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--spec", "spec_option", type=click.Path(exists=True, path_type=Path), help="Harness spec file"
)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--prompt", default="Reply with exactly: superqode harness ok", show_default=True)
@click.option("--live", is_flag=True, help="Actually call the configured model endpoint")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_test(
    spec_arg,
    spec_option,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    prompt,
    live,
    json_output,
):
    """Run a fast HarnessSpec smoke test with a failure digest."""
    import asyncio

    from superqode.harness import render_harness_smoke_test, run_harness_smoke_test

    spec_path = spec_option or spec_arg
    if spec_path is None:
        raise click.ClickException("Missing harness spec. Pass --spec <path>.")
    payload = asyncio.run(
        run_harness_smoke_test(
            spec_path,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_dir=working_dir,
            sandbox_backend=sandbox_backend,
            prompt=prompt,
            live=live,
        )
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_harness_smoke_test(payload))
    if payload["status"] == "failed":
        raise click.exceptions.Exit(1)


@harness.command("eval")
@click.option(
    "--spec",
    "spec_paths",
    type=click.Path(exists=True, path_type=Path),
    multiple=True,
    required=True,
)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--variant", "variant_paths", type=click.Path(exists=True, path_type=Path), multiple=True
)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--split",
    "eval_split",
    type=click.Choice(["all", "held-in", "held-out"]),
    default="all",
    show_default=True,
    help="Run all tasks, held-in tasks, or held-out tasks",
)
@click.option("--live", is_flag=True, help="Execute tasks against the model endpoint")
@click.option(
    "--allow-regressions",
    is_flag=True,
    help="Do not fail when a variant regresses a task the baseline solved (seesaw gate)",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_eval(
    spec_paths,
    tasks_path,
    variant_paths,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    eval_split,
    live,
    allow_regressions,
    json_output,
):
    """Run a HarnessSpec eval scorecard across tasks and variants.

    Acts as a seesaw gate: if any variant regresses a task the baseline solved,
    the command exits non-zero unless --allow-regressions is set.
    """
    import asyncio

    from superqode.harness import render_harness_eval, run_harness_eval

    payload = asyncio.run(
        run_harness_eval(
            spec_paths=[*spec_paths, *variant_paths],
            tasks_path=tasks_path,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_dir=working_dir,
            sandbox_backend=sandbox_backend,
            live=live,
            eval_split=eval_split,
        )
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_harness_eval(payload))
        if payload.get("regressed") and not allow_regressions:
            click.echo(
                "REGRESSION: "
                + ", ".join(payload.get("regressed_variants") or [])
                + " regressed a task the baseline solved. "
                + "Pass --allow-regressions to override.",
                err=True,
            )
    if payload["status"] == "failed":
        raise click.exceptions.Exit(1)
    if payload.get("regressed") and not allow_regressions:
        raise click.exceptions.Exit(2)


@harness.command("eval-packs")
@click.argument("pack", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_eval_packs(pack, json_output):
    """List bundled HarnessSpec eval packs, or show one pack path."""
    from superqode.harness import eval_pack_path, list_eval_packs

    if pack:
        path = eval_pack_path(pack)
        payload = {"id": pack, "path": str(path)}
        if json_output:
            click.echo(json.dumps(payload, indent=2))
        else:
            click.echo(str(path))
        return

    payload = list_eval_packs()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No bundled eval packs found.")
        return
    for item in payload:
        click.echo(f"{item['id']}  tasks={item['tasks']}  {item['description']}\n  {item['path']}")


@harness.command("auto-bench")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--live", is_flag=True, help="Call the configured model endpoint")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_auto_bench(
    spec_path,
    tasks_path,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    live,
    json_output,
):
    """Probe a model-backed harness and recommend next settings."""
    import asyncio

    from superqode.harness import run_harness_eval, run_harness_smoke_test

    if tasks_path:
        payload = asyncio.run(
            run_harness_eval(
                spec_paths=[spec_path],
                tasks_path=tasks_path,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
        status = payload["status"]
        recommendation = _auto_bench_recommendation(status, payload, live=live)
        result = {
            "mode": "eval",
            "status": status,
            "scorecard": payload,
            "recommendation": recommendation,
        }
    else:
        payload = asyncio.run(
            run_harness_smoke_test(
                spec_path,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
        status = payload["status"]
        recommendation = _auto_bench_recommendation(status, payload, live=live)
        result = {
            "mode": "test",
            "status": status,
            "test": payload,
            "recommendation": recommendation,
        }

    if json_output:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"Harness auto-bench: {result['status']}")
    click.echo(f"Recommendation: {result['recommendation']['summary']}")
    for item in result["recommendation"]["next_steps"]:
        click.echo(f"  next: {item}")


def _auto_bench_recommendation(status: str, payload: dict, *, live: bool) -> dict:
    if not live:
        return {
            "summary": "Dry run completed. Re-run with --live to benchmark the model endpoint.",
            "next_steps": ["Pass --live once the local endpoint is running."],
        }
    if status == "passed":
        return {
            "summary": "Harness/model path is usable with the current settings.",
            "next_steps": [
                "Keep the current model_policy settings as a baseline.",
                "Run `superqode harness eval` with task-specific variants before widening permissions.",
            ],
        }
    digest = payload.get("failure_digest") or {}
    if payload.get("variants"):
        failed = [variant for variant in payload["variants"] if variant.get("failed")]
        digest = (
            failed[0]["tasks"][0].get("failure_digest") if failed and failed[0]["tasks"] else {}
        ) or {}
    return {
        "summary": f"Benchmark failed: {digest.get('failure_category') or 'unknown'}",
        "next_steps": digest.get("suggested_next_checks")
        or ["Run `superqode harness test --live --json` and inspect the failure digest."],
    }


def _csv_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@harness.command("mine-failures")
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to mine",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to mine",
)
@click.option(
    "--harbor-run",
    "harbor_runs",
    type=click.Path(exists=True, path_type=Path),
    multiple=True,
    help="Harbor/Terminal-Bench style run JSON, JSONL, or directory to mine",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "failures.json",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_mine_failures(test_results, eval_results, harbor_runs, output_path, json_output):
    """Mine structured failure records from harness test/eval JSON outputs."""
    from superqode.harness import (
        mine_harness_failures,
        render_failure_report,
        write_failure_report,
    )

    if not test_results and not eval_results and not harbor_runs:
        raise click.ClickException(
            "Pass at least one --test-result, --eval-result, or --harbor-run file."
        )
    try:
        report = mine_harness_failures(
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            harbor_run_paths=harbor_runs,
        )
        written = write_failure_report(report, output_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**report, "output": str(written)}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_failure_report(report))
    click.echo(f"Wrote: {written}")
