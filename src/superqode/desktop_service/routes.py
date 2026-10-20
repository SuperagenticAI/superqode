"""Offline ACP launch routes derived from the shared terminal catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import shutil


def acp_routes(root: Path):
    from superqode.app.harness_picker import harness_picker_items
    from superqode.providers.acp_registry import get_bundled_acp_catalog
    from superqode.providers.subscription_env import resolve_vendor

    agents = {str(agent.get("short_name")): agent for agent in get_bundled_acp_catalog()}
    result = []
    for item in harness_picker_items(
        root, include_all=True, expand_protocol_catalog=True, include_live_registry=False
    ):
        vendor = None
        if item.kind == "acp":
            agent = item.target
        elif item.kind == "connection" and item.target.connector == "acp":
            profile = item.target
            agent = agents.get(str(profile.acp_agent))
            if profile.auth_mode == "subscription":
                vendor = resolve_vendor(profile.id) or resolve_vendor(profile.acp_agent or "")
        else:
            continue
        if not agent:
            continue
        declared = agent.get("run_command", {})
        command = declared.get("*") if isinstance(declared, dict) else declared
        parts = shlex.split(str(command or ""))
        installed = bool(item.available and parts and shutil.which(parts[0]))
        # Package launchers must use existing local caches, never install on selection.
        if parts and Path(parts[0]).name == "npx":
            parts = [
                part for part in parts if part not in {"-y", "--yes", "--yes=true", "--install"}
            ]
            parts.insert(1, "--no-install")
        elif parts and Path(parts[0]).name == "uvx":
            parts = [part for part in parts if part != "--online"]
            parts.insert(1, "--offline")
        launch = {"reference": item.id, "command": shlex.join(parts), "subscription_vendor": vendor}
        digest = hashlib.sha256(json.dumps(launch, sort_keys=True).encode()).hexdigest()
        from superqode.agents.install_commands import managed_agent_install

        recipe = managed_agent_install(agent)
        install = (
            {"reference": item.id, "command": recipe.command}
            if recipe and recipe.runnable and recipe.managed
            else None
        )
        result.append(
            {
                **launch,
                "id": item.id,
                "name": item.display_name,
                "description": item.description,
                "runtime": "ACP",
                "available": installed,
                "issue": ""
                if installed
                else item.issue or "Install and sign in to the agent before connecting.",
                "digest": digest,
                "path": None,
                "desktop_kind": "acp",
                "auth": "subscription requested" if vendor else "agent-managed; unverified",
                "install": install,
            }
        )
    return result


def resolve_acp_route(root: Path, reference: str):
    for route in acp_routes(root):
        if route["id"] == reference:
            if not route["available"]:
                raise ValueError("ACP agent is not available. " + route["issue"])
            return route
    raise ValueError("This connection is not an available desktop ACP route")
