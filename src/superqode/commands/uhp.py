"""Connect to a Unified Harness Protocol server and select one of its harnesses.

A UHP server is a remote catalog: the address comes first, the harness list
arrives over the network, and only then is there something to select.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from superqode.providers.uhp import (
    API_KEY_ENV,
    BASE_URL_ENV,
    UHPSettings,
    resolve_settings,
    save_connection,
    setup_hint,
)


def connect_uhp_server(
    base_url: str | None = None,
    api_key: str | None = None,
    harness_id: str | None = None,
    *,
    save: bool = True,
    json_output: bool = False,
) -> int:
    """Resolve a UHP server, discover its harnesses, and select one."""
    settings = resolve_settings(base_url, api_key, harness_id)
    if not settings.configured:
        return _fail("No UHP server is configured.", setup_hint(), json_output=json_output)

    try:
        result = asyncio.run(_discover(settings))
    except Exception as exc:  # noqa: BLE001 - report any transport or protocol failure
        return _fail(
            f"Could not reach the UHP server at {settings.base_url}: {exc}",
            json_output=json_output,
        )

    harnesses = result["harnesses"]
    requested = settings.harness_id
    selected = _select(harnesses, requested)

    if requested and selected is None:
        return _fail(
            f"The UHP server does not advertise a harness with id {requested!r}.",
            "Run `superqode connect uhp` without --harness to see the catalog.",
            json_output=json_output,
            extra={"requested_harness": requested, "harnesses": harnesses},
        )

    saved = False
    if save and selected is not None:
        settings = UHPSettings(
            base_url=settings.base_url,
            api_key=settings.api_key,
            harness_id=selected["id"],
        )
        save_connection(settings)
        saved = True

    if json_output:
        click.echo(
            json.dumps(
                {
                    "connected": True,
                    "base_url": settings.base_url,
                    "uhp_version": result["version"],
                    "conformance_class": result["conformance_class"],
                    "capabilities": result["capabilities"],
                    "saved": saved,
                    "selected": selected,
                    "harnesses": harnesses,
                },
                indent=2,
            )
        )
        return 0

    _render(settings, result, harnesses, selected, saved=saved)
    return 0


def _fail(
    message: str,
    hint: str = "",
    *,
    json_output: bool,
    extra: dict[str, Any] | None = None,
) -> int:
    """Report a failed connection consistently in both output modes."""
    if json_output:
        payload: dict[str, Any] = {"connected": False, "error": message}
        payload.update(extra or {})
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(message)
        if hint:
            click.echo(hint)
    return 1


async def _discover(settings: UHPSettings) -> dict[str, Any]:
    """Fetch the server's declaration and harness catalog."""
    from superqode.harness.uhp_client import UHPClient

    async with UHPClient(settings.base_url, api_key=settings.api_key or None) as client:
        try:
            discovery = await client.discover()
        except Exception:  # noqa: BLE001 - discovery is not required to list
            discovery = None
        harnesses = await client.list_harnesses()
    return {
        "version": (discovery.default_version if discovery else "") or "unknown",
        "versions": list(discovery.versions) if discovery else [],
        "conformance_class": discovery.conformance_class if discovery else "",
        "capabilities": dict(discovery.capabilities) if discovery else {},
        "speaks_target_version": bool(discovery and discovery.speaks_target_version),
        "discovered": discovery is not None,
        "harnesses": [
            {
                "id": harness.id,
                "name": harness.name or harness.id,
                "base": harness.base,
                "base_label": harness.base_label,
                "default_model": harness.default_model,
            }
            for harness in harnesses
        ],
    }


def _select(harnesses: list[dict[str, Any]], harness_id: str) -> dict[str, Any] | None:
    """Return the requested harness, the only one, or nothing to pick from."""
    if harness_id:
        for harness in harnesses:
            if harness["id"] == harness_id:
                return harness
        return None
    if len(harnesses) == 1:
        return harnesses[0]
    return None


def _render(
    settings: UHPSettings,
    result: dict[str, Any],
    harnesses: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    *,
    saved: bool,
) -> None:
    """Print the connection, the catalog, and the next command to run."""
    click.echo(f"Connected:  {settings.base_url}")
    version = result["version"]
    conformance = result["conformance_class"]
    click.echo(f"Protocol:   UHP {version}{f' ({conformance})' if conformance else ''}")
    click.echo(f"Auth:       {'bearer key' if settings.api_key else 'none supplied'}")
    if result["discovered"] and not result["speaks_target_version"]:
        from superqode.harness.uhp_client import UHP_PROTOCOL_VERSION

        click.echo(
            f"\n!  This server does not list {UHP_PROTOCOL_VERSION}, "
            "which is the version SuperQode speaks."
        )

    if not harnesses:
        click.echo("\nThis server advertises no harnesses.")
        return

    click.echo(f"\nHarnesses ({len(harnesses)}):")
    for harness in harnesses:
        marker = "*" if selected and harness["id"] == selected["id"] else " "
        label = harness["base_label"] or harness["base"] or "harness"
        model = harness["default_model"] or "server default"
        click.echo(f" {marker} {harness['id']:<24} {harness['name']:<20} {label} · {model}")

    if selected is None:
        click.echo("\nSelect one:")
        click.echo(f"  superqode connect uhp --harness {harnesses[0]['id']}")
        return

    click.echo(f"\nSelected:   {selected['id']}")
    if saved:
        click.echo("\nThis harness is now the `uhp` route:")
        click.echo("  superqode harness protocol list")
        click.echo('  superqode harness run uhp "review this repository"')
        click.echo(f"\nThe connection is saved. Override per shell with {BASE_URL_ENV}.")
    else:
        click.echo("\nThe connection was not saved, so this selection applies to this run only.")
    if not settings.api_key:
        click.echo(
            f"\nThis server accepted an unauthenticated listing. Export {API_KEY_ENV} "
            "if running tasks needs a credential."
        )
