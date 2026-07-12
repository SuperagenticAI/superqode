"""SuperQode 'share' CLI: create/export/import/list portable session shares."""

import json
import click
import click

import click


@click.group()
def share():
    """Create and import local portable session share artifacts."""
    pass
@share.command("create")
@click.argument("session_id")
@click.option("--output", "-o", type=click.Path(), help="Write artifact to this path")
@click.option("--tree", "include_tree", is_flag=True, help="Include the session subtree graph")
def share_create(session_id, output, include_tree):
    """Create a portable SuperQode share artifact."""
    from superqode.session.share_artifacts import create_share_artifact

    try:
        path = create_share_artifact(session_id, output=output, include_tree=include_tree)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created share artifact: {path}")
@share.command("export")
@click.argument("session_id")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
@click.option("--output", "-o", type=click.Path(), required=True, help="Write export to file")
def share_export(session_id, fmt, output):
    """Export a stored session as Markdown or JSON."""
    from superqode.session.share_artifacts import export_session_file

    try:
        path = export_session_file(session_id, fmt=fmt, output=output)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Exported session: {path}")
@share.command("import")
@click.argument("artifact", type=click.Path(exists=True))
@click.option("--session-id", help="New session id to create")
def share_import(artifact, session_id):
    """Import a portable share artifact into local sessions."""
    from superqode.session.share_artifacts import import_share_artifact

    try:
        imported_id = import_share_artifact(artifact, new_session_id=session_id or "")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported session: {imported_id}")
@share.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def share_list(json_output):
    """List managed local share artifacts."""
    from superqode.session.share_artifacts import list_share_artifacts

    artifacts = list_share_artifacts()
    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "path": str(artifact.path),
                        "source_session_id": artifact.source_session_id,
                        "created_at": artifact.created_at,
                    }
                    for artifact in artifacts
                ],
                indent=2,
            )
        )
        return
    if not artifacts:
        click.echo("No share artifacts found.")
        return
    for artifact in artifacts:
        suffix = f"  session {artifact.source_session_id}" if artifact.source_session_id else ""
        click.echo(f"{artifact.path}{suffix}")
@share.command("revoke")
@click.argument("artifact")
def share_revoke(artifact):
    """Delete a managed local share artifact."""
    from superqode.session.share_artifacts import revoke_share_artifact

    try:
        path = revoke_share_artifact(artifact)
    except FileNotFoundError as exc:
        raise click.ClickException(f"share artifact not found: {artifact}") from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Revoked share artifact: {path}")
