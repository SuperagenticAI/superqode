"""Connect to an A2A agent from a card URL, the same shape as UHP connect."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from superqode.a2a.connection import (
    TOKEN_ENV,
    URL_ENV,
    A2ASettings,
    resolve_settings,
    save_connection,
)


def connect_a2a_agent(
    url: str | None = None,
    token: str | None = None,
    *,
    message: str | None = None,
    save: bool = True,
    inspect: bool = False,
    conformance: bool = False,
    json_output: bool = False,
) -> int:
    """Fetch the Agent Card, print what it advertises, optionally send one message."""
    settings = resolve_settings(url, token)
    if not settings.configured:
        return _fail(
            "No A2A agent URL is configured.",
            f"Pass --url or set {URL_ENV}.",
            json_output=json_output,
        )

    if conformance:
        return _run_conformance(
            settings,
            message=message,
            inspect=inspect,
            json_output=json_output,
        )

    try:
        result = asyncio.run(_probe(settings, message=message))
    except Exception as exc:  # noqa: BLE001 - report any transport or protocol failure
        inspect_payload = _inspect_from_exc(exc)
        return _fail(
            f"Could not reach the A2A agent at {settings.url}: {exc}",
            json_output=json_output,
            inspect=inspect_payload,
            show_inspect=True,
        )

    saved = False
    if save:
        save_connection(settings)
        saved = True

    if json_output:
        payload = {"connected": True, "saved": saved, **result}
        click.echo(json.dumps(payload, indent=2))
        return 0

    _render(settings, result, saved=saved, inspect=inspect)
    return 0


def _fail(
    message: str,
    hint: str = "",
    *,
    json_output: bool,
    inspect: dict[str, Any] | None = None,
    show_inspect: bool = False,
) -> int:
    if json_output:
        payload: dict[str, Any] = {"connected": False, "error": message}
        if inspect:
            payload["inspect"] = inspect
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(message)
        if hint:
            click.echo(hint)
        if show_inspect:
            _render_inspect(inspect)
    return 1


def _run_conformance(
    settings: A2ASettings,
    *,
    message: str | None,
    inspect: bool,
    json_output: bool,
) -> int:
    """Run the client checks. A check does not save the connection."""
    from superqode.a2a.conformance import render_a2a_conformance, run_a2a_conformance

    try:
        report = asyncio.run(run_a2a_conformance(settings, message=message))
    except Exception as exc:  # noqa: BLE001 - report any transport or protocol failure
        return _fail(
            f"Could not check the A2A agent at {settings.url}: {exc}",
            json_output=json_output,
            inspect=_inspect_from_exc(exc),
            show_inspect=True,
        )

    payload = report.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_a2a_conformance(report))
        if inspect or not report.passed:
            _render_inspect(report.inspect)
    return 0 if report.passed else 1


def _inspect_from_exc(exc: BaseException) -> dict[str, Any] | None:
    log = getattr(exc, "inspect", None)
    if log is None:
        return None
    if hasattr(log, "to_dict"):
        return log.to_dict()
    if isinstance(log, dict):
        return log
    return None


async def _probe(settings: A2ASettings, *, message: str | None) -> dict[str, Any]:
    from superqode.a2a.client import A2AClient, A2AClientError

    async with A2AClient(
        settings.url, bearer_token=settings.token or None, timeout=180.0
    ) as client:
        try:
            return await _probe_with(client, settings, message=message)
        except A2AClientError as exc:
            if exc.inspect is None:
                exc.inspect = client.inspect
            raise
        except Exception as exc:
            raise A2AClientError(str(exc), inspect=client.inspect) from exc


async def _probe_with(client, settings: A2ASettings, *, message: str | None) -> dict[str, Any]:
    card = await client.get_agent_card()
    payload: dict[str, Any] = {
        "url": settings.url,
        "interface_url": card.url,
        "binding": client._binding,
        "protocol_version": client._protocol_version,
        "name": card.name,
        "version": card.version,
        "description": card.description,
        "streaming": card.capabilities.streaming,
        "skills": [
            {"id": skill.id, "name": skill.name, "description": skill.description}
            for skill in card.skills
        ],
        "interfaces": list(card.supported_interfaces),
        "inspect": client.inspect.to_dict(),
    }
    if message:
        task = await client.send_message(message)
        text = ""
        if task.artifacts and task.artifacts[0].parts:
            text = task.artifacts[0].parts[0].text or ""
        payload["task"] = {
            "id": task.task_id,
            "state": task.status.state.value
            if hasattr(task.status.state, "value")
            else str(task.status.state),
            "text": text,
        }
        payload["inspect"] = client.inspect.to_dict()
    return payload


def _render(
    settings: A2ASettings, result: dict[str, Any], *, saved: bool, inspect: bool = False
) -> None:
    click.echo(f"Connected:  {result['name']} ({result['version']})")
    click.echo(f"Card:       {settings.url}")
    click.echo(f"Interface:  {result['interface_url']}")
    click.echo(f"Binding:    {result['binding']} {result['protocol_version']}")
    click.echo(f"Auth:       {'bearer' if settings.token else 'none'}")
    if result.get("description"):
        click.echo(f"About:      {result['description']}")
    skills = result.get("skills") or []
    if skills:
        click.echo(f"\nSkills ({len(skills)}):")
        for skill in skills:
            click.echo(f"  {skill['id']:<24} {skill['name']}")
    task = result.get("task")
    if task:
        click.echo(f"\nTask:       {task['id']}  {task['state']}")
        if task.get("text"):
            click.echo(task["text"])
    if inspect:
        _render_inspect(result.get("inspect"))
    if saved:
        click.echo(f"\nSaved. Override per shell with {URL_ENV} and {TOKEN_ENV}.")
        click.echo('  superqode connect a2a --send "Which coding agents are open source?"')


def _render_inspect(inspect: dict[str, Any] | None) -> None:
    events = (inspect or {}).get("events") or []
    if not events:
        return
    click.echo("\nInspect:")
    for event in events:
        if not isinstance(event, dict):
            continue
        click.echo(f"  {event.get('summary', '')}")
        detail = event.get("detail") or {}
        for skipped in detail.get("skipped") or []:
            if not isinstance(skipped, dict):
                continue
            binding = skipped.get("binding") or "?"
            version = skipped.get("version") or "?"
            loc = skipped.get("url") or "(no url)"
            reason = skipped.get("reason") or "unusable"
            click.echo(f"    skip {binding} {version} at {loc}: {reason}")
        body = detail.get("body")
        if body:
            for line in str(body).splitlines()[:12]:
                click.echo(f"    {line}")
