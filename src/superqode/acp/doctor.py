"""ACP agent diagnostics shared by CLI and TUI."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any


def _run_command(agent: dict[str, Any]) -> str:
    command = agent.get("run_command", {}).get("*", "")
    return command.strip()


def _command_name(command: str) -> str:
    return command.split()[0] if command else ""


def _install_command(agent: dict[str, Any]) -> str:
    actions = agent.get("actions", {})
    for action_group in actions.values():
        if isinstance(action_group, dict) and "install" in action_group:
            install = action_group["install"]
            if isinstance(install, dict):
                return install.get("command", "")
    return ""


def _env_requirements(agent: dict[str, Any]) -> list[str]:
    """Return known env vars for common ACP agents.

    Most ACP agents manage their own auth. These hints are intentionally
    conservative and only cover common direct-provider CLIs.
    """
    short_name = agent.get("short_name", "").lower()
    identity = agent.get("identity", "").lower()
    key = short_name or identity

    requirements = {
        "claude": ["ANTHROPIC_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "codex": ["OPENAI_API_KEY", "CODEX_API_KEY"],
        "kimi": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "auggie": ["AUGMENT_API_KEY"],
    }
    return requirements.get(key, [])


async def _run_live_protocol_check(
    command: str,
    *,
    project_root: Path,
    timeout: float,
) -> dict[str, Any]:
    from superqode.acp.client import ACPClient

    client = ACPClient(project_root=project_root, command=command)
    payload: dict[str, Any] = {
        "started": False,
        "initialized": False,
        "session": False,
        "models": [],
        "modes": [],
    }
    try:
        started = await asyncio.wait_for(client.start(), timeout=timeout)
        payload["started"] = bool(started)
        payload["initialized"] = bool(started)
        payload["session"] = bool(client.get_session_id())
        if started:
            try:
                payload["models"] = await asyncio.wait_for(
                    client.get_available_models(), timeout=timeout
                )
            except Exception as exc:
                payload["models_error"] = str(exc)
            try:
                payload["modes"] = await asyncio.wait_for(
                    client.get_available_modes(), timeout=timeout
                )
            except Exception as exc:
                payload["modes_error"] = str(exc)
        return payload
    except Exception as exc:
        payload["error"] = str(exc)
        return payload
    finally:
        await client.stop()


async def acp_doctor(
    agent_identifier: str | None = None,
    *,
    live: bool = False,
    timeout: float = 10.0,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return structured diagnostics for ACP agents."""
    from superqode.agents.registry import get_all_acp_agents

    agents = await get_all_acp_agents()
    if agent_identifier:
        needle = agent_identifier.lower()
        agents = {
            identity: agent
            for identity, agent in agents.items()
            if identity.lower() == needle or agent.get("short_name", "").lower() == needle
        }

    results: list[dict[str, Any]] = []
    for identity, agent in sorted(agents.items(), key=lambda item: item[1].get("short_name", "")):
        command = _run_command(agent)
        command_name = _command_name(command)
        installed = bool(command_name and shutil.which(command_name))
        required_env = _env_requirements(agent)

        result: dict[str, Any] = {
            "identity": identity,
            "short_name": agent.get("short_name", identity),
            "name": agent.get("name", identity),
            "protocol": agent.get("protocol", ""),
            "type": agent.get("type", ""),
            "installed": installed,
            "command": command,
            "command_name": command_name,
            "install_command": _install_command(agent),
            "required_env_vars": required_env,
            "missing_env_vars": required_env
            if required_env and not any(os.getenv(item) for item in required_env)
            else [],
            "live": None,
        }

        if live:
            if not command:
                result["live"] = {"started": False, "error": "No run command configured"}
            elif not installed:
                result["live"] = {"started": False, "error": f"Command not found: {command_name}"}
            else:
                result["live"] = await _run_live_protocol_check(
                    command,
                    project_root=project_root or Path.cwd(),
                    timeout=timeout,
                )

        results.append(result)

    return results
