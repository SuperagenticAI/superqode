"""SuperQode 'sessions' CLI: list/tree/graph/switch/handoff/fork stored sessions."""

import json
import click
import click

import click


@click.group()
def sessions():
    """Manage stored SuperQode coding sessions."""
    pass


@sessions.command("list")
@click.option("--limit", default=20, type=int, help="Maximum sessions to show")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_list(limit, json_output):
    """List stored sessions."""
    from superqode.headless import list_sessions

    items = list_sessions(limit=limit)
    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "session_id": item.session_id,
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                        "provider": item.provider,
                        "model": item.model,
                        "harness_id": item.harness_id or "workbench",
                        "message_count": item.message_count,
                    }
                    for item in items
                ]
            )
        )
        return

    if not items:
        click.echo("No sessions found.")
        return

    for item in items:
        click.echo(
            f"{item.session_id}  {item.harness_id or 'workbench'}  "
            f"{item.provider or '-'}  {item.model or '-'}  "
            f"{item.message_count} messages  {item.updated_at}"
        )


@sessions.command("tree")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_tree(json_output):
    """Show session fork lineage."""
    from superqode.headless import session_tree

    tree = session_tree()
    if json_output:
        click.echo(json.dumps(tree, indent=2))
        return

    def print_node(node, indent=0):
        click.echo(
            "  " * indent
            + f"{node['session_id']}  {node['model'] or '-'}  {node['message_count']} messages"
        )
        for child in node["children"]:
            print_node(child, indent + 1)

    if not tree:
        click.echo("No sessions found.")
        return
    for node in tree:
        print_node(node)


@sessions.command("graph")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_graph(json_output):
    """Show the durable switchboard session graph."""
    from superqode.session.switchboard import SessionSwitchboard

    tree = SessionSwitchboard().graph_tree()
    if json_output:
        click.echo(json.dumps(tree, indent=2))
        return

    def print_node(node, indent=0):
        title = f"  {node['title']}" if node.get("title") else ""
        agent = f"  agent={node['agent_id']}" if node.get("agent_id") else ""
        click.echo(
            "  " * indent
            + f"{node['session_id']}  {node.get('kind') or '-'}  {node.get('status') or '-'}"
            + agent
            + title
        )
        for child in node.get("children") or []:
            print_node(child, indent + 1)

    if not tree:
        click.echo("No sessions found.")
        return
    for node in tree:
        print_node(node)


@sessions.command("switch")
@click.argument("session_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_switch(session_id, json_output):
    """Set or show the active switchboard session."""
    from superqode.session.switchboard import SessionSwitchboard

    switchboard = SessionSwitchboard()
    try:
        record = switchboard.switch(session_id or "")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(record, indent=2))
    else:
        click.echo(f"Active session: {record['session_id']}  {record.get('title') or ''}")


@sessions.command("info")
@click.argument("session_id", required=False)
def sessions_info(session_id):
    """Show switchboard metadata for a session."""
    from superqode.session.switchboard import SessionSwitchboard

    try:
        click.echo(json.dumps(SessionSwitchboard().info(session_id or ""), indent=2))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@sessions.command("history")
@click.argument("session_id", required=False)
@click.option("--limit", default=20, type=int, help="Maximum messages to show")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_history(session_id, limit, json_output):
    """Show recent messages for a session."""
    from superqode.session.switchboard import SessionSwitchboard

    try:
        payload = SessionSwitchboard().history(session_id or "", limit=limit)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    for item in payload["messages"]:
        content = " ".join(str(item.get("content") or "").split())
        click.echo(f"{item.get('timestamp')}  {item.get('role')}: {content[:500]}")


@sessions.command("children")
@click.argument("session_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_children(session_id, json_output):
    """List child sessions for a session."""
    from superqode.session.switchboard import SessionSwitchboard

    try:
        children = SessionSwitchboard().children(session_id or "")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(children, indent=2))
        return
    if not children:
        click.echo("No child sessions.")
        return
    for child in children:
        click.echo(
            f"{child['session_id']}  {child.get('agent_id') or '-'}  "
            f"{child.get('status') or '-'}  {child.get('title') or ''}"
        )


@sessions.command("handoff")
@click.argument("source_session_id", required=False)
@click.option(
    "--target-session-id", default="", help="Existing target session to receive the handoff"
)
@click.option("--agent", default="", help="Target agent id/name")
@click.option("--goal", default="", help="Goal for the receiving session/agent")
@click.option("--reason", default="", help="Why the handoff is being made")
@click.option("--deliver", is_flag=True, help="Append the handoff message to --target-session-id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_handoff(
    source_session_id, target_session_id, agent, goal, reason, deliver, json_output
):
    """Create or deliver a cross-session handoff packet."""
    from superqode.session.switchboard import SessionSwitchboard

    switchboard = SessionSwitchboard()
    try:
        if deliver:
            if not target_session_id:
                raise click.ClickException("--target-session-id is required with --deliver")
            payload = switchboard.handoff_to_session(
                source_session_id or "",
                target_session_id,
                goal=goal,
                reason=reason,
            )
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(f"Delivered handoff {payload['id']} to {payload['target_session_id']}")
            return
        packet = switchboard.make_handoff(
            source_session_id or "",
            target_session_id=target_session_id,
            target_agent=agent,
            goal=goal,
            reason=reason,
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(packet.to_dict(), indent=2))
    else:
        click.echo(packet.to_message(), nl=False)


@sessions.command("fork-agent")
@click.argument("source_session_id", required=False)
@click.option("--agent", required=True, help="Agent id/name receiving the fork")
@click.option("--session-id", default="", help="New fork session id")
@click.option("--title", default="", help="Title for the fork")
@click.option("--goal", default="", help="Goal appended as a handoff message")
def sessions_fork_agent(source_session_id, agent, session_id, title, goal):
    """Fork a session and tag the fork for another coding agent."""
    from superqode.session.switchboard import SessionSwitchboard

    try:
        payload = SessionSwitchboard().fork_to_agent(
            source_session_id or "",
            agent=agent,
            new_session_id=session_id,
            title=title,
            goal=goal,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Forked {source_session_id or 'active'} to {payload['session']['session_id']} "
        f"for agent {agent} with handoff {payload['handoff']['id']}"
    )


@sessions.command("show")
@click.argument("session_id")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
def sessions_show(session_id, fmt):
    """Show a stored session."""
    from superqode.headless import export_session

    click.echo(export_session(session_id, fmt=fmt), nl=False)


@sessions.command("export")
@click.argument("session_id")
@click.option(
    "--format", "fmt", type=click.Choice(["markdown", "json", "html"]), default="markdown"
)
@click.option("--output", "-o", type=click.Path(), help="Write export to file")
def sessions_export(session_id, fmt, output):
    """Export a stored session (markdown, json, or a shareable html page)."""
    from pathlib import Path
    from superqode.headless import export_session

    content = export_session(session_id, fmt=fmt)
    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Exported session to {output}")
    else:
        click.echo(content, nl=False)


@sessions.command("delete")
@click.argument("session_id")
def sessions_delete(session_id):
    """Delete a stored session."""
    from superqode.headless import resolve_session_id
    from superqode.agent.session_manager import SessionManager

    resolved = resolve_session_id(session_id)
    SessionManager(storage_dir=".superqode/sessions").delete_session(resolved)
    click.echo(f"Deleted session {resolved}")
