"""Check agent startup and account metadata without sending a model prompt."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shlex
import time


async def probe_route(root: Path, route: dict, status, method_id=None, terminal_method=None):
    if not route.get("available"):
        raise ValueError(route.get("issue") or "Install this agent before connecting.")
    status("Checking " + str(route.get("name") or "agent") + " without a coding prompt…")
    if route.get("desktop_kind") == "acp":
        from .acp_worker import DesktopACPClient

        async def deny_tools(*args):
            raise PermissionError(
                "Connection checks do not execute tools. Start a coding task first."
            )

        class ProbeTerminals:
            create = output = wait_for_exit = kill = release = staticmethod(deny_tools)

        async def diagnostic(message):
            status(message)

        client = DesktopACPClient(
            root,
            route["command"],
            launch_argv=route.get("command_argv") or shlex.split(route["command"]),
            own_process_group=True,
            initialize_only=True,
            terminal_auth_supported=Path(
                (route.get("command_argv") or shlex.split(route["command"]))[0]
            ).name
            not in {"sh", "bash", "zsh", "fish", "ssh", "env"},
            allow_host_tools=False,
            subscription_vendor=route.get("subscription_vendor"),
            extra_env=route.get("extra_env"),
            traffic_log_enabled=False,
            terminal_service=ProbeTerminals(),
            on_permission_request=deny_tools,
            on_thinking=diagnostic,
        )
        try:
            if not await asyncio.wait_for(client.start(), timeout=30):
                raise ValueError(client.last_startup_error or "The ACP agent could not initialize.")
            methods = getattr(client, "get_auth_methods", lambda: [])()
            if terminal_method:
                return terminal_auth_plan(route, methods, terminal_method)
            if method_id:
                status("Complete sign-in with the selected agent. No coding prompt is sent.")
                await client.authenticate(method_id)
            try:
                if hasattr(client, "_restore_or_create_session") and not await asyncio.wait_for(
                    client._restore_or_create_session(), timeout=30
                ):
                    raise ValueError("The agent could not create a session")
            except Exception as exc:
                if getattr(exc, "acp_code", None) != -32000:
                    raise
                return {
                    "connected": False,
                    "state": "authentication-required",
                    "auth_methods": public_auth_methods(methods),
                    "message": "Choose a sign-in method offered by this agent, then check the connection again.",
                    "initialization": client.get_initialization_info(),
                }
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
                "checked_at": time.time(),
                "route_digest": route.get("digest", ""),
                "initialization": getattr(client, "get_initialization_info", lambda: {})(),
                "auth_methods": public_auth_methods(methods),
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


def public_auth_methods(methods):
    return [
        {
            key: str(row.get(key) or ("agent" if key == "type" else ""))[:1000]
            for key in ("id", "name", "description", "type")
        }
        for row in methods[:30]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def terminal_auth_plan(route, methods, method_id):
    from superqode.tools.env_policy import is_secret_name
    from superqode.providers.subscription_env import subscription_child_env
    import re
    import shutil

    method = next(
        (m for m in methods if m.get("id") == method_id and m.get("type") == "terminal"), None
    )
    if not method:
        raise ValueError("This agent did not advertise the selected terminal sign-in method")
    argv = route.get("command_argv") or shlex.split(route["command"])
    args, env = method.get("args", []), method.get("env", {})
    if (
        not isinstance(args, list)
        or len(args) > 100
        or any(not isinstance(v, str) or len(v) > 4000 or "\0" in v for v in args)
    ):
        raise ValueError("The agent returned invalid terminal login arguments")
    if not isinstance(env, dict) or len(env) > 50:
        raise ValueError("The agent returned invalid terminal login environment")
    for name, value in env.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
            or not isinstance(value, str)
            or len(value) > 4000
            or "\0" in value
        ):
            raise ValueError("The agent returned invalid terminal login environment")
        if (
            is_secret_name(name)
            or name
            in {"PATH", "ENV", "BASH_ENV", "ZDOTDIR", "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME"}
            or name.startswith(("DYLD_", "LD_"))
            or any(part in name.upper() for part in ("PROXY", "CERT", "TLS", "TRUST"))
        ):
            raise ValueError(
                "This terminal sign-in changes sensitive environment settings. Use the vendor's manual sign-in instructions."
            )
    if not argv or Path(argv[0]).name in {"sh", "bash", "zsh", "fish", "ssh", "env"}:
        raise ValueError("Use an executable ACP launch command before terminal sign-in")
    executable = shutil.which(argv[0])
    if not executable:
        raise ValueError("Install this agent before signing in")
    unset = []
    if route.get("subscription_vendor"):
        _, unset = subscription_child_env(route["subscription_vendor"])
    return {
        "argv": [executable, *argv[1:], *args],
        "env": {**(route.get("extra_env") or {}), **env},
        "unset_env": unset,
        "reference": route["id"],
        "digest": route["digest"],
        "method": method_id,
    }
