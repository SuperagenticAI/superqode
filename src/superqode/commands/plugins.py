"""SuperQode 'plugins' CLI: list/show/validate/enable plugins."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def plugins():
    """Inspect SuperQode plugin manifests."""
    pass
@plugins.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.option("--all", "include_disabled", is_flag=True, help="Include disabled plugins")
def plugins_list(json_output, include_disabled):
    """List discoverable plugins."""
    from superqode.plugins import disabled_plugin_ids, load_plugins

    loaded = load_plugins(Path.cwd(), include_disabled=include_disabled)
    disabled = disabled_plugin_ids(Path.cwd())
    if json_output:
        click.echo(
            json.dumps(
                [{**plugin.to_dict(), "enabled": plugin.id not in disabled} for plugin in loaded],
                indent=2,
            )
        )
        return

    if not loaded:
        click.echo("No plugins found.")
        return

    for plugin in loaded:
        state = "enabled" if plugin.id not in disabled else "disabled"
        click.echo(f"{plugin.id}  {plugin.version}  {state}  {plugin.name}")
@plugins.command("show")
@click.argument("plugin_id")
def plugins_show(plugin_id):
    """Show one plugin manifest."""
    from superqode.plugins import load_plugins

    for plugin in load_plugins(Path.cwd()):
        if plugin.id == plugin_id or plugin.name == plugin_id:
            click.echo(json.dumps(plugin.to_dict(), indent=2))
            return
    raise click.ClickException(f"Plugin not found: {plugin_id}")
@plugins.command("validate")
@click.argument("path", type=click.Path(exists=True))
def plugins_validate(path):
    """Validate a plugin manifest file."""
    from superqode.plugins import validate_plugin_manifest

    issues = validate_plugin_manifest(path)
    if issues:
        for issue in issues:
            click.echo(f"Error: {issue}")
        raise click.ClickException("Plugin manifest is invalid")
    click.echo("Plugin manifest is valid.")
@plugins.command("doctor")
@click.argument("path", required=False, type=click.Path())
def plugins_doctor(path):
    """Validate all discoverable plugin manifests, or one path."""
    from superqode.plugins import (
        discover_plugin_manifests,
        load_plugin_manifest,
        validate_plugin_manifest,
    )

    if path:
        target = Path(path)
        if target.is_dir():
            target = target / "plugin.json"
        paths = [target]
    else:
        paths = discover_plugin_manifests(Path.cwd())
    if not paths:
        click.echo("No plugin manifests found.")
        return
    ok_count = 0
    failed = False
    for manifest_path in paths:
        issues = validate_plugin_manifest(manifest_path)
        label = str(manifest_path)
        try:
            label = load_plugin_manifest(manifest_path).id
        except Exception:
            pass
        if issues:
            failed = True
            click.echo(f"FAIL {label}")
            for issue in issues:
                click.echo(f"  - {issue}")
        else:
            ok_count += 1
            click.echo(f"OK {label}")
    click.echo(f"{ok_count}/{len(paths)} manifests valid.")
    if failed:
        raise click.ClickException("Plugin doctor found issues")
@plugins.command("add")
@click.argument("source", type=click.Path(exists=True))
def plugins_add(source):
    """Install a local plugin directory or plugin.json."""
    from superqode.plugins import install_plugin
    from superqode.project_trust import is_project_trusted

    if not is_project_trusted(Path.cwd()):
        raise click.ClickException("Project is untrusted. Run `superqode trust yes` first.")
    try:
        plugin = install_plugin(source, Path.cwd())
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Installed plugin {plugin.id}")
@plugins.command("enable")
@click.argument("plugin_id")
def plugins_enable(plugin_id):
    """Enable a plugin id for this project."""
    from superqode.plugins import enable_plugin
    from superqode.project_trust import is_project_trusted

    if not is_project_trusted(Path.cwd()):
        raise click.ClickException("Project is untrusted. Run `superqode trust yes` first.")
    changed = enable_plugin(plugin_id, Path.cwd())
    click.echo(
        f"Enabled plugin {plugin_id}" if changed else f"Plugin {plugin_id} was already enabled"
    )
@plugins.command("disable")
@click.argument("plugin_id")
def plugins_disable(plugin_id):
    """Disable a plugin id for this project."""
    from superqode.plugins import disable_plugin

    changed = disable_plugin(plugin_id, Path.cwd())
    click.echo(
        f"Disabled plugin {plugin_id}" if changed else f"Plugin {plugin_id} was already disabled"
    )
