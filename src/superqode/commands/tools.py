"""SuperQode 'tools' CLI: list available tools."""

import json
import click
import click

import click


@click.group()
def tools():
    """Inspect coding harness tools."""
    pass
@tools.command("list")
@click.option("--profile", default="build", help="Harness profile to inspect")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def tools_list(profile, json_output):
    """List tools available to a harness profile."""
    from superqode.headless import create_tool_registry, get_harness_profiles
    from superqode.tools.permissions import TOOL_GROUPS

    profiles_map = get_harness_profiles()
    if profile not in profiles_map:
        raise click.ClickException(f"Unknown profile: {profile}")

    harness_profile = profiles_map[profile]
    registry = create_tool_registry(harness_profile)
    payload = []
    for tool in sorted(registry.list(), key=lambda item: item.name):
        group = TOOL_GROUPS.get(tool.name)
        permission = harness_profile.permissions.get_permission(tool.name).value
        payload.append(
            {
                "name": tool.name,
                "group": group.value if group else "other",
                "permission": permission,
                "description": tool.description,
            }
        )

    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for item in payload:
        click.echo(f"{item['name']}  {item['group']}  {item['permission']}  {item['description']}")
