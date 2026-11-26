"""FactorySpec authoring, readiness and release decision commands.

These share the engine used by the macOS app (``superqode.factory.authoring``),
so a Factory created or changed here is the same as one changed in the app.
"""

import asyncio
import json

import click

from superqode.factory.authoring import TEMPLATES

TEMPLATE_CHOICE = click.Choice(list(TEMPLATES))


def _project(function):
    return click.option(
        "--project", default=".", type=click.Path(file_okay=False), show_default=True
    )(function)


def _json(function):
    return click.option("--json", "json_output", is_flag=True, help="Emit JSON")(function)


def _fail(exc):
    raise click.ClickException(str(exc)) from exc


def _lines(lines):
    for line in lines:
        click.echo(line)


@click.command("init")
@_project
@click.option("--template", type=TEMPLATE_CHOICE, default="fix-and-verify", show_default=True)
@click.option("--force", is_flag=True, help="Replace an existing FactorySpec from the template")
@_json
def init(project, template, force, json_output):
    """Create .superqode/factory.yaml as a full FactorySpec from a template.

    An existing route-only policy is upgraded and its routes are kept.
    """
    from superqode.factory.authoring import init_from_template

    try:
        result = init_from_template(project, template, force=force)
    except (ValueError, OSError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"✅ Factory created from {template}: {result['path']}")
    click.echo(f"   Revision {result['digest'][:12]}  snapshot {result['snapshot_digest'][:19]}")
    click.echo("   Next: sq factory check --project . --application")


@click.command("show")
@_project
@_json
def show(project, json_output):
    """Show the FactorySpec, its release policy and recent runs."""
    from superqode.factory.summaries import overview, overview_lines

    try:
        value = overview(project)
    except (ValueError, OSError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(value, indent=2))
    else:
        _lines(overview_lines(value))


@click.command("workflows")
@_json
def workflows(json_output):
    """List built-in factory workflows and the stages each one runs."""
    from superqode.factory.templates import workflow_catalog

    rows = workflow_catalog()
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        click.echo(f"{row['name']}: {row['summary']}")
        click.echo("   stages: " + " → ".join(row["stages"]))
    click.echo('Next: sq factory describe "how the team works" [--workflow NAME]')
    click.echo("      or sq factory init --template NAME")


@click.command("models")
@_project
@click.option("--draft-model", default="", help="Optional drafting model as provider/model")
@click.option(
    "--check-connections",
    is_flag=True,
    help="Check configuration and discover local models; sends no inference prompt",
)
@_json
def models(project, draft_model, check_connections, json_output):
    """Explain drafting and execution model setup without running the Factory."""
    from superqode.factory.model_setup import inspect_models
    from superqode.desktop_service.connections import inspect_route

    try:
        value = inspect_models(
            project,
            drafting_model=draft_model,
            check_connection=(
                lambda provider, model, binding: inspect_route(
                    {}, {"provider": provider, "model": model}
                )
            )
            if check_connections
            else None,
        )
    except (ValueError, OSError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(value, indent=2))
        return
    click.echo(f"Factory model setup · route: {value['default_route']}")
    click.echo(value["guidance"])
    for row in [value["drafting"], *value["execution"]]:
        label = row["purpose"] + (f"/{row['binding']}" if row.get("binding") else "")
        if row.get("fallback"):
            label += " (fallback)"
        click.echo(f"{label}: {row['reference'] or 'starter generation'} [{row['state']}]")
        click.echo("  " + row["message"])
    if value.get("execution_error"):
        click.echo(value["execution_error"])
    elif not value["execution_configured"]:
        click.echo(
            "Choose a Factory starter or draft, then configure its execution harness models."
        )


@click.command("describe")
@_project
@click.argument("description", required=False)
@click.option("--model", "model_ref", default="", help="Optional drafting model as provider/model")
@click.option(
    "--workflow",
    type=TEMPLATE_CHOICE,
    default=None,
    help="Starter when the description does not name one",
)
@click.option(
    "--rlm",
    is_flag=True,
    help="Inspect this repository with SuperQode's RLM context engine to build a repo-native Factory draft",
)
@click.option("--apply", "apply_digest", default="", help="Save a reviewed draft by its digest")
@click.option("--reason", default="", help="Why the reviewed draft is being saved")
@click.option("--confirm", is_flag=True, help="Confirm saving the reviewed draft")
@_json
def describe(
    project, description, model_ref, workflow, rlm, apply_digest, reason, confirm, json_output
):
    """Describe how the team works and draft a FactorySpec to review.

    With --rlm, SuperQode inspects the repository lazily via RLMContext/Monty
    and drafts a tailored FactorySpec (with optional bounded model sub-calls).
    With no --model, SuperQode builds starter settings on this machine.
    Words in the description pick the workflow. --workflow is the fallback.
    Drafting writes nothing to the Factory. Save a reviewed draft with
    --apply DIGEST --reason TEXT --confirm.
    """
    from superqode.factory import authoring

    if apply_digest:
        try:
            result = authoring.apply_draft(
                project,
                apply_digest,
                reason=reason or "Saved a reviewed AI Factory draft",
                confirmed=confirm,
            )
        except (ValueError, OSError, KeyError) as exc:
            _fail(exc)
        if json_output:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"✅ Saved reviewed draft {apply_digest[:12]} to {result['path']}")
        return
    if not rlm and (not description or not description.strip()):
        raise click.ClickException(
            "Give a description of the factory, or pass --rlm to inspect this repo. See: sq factory workflows"
        )
    if model_ref and "/" not in model_ref:
        raise click.ClickException("Write --model as provider/model")
    try:
        if rlm:
            provider, model = model_ref.split("/", 1) if model_ref else ("", "")
            result = asyncio.run(
                authoring.architect(
                    project,
                    description or "",
                    provider=provider,
                    model=model,
                    workflow=workflow or "",
                )
            )
        elif model_ref:
            provider, model = model_ref.split("/", 1)
            result = asyncio.run(
                authoring.draft(
                    project,
                    description,
                    provider=provider,
                    model=model,
                    workflow=workflow or "",
                )
            )
        else:
            result = authoring.draft_from_description(project, description, workflow=workflow or "")
    except (ValueError, OSError, KeyError, asyncio.TimeoutError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"⏸️ Draft {result['digest'][:12]} for {result['name']} (nothing saved yet)")
    lineage = result.get("rlm_lineage")
    if isinstance(lineage, dict):
        click.echo(
            f"   RLM ({lineage.get('engine')}, {lineage.get('mode')}): "
            f"{lineage.get('repo_files', 0)} files · "
            f"stacks={','.join(lineage.get('detected_stacks') or [])} · "
            f"test=`{lineage.get('detected_test_command', '')}`"
        )
    click.echo(result["diff"] or "(no changes)")
    for label, key in (("Assumptions", "assumptions"), ("Missing", "missing_capabilities")):
        for item in result[key]:
            click.echo(f"   {label}: {item}")
    for warning in result["warnings"]:
        click.echo(f"   ⚠️ {warning}")
    click.echo(
        f'   Save after review: sq factory describe --apply {result["digest"]} --reason "..." --confirm'
    )


@click.group("sources")
def sources():
    """Review and commit Factory source files to Git."""


@sources.command("inspect")
@_project
def sources_inspect(project):
    """Show changed Factory sources and the review digest to commit against."""
    from superqode.factory.versioning import inspect_sources

    try:
        value = inspect_sources(project)
    except (ValueError, OSError) as exc:
        _fail(exc)
    click.echo(json.dumps(value, indent=2))


@sources.command("commit")
@_project
@click.option("--digest", "review_digest", required=True, help="Digest from sources inspect")
@click.option("--path", "paths", multiple=True, required=True, help="Reviewed source to commit")
@click.option("--message", required=True)
@click.option("--confirm", is_flag=True, help="Confirm committing the reviewed sources")
def sources_commit(project, review_digest, paths, message, confirm):
    """Commit reviewed Factory sources. Never pushes."""
    from superqode.factory.operations import ownership
    from superqode.factory.versioning import commit_sources, inspect_sources

    if not confirm:
        raise click.ClickException("Use --confirm to commit the reviewed Factory sources")
    try:
        with ownership(project):
            review = inspect_sources(project)
            if review["digest"] != review_digest:
                raise ValueError("Factory sources changed since review; run sources inspect again")
            result = commit_sources(project, review, list(paths), message)
    except (ValueError, OSError) as exc:
        _fail(exc)
    click.echo(json.dumps(result, indent=2))


@click.command("check")
@_project
@click.option("--probe", is_flag=True, help="Also run protected isolation probes; no models")
@click.option("--application", is_flag=True, help="Run build, start, health and service checks")
@click.option("--timeout", default=300, type=click.IntRange(min=1, max=1800), show_default=True)
@_json
def check(project, probe, application, timeout, json_output):
    """Readiness with labelled findings: configured, execution_tested, quality_evaluated."""
    from superqode.factory.operations import readiness
    from superqode.factory.summaries import readiness_lines

    try:
        report = readiness(project, probe=probe, application=application, timeout=timeout)
    except (ValueError, OSError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(report, indent=2))
    else:
        _lines(readiness_lines(report))
    if report["structural_passed"] is False or report["application_passed"] is False:
        raise click.exceptions.Exit(2)


@click.command("decide")
@_project
@click.argument("work_order_id")
@_json
def decide(project, work_order_id, json_output):
    """Show the release decision for a run and everything still missing."""
    from superqode.factory.release import release_status
    from superqode.factory.summaries import decision_lines

    try:
        status = release_status(work_order_id, root=project)
    except (ValueError, OSError, KeyError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(status, indent=2))
    else:
        _lines(decision_lines(status))
    if status["blockers"]:
        raise click.exceptions.Exit(2)


@click.command("trial")
@_project
@click.argument("goal")
@click.option("--request-id", default="", help="Stable intake id; reuse it when retrying")
@click.option("--actor", default="cli", show_default=True, help="Local audit attribution")
@_json
def trial(project, goal, request_id, actor, json_output):
    """Compile the saved Factory for GOAL and queue one WorkOrder without running agents.

    Run it afterwards with: sq factory worker <id> --live
    """
    from superqode.factory.authoring import queue_trial

    try:
        result = queue_trial(project, goal, actor=actor, request_id=request_id)
    except (ValueError, OSError, KeyError) as exc:
        _fail(exc)
    if json_output:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"⏸️ Queued {result['work_order_id']} ({result['status']}); no agent has run.")
    click.echo(f"   Next: sq factory worker {result['work_order_id']} --live")
