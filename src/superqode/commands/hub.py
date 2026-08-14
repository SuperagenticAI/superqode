"""Browse and export the shared SuperQode Harness Hub catalog."""

from __future__ import annotations

import json
from pathlib import Path

import click

from superqode.harness.hub import READINESS_VALUES


def _catalog(*, query: str, readiness: str | None, category: str, public: bool = False) -> dict:
    from superqode.harness.hub import build_hub_index, filter_hub_records

    payload = build_hub_index(Path.cwd(), public=public)
    payload["items"] = filter_hub_records(
        payload["items"], query=query, readiness=readiness, category=category
    )
    payload["count"] = len(payload["items"])
    payload["categories"] = list(dict.fromkeys(item["category"] for item in payload["items"]))
    return payload


def _render(payload: dict, *, json_output: bool) -> None:
    from superqode.harness.hub import readiness_label

    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload["items"]:
        click.echo("No harnesses match those filters.")
        return
    current_category = None
    for item in payload["items"]:
        if item["category"] != current_category:
            current_category = item["category"]
            click.echo(f"\n{current_category}")
        state = readiness_label(item["readiness"])
        click.echo(f"  {item['id']:<24} {state:<20} {item['name']}")


def _filters(function):
    function = click.option(
        "--public",
        "public_catalog",
        is_flag=True,
        help="Exclude repository and user-registry harnesses for publication",
    )(function)
    function = click.option("--category", default="", help="Filter by exact Hub category")(function)
    function = click.option(
        "--readiness",
        type=click.Choice(list(READINESS_VALUES)),
        default=None,
        help="Filter by current readiness",
    )(function)
    function = click.option("--search", "query", "-s", default="", help="Search the catalog")(
        function
    )
    function = click.option(
        "--json", "json_output", is_flag=True, help="Emit the versioned Hub index"
    )(function)
    return function


@click.group(invoke_without_command=True)
@click.pass_context
@_filters
def hub(
    ctx,
    json_output: bool,
    query: str,
    readiness: str | None,
    category: str,
    public_catalog: bool,
):
    """Discover every harness available through SuperQode."""
    if ctx.invoked_subcommand is None:
        _render(
            _catalog(
                query=query,
                readiness=readiness,
                category=category,
                public=public_catalog,
            ),
            json_output=json_output,
        )


@hub.command("list")
@_filters
def hub_list(
    json_output: bool,
    query: str,
    readiness: str | None,
    category: str,
    public_catalog: bool,
):
    """List or search the complete Harness Hub."""
    _render(
        _catalog(
            query=query,
            readiness=readiness,
            category=category,
            public=public_catalog,
        ),
        json_output=json_output,
    )


@hub.command("show")
@click.argument("harness_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def hub_show(harness_id: str, json_output: bool):
    """Show one harness and its setup or continuity information."""
    payload = _catalog(query="", readiness="", category="")
    item = next((entry for entry in payload["items"] if entry["id"] == harness_id), None)
    if item is None:
        raise click.ClickException(f"Harness not found: {harness_id}")
    if json_output:
        click.echo(json.dumps(item, indent=2))
        return
    for label, field in (
        ("Name", "name"),
        ("ID", "id"),
        ("Category", "category"),
        ("Readiness", "readiness"),
        ("Integration", "integration_level"),
        ("Runtime", "runtime"),
        ("Continuity", "continuity"),
        ("Description", "description"),
        ("Setup", "setup"),
        ("Warning", "warning"),
    ):
        if item.get(field):
            click.echo(f"{label}: {item[field]}")


__all__ = ["hub"]
