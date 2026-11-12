"""Desktop controls for vendor CLIs. No prompts, shell evaluation or credential imports."""

from __future__ import annotations

import asyncio
import os
import re
import shutil

from .redaction import redact


def select_option(identity, name, values):
    return {
        "id": identity,
        "name": name,
        "type": "select",
        "options": [{"value": value, "name": value.capitalize()} for value in values],
    }


def runtime_settings(runtime):
    if runtime == "antigravity-cli":
        return [
            select_option("effort", "Reasoning effort (agy 1.1.5+)", ["low", "medium", "high"]),
            {"id": "agent", "name": "Antigravity agent", "type": "text"},
        ]
    if runtime == "codex-cli":
        return [
            select_option(
                "effort",
                "Reasoning effort",
                ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"],
            ),
            select_option("plan", "Codex mode", ["on", "off"]),
            select_option("sandbox", "Codex sandbox", ["read-only", "workspace-write"]),
            select_option("approval", "Codex approvals", ["on-request", "untrusted", "never"]),
        ]
    return []


def apply_runtime_controls(runtime, route, controls):
    """Fail closed rather than silently ignoring an unsupported desktop setting."""
    config = controls.get("config") or {}
    allowed = {option["id"]: option for option in runtime_settings(route["runtime"])}
    if controls.get("mode"):
        raise ValueError("This runtime does not support ACP session modes")
    for key, value in config.items():
        option = allowed.get(key)
        if not option or not isinstance(value, str):
            raise ValueError("Unsupported agent setting: " + str(key))
        if option["type"] == "select" and value not in [v["value"] for v in option["options"]]:
            raise ValueError("Invalid value for agent setting " + key)
        if key == "agent":
            runtime.set_agent(value)
        elif key == "effort":
            runtime.set_reasoning_effort(value)
        elif key == "sandbox":
            runtime.set_sandbox_backend(value)
        elif key == "approval":
            runtime.set_approval_policy(value)
    # Plan requires the initialized app-server; apply after restoring the thread.
    return config.get("plan")


async def cli_output(root, argv, vendor=None, timeout=20):
    """Bound output and terminate/reap the entire CLI process group on timeout/cancel."""
    import signal
    from superqode.herdr import child_env
    from superqode.tools.env_policy import is_secret_name

    env = child_env()
    if vendor:
        from superqode.providers.subscription_env import subscription_child_env

        env, _ = subscription_child_env(vendor, env)
    secrets = sorted(
        {v for k, v in env.items() if is_secret_name(k) and len(v) > 3}, key=len, reverse=True
    )
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=root,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt",
    )

    async def read(stream):
        output = bytearray()
        while chunk := await stream.read(8192):
            output.extend(chunk)
            if len(output) > 256_000:
                raise ValueError(
                    "CLI output is too large. Use the vendor CLI for the complete result."
                )
        return output.decode(errors="replace")

    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await asyncio.gather(read(process.stdout), read(process.stderr))
            await process.wait()
        if process.returncode:
            raise ValueError(
                redact((stderr or stdout).strip()[:4000], secrets)
                or f"CLI exited {process.returncode}"
            )
        return redact(stdout.strip(), secrets)
    except TimeoutError:
        raise ValueError("The CLI did not respond in time. Check sign-in and try again.") from None
    finally:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()
        await process.wait()


def parse_agy_models(output):
    """Use the same one-ID-per-line contract as :agy models; skip decorations."""
    result = []
    seen = set()
    for line in output.splitlines():
        identity = line.strip()
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", identity)
            and identity.lower() not in {"model", "models", "available"}
            and identity not in seen
        ):
            seen.add(identity)
            result.append({"id": identity, "name": identity})
    return result


def cli_plan(route):
    """Only known interactive binaries, never ACP launch flags or package installers."""
    if route.get("custom"):
        return None
    from superqode.providers.subscription_login import get_login_spec, binary_path

    if route.get("runtime") == "antigravity-cli":
        binary = shutil.which("agy")
    elif route.get("subscription_vendor"):
        try:
            binary = binary_path(get_login_spec(route["subscription_vendor"]))
        except KeyError:
            binary = None
    else:
        from superqode.runtime.vendor_cli import VENDOR_CLI_SPECS

        spec = next((s for s in VENDOR_CLI_SPECS.values() if s.name == route.get("runtime")), None)
        binary = shutil.which(spec.binary) if spec else None
    if not binary:
        # Bundled ACP routes are selectable independently of subscription profiles.
        # Only explicitly known interactive binaries are launched without ACP flags.
        binaries = {
            "codex": "codex",
            "grok": "grok",
            "copilot": "copilot",
            "claude": "claude",
            "claude-code": "claude",
            "gemini": "gemini",
            "gemini-cli": "gemini",
            "qwen": "qwen",
            "kimi": "kimi",
            "opencode": "opencode",
            "goose": "goose",
            "kiro": "kiro-cli",
            "auggie": "auggie",
            "cursor": "cursor-agent",
            "cline": "cline",
            "prime-agent": "prime-agent",
            "muse": "muse",
            "droid": "droid",
        }
        name = binaries.get(route.get("agent_id")) or binaries.get(route.get("runtime"))
        binary = shutil.which(name) if name else None
    if not binary:
        return None
    from superqode.providers.subscription_env import subscription_child_env

    _, unset = (
        subscription_child_env(route["subscription_vendor"])
        if route.get("subscription_vendor")
        else ({}, [])
    )
    return {"argv": [str(binary)], "unset_env": unset}


CODEX_QUERIES = (
    "account",
    "models",
    "sessions",
    "usage",
    "skills",
    "plugins",
    "apps",
    "hooks",
    "features",
    "permissions",
    "mcp",
    "config",
    "doctor",
)
AGY_QUERIES = {
    "models": ["models"],
    "agents": ["agents"],
    "changelog": ["changelog"],
    "plugins": ["plugin", "list"],
    "version": ["--version"],
    "help": ["--help"],
}


def command_catalog(route):
    runtime = route.get("runtime")
    names = (
        CODEX_QUERIES
        if runtime == "codex-cli"
        else tuple(AGY_QUERIES)
        if runtime == "antigravity-cli"
        else ()
    )
    return [{"id": name, "name": name.capitalize()} for name in names]


async def run_command(root, route, command, status, cursor=None):
    if not route.get("available"):
        raise ValueError(route.get("issue") or "Install this CLI and sign in first.")
    if command not in {item["id"] for item in command_catalog(route)}:
        raise ValueError("This agent does not support the selected native command")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4000):
        raise ValueError("Invalid pagination cursor")
    status("Reading " + command + " from the installed agent…")
    if route["runtime"] == "antigravity-cli":
        binary = shutil.which("agy")
        if not binary:
            raise ValueError("Install Antigravity CLI: https://antigravity.google/docs/cli-install")
        return {
            "text": await cli_output(
                root, [binary, *AGY_QUERIES[command]], route.get("subscription_vendor")
            )
        }
    from superqode.agent.loop import AgentConfig
    from superqode.runtime.codex_cli import CodexCLIRuntime
    from superqode.codex_commands import redact_codex_data

    runtime = CodexCLIRuntime(
        config=AgentConfig(provider="agent", model="", working_directory=root),
        billing_requested="subscription" if route.get("subscription_vendor") else "agent-managed",
        request_timeout=20,
    )
    try:
        await runtime.verify_account()
        if command == "models":
            result = await runtime.models()
        elif command == "sessions":
            result = await runtime.list_threads(cursor=cursor)
        elif command == "config":
            result = await runtime.read_config()
        elif command in {"account", "usage", "doctor"}:
            result = await getattr(runtime, command)()
        else:
            result = await runtime.inspect(command, cursor=cursor)
        safe = redact_codex_data(result)
        return {
            "data": safe,
            "text": command.capitalize() + " loaded from Codex.",
            "next_cursor": result.get("nextCursor", "") if isinstance(result, dict) else "",
        }
    finally:
        await runtime.aclose()
