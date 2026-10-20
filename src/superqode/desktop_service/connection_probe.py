"""Check agent startup and account metadata without sending a model prompt."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shlex


async def probe_route(root: Path, route: dict, status):
    if not route.get("available"):
        raise ValueError(route.get("issue") or "Install this agent before connecting.")
    status("Checking " + str(route.get("name") or "agent") + " without a coding prompt…")
    if route.get("desktop_kind") == "acp":
        from .acp_worker import DesktopACPClient

        async def deny_tools(*args):
            raise PermissionError(
                "Connection checks do not execute tools. Start a coding task first."
            )

        client = DesktopACPClient(
            root,
            route["command"],
            subscription_vendor=route.get("subscription_vendor"),
            extra_env=route.get("extra_env"),
            traffic_log_enabled=False,
            on_permission_request=deny_tools,
        )
        try:
            if not await asyncio.wait_for(client.start(), timeout=30):
                raise ValueError(client.last_startup_error or "The ACP agent could not initialize.")
            models = client.get_session_models()
            command = shlex.split(route["command"])
            if command and Path(command[0]).name == "opencode":
                from superqode.providers.opencode_models import get_opencode_models

                try:
                    catalog = await asyncio.wait_for(get_opencode_models(), timeout=12)
                except Exception:
                    catalog = []
                metadata = {m["id"]: m for m in catalog if not m.get("catalog_unavailable")}
                models = {
                    **models,
                    "availableModels": [
                        {
                            **row,
                            "free": bool(
                                metadata.get(row.get("modelId") or row.get("id"), {}).get("is_free")
                            ),
                        }
                        for row in models.get("availableModels", [])
                    ],
                }
            return {
                "connected": True,
                "message": "ACP connection checked. The agent owns model access and billing.",
                "session": {
                    "capabilities": client.get_agent_capabilities(),
                    "models": models,
                    "modes": client.get_session_modes(),
                    "config_options": client.get_session_config_options(),
                },
            }
        finally:
            await client.stop()
    if route.get("runtime") == "codex-cli":
        from superqode.agent.loop import AgentConfig
        from superqode.runtime.codex_cli import CodexCLIRuntime

        runtime = CodexCLIRuntime(
            config=AgentConfig(provider="agent", model="", working_directory=root),
            billing_requested="subscription"
            if route.get("subscription_vendor")
            else "agent-managed",
            request_timeout=15,
        )
        try:
            await runtime.verify_account()
            data = await runtime.account()
            account = data.get("account") or {}
            try:
                models = (await runtime.models()).get("data", [])
            except Exception:
                models = []
            return {
                "connected": bool(account),
                "identity": account.get("email") or account.get("name") or "",
                "message": "ChatGPT account connected to Codex."
                if account.get("type") in {"chatgpt", "chatgptAuthTokens"}
                else "Codex account checked; the agent owns its model access.",
                "models": [
                    {
                        "id": m.get("model") or m.get("id"),
                        "name": m.get("displayName") or m.get("model") or m.get("id"),
                    }
                    for m in models
                    if m.get("model") or m.get("id")
                ],
            }
        finally:
            await runtime.aclose()
    from superqode.providers.subscription_login import get_login_spec, has_local_login

    vendor = route.get("subscription_vendor")
    if vendor:
        try:
            spec = get_login_spec(vendor)
            configured = has_local_login(spec)
        except KeyError:
            configured = False
        return {
            "connected": False,
            "configured": configured,
            "message": "Existing local sign-in found. The vendor verifies access when coding starts."
            if configured
            else "Sign in with this agent's account before starting a task.",
        }
    return {"connected": False, "message": "Agent installed. Access is checked when coding starts."}
