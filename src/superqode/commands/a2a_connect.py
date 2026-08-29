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
    headers: dict[str, str] | None = None,
    message: str | None = None,
    save: bool = True,
    inspect: bool = False,
    conformance: bool = False,
    send: bool = True,
    json_output: bool = False,
    oauth: bool = True,
    logout: bool = False,
    cert: str | None = None,
    key: str | None = None,
) -> int:
    """Fetch the Agent Card, print what it advertises, optionally send one message."""
    settings = resolve_settings(url, token, headers, cert=cert, key=key)
    if not settings.configured:
        return _fail(
            "No A2A agent URL is configured.",
            f"Pass --url or set {URL_ENV}.",
            json_output=json_output,
        )

    if logout:
        return _logout(settings.url, json_output=json_output)

    if conformance:
        return _run_conformance(
            settings,
            message=message,
            inspect=inspect,
            send=send,
            json_output=json_output,
        )

    try:
        result = asyncio.run(
            _probe(
                settings,
                message=message,
                interactive=not json_output,
                oauth=oauth,
            )
        )
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


def _logout(origin: str, *, json_output: bool) -> int:
    from superqode.a2a.oauth import logout_origin

    cleared, revoked = asyncio.run(logout_origin(origin))
    if json_output:
        click.echo(
            json.dumps(
                {"logout": True, "url": origin, "cleared": cleared, "revoked": revoked},
                indent=2,
            )
        )
        return 0
    if cleared:
        click.echo(f"Deleted OAuth tokens for {origin}")
    else:
        click.echo(f"No stored OAuth tokens for {origin}")
    if revoked:
        click.echo("Revoked tokens at the identity provider.")
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
    send: bool,
    json_output: bool,
) -> int:
    """Run the client checks. A check does not save the connection."""
    from superqode.a2a.conformance import render_a2a_conformance, run_a2a_conformance

    try:
        report = asyncio.run(run_a2a_conformance(settings, message=message, send=send))
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


async def _probe(
    settings: A2ASettings,
    *,
    message: str | None,
    interactive: bool = True,
    oauth: bool = True,
) -> dict[str, Any]:
    from superqode.a2a.client import A2AClient, A2AClientError

    async with A2AClient(
        settings.url,
        bearer_token=settings.token or None,
        extra_headers=settings.headers or None,
        client_cert=settings.cert or None,
        client_key=settings.key or None,
        timeout=180.0,
    ) as client:
        try:
            return await _probe_with(
                client,
                settings,
                message=message,
                interactive=interactive,
                oauth=oauth,
            )
        except A2AClientError as exc:
            if exc.inspect is None:
                exc.inspect = client.inspect
            raise
        except Exception as exc:
            raise A2AClientError(str(exc), inspect=client.inspect) from exc


async def _probe_with(
    client,
    settings: A2ASettings,
    *,
    message: str | None,
    interactive: bool = True,
    oauth: bool = True,
) -> dict[str, Any]:
    import click

    from superqode.a2a.oauth import satisfy_card_auth

    card = await client.get_agent_card()
    await satisfy_card_auth(
        client,
        settings.url,
        token=settings.token,
        headers=dict(settings.headers),
        interactive=interactive,
        skip_oauth=not oauth,
        prompt_secret=(
            (lambda name: click.prompt(f"API key for {name}", hide_input=True))
            if interactive
            else None
        ),
        on_status=click.echo if interactive else None,
    )
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
        from superqode.a2a.reply import task_reply

        task = await client.send_message(message)
        payload["task"] = {
            "id": task.task_id,
            "state": task.status.state.value
            if hasattr(task.status.state, "value")
            else str(task.status.state),
            "text": task_reply(task),
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
    auth = []
    if settings.token:
        auth.append("credential")
    if settings.headers:
        auth.append("headers")
    if settings.cert:
        auth.append("mtls")
    click.echo(f"Auth:       {', '.join(auth) or 'none'}")
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
