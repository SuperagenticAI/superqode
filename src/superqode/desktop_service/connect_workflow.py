"""Native projection of the terminal connection ownership ladder."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from .routes import acp_routes

MENU_CONNECTORS = {
    "agent-picker": "agents",
    "subscription-picker": "agents",
    "vendor-picker": "vendors",
    "harness-picker-menu": "harness",
    "model-picker": "models",
    "plan-picker": "plan",
    "build-picker": "build",
    "protocols-menu": "protocols",
    "open-harness-picker": "open-harnesses",
    "closed-harness-picker": "closed-harnesses",
    "language-picker": "by-language",
    "rlm-picker": "rlm-options",
    "systemone-picker": "systemone-models",
}


def profile_route(root: Path, profile_id: str):
    from superqode.providers.connection_profiles import get_connection_profile
    from superqode.providers.subscription_env import resolve_vendor

    profile = get_connection_profile(profile_id)
    if not profile:
        raise ValueError("Unknown connection profile")
    if profile.connector == "plan-agent":
        return profile_route(root, profile.acp_agent)
    if profile.connector == "harness-account":
        from superqode.providers.harness_catalog import get_entry

        entry = get_entry(profile.runtime or "")
        auth = next((a for a in entry.auth if a.mode == "subscription"), None) if entry else None
        base = (
            next((r for r in acp_routes(root) if r["id"] == "acp:" + (entry.acp_agent or "")), None)
            if entry
            else None
        )
        if not base or not auth:
            raise ValueError("This harness does not advertise an account route")
        route = {
            **base,
            "id": "connection:" + profile.id,
            "extra_env": dict(auth.account_env),
            "subscription_vendor": "codex"
            if entry.acp_agent == "fast-agent"
            else resolve_vendor(entry.acp_agent or ""),
            "auth": "subscription requested",
        }
        route["digest"] = hashlib.sha256(json.dumps(route, sort_keys=True).encode()).hexdigest()
        return route
    if profile.connector == "acp":
        route = next((r for r in acp_routes(root) if r["id"] == profile.id), None)
        if route:
            return route
    runtime = "copilot-sdk" if profile.connector == "copilot" else profile.runtime
    if profile.connector == "prime-rpc":
        runtime = "prime-agent"
    if profile.connector not in {"runtime", "copilot", "prime-rpc"}:
        raise ValueError("This profile needs a model, protocol address or harness setup first")
    route = {
        "id": "connection:" + profile.id,
        "name": profile.label,
        "description": profile.description,
        "runtime": runtime,
        "available": profile.available,
        "issue": profile.unavailable_hint,
        "desktop_kind": "connection",
        "kind": "runtime",
        "subscription_vendor": resolve_vendor(profile.id)
        if profile.auth_mode == "subscription"
        else None,
        "auth": profile.auth_mode or "agent-managed",
    }
    route["digest"] = hashlib.sha256(json.dumps(route, sort_keys=True).encode()).hexdigest()
    return route


def connection_menu(root: Path, menu: str):
    from superqode.providers.connection_profiles import (
        list_connection_profiles,
        connect_menu_titles,
    )

    title = connect_menu_titles().get(menu, ("Protocols" if menu == "protocols" else "Connect", ""))
    rows = []
    for p in list_connection_profiles(menu):
        row = {
            "id": p.id,
            "name": p.label,
            "description": p.description,
            "connector": p.connector,
            "available": p.available,
            "issue": p.unavailable_hint,
            "auth": p.auth_mode,
            "transport": p.transport,
            "runtime": p.runtime or "",
            "provider": p.byok_provider or "",
            "next": MENU_CONNECTORS.get(p.connector, ""),
        }
        if p.connector == "language-harness-picker":
            row["next"] = "by-language:" + p.label
        if p.connector == "key-harness":
            from superqode.providers.harness_catalog import get_entry

            entry = get_entry(p.id)
            auth = (
                next((a for a in entry.auth if a.mode in {"byok", "local"}), None)
                if entry
                else None
            )
            if auth and auth.after_auth == "switch-and-model":
                row["harness_ref"] = entry.harness_id or p.runtime
            if auth:
                row["setup_note"] = auth.notes or (entry.support_note if entry else "")
        if p.connector == "key-harness" and not row.get("harness_ref"):
            try:
                row["attachment"] = attachment_route(root, p.id)
            except ValueError:
                pass
        if p.connector in {"vendor-key", "external-cli", "key-harness"}:
            from .configuration import vendor_key_route

            try:
                row["vendor_key"] = vendor_key_route(root, p.id)
            except ValueError:
                pass
        try:
            row["route"] = profile_route(root, p.id)
        except ValueError:
            pass
        if p.auth_mode == "subscription" or p.connector in {"runtime", "copilot", "acp"}:
            from superqode.providers.subscription_env import resolve_vendor
            from superqode.providers.subscription_login import get_login_spec, login_command

            try:
                login = get_login_spec(resolve_vendor(p.id) or p.id)
                row["login"] = {
                    "id": login.id,
                    "label": login.label,
                    "command": login_command(login),
                    "interactive": login.interactive_tty,
                }
            except (KeyError, FileNotFoundError):
                pass
        from .configuration import install_plan

        try:
            row["install"] = install_plan(root, p.id)
        except ValueError:
            pass
        rows.append(row)
    result = {"menu": menu, "title": title[0], "subtitle": title[1], "rows": rows}
    if menu == "root":
        from superqode.providers.connection_profiles import detected_chips

        chips = []
        for chip in detected_chips(root):
            item = asdict(chip)
            if chip.kind == "profile":
                try:
                    item["route"] = profile_route(root, chip.target)
                except ValueError:
                    pass
            chips.append(item)
        result["detected"] = chips
    return result


def validate_origin(url: str, has_credentials: bool):
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter an HTTP(S) server address without credentials, query or fragment")
    if (
        has_credentials
        and parsed.scheme != "https"
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Use HTTPS to send credentials to a remote server")
    return url.strip().rstrip("/")


async def discover_protocol(kind: str, config: dict, on_status=None):
    url = validate_origin(
        str(config.get("url") or ""), bool(config.get("token") or config.get("headers"))
    )
    if kind == "uhp":
        from superqode.harness.uhp_client import UHPClient

        async with UHPClient(url, api_key=config.get("token") or None, timeout=15) as client:
            harnesses = await client.list_harnesses()
            return {"url": url, "name": "UHP server", "items": [asdict(h) for h in harnesses]}
    if kind != "a2a":
        raise ValueError("Choose ACP, A2A or UHP")
    from superqode.a2a.client import A2AClient
    from superqode.a2a.connection import normalize_url

    async with A2AClient(
        normalize_url(url),
        bearer_token=config.get("token") or None,
        extra_headers=config.get("headers") or None,
        client_cert=config.get("cert") or None,
        client_key=config.get("key") or None,
        timeout=15,
        strict_origin=True,
    ) as client:
        card = await client.get_agent_card()
        if (
            config.get("oauth")
            or (client._card_data or {}).get("securitySchemes")
            or (client._card_data or {}).get("security_schemes")
        ):
            from superqode.a2a.oauth import satisfy_card_auth, oauth_storage

            if config.get("client_id"):
                oauth_storage().save_client(
                    normalize_url(url), config["client_id"], config.get("client_secret") or ""
                )
            await satisfy_card_auth(
                client,
                normalize_url(url),
                token=config.get("token") or "",
                headers=config.get("headers") or {},
                interactive=bool(config.get("oauth")),
                skip_oauth=not config.get("oauth"),
                on_status=on_status,
            )
            auth = client._http.headers.get("Authorization")
            if auth:
                config["headers"] = {**config.get("headers", {}), "Authorization": auth}
            config["query"] = dict(client._query_params)
        from superqode.a2a.security import requirement_groups

        needs = [
            asdict(need)
            for group in requirement_groups(client._card_data or {})
            for need in group.oauth
        ]
        return {
            "url": normalize_url(url),
            "oauth_needs": needs,
            "name": card.name,
            "card": asdict(card),
            "items": [asdict(s) for s in card.skills],
        }


def discover(kind: str, config: dict, on_status=None):
    return asyncio.run(discover_protocol(kind, config, on_status))


def connection_secrets(config: dict):
    values = [
        config.get("token"),
        config.get("client_secret"),
        *(config.get("headers") or {}).values(),
        *(config.get("query") or {}).values(),
    ]
    result = {value for value in values if value}
    for value in tuple(result):
        prefix, _, credential = value.partition(" ")
        if prefix.lower() in {"bearer", "basic"} and credential:
            result.add(credential)
    return sorted(result, key=len, reverse=True)


def attachment_route(root: Path, entry_id: str):
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry(entry_id)
    auth = next((a for a in entry.auth if a.mode == "byok"), None) if entry else None
    if entry and auth and auth.after_auth == "vendor-key-rpc":
        import shutil

        return {
            "id": "attach:" + entry.id,
            "name": entry.label,
            "description": entry.description,
            "desktop_kind": "attached",
            "kind": "runtime",
            "runtime": "prime-agent",
            "available": bool(shutil.which("prime-agent")),
            "auth": "your model and key",
            "subscription_vendor": None,
            "byok_providers": auth.byok_providers,
            "local_providers": [],
            "entry_id": entry.id,
            "digest": hashlib.sha256((entry.id + "prime-agent-rpc").encode()).hexdigest(),
        }
    if not entry or not entry.acp_agent or not auth or auth.after_auth != "acp-attach":
        raise ValueError("This harness needs its existing vendor setup workflow")
    base = next((r for r in acp_routes(root) if r["id"] == "acp:" + entry.acp_agent), None)
    if not base:
        raise ValueError("This harness has no bundled ACP launch route")
    local = next((a for a in entry.auth if a.mode == "local"), None)
    return {
        **base,
        "id": "attach:" + entry.id,
        "name": entry.label,
        "desktop_kind": "attached",
        "subscription_vendor": None,
        "auth": "your model and key",
        "byok_providers": [auth.byok_provider] if auth.byok_provider else auth.byok_providers,
        "local_providers": local.local_providers if local else [],
        "entry_id": entry.id,
    }


def attachment_environment(route: dict, provider: str, credentials: dict):
    from superqode.providers.registry import PROVIDERS, ProviderTier
    from superqode.providers.harness_catalog import get_entry
    from superqode.providers.credentials import provider_api_key
    from superqode.providers.dynamic import resolve_base_url

    definition = PROVIDERS.get(provider)
    if not definition:
        raise ValueError("Unknown model provider")
    local = definition.tier == ProviderTier.LOCAL
    allowed = route["local_providers" if local else "byok_providers"]
    if allowed is not None and provider not in allowed:
        raise ValueError("This harness does not declare support for the selected model provider")
    entry = get_entry(route["entry_id"])
    auth = next(a for a in entry.auth if a.mode == ("local" if local else "byok"))
    key = credentials.get(provider) or provider_api_key(definition)
    if not local and not key:
        raise ValueError("Configure this model provider's API key first")
    environment = {name: key for name in (auth.env_vars or definition.env_vars) if key}
    if auth.base_url_env:
        endpoint = resolve_base_url(definition) or auth.default_base_url
        if endpoint:
            environment[auth.base_url_env] = endpoint
    return environment


def desktop_routes(root: Path):
    from superqode.providers.connection_profiles import list_connection_profiles

    rows = acp_routes(root)
    for p in list_connection_profiles("vendors"):
        if p.connector in {"runtime", "copilot", "prime-rpc"}:
            rows.append(profile_route(root, p.id))
    for p in list_connection_profiles():
        if p.connector == "harness-account":
            try:
                rows.append(profile_route(root, p.id))
            except ValueError:
                pass
    for p in list_connection_profiles("open-harnesses"):
        try:
            rows.append(attachment_route(root, p.id))
        except ValueError:
            pass
    return rows


def save_harness(root: Path, name: str, text: str):
    import os
    import re
    import yaml
    from superqode.harness.catalog import list_harnesses
    from superqode.harness.loader import validate_harness_data, harness_spec_from_dict

    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
        raise ValueError(
            "Start the harness name with a lowercase letter; use letters, numbers or hyphens "
            "(64 characters maximum)"
        )
    if len(text) > 250_000:
        raise ValueError("Harness definition exceeds 250,000 characters")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Enter a YAML HarnessSpec mapping")
    data = data.get("harness", data)
    if not isinstance(data, dict):
        raise ValueError("HarnessSpec must be a YAML mapping")
    if "inherits" in data or "extends" in data:
        raise ValueError("Use a resolved definition; load a preset before editing")
    data["name"] = name
    validate_harness_data(data)
    harness_spec_from_dict(data)
    if any(h.id == name for h in list_harnesses(root)):
        raise ValueError("That harness already exists. Choose a new name")
    folder = (root / ".superqode" / "harnesses").resolve()
    if not folder.is_relative_to(root):
        raise ValueError("Harness folder is outside the project")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (name + ".yaml")
    with target.open("x", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(yaml.safe_dump(data, sort_keys=False))
    return {"id": name, "path": str(target)}
