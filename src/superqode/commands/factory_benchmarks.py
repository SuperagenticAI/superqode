"""Historical task selection and explicit local benchmark dataset review."""

import json
from pathlib import Path

import click

from .factory_operations import output, project_option


@click.group()
def benchmark():
    """Build reviewed workloads from past runs; execute through paired trials."""


@benchmark.command("history")
@project_option
@output
def history(project):
    from superqode.factory.benchmarks import history

    return history(project)


@benchmark.command("draft")
@project_option
@click.option("--held-in", multiple=True, required=True)
@click.option("--held-out", multiple=True, required=True)
@click.option("--candidate", required=True, help="Project-relative Factory definition or snapshot")
@output
def draft(project, held_in, held_out, candidate):
    from superqode.factory.benchmarks import draft

    return draft(project, held_in=list(held_in), held_out=list(held_out), candidate=candidate)


@benchmark.command("install")
@project_option
@click.option("--proposal", required=True, help="Reviewed project-relative proposal JSON")
@click.option("--digest", required=True)
@click.option("--confirm", is_flag=True)
@output
def install(project, proposal, digest, confirm):
    from superqode.factory.benchmarks import install
    from superqode.factory.definition import project_path
    from superqode.factory.operations import read

    value = json.loads(read(project_path(Path(project).resolve(), proposal), 5_000_000))
    return install(project, value, expected=digest, confirmed=confirm)
