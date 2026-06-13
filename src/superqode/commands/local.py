"""The `superqode local` command group: Local Agentic Coding on this machine."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group("local")
def local():
    """Local Agentic Coding: tune SuperQode for the machine in front of you."""


@local.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Emit the full report as JSON")
@click.option(
    "--generate",
    "generate_path",
    default=None,
    metavar="PATH",
    help="Write a tuned harness spec for the recommended stack",
)
@click.option(
    "--name", default="local-coder", show_default=True, help="Name for the generated harness"
)
def local_doctor(json_output, generate_path, name):
    """Detect hardware, engines, and downloaded models; recommend a local stack.

    Reads the shipped recommendation matrix (override it with
    ~/.superqode/stack_matrix.yaml) and tells you the best engine and model
    for this machine, preferring what is already installed and downloaded.
    """
    from dataclasses import asdict

    from superqode.local.doctor import generate_harness_yaml, render_report, run_doctor

    report = run_doctor()

    if json_output:
        payload = {
            "hardware": asdict(report.hardware),
            "tier": report.hardware.tier,
            "engines": {k: asdict(v) for k, v in report.engines.items()},
            "inventory": [asdict(m) for m in report.inventory],
            "recommendation": asdict(report.recommendation),
            "matrix_version": report.matrix_version,
            "apple_fm_available": report.apple_fm_available,
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_report(report))

    if generate_path:
        target = Path(generate_path)
        if target.exists():
            raise click.ClickException(f"{target} already exists; choose another path")
        target.write_text(generate_harness_yaml(report, name=name), encoding="utf-8")
        click.echo(f"\nWrote tuned harness to {target}")
        click.echo(f"Run it with: superqode --harness {target} -p 'your task'")


@local.command("packs")
@click.option("--json", "json_output", is_flag=True, help="Emit packs as JSON")
def local_packs(json_output):
    """List model policy packs (shipped plus ~/.superqode/model-packs/).

    A pack carries tuned defaults for one open-model family. Reference one
    from a harness with model_policy.pack, or let SuperQode auto-detect it
    from the model id.
    """
    from dataclasses import asdict

    from superqode.local.packs import USER_PACKS_DIR, list_packs

    packs = list_packs()
    if json_output:
        click.echo(json.dumps([asdict(p) for p in packs], indent=2))
        return
    for pack in packs:
        click.echo(f"{pack.name:<12} {pack.description}")
        if pack.match:
            click.echo(f"{'':<12} matches: {', '.join(pack.match)}")
    click.echo(f"\nOverride or add packs in {USER_PACKS_DIR}")


@local.command("bench")
@click.option(
    "--endpoint",
    default=None,
    metavar="URL",
    help="OpenAI-compatible base URL (default: every running engine the doctor finds)",
)
@click.option("--model", "models", multiple=True, help="Model id to bench (repeatable)")
@click.option("--max-tokens", default=256, show_default=True, type=int)
@click.option("--api-key", default="", help="Bearer token if the endpoint needs one")
@click.option(
    "--agentic",
    is_flag=True,
    help="Also probe tool-call, edit-format, shell-call, and context-recall behavior",
)
@click.option("--json", "json_output", is_flag=True, help="Emit results as JSON")
def local_bench(endpoint, models, max_tokens, api_key, agentic, json_output):
    """Measure TTFT and decode speed on local endpoints with a coding prompt.

    Without --endpoint, benches the first model of every engine the doctor
    finds running. TTFT (prefill) matters most: agent loops resend a growing
    context every turn.
    """
    from dataclasses import asdict

    from superqode.local.bench import (
        list_endpoint_models,
        render_bench,
        run_agentic_bench,
        run_bench,
    )

    targets: list[tuple[str, str]] = []
    if endpoint:
        ids = list(models) or list_endpoint_models(endpoint)[:1]
        if not ids:
            raise click.ClickException(f"No models found at {endpoint}; pass --model explicitly")
        targets = [(endpoint, m) for m in ids]
    else:
        from superqode.local.engines import detect_engines

        for status in detect_engines().values():
            if not status.running or not status.endpoint:
                continue
            wanted = list(models) or list_endpoint_models(status.endpoint)[:1]
            targets.extend((status.endpoint, m) for m in wanted)
        if not targets:
            raise click.ClickException(
                "No running engines found. Start one (ollama serve, lms server start, "
                "superqode providers mlx server) or pass --endpoint."
            )

    results = []
    for target_endpoint, model in targets:
        click.echo(f"Benching {model} at {target_endpoint} ...", err=True)
        if agentic:
            results.append(
                run_agentic_bench(
                    target_endpoint,
                    model,
                    max_tokens=max_tokens,
                    api_key=api_key,
                )
            )
        else:
            results.append(run_bench(target_endpoint, model, max_tokens=max_tokens, api_key=api_key))

    if json_output:
        click.echo(json.dumps([asdict(r) for r in results], indent=2))
    else:
        click.echo(render_bench(results))


@local.command("optimize")
@click.option(
    "--endpoint",
    default=None,
    metavar="URL",
    help="OpenAI-compatible base URL (default: every running engine the doctor finds)",
)
@click.option("--model", "models", multiple=True, help="Candidate model id (repeatable)")
@click.option(
    "--role",
    "roles",
    multiple=True,
    help="Workflow role to optimize (default: planner, implementer, reviewer, utility)",
)
@click.option("--max-tokens", default=384, show_default=True, type=int)
@click.option("--api-key", default="", help="Bearer token if the endpoint needs one")
@click.option(
    "--generate",
    "generate_path",
    default=None,
    metavar="PATH",
    help="Write a role-routed harness spec from the recommendations",
)
@click.option(
    "--name",
    default="local-optimized",
    show_default=True,
    help="Name for the generated harness",
)
@click.option("--json", "json_output", is_flag=True, help="Emit report as JSON")
def local_optimize(endpoint, models, roles, max_tokens, api_key, generate_path, name, json_output):
    """Benchmark candidates and recommend role-specific local model routing."""
    from dataclasses import asdict

    from superqode.local.optimize import (
        DEFAULT_ROLES,
        discover_targets,
        optimization_harness_yaml,
        render_optimization,
        run_optimization,
    )

    targets = discover_targets(endpoint, models)
    if not targets:
        raise click.ClickException(
            "No candidate models found. Start a local engine or pass --endpoint and --model."
        )

    for target_endpoint, model in targets:
        click.echo(f"Optimizing {model} at {target_endpoint} ...", err=True)
    report = run_optimization(
        targets,
        roles=roles or DEFAULT_ROLES,
        max_tokens=max_tokens,
        api_key=api_key,
    )

    if json_output:
        click.echo(
            json.dumps(
                {
                    "results": [asdict(r) for r in report.results],
                    "recommendations": [asdict(r) for r in report.recommendations],
                    "notes": list(report.notes),
                },
                indent=2,
            )
        )
    else:
        click.echo(render_optimization(report))

    if generate_path:
        target = Path(generate_path)
        if target.exists():
            raise click.ClickException(f"{target} already exists; choose another path")
        target.write_text(optimization_harness_yaml(report, name=name), encoding="utf-8")
        click.echo(f"\nWrote role-routed harness to {target}")
        click.echo(f"Run it with: superqode harness run --spec {target} --prompt 'your task'")


__all__ = ["local"]
