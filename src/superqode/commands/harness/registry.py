"""Harness registry commands."""

import json
from pathlib import Path

import click

from ._group import harness


@harness.group("registry")
def harness_registry():
    """Publish, list, and install local HarnessSpec registry entries."""


@harness_registry.command("publish")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--name", default=None, help="Registry entry name")
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Replace an existing registry entry")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_publish(spec_path, name, registry_path, force, json_output):
    """Publish a validated HarnessSpec to the local registry."""
    from superqode.harness import publish_harness_spec

    try:
        payload = publish_harness_spec(spec_path, root=registry_path, name=name, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Published {payload['name']} -> {payload['spec']}")


@harness_registry.command("list")
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_list(registry_path, json_output):
    """List local registry entries."""
    from superqode.harness import list_registry_specs

    payload = list_registry_specs(root=registry_path)
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No harness registry entries found.")
        return
    for item in payload:
        click.echo(
            f"{item['name']}  {item.get('flavor', '-')}  "
            f"{item.get('runtime', '-')}  {item.get('model', '-')}"
        )


@harness_registry.command("install")
@click.argument("name")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
)
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Overwrite output")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_install(name, output, registry_path, force, json_output):
    """Install a local registry HarnessSpec into this project."""
    from superqode.harness import install_registry_spec

    try:
        payload = install_registry_spec(name, output, root=registry_path, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Installed {name} -> {payload['installed_to']}")
