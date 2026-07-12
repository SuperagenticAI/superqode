"""SuperQode 'factory' CLI: record model/harness switches and forks for a session."""

import json
import click
import click

import click


@click.group()
def factory():
    """Model- and harness-independent Software Factory commands."""
    pass
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
