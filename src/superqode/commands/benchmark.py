"""SuperQode 'benchmark' CLI."""

import json
import click
import click

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
    help="Target to run: superqode, opencode, pi, deepagents",
)
def benchmark_run(tasks_file, targets):
    """Run benchmark tasks against harness CLIs."""
    from superqode.benchmarks import DEFAULT_TARGETS, load_tasks, run_benchmark_suite

    selected = [DEFAULT_TARGETS[name] for name in targets] if targets else None
    results = run_benchmark_suite(load_tasks(tasks_file), selected)
    click.echo(json.dumps({"results": results}, indent=2))
