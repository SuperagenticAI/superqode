"""Offline ACP launch routes derived from the shared terminal catalog."""

from __future__ import annotations

import hashlib
import json
import os
import sys
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
        from superqode.agents.install_commands import managed_agent_install

        recipe = managed_agent_install(agent)
        parts, tool_ready = prepare_tool_launch(parts, recipe.executable if recipe else "")
        # A uvx command is ready only when its installed program is on PATH.
        # uvx itself is not that program, and a check must not download it.
        if tool_ready is None:
            installed = bool(item.available and parts and shutil.which(parts[0]))
        else:
            installed = tool_ready
        launch = {"reference": item.id, "command": shlex.join(parts), "subscription_vendor": vendor}
        digest = hashlib.sha256(json.dumps(launch, sort_keys=True).encode()).hexdigest()
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
                else "Install this agent to download its released packages. A connection check does not download them."
                if tool_ready is False
                else item.issue or "Install and sign in to the agent before connecting.",
                "digest": digest,
                "path": None,
                "desktop_kind": "acp",
                "agent_id": str(agent.get("short_name") or ""),
                "website": str(agent.get("url") or ""),
                "registry_source": "Bundled catalog",
                "auth": "subscription requested" if vendor else "agent-managed; unverified",
                "install": install,
            }
        )
    return result


def prepare_tool_launch(argv: list[str], executable: str = "") -> tuple[list[str], bool | None]:
    """Return the launch command and whether a uv tool is already installed.

    ``None`` means this is not a uv tool command. ``npx`` stays offline and the
    caller keeps its own installed check. A uv tool runs its installed program.
    Until that program exists, the command stays offline and is not ready.
    """
    if not argv:
        return argv, None
    name = Path(argv[0]).name
    if name == "npx":
        return [
            argv[0],
            "--no-install",
            *[
                part
                for part in argv[1:]
                if part not in {"-y", "--yes", "--yes=true", "--install", "--no-install"}
            ],
        ], None
    if name != "uvx":
        return argv, None
    script = executable or _uvx_script(argv)
    found = shutil.which(script) if script else None
    if found:
        return [found], True
    python = sys.executable if os.environ.get("SUPERQODE_APP") == "1" and sys.executable else "3.13"
    return [argv[0], "--offline", "--python", python, *_uvx_package_args(argv[1:])], False


def _uvx_script(argv: list[str]) -> str:
    for part in argv[1:]:
        if part.startswith("-") or "@" in part or "/" in part:
            continue
        return part
    return ""


def _uvx_package_args(argv: list[str]) -> list[str]:
    result = []
    skip = False
    for token in argv:
        if skip:
            skip = False
            continue
        if token in {"--online", "--offline"} or token.startswith("--python="):
            continue
        if token == "--python":
            skip = True
            continue
        result.append(token)
    return result


def resolve_acp_route(root: Path, reference: str):
    for route in acp_routes(root):
        if route["id"] == reference:
            if not route["available"]:
                raise ValueError("ACP agent is not available. " + route["issue"])
            return route
    raise ValueError("This connection is not an available desktop ACP route")
