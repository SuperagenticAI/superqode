"""Check agent startup and account metadata without sending a model prompt."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shlex
import time


async def _antigravity_model_efforts(root, binary, models, levels):
    """Read model-specific effort tiers through agy's zero-turn /effort command."""
    from .connection_controls import cli_output

    slots = asyncio.Semaphore(4)

    async def check(model):
        async with slots:
            try:
                selection = [f"--model={model['id']}"] if model["id"] else []
                output = await cli_output(
                    root,
                    [binary, *selection, "--print", "/effort", "--output-format", "json"],
                    "antigravity",
                    timeout=5,
                )
                data = json.loads(output)["command"]["data"]
                if data.get("adjustable") is False:
                    model["reasoning_efforts"] = []
                elif isinstance(data.get("available"), list):
                    model["reasoning_efforts"] = [
                        level for level in levels if level in data["available"]
                    ]
                    if isinstance(data.get("current"), str):
                        model["current_reasoning_effort"] = data["current"]
            except (AttributeError, KeyError, OSError, TypeError, ValueError):
                pass

    try:
        async with asyncio.timeout(9):
            await asyncio.gather(*(check(model) for model in models))
    except TimeoutError:
        pass


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

        missing_packages = False

        async def diagnostic(message):
            nonlocal missing_packages
            summary = dependency_install_message(message)
            if summary:
                if not missing_packages:
                    status(summary)
                missing_packages = True
                return
            if missing_packages:
                return
            status(message[:500])

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
                detail = client.last_startup_error or "The ACP agent could not initialize."
                if missing_packages:
                    detail = dependency_install_message("network was disabled")
                raise ValueError(dependency_install_message(detail) or detail)
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
                "message": "ACP session ready. Account and model access unverified.",
                "checked_at": time.time(),
                "route_digest": route.get("digest", ""),
                "initialization": getattr(client, "get_initialization_info", lambda: {})(),
                "auth_methods": public_auth_methods(methods),
                "session": {
                    "capabilities": client.get_agent_capabilities(),
                    "models": models,
                    "modes": client.get_session_modes(),
                    "config_options": client.get_session_config_options(),
                    "commands": getattr(client, "get_available_commands_cached", lambda: [])(),
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
            from .connection_controls import runtime_settings

            public_models = [
                {
                    "id": m.get("model") or m.get("id"),
                    "name": m.get("displayName") or m.get("model") or m.get("id"),
                    "reasoning_efforts": [
                        e.get("reasoningEffort")
                        for e in m.get("supportedReasoningEfforts", [])
                        if isinstance(e, dict) and e.get("reasoningEffort")
                    ],
                }
                for m in models
                if m.get("model") or m.get("id")
            ]
            default_model = next(
                (m.get("model") or m.get("id") for m in models if m.get("isDefault")), ""
            )
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
                "session": {
                    "models": {"availableModels": public_models, "currentModelId": default_model},
                    "config_options": runtime_settings("codex-cli"),
                },
            }
        finally:
            await runtime.aclose()
    if route.get("runtime") == "antigravity-cli":
        import shutil
        from superqode.runtime.antigravity_status import parse_agy_models, probe_antigravity_cli
        from superqode.vendor_command_help import antigravity_efforts
        from .connection_controls import cli_output, runtime_settings

        binary = shutil.which("agy")
        if not binary:
            raise ValueError("Install Antigravity CLI: https://antigravity.google/docs/cli-install")
        output = await cli_output(root, [binary, "models"], route.get("subscription_vendor"))
        models = parse_agy_models(output)
        try:
            help_text = await cli_output(
                root,
                [binary, "--help"],
                route.get("subscription_vendor"),
                timeout=6,
                include_stderr=True,
            )
            efforts = antigravity_efforts(help_text) or ["low", "medium", "high"]
        except (OSError, ValueError):
            efforts = ["low", "medium", "high"]
        default = {"id": ""}
        status_info = await asyncio.to_thread(probe_antigravity_cli)
        if status_info.version and status_info.version >= (1, 5, 7):
            await _antigravity_model_efforts(root, binary, [default, *models], efforts)
        return {
            "connected": False,
            "configured": True,
            "message": "Antigravity models loaded. Google Sign-In and model access are verified by agy when a task starts."
            if models
            else "Antigravity returned no models. Check Google Sign-In in agy and refresh.",
            "session": {
                "models": {"availableModels": models, "defaultModelSettings": default},
                "config_options": runtime_settings("antigravity-cli", antigravity_efforts=efforts),
            },
        }
    if route.get("runtime") in {"grok-cli", "copilot-cli"}:
        import shutil
        from .connection_controls import cli_output

        binary_name = "grok" if route["runtime"] == "grok-cli" else "copilot"
        binary = shutil.which(binary_name)
        if not binary:
            raise ValueError("Install and sign in to " + binary_name + " before loading models.")
        if binary_name == "grok":
            from superqode.providers.grok_cli_auth import parse_cli_models_output

            data = parse_cli_models_output(await cli_output(root, [binary, "models"], "grok"))
            models = [{"id": identity, "name": identity} for identity in data["models"]]
        else:
            # Copilot's account catalog and modes are exposed over its ACP session.
            metadata = await probe_route(
                root,
                {
                    **route,
                    "desktop_kind": "acp",
                    "command": str(binary) + " --acp",
                    "command_argv": [str(binary), "--acp"],
                },
                status,
            )
            session = metadata.get("session") or {}
            metadata["session"] = {"models": session.get("models", {})}
            metadata["allow_manual_model"] = False
            return metadata
        return {
            "connected": False,
            "configured": bool(models),
            "message": "Grok subscription models loaded. The CLI verifies access when a task starts."
            if models
            else "No models returned. Sign in with grok login and refresh.",
            "session": {"models": {"availableModels": models}},
        }
    if route.get("runtime") == "copilot-sdk":
        from superqode.agent.loop import AgentConfig
        from superqode.runtime.copilot_sdk import CopilotSDKRuntime

        runtime = CopilotSDKRuntime(
            config=AgentConfig(provider="agent", model="", working_directory=root),
            billing_requested="subscription",
        )
        try:
            models = await asyncio.wait_for(runtime.models(), timeout=30)
            return {
                "connected": True,
                "message": "Copilot account models loaded. An empty catalog means Copilot chooses the model for your plan.",
                "session": {"models": {"availableModels": models}},
                "allow_manual_model": False,
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


def dependency_install_message(text: str) -> str:
    """Turn uv's offline resolver transcript into one install instruction."""
    lowered = text.lower()
    if (
        "network was disabled" in lowered
        or "no solution found when resolving tool dependencies" in lowered
    ):
        return (
            "This agent's packages are not installed. Choose Install agent to download "
            "the current release and its dependencies. A connection check does not download packages."
        )
    return ""


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
