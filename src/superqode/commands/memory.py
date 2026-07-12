"""SuperQode 'memory' CLI: agent memory providers/status/remember/search."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def memory():
    """Manage SuperQode agent memory."""
    pass
@memory.command("providers")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def memory_providers(json_output):
    """List built-in memory providers and readiness."""
    from superqode.memory import available_memory_providers

    statuses = available_memory_providers(Path.cwd())
    if json_output:
        click.echo(json.dumps([status.to_dict() for status in statuses], indent=2))
        return
    for status in statuses:
        state = _memory_status_state(status)
        click.echo(f"{status.provider:<12} {state:<9} {status.detail}")
@memory.command("status")
@click.option(
    "--provider",
    default="local",
    help="Memory provider: local, specmem, mem0, cognee, or supermemory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def memory_status(provider, json_output):
    """Show memory provider status."""
    from superqode.memory import create_memory_provider

    try:
        status = create_memory_provider(provider, project_root=Path.cwd()).status()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(status.to_dict(), indent=2))
        return
    click.echo(f"Provider: {status.provider}")
    click.echo(f"Status: {_memory_status_state(status)}")
    click.echo(f"Records: {status.record_count}")
    if status.path:
        click.echo(f"Path: {status.path}")
    if status.detail:
        click.echo(f"Detail: {status.detail}")
@memory.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def memory_doctor(json_output):
    """Check memory provider readiness."""
    from superqode.memory import available_memory_providers

    statuses = available_memory_providers(Path.cwd())
    payload = {
        "providers": [status.to_dict() for status in statuses],
        "ready": any(status.available for status in statuses),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    for status in statuses:
        state = _memory_status_state(status).upper()
        click.echo(f"{state} {status.provider}: {status.detail}")
@memory.command("remember")
@click.argument("text")
@click.option(
    "--kind", default="note", help="Memory kind: preference, project, decision, procedure, note"
)
@click.option("--scope", default="project", help="Memory scope: user, project, team")
@click.option("--tag", "tags", multiple=True, help="Tag to attach")
def memory_remember(text, kind, scope, tags):
    """Store an explicit local memory."""
    from superqode.memory import create_memory_provider

    provider = create_memory_provider("local", project_root=Path.cwd())
    try:
        record = provider.remember(text, kind=kind, scope=scope, tags=tuple(tags))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Remembered {record.id}")
@memory.command("search")
@click.argument("query")
@click.option(
    "--provider",
    default="local",
    help="Memory provider: local, specmem, mem0, cognee, or supermemory",
)
@click.option("--limit", default=8, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def memory_search(query, provider, limit, json_output):
    """Search memory."""
    from superqode.memory import create_memory_provider

    try:
        results = create_memory_provider(provider, project_root=Path.cwd()).search(
            query, limit=limit
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps([result.to_dict() for result in results], indent=2))
        return
    if not results:
        click.echo("No memory matches.")
        return
    for result in results:
        record = result.record
        click.echo(f"{record.id}  {result.provider}  {record.kind}  score={result.score:.2f}")
        click.echo(f"  {record.content}")
@memory.command("forget")
@click.argument("memory_id")
def memory_forget(memory_id):
    """Delete a local memory by id or unique prefix."""
    from superqode.memory import create_memory_provider

    provider = create_memory_provider("local", project_root=Path.cwd())
    if provider.forget(memory_id):
        click.echo(f"Forgot {memory_id}")
    else:
        raise click.ClickException(f"Memory not found: {memory_id}")
@memory.command("export")
@click.option(
    "--provider",
    default="local",
    help="Memory provider: local, specmem, mem0, cognee, or supermemory",
)
@click.option("--output", "-o", type=click.Path(), help="Write JSON to file")
def memory_export(provider, output):
    """Export memory provider data as JSON."""
    from superqode.memory import create_memory_provider

    try:
        payload = create_memory_provider(provider, project_root=Path.cwd()).export()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Exported memory to {output}")
    else:
        click.echo(content, nl=False)
def _memory_status_state(status) -> str:
    if getattr(status, "available", False):
        return "ready"
    if not getattr(status, "enabled", True):
        return "disabled"
    if getattr(status, "installed", None) is False:
        return "missing"
    return "missing"
