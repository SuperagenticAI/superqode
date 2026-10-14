"""SuperQode 'benchmark' CLI."""

import json
import click


@click.group()
def benchmark():
    """Run coding harness benchmarks."""
    pass


@benchmark.command("run")
@click.argument("tasks_file", type=click.Path(exists=True))
@click.option(
    "--target",
    "targets",
    multiple=True,
    type=click.Choice(["superqode", "opencode", "pi", "deepagents"]),
    help="Target to run: superqode, opencode, pi, deepagents",
)
def benchmark_run(tasks_file, targets):
    """Run benchmark tasks against harness CLIs."""
    from superqode.benchmarks import (
        DEFAULT_TARGETS,
        benchmark_scorecard,
        load_tasks,
        run_benchmark_suite,
    )

    selected = [DEFAULT_TARGETS[name] for name in targets] if targets else None
    results = run_benchmark_suite(load_tasks(tasks_file), selected)
    click.echo(
        json.dumps({"results": results, "scorecard": benchmark_scorecard(results)}, indent=2)
    )


@benchmark.command("compare")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--repetitions", type=click.IntRange(1, 20), default=3, show_default=True)
@click.option("--output", type=click.Path(dir_okay=False), default=None)
@click.option(
    "--dry-run", is_flag=True, help="Validate the plan without starting agents or graders."
)
@click.option(
    "--artifacts",
    type=click.Path(file_okay=False),
    default=None,
    help="Preserve graded attempt workspaces outside the task seed directories.",
)
def benchmark_compare(manifest, repetitions, output, dry_run, artifacts):
    """Run a pinned comparison with matched models and executable graders."""
    from pathlib import Path
    from superqode.benchmarks import (
        load_comparison,
        run_benchmark_suite,
        benchmark_scorecard,
        comparison_plan,
    )

    try:
        tasks, targets = load_comparison(manifest)
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise click.ClickException(str(error)) from error
    plan = comparison_plan(tasks, targets, repetitions=repetitions)
    if dry_run:
        payload = json.dumps(plan, indent=2)
    else:
        if not plan["ready"]:
            raise click.ClickException(
                "Comparison setup incomplete: " + "; ".join(plan["blockers"])
            )
        results = run_benchmark_suite(
            tasks, targets, repetitions=repetitions, artifacts_dir=artifacts
        )
        payload = json.dumps(
            {"results": results, "scorecard": benchmark_scorecard(results)}, indent=2
        )
    if output:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    click.echo(payload)
