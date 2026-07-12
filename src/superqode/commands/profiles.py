"""SuperQode 'profiles' CLI: list connection profiles."""

import json
import click
import click

import click


@click.group()
def profiles():
    """List built-in SuperQode harness profiles."""
    pass
@profiles.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def profiles_list(json_output):
    """List harness profiles."""
    from superqode.headless import get_harness_profiles

    items = get_harness_profiles()
    payload = [
        {
            "name": profile.name,
            "description": profile.description,
            "system_level": profile.system_level.value,
            "tools": profile.tools,
        }
        for profile in items.values()
    ]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    for item in payload:
        click.echo(f"{item['name']}  {item['system_level']}  {item['description']}")
