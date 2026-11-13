"""GUI form adapters using the same wizard, RLM validation and catalog contracts."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shlex


def options():
    from superqode.harness.wizard import WIZARD_STARTERS, APPROVAL_PROFILES, TOOL_CALL_FORMATS
    from superqode.harness.workflow_presets import list_workflow_presets

    def rows(values):
        return [{"id": key, "label": label} for key, label in values]

    return {
        "starters": rows(WIZARD_STARTERS),
        "approvals": rows(APPROVAL_PROFILES),
        "formats": rows(TOOL_CALL_FORMATS),
        "workflows": [{"id": p.name, "label": p.description} for p in list_workflow_presets()],
    }


def configured_spec(root: Path, params):
    import yaml
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.harness.catalog import resolve_harness

    mode = params["mode"]
    if mode == "wizard":
        from superqode.harness.wizard import WizardAnswers, build_wizard_spec

        spec = build_wizard_spec(WizardAnswers(**params.get("answers", {})))
    else:
        spec = resolve_harness(params.get("harness") or "rlm", root=root).spec
        if mode in {"rlm", "rlm-routing"}:
            from superqode.rlm.profile import RLMProfile
            from superqode.rlm.sandbox import RLMSandboxConfig
            from superqode.rlm.budget import BudgetPolicy
            from superqode.rlm.delegation_policy import DelegationPolicy

            if spec.runtime.backend != "rlm":
                raise ValueError("Choose an RLM harness before configuring this profile")
            config = {**spec.runtime.config, **params.get("config", {})}
            if mode == "rlm-routing":
                config = {
                    **spec.runtime.config,
                    "a2a": {**spec.runtime.config.get("a2a", {}), **params.get("config", {})},
                }
            policy = DelegationPolicy.from_config(config.get("a2a"))
            if policy.enabled and not policy.inventory():
                raise ValueError("Add an allowed peer before enabling A2A routing")
            if policy.hosted_enabled and not policy.max_hosted_credits:
                raise ValueError("Set a positive hosted credit allowance")
            selected = RLMProfile.from_config(config)
            sandbox = RLMSandboxConfig.from_config(config, execution_policy=spec.execution_policy)
            selected.validate_sandbox(sandbox)
            BudgetPolicy.from_config(config.get("budget"))
            spec = replace(
                spec,
                runtime=replace(spec.runtime, config=config),
                execution_policy=replace(
                    spec.execution_policy,
                    sandbox=sandbox.backend,
                    allow_read=sandbox.policy.allow_read,
                    allow_write=sandbox.policy.allow_write,
                    allow_shell=sandbox.policy.allow_shell,
                    allow_network=sandbox.allow_network,
                ),
                agents=tuple(replace(agent, tools=selected.tools) for agent in spec.agents),
            )
        else:
            raise ValueError("Unknown native configuration form")
    return {"yaml": yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False)}


def vendor_key_route(root: Path, entry_id: str):
    if entry_id == "antigravity-managed":
        route = {
            "id": "vendor-key:antigravity-managed",
            "entry_id": entry_id,
            "name": "Antigravity Managed Agent",
            "description": "Run Google's agent in a hosted sandbox using a Gemini API key.",
            "kind": "runtime",
            "desktop_kind": "connection",
            "runtime": entry_id,
            "available": True,
            "subscription_vendor": None,
            "auth": "byok",
            "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        }
        route["digest"] = hashlib.sha256(json.dumps(route, sort_keys=True).encode()).hexdigest()
        return route
    from superqode.providers.harness_catalog import get_entry
    from .routes import acp_routes

    entry = get_entry(entry_id)
    auth = next((a for a in entry.auth if a.mode == "byok"), None) if entry else None
    if not entry or not auth or not auth.env_vars:
        raise ValueError("This harness requires a model/provider selection")
    if entry.acp_agent:
        base = next((r for r in acp_routes(root) if r["id"] == "acp:" + entry.acp_agent), None)
        if not base:
            raise ValueError("No ACP launch command is available for this vendor")
        route = {**base, "desktop_kind": "acp", "subscription_vendor": None}
    elif entry.id == "muse-key":
        import shutil

        route = {
            "kind": "runtime",
            "desktop_kind": "connection",
            "runtime": "muse",
            "available": bool(shutil.which("muse")),
            "subscription_vendor": None,
        }
    else:
        raise ValueError(entry.support_note or "The vendor does not expose an executable protocol")
    route.update(
        id="vendor-key:" + entry.id,
        name=entry.label,
        description=entry.description,
        auth="byok",
        entry_id=entry.id,
        env_vars=list(auth.env_vars),
    )
    route["digest"] = hashlib.sha256(json.dumps(route, sort_keys=True).encode()).hexdigest()
    return route


def installer_requirements(argv):
    """Identify the local package manager required by a reviewed install plan."""
    import shutil

    binary = argv[0]
    name = Path(binary).name
    docs = {
        "npm": ("Node.js and npm", "https://nodejs.org/en/download"),
        "uv": ("uv", "https://docs.astral.sh/uv/getting-started/installation/"),
        "bun": ("Bun", "https://bun.sh/docs/installation"),
    }
    label, url = docs.get(name, (name, ""))
    return [
        {
            "id": "installer",
            "name": label,
            "installed": shutil.which(binary) is not None,
            "instruction": f"Install {label} using its official setup instructions before installing this agent. Then choose Check installation again.",
            "docs_url": url,
        }
    ]


def bind_app_install(argv: list[str]) -> list[str]:
    """Point a reviewed uv install at the uv and Python shipped with the Mac app."""
    import os
    import sys

    if os.environ.get("SUPERQODE_APP") != "1" or not argv or Path(argv[0]).name != "uv":
        return list(argv)
    state = os.environ.get("SUPERQODE_STATE_DIR", "")
    if not state:
        return list(argv)
    from .app_setup import ensure_uv

    uv = ensure_uv(Path(state) / "bin")
    if not uv:
        raise ValueError(
            "SuperQode could not prepare the uv included with the app. Check the network, then choose Check installation again."
        )
    bound = [uv]
    skip = False
    saw_python = False
    for token in argv[1:]:
        if skip:
            bound.append(sys.executable)
            skip = False
            saw_python = True
            continue
        if token == "--python":
            bound.append(token)
            skip = True
            continue
        if token.startswith("--python="):
            bound.append("--python")
            bound.append(sys.executable)
            saw_python = True
            continue
        bound.append(token)
    if not saw_python:
        insert_at = 3 if bound[1:3] == ["tool", "install"] else 1
        bound[insert_at:insert_at] = ["--python", sys.executable]
    return bound


def install_plan(root: Path, reference: str):
    from superqode.providers.connection_profiles import get_connection_profile
    from superqode.providers.acp_registry import get_bundled_acp_catalog
    from superqode.agents.install_commands import managed_agent_install

    profile = get_connection_profile(reference)
    target = profile.acp_agent if profile and profile.acp_agent else reference.removeprefix("acp:")
    agent = next((a for a in get_bundled_acp_catalog() if a.get("short_name") == target), None)
    plan = managed_agent_install(agent) if agent else None
    if not plan or not plan.runnable or not plan.managed:
        raise ValueError(
            "This agent has no reviewed native install recipe. Use the vendor's setup instructions."
        )
    argv = bind_app_install(plan.argv)
    return {
        "reference": reference,
        "command": shlex.join(argv),
        "argv": argv,
        "requirements": installer_requirements(argv),
    }


async def install_agent(root: Path, reference: str, status):
    plan = install_plan(root, reference)
    return await run_install_command(plan["argv"], status)


async def run_install_command(argv, status):
    import asyncio
    import os
    import signal

    missing = [r for r in installer_requirements(argv) if not r["installed"]]
    if missing:
        raise ValueError(" ".join(r["instruction"] + " " + r["docs_url"] for r in missing))
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        while line := await process.stdout.readline():
            status(line.decode(errors="replace")[:4000])
        if await process.wait():
            raise ValueError("Agent installation failed; inspect the output above")
        return {"installed": True}
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
