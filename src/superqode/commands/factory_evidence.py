"""Factory acceptance configuration, traceability and observed outcomes."""

import asyncio
import json
from pathlib import Path

import click

from .factory_operations import output, project_option


@click.group()
def evidence():
    """Trace acceptance evidence and compare observed revision outcomes."""


@evidence.command("trace")
@project_option
@click.argument("run")
@output
def trace(project, run):
    from superqode.factory.evidence import trace

    return trace(project, run)


@evidence.command("summary")
@project_option
@click.argument("run")
@output
def summary(project, run):
    """Explain changes, protected evidence, reported cost and remaining human steps."""
    from superqode.factory.onboarding import result_summary

    return result_summary(project, run)


@evidence.command("record-outcome")
@project_option
@click.argument("run")
@click.option("--observation", required=True, help="Stable id for idempotent retries")
@click.option("--outcome", type=click.Choice(["met", "not_met", "unknown"]), required=True)
@click.option("--human-minutes", type=click.FloatRange(min=0), default=None)
@click.option("--actor", required=True)
@output
def record_outcome(project, run, observation, outcome, human_minutes, actor):
    from superqode.factory.evidence import record_outcome

    return record_outcome(
        project,
        run,
        observation=observation,
        outcome=outcome,
        human_minutes=human_minutes,
        actor=actor,
    )


@evidence.command("outcomes")
@project_option
@output
def outcomes(project):
    from superqode.factory.evidence import outcomes

    return outcomes(project)


@click.group()
def verifier():
    """Draft and explicitly save project-specific protected acceptance probes."""


def _input(root, name):
    from superqode.factory.definition import project_path
    from superqode.factory.operations import read

    return json.loads(read(project_path(Path(root).resolve(), name), 1000000))


@verifier.command("draft")
@project_option
@click.option(
    "--checks", required=True, help="Project-relative JSON map of check names to probe manifests"
)
@output
def draft(project, checks):
    from superqode.factory.verifiers import draft

    return draft(project, _input(project, checks))


@verifier.command("generate")
@project_option
@click.option("--description", required=True)
@click.option("--provider", required=True)
@click.option("--model", required=True)
@click.option(
    "--live", is_flag=True, help="Authorize one drafting-model request; no probe execution"
)
@output
def generate(project, description, provider, model, live):
    from superqode.factory.verifiers import generate

    if not live:
        raise ValueError("Use --live to authorize the selected drafting model")
    return asyncio.run(generate(project, description=description, provider=provider, model=model))


@verifier.command("install")
@project_option
@click.option("--proposal", required=True, help="Project-relative reviewed verifier proposal JSON")
@click.option("--digest", required=True)
@click.option("--confirm", is_flag=True)
@output
def install(project, proposal, digest, confirm):
    from superqode.factory.verifiers import install

    value = _input(project, proposal)
    if isinstance(value, dict):
        value = value.get("proposal", value)
    return install(project, value, expected=digest, confirmed=confirm)
