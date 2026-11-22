"""Headless Factory improvement over the same pinned contracts as Studio."""

import asyncio
from pathlib import Path

import click

from .factory_operations import output, project_option


@click.group()
def improve():
    """Prepare, search and compare improvements; never activate a factory."""


@improve.command("capabilities")
@output
def capabilities():
    from superqode.factory.improvement import capabilities

    return capabilities()


@improve.command("prepare")
@project_option
@click.option("--binding", required=True)
@click.option("--tasks", required=True, help="Project-relative evaluation YAML")
@click.option("--fixture", required=True, help="Disposable project directory, or @empty")
@click.option(
    "--target-kind", type=click.Choice(["harness", "skill", "route", "workflow"]), default="harness"
)
@click.option("--skill", default="")
@click.option("--stage", default="")
@click.option("--route-model", "route_models", multiple=True)
@click.option(
    "--engine",
    "optimizer_engine",
    type=click.Choice(["evaluator-optimizer", "gepa", "metaharness", "omni"]),
    default="evaluator-optimizer",
)
@click.option("--reflection-model", default="")
@click.option("--max-evals", type=click.IntRange(1, 20), default=4)
@click.option("--max-seconds", type=click.IntRange(1, 600), default=120)
@output
def prepare(project, **options):
    from superqode.factory.improvement import prepare

    options["route_models"] = list(options["route_models"]) or None
    return prepare(project, **options)


@improve.command("inspect")
@project_option
@click.argument("plan")
@output
def inspect(project, plan):
    from superqode.factory import improvement as imp

    value, _ = imp.load(project, plan)
    return {
        "plan": value,
        "budget": imp.budget_summary(project, value, detail=True),
        "baseline": imp.baseline_proposal(project, value),
    }


@improve.command("stage")
@project_option
@click.argument("plan")
@click.option("--file", required=True, help="Project-relative proposal")
@output
def stage(project, plan, file):
    from superqode.factory import improvement as imp
    from superqode.factory.versioning import source_path

    return imp.stage(project, plan, imp._read(source_path(Path(project).resolve(), file), 250000))


@improve.command("import")
@project_option
@click.argument("plan")
@click.option("--engine", type=click.Choice(["metaharness", "omni"]), required=True)
@click.option("--artifact", required=True)
@output
def import_candidate(project, plan, engine, artifact):
    from superqode.factory.external import import_candidate

    return import_candidate(project, plan, engine=engine, artifact=artifact)


@improve.command("preview")
@project_option
@click.argument("plan")
@click.argument("candidate")
@output
def preview(project, plan, candidate):
    from superqode.factory.improvement import preview

    return preview(project, plan, candidate)


def require_live(live):
    if not live:
        raise ValueError("Use --live to authorize bounded model and tool execution")


@improve.command("search")
@project_option
@click.argument("plan")
@click.option("--digest", required=True)
@click.option("--live", is_flag=True)
@output
def search(project, plan, digest, live):
    from superqode.factory.improvement import optimize

    require_live(live)
    return optimize(project, plan, digest)


@improve.command("compare")
@project_option
@click.argument("plan")
@click.argument("candidate")
@click.option("--digest", required=True)
@click.option("--live", is_flag=True)
@output
def compare(project, plan, candidate, digest, live):
    from superqode.factory.improvement import compare

    require_live(live)
    return asyncio.run(compare(project, plan, candidate, digest))


@improve.command("draft")
@project_option
@click.argument("plan")
@click.argument("candidate")
@click.option("--receipt", required=True)
@click.option("--confirm", is_flag=True)
@output
def draft(project, plan, candidate, receipt, confirm):
    """Emit an eligible proposed YAML; component creation requires --confirm."""
    from superqode.factory import improvement as imp

    if not confirm:
        raise ValueError("Use --confirm after reviewing the exact candidate and comparison receipt")
    return imp.adoption(project, plan, candidate, receipt)


@improve.command("mcp")
@project_option
@click.option(
    "--allow-execution", is_flag=True, help="Permit explicitly confirmed search/comparison calls"
)
def mcp(project, allow_execution):
    """Serve project-scoped Factory tools over stdio; no models at startup."""
    from superqode.mcp.factory_server import build_factory_mcp_server

    build_factory_mcp_server(project, allow_execution=allow_execution).run(transport="stdio")
