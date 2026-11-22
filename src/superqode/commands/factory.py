"""Factory definitions, compilation, routing and session lineage."""

import json
import click

from .factory_operations import operations
from .factory_improvement import improve
from .factory_campaigns import campaign
from .factory_intake import intake
from .factory_evidence import evidence, verifier


@click.group()
def factory():
    """Model- and harness-independent Code Factory commands."""
    pass


factory.add_command(operations)
factory.add_command(improve)
factory.add_command(campaign)
factory.add_command(intake)
factory.add_command(evidence)
factory.add_command(verifier)


@factory.command("suite-prepare")
@click.option("--project", default=".", type=click.Path(file_okay=False))
@click.option("--suite", required=True, help="Project-relative suite YAML")
def factory_suite_prepare(project, suite):
    """Pin paired application projects and WorkOrders without model calls."""
    from pathlib import Path
    from superqode.factory import trials
    from superqode.factory.versioning import source_path

    try:
        root = Path(project).resolve()
        plan = trials.prepare(root, suite_text=trials._read(source_path(root, suite), 250000))
        click.echo(json.dumps(plan, indent=2))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@factory.command("suite-inspect")
@click.option("--project", default=".", type=click.Path(file_okay=False))
@click.argument("suite_id")
def factory_suite_inspect(project, suite_id):
    """Inspect paired outcomes, usage and pending human gates."""
    from superqode.factory import trials

    try:
        click.echo(json.dumps(trials.scorecard(project, suite_id), indent=2))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@factory.command("suite-run")
@click.option("--project", default=".", type=click.Path(file_okay=False))
@click.option("--live", is_flag=True)
@click.argument("suite_id")
def factory_suite_run(project, live, suite_id):
    """Advance existing WorkOrders; pause at gates and never deliver changes."""
    import asyncio
    from superqode.factory import trials

    if not live:
        raise click.ClickException(
            "Use --live to authorize models, self-checks and protected probes"
        )
    try:
        click.echo(json.dumps(asyncio.run(trials.advance(project, suite_id)), indent=2))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@factory.command("suite-gate")
@click.option("--project", default=".", type=click.Path(file_okay=False))
@click.option("--entry", required=True)
@click.option("--stage", required=True)
@click.option("--digest", required=True)
@click.option("--decision", type=click.Choice(["approve", "hold"]), required=True)
@click.option("--reason", default="")
@click.argument("suite_id")
def factory_suite_gate(project, entry, stage, digest, decision, reason, suite_id):
    """Record an explicit workflow continuation; never authorize a release."""
    from superqode.factory import trials

    try:
        click.echo(
            json.dumps(
                trials.gate(project, suite_id, entry, stage, digest, decision, reason), indent=2
            )
        )
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@factory.command("suite-retry")
@click.option("--project", default=".", type=click.Path(file_okay=False))
@click.option("--entry", required=True)
@click.option("--stage", required=True)
@click.option("--attempt", required=True, type=click.IntRange(min=1))
@click.option("--reason", required=True)
@click.argument("suite_id")
def factory_suite_retry(project, entry, stage, attempt, reason, suite_id):
    """Explicitly authorize another known-failed attempt; execute separately."""
    from superqode.factory import trials

    try:
        click.echo(
            json.dumps(trials.retry(project, suite_id, entry, stage, attempt, reason), indent=2)
        )
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


def _definition_options(command):
    command = click.option(
        "--spec",
        default=".superqode/factory.yaml",
        show_default=True,
        help="Factory file, relative to the project",
    )(command)
    return _project_option(command)


def _project_option(command):
    return click.option(
        "--project",
        default=".",
        type=click.Path(file_okay=False),
        show_default=True,
        help="Project root; resolution stays inside this directory",
    )(command)


@factory.command("validate")
@_definition_options
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_validate(project, spec, json_output):
    """Validate a definition and its components without model calls or writes."""
    from superqode.factory import load_factory, resolve_factory

    try:
        definition = load_factory(spec, root=project)
        snapshot = None if definition.legacy else resolve_factory(definition)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "valid": True,
        "kind": "routing-policy" if definition.legacy else "Factory",
        "snapshot_digest": snapshot.digest if snapshot else None,
        "execution_started": False,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(
            "Valid routing-only policy."
            if definition.legacy
            else f"Valid FactorySpec: {snapshot.digest}"
        )
        click.echo("No agents or acceptance checks were executed.")


@factory.command("resolve")
@_definition_options
def factory_resolve(project, spec):
    """Print a pinned definition/component snapshot as JSON, without writes."""
    from superqode.factory import load_factory, resolve_factory

    try:
        snapshot = resolve_factory(load_factory(spec, root=project))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(snapshot.to_dict(), indent=2))


@factory.command("compile")
@_definition_options
@click.option("--goal", required=True, help="Delivery goal for the draft WorkOrder")
@click.option(
    "--write-snapshot",
    is_flag=True,
    help="Also write the pinned bundle inside the project; does not submit work",
)
def factory_compile(project, spec, goal, write_snapshot):
    """Print a draft WorkOrder plan; never queue, execute, merge or activate it."""
    from superqode.factory import (
        compile_factory,
        load_factory,
        materialize_snapshot,
        resolve_factory,
    )

    try:
        snapshot = resolve_factory(load_factory(spec, root=project))
        plan = compile_factory(snapshot, root=project, goal=goal)
        if write_snapshot:
            materialize_snapshot(plan)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({**plan.to_dict(), "snapshot_written": write_snapshot}, indent=2))


@factory.command("submit")
@_project_option
@click.option("--plan", required=True, help="Saved compiler JSON plan, relative to the project")
@click.option("--request-id", required=True, help="Stable intake id; reuse it when retrying")
@click.option("--actor", required=True, help="Local audit attribution")
def factory_submit(project, plan, request_id, actor):
    """Admit a materialized plan to WorkOrders without executing agents."""
    from pathlib import Path
    from superqode.factory.definition import project_path
    from superqode.factory.runtime import admit_factory, load_compiled_plan

    try:
        root = Path(project).resolve()
        path = project_path(root, plan)
        if path.stat().st_size > 16_000_000:
            raise ValueError("Factory plan exceeds 16 MB")
        compiled = load_compiled_plan(json.loads(path.read_text(encoding="utf-8")), root=root)
        order = admit_factory(compiled, request_id=request_id, actor=actor)
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"work_order": order.to_dict(), "execution_started": False}, indent=2))


@factory.command("inspect")
@_project_option
@click.argument("work_order_id")
def factory_inspect(project, work_order_id):
    """Inspect a factory run, pending gates and evidence without running work."""
    from superqode.factory.runtime import factory_store, is_factory_order
    from superqode.workorders.cockpit import build_cockpit_snapshot

    try:
        store = factory_store(project, read_only=True)
        if not is_factory_order(store.get(work_order_id)):
            raise ValueError("WorkOrder is not a factory run")
        snapshot = build_cockpit_snapshot(store, work_order_id)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(snapshot, indent=2))


@factory.command("gate")
@_project_option
@click.argument("work_order_id")
@click.argument("stage")
@click.option("--digest", required=True, help="Gate digest from factory inspect")
@click.option("--decision", type=click.Choice(["approve", "hold"]), required=True)
@click.option("--actor", required=True, help="Local audit attribution; not a release authorization")
@click.option("--reason", default="")
def factory_gate(project, work_order_id, stage, digest, decision, actor, reason):
    """Continue or hold a workflow gate; never approve a release."""
    from superqode.factory.runtime import factory_store, validate_factory_order

    try:
        store = factory_store(project)
        validate_factory_order(store.get(work_order_id))
        order = store.decide_gate(
            work_order_id,
            stage,
            expected_digest=digest,
            decision=decision,
            actor=actor,
            reason=reason,
        )
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(order.to_dict(), indent=2))


@factory.command("worker")
@_project_option
@click.argument("work_order_id")
@click.option(
    "--live", is_flag=True, help="Authorize agent execution, including possible provider charges"
)
@click.option("--id", "worker_id", default="factory-worker", show_default=True)
@click.option("--concurrency", default=1, type=click.IntRange(min=1, max=64), show_default=True)
@click.option(
    "--once/--follow", default=True, help="Drain ready work, or keep waiting for more work"
)
def factory_worker(project, work_order_id, live, worker_id, concurrency, once):
    """Execute through existing durable workers; pending human gates remain paused."""
    import asyncio
    from superqode.factory.runtime import factory_store, validate_factory_order
    from superqode.workorders.worker import WorkOrderWorker, WorkOrderWorkerConfig

    if not live:
        raise click.ClickException(
            "Use --live to authorize agent execution and possible provider charges"
        )
    try:
        store = factory_store(project)
        validate_factory_order(store.get(work_order_id))
        worker = WorkOrderWorker(
            store,
            WorkOrderWorkerConfig(
                worker_id=worker_id,
                reference=work_order_id,
                concurrency=concurrency,
                isolation="worktree",
                once=once,
            ),
        )
        stats = asyncio.run(worker.run())
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(stats.to_dict(), indent=2))


@factory.command("verify")
@_project_option
@click.argument("work_order_id")
@click.option("--execute", is_flag=True, help="Authorize bounded application probe execution")
@click.option("--timeout", default=120, type=click.IntRange(min=1, max=300), show_default=True)
def factory_verify(project, work_order_id, execute, timeout):
    """Run protected deterministic acceptance; never approve or release software."""
    from superqode.factory.verification import verify_factory

    if not execute:
        raise click.ClickException("Use --execute to authorize protected application probes")
    try:
        result = verify_factory(work_order_id, root=project, timeout=timeout)
    except (OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2))
    if result["report"]["status"] != "passed":
        raise click.exceptions.Exit(2)


@factory.command("release-challenge")
@_project_option
@click.argument("work_order_id")
@click.option("--key", "key_id", required=True, help="Signer id pinned in release_authority")
def factory_release_challenge(project, work_order_id, key_id):
    """Request a short-lived signature challenge for the exact verified change."""
    from superqode.factory.release import issue_challenge

    try:
        result = issue_challenge(work_order_id, root=project, key_id=key_id)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2))


@factory.command("authorize")
@_project_option
@click.argument("work_order_id")
@click.option("--proof", required=True, help="Signed proof JSON, relative to the project")
def factory_authorize(project, work_order_id, proof):
    """Verify a pinned signer's signature; this does not apply the change."""
    from pathlib import Path
    from superqode.factory.definition import project_path
    from superqode.factory.release import authorize_release

    try:
        path = project_path(Path(project).resolve(), proof)
        if path.stat().st_size > 8192:
            raise ValueError("Release proof exceeds 8 KB")
        result = authorize_release(work_order_id, json.loads(path.read_text()), root=project)
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result.to_dict(), indent=2))


@factory.command("apply")
@_project_option
@click.argument("work_order_id")
@click.option("--candidate-id", required=True)
@click.option("--candidate-digest", required=True)
def factory_apply(project, work_order_id, candidate_id, candidate_digest):
    """Apply an authenticated candidate to the working tree; no commit or deployment."""
    from superqode.factory.release import apply_approved

    try:
        order = apply_approved(
            work_order_id,
            root=project,
            candidate_id=candidate_id,
            candidate_digest=candidate_digest,
        )
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(order.to_dict(), indent=2))


@factory.command("status")
@click.argument("session_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_status(session_id, json_output):
    """Show factory metadata, routes, and lineage for a session."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().status(session_id or "")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Session: {payload['session_id']}")
    factory_meta = payload.get("factory") or {}
    click.echo(f"Mode: {factory_meta.get('mode') or '-'}")
    click.echo(f"Route: {factory_meta.get('route') or '-'}")
    click.echo(f"Model: {factory_meta.get('model_ref') or '-'}")
    click.echo(f"Harness: {factory_meta.get('harness') or '-'}")
    click.echo(f"Lineage events: {len(payload.get('lineage') or [])}")


@factory.command("routes")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_routes(json_output):
    """List built-in factory route presets."""
    from superqode.session.factory import SoftwareFactory

    routes = SoftwareFactory().routes()
    if json_output:
        click.echo(json.dumps(routes, indent=2))
        return
    for name, route in routes.items():
        tags = ", ".join(route.get("tags") or [])
        click.echo(f"{name:<16} {route.get('policy'):<18} {tags}")
        click.echo(f"  {route.get('description')}")


@factory.command("policy")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_policy(json_output):
    """Show the project factory policy file and merged policy."""
    from superqode.session.factory import SoftwareFactory

    factory_obj = SoftwareFactory()
    payload = {"path": str(factory_obj.policy_path), "policy": factory_obj.policy()}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Policy path: {payload['path']}")
    click.echo(json.dumps(payload["policy"], indent=2))


@factory.command("init-policy")
@click.option("--force", is_flag=True, help="Overwrite an existing .superqode/factory.yaml")
def factory_init_policy(force):
    """Create .superqode/factory.yaml with local-first defaults."""
    from superqode.session.factory import SoftwareFactory

    try:
        path = SoftwareFactory().init_policy(force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Factory policy: {path}")


@factory.command("resolve-route")
@click.argument("route")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_resolve_route(route, json_output):
    """Resolve a route through built-in defaults plus .superqode/factory.yaml."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().resolve_route(route)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(json.dumps(payload, indent=2))


@factory.command("mode")
@click.argument("mode")
@click.argument("session_id", required=False)
@click.option("--reason", default="", help="Why this factory mode was selected")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_mode(mode, session_id, reason, json_output):
    """Set a factory route/mode such as private, cheap, best, or no-subscription."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().set_mode(mode, session_id=session_id or "", reason=reason)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Factory mode for {payload['session_id']}: {mode}")


@factory.command("switch-model")
@click.argument("model_ref")
@click.argument("session_id", required=False)
@click.option("--runtime", default="", help="Runtime/backend label")
@click.option("--reason", default="", help="Why this model was selected")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_switch_model(model_ref, session_id, runtime, reason, json_output):
    """Record that a session moved to another model/provider/runtime."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().switch_model(
            model_ref,
            session_id=session_id or "",
            runtime=runtime,
            reason=reason,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Session {payload['session']['session_id']} model -> {model_ref}")
        for warning in payload.get("privacy_warnings") or []:
            click.echo(f"Warning: {warning}")


@factory.command("switch-harness")
@click.argument("harness")
@click.argument("session_id", required=False)
@click.option("--reason", default="", help="Why this harness was selected")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_switch_harness(harness, session_id, reason, json_output):
    """Record that a session moved to another harness/orchestration style."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().switch_harness(
            harness, session_id=session_id or "", reason=reason
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(f"Session {payload['session']['session_id']} harness -> {harness}")


@factory.command("fork-model")
@click.argument("source_session_id", required=False)
@click.option("--model", "model_ref", required=True, help="Provider/model reference")
@click.option("--role", default="", help="Factory worker role")
@click.option("--session-id", default="", help="New fork session id")
@click.option("--title", default="", help="Title for the fork")
@click.option("--goal", default="", help="Goal appended as a handoff message")
def factory_fork_model(source_session_id, model_ref, role, session_id, title, goal):
    """Fork work to another model/provider while preserving graph lineage."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().fork_model(
            source_session_id or "",
            model_ref=model_ref,
            role=role,
            new_session_id=session_id,
            title=title,
            goal=goal,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Forked to {payload['fork']['session']['session_id']} on {model_ref}")


@factory.command("fork-harness")
@click.argument("source_session_id", required=False)
@click.option("--harness", required=True, help="Harness id/name")
@click.option("--role", default="", help="Factory worker role")
@click.option("--session-id", default="", help="New fork session id")
@click.option("--title", default="", help="Title for the fork")
@click.option("--goal", default="", help="Goal appended as a handoff message")
def factory_fork_harness(source_session_id, harness, role, session_id, title, goal):
    """Fork work to another harness/orchestration style."""
    from superqode.session.factory import SoftwareFactory

    try:
        payload = SoftwareFactory().fork_harness(
            source_session_id or "",
            harness=harness,
            role=role,
            new_session_id=session_id,
            title=title,
            goal=goal,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Forked to {payload['fork']['session']['session_id']} using harness {harness}")


@factory.command("lineage")
@click.argument("session_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def factory_lineage(session_id, json_output):
    """Show model/harness/mode lineage for a session."""
    from superqode.session.factory import SoftwareFactory

    try:
        events = SoftwareFactory().lineage(session_id or "")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(events, indent=2))
        return
    if not events:
        click.echo("No factory lineage events.")
        return
    for event in events:
        click.echo(
            f"{event.get('created_at')}  {event.get('kind')}  "
            f"{event.get('previous')} -> {event.get('new')}"
        )
