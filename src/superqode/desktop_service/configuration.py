"""GUI form adapters using the same wizard, RLM validation and catalog contracts."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path


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
    return {"reference": reference, "command": plan.command, "argv": plan.argv}


async def install_agent(root: Path, reference: str, status):
    import asyncio
    import os
    import signal

    plan = install_plan(root, reference)
    process = await asyncio.create_subprocess_exec(
        *plan["argv"], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
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
