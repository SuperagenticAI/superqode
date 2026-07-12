"""SuperQode 'skills' CLI: optimize skills."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def skills():
    """Manage and optimize SuperQode markdown skills."""
    pass
@skills.command("optimize")
@click.argument("skill")
@click.option("--engine", type=click.Choice(["gepa"]), default="gepa", show_default=True)
@click.option(
    "--harness", "harness_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for staged optimization artifacts",
)
@click.option("--root", type=click.Path(path_type=Path), default=Path("."), show_default=True)
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
@click.option("--reflection-lm", default="openai/gpt-5.1", show_default=True)
@click.option("--max-metric-calls", default=20, show_default=True, type=int)
@click.option("--max-candidate-proposals", default=None, type=int)
@click.option("--max-reflection-cost", default=None, type=float)
@click.option("--minibatch-size", default=None, type=int)
@click.option("--max-workers", default=1, show_default=True, type=int)
@click.option("--seed", default=0, show_default=True, type=int)
@click.option("--max-edits", default=8, show_default=True, type=int)
@click.option(
    "--candidate-selection",
    type=click.Choice(["pareto", "current_best", "epsilon_greedy", "top_k_pareto"]),
    default="pareto",
    show_default=True,
)
@click.option(
    "--frontier-type",
    type=click.Choice(["instance", "objective", "hybrid", "cartesian"]),
    default="hybrid",
    show_default=True,
)
@click.option(
    "--acceptance",
    type=click.Choice(["strict_improvement", "improvement_or_equal"]),
    default="strict_improvement",
    show_default=True,
)
@click.option("--cache-evaluation", is_flag=True, help="Enable GEPA candidate/example cache")
@click.option(
    "--use-merge", is_flag=True, help="Enable GEPA merge proposals across frontier candidates"
)
@click.option("--max-merge-invocations", default=5, show_default=True, type=int)
@click.option("--live", is_flag=True, help="Execute eval tasks against the configured model")
@click.option("--force", is_flag=True, help="Overwrite an existing output directory")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def skills_optimize(
    skill,
    engine,
    harness_path,
    tasks_path,
    output_dir,
    root,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    reflection_lm,
    max_metric_calls,
    max_candidate_proposals,
    max_reflection_cost,
    minibatch_size,
    max_workers,
    seed,
    max_edits,
    candidate_selection,
    frontier_type,
    acceptance,
    cache_evaluation,
    use_merge,
    max_merge_invocations,
    live,
    force,
    json_output,
):
    """Optimize a markdown skill with a staged GEPA run."""
    from datetime import datetime

    from superqode.skillopt import optimize_skill_with_gepa, render_skill_optimization_result

    if engine != "gepa":
        raise click.ClickException(f"Unsupported skills optimizer engine: {engine}")
    if not live:
        raise click.ClickException(
            "GEPA optimization requires --live so harness eval tasks produce real scores."
        )
    target_output = output_dir or (
        Path(".superqode")
        / "skill-optimizations"
        / f"{skill}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )

    try:
        result = optimize_skill_with_gepa(
            skill=skill,
            harness_path=harness_path,
            tasks_path=tasks_path,
            output_dir=target_output,
            root=root,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_dir=working_dir,
            sandbox_backend=sandbox_backend,
            reflection_lm=reflection_lm,
            max_metric_calls=max_metric_calls,
            max_candidate_proposals=max_candidate_proposals,
            max_reflection_cost=max_reflection_cost,
            reflection_minibatch_size=minibatch_size,
            max_workers=max_workers,
            seed=seed,
            max_edits=max_edits,
            candidate_selection_strategy=candidate_selection,
            frontier_type=frontier_type,
            acceptance_criterion=acceptance,
            cache_evaluation=cache_evaluation,
            use_merge=use_merge,
            max_merge_invocations=max_merge_invocations,
            live=live,
            force=force,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    click.echo(render_skill_optimization_result(result))
    if not result.check.get("ok"):
        raise click.exceptions.Exit(2)
