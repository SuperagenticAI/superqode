"""Explicit ACP registry refresh and project-scoped user launch configurations."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import time
import uuid


def _snapshot(service):
    path = service.root / "acp-registry.json"
    if not path.exists():
        return {"agents": [], "updated": None}
    if path.stat().st_size > 4_000_000:
        raise ValueError("Saved ACP registry is too large; refresh it again")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
        raise ValueError("Saved ACP registry is unreadable; refresh it again")
    return data


def registry_status(service):
    try:
        data = _snapshot(service)
        return {
            "updated": data.get("updated"),
            "count": len(data["agents"]),
            "source": "Official ACP registry" if data["agents"] else "Bundled catalog",
            "issue": "",
        }
    except (ValueError, OSError) as exc:
        return {"updated": None, "count": 0, "source": "Bundled catalog", "issue": str(exc)}


async def refresh_registry(service, status):
    import httpx
    from superqode.providers.acp_registry import REGISTRY_CDN_URL, convert_registry_agent

    status("Fetching the official ACP registry. No agents are installed or started.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        async with client.stream("GET", REGISTRY_CDN_URL) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 4_000_000:
                    raise ValueError("ACP registry exceeds the catalog size limit")
                chunks.append(chunk)
    payload = json.loads(b"".join(chunks))
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("agents"), list)
        or not 0 < len(payload["agents"]) <= 2000
    ):
        raise ValueError("The ACP registry returned an invalid agent catalog")
    agents, seen = [], set()
    for manifest in payload["agents"]:
        if not isinstance(manifest, dict) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", str(manifest.get("id") or "")
        ):
            raise ValueError("The ACP registry contains an invalid agent ID")
        # Do not accept SuperQode-specific overrides from untrusted manifests.
        manifest = {
            key: value for key, value in manifest.items() if key not in {"_superqode", "source"}
        }
        distribution = manifest.get("distribution", {})
        if not isinstance(distribution, dict):
            raise ValueError("The ACP registry contains an invalid distribution")
        launches = [distribution[key] for key in ("npx", "uvx") if key in distribution]
        binaries = distribution.get("binary", {})
        if not isinstance(binaries, dict):
            raise ValueError("The ACP registry contains invalid platform binaries")
        launches += list(binaries.values())
        for launch in launches:
            if not isinstance(launch, dict):
                raise ValueError("The ACP registry contains an invalid launch description")
            args, env = launch.get("args", []), launch.get("env", {})
            if (
                not isinstance(args, list)
                or len(args) > 100
                or any(not isinstance(arg, str) or len(arg) > 4000 or "\0" in arg for arg in args)
            ):
                raise ValueError("The ACP registry contains invalid launch arguments")
            if (
                not isinstance(env, dict)
                or len(env) > 50
                or any(
                    not isinstance(k, str) or not isinstance(v, str) or len(v) > 4000
                    for k, v in env.items()
                )
            ):
                raise ValueError("The ACP registry contains invalid launch environment")
        converted = convert_registry_agent(manifest)
        reference = converted["short_name"]
        if reference in seen:
            raise ValueError("The ACP registry contains duplicate agent identities")
        seen.add(reference)
        agents.append(converted)
    data = {"agents": agents, "updated": time.time(), "source": REGISTRY_CDN_URL}
    serialized = json.dumps(data)
    if len(serialized.encode()) > 4_000_000:
        raise ValueError("Converted ACP registry exceeds the catalog size limit")
    path = service.root / "acp-registry.json"
    temporary = path.with_name(".acp-registry-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    status(f"Updated {len(agents)} registry agents. Existing offline catalog remains available.")
    return registry_status(service)


def extra_routes(service, project):
    from superqode.commands.acp import check_agent_installed

    try:
        agents = _snapshot(service)["agents"]
    except (OSError, ValueError):
        agents = []
    rows = []
    for agent in agents:
        command = (agent.get("run_command") or {}).get("*", "")
        try:
            argv = shlex.split(command)
        except ValueError:
            continue
        if argv and Path(argv[0]).name == "npx":
            argv = [argv[0], "--no-install", *[v for v in argv[1:] if v not in {"-y", "--yes"}]]
        elif argv and Path(argv[0]).name == "uvx":
            argv = [argv[0], "--offline", *[v for v in argv[1:] if v != "--online"]]
        row = _route(
            "acp:" + agent["short_name"],
            agent["name"],
            argv,
            available=bool(argv and check_agent_installed(agent) and shutil.which(argv[0])),
            description=agent.get("description", ""),
            website=agent.get("url", ""),
            registry_version=agent.get("registry_version", ""),
            registry_source="Official ACP registry",
            agent_id=agent["short_name"],
            setup_note=agent.get("installation_instructions", ""),
            # Installation is a separate, explicitly reviewed package-manager plan.
            registry_install=(agent.get("actions", {}).get("*", {}).get("install", {}) or {}).get(
                "command", ""
            ),
        )
        environment = agent.get("launch_env") or {}
        from superqode.tools.env_policy import is_secret_name

        unsafe = any(
            is_secret_name(name)
            or name
            in {"PATH", "ENV", "BASH_ENV", "ZDOTDIR", "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME"}
            or name.startswith(("DYLD_", "LD_"))
            or any(part in name.upper() for part in ("PROXY", "CERT", "TLS", "TRUST"))
            for name in environment
        )
        if unsafe:
            row["available"] = False
            row["issue"] = (
                "This manifest changes sensitive environment settings. Follow its vendor instructions or configure a trusted wrapper executable."
            )
        else:
            row["extra_env"] = environment
            row["digest"] = hashlib.sha256(
                json.dumps({"argv": argv, "env": environment}, sort_keys=True).encode()
            ).hexdigest()
        if (
            not row["available"]
            and not unsafe
            and argv
            and shutil.which(argv[0])
            and service._all(
                "SELECT reference FROM acp_install_receipts WHERE reference=? AND digest=?",
                (row["id"], row["digest"]),
            )
        ):
            row["available"] = True
            row["issue"] = ""
        rows.append(row)
    for record in service._all("SELECT * FROM custom_acp_agents WHERE project=?", (project,)):
        data = json.loads(record["definition"])
        rows.append(
            _route(
                record["id"],
                data["name"],
                data["argv"],
                available=shutil.which(data["argv"][0]) is not None,
                description="Project-specific ACP agent",
                registry_source="Your configuration",
                custom=True,
            )
        )
    return rows


def _route(identity, name, argv, *, available, **metadata):
    command = shlex.join(argv)
    digest = hashlib.sha256(json.dumps({"argv": argv}, sort_keys=True).encode()).hexdigest()
    return {
        "id": identity,
        "reference": identity,
        "name": name,
        "command": command,
        "command_argv": argv,
        "digest": digest,
        "available": available,
        "desktop_kind": "acp",
        "runtime": "ACP",
        "auth": "agent-managed; unverified",
        "subscription_vendor": None,
        "issue": ""
        if available
        else "Install the agent's executable, then refresh installed agents."
        if argv
        else "No compatible launch command is published for this platform. Review the vendor's setup instructions.",
        "install": None,
        **metadata,
    }


def custom_agent(service, params):
    project = params["project"]
    service.project(project)
    identity = params.get("id") or "acp:custom-" + uuid.uuid4().hex
    if not isinstance(identity, str) or not re.fullmatch(r"acp:custom-[a-f0-9]{32}", identity):
        raise ValueError("Choose a custom ACP configuration")
    name, argv = params.get("name"), params.get("argv")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 120
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Use an agent name of 1 to 120 characters")
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 100
        or any(not isinstance(v, str) or len(v) > 4000 or "\0" in v or "\n" in v for v in argv)
        or not argv[0].strip()
        or argv[0].startswith("-")
    ):
        raise ValueError("Enter an executable and up to 99 separate arguments")
    if Path(argv[0]).name == "npx":
        argv = [
            argv[0],
            "--no-install",
            *[
                v
                for v in argv[1:]
                if v not in {"-y", "--yes", "--yes=true", "--install", "--no-install"}
            ],
        ]
    elif Path(argv[0]).name == "uvx":
        argv = [argv[0], "--offline", *[v for v in argv[1:] if v not in {"--online", "--offline"}]]
    with service.lock:
        from .ownership import assert_project_idle

        assert_project_idle(service, project)
        if service._all(
            "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
            (project,),
        ):
            raise ValueError("Finish or stop project work before changing agent configuration")
        found = service._all(
            "SELECT definition FROM custom_acp_agents WHERE id=? AND project=?", (identity, project)
        )
        if params.get("id") and not found:
            raise ValueError("Custom agent not found in this project")
        if found:
            previous = json.loads(found[0]["definition"])
            expected = _route(identity, previous["name"], previous["argv"], available=False)[
                "digest"
            ]
            if params.get("expected_digest") != expected:
                raise ValueError("This configuration changed. Reopen it before saving.")
        data = {"name": name.strip(), "argv": argv}
        service._write(
            "INSERT INTO custom_acp_agents VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET definition=excluded.definition",
            (identity, project, json.dumps(data)),
        )
    return _route(
        identity,
        data["name"],
        argv,
        available=shutil.which(argv[0]) is not None,
        custom=True,
        registry_source="Your configuration",
    )


def remove_custom_agent(service, params):
    from .ownership import assert_project_idle

    with service.lock:
        project, identity = params["project"], params["id"]
        assert_project_idle(service, project)
        found = service._all(
            "SELECT definition FROM custom_acp_agents WHERE id=? AND project=?", (identity, project)
        )
        if not found:
            raise ValueError("Custom agent not found in this project")
        data = json.loads(found[0]["definition"])
        digest = _route(identity, data["name"], data["argv"], available=False)["digest"]
        if params.get("expected_digest") != digest:
            raise ValueError("This configuration changed. Reopen it before removing.")
        service._write(
            "DELETE FROM custom_acp_agents WHERE id=? AND project=?", (identity, project)
        )
    return {"ok": True}


def install_plan(service, project, reference):
    from .configuration import install_plan as bundled_plan
    from .configuration import installer_requirements

    root = service.project(project)
    try:
        plan = bundled_plan(root, reference.removeprefix("connection:"))
    except ValueError:
        route = next((r for r in extra_routes(service, project) if r["id"] == reference), None)
        if not route:
            raise ValueError("Choose an ACP agent from the catalog") from None
        argv = shlex.split(route.get("registry_install") or "")
        if (
            len(argv) != 4
            or argv[:3] not in [["npm", "install", "-g"], ["uv", "tool", "install"]]
            or not re.fullmatch(
                r"(?:@[a-z0-9._-]+/)?[a-zA-Z0-9][a-zA-Z0-9._-]*(?:(?:@|==)[a-zA-Z0-9._+~-]+)?",
                argv[-1],
            )
        ):
            raise ValueError("This agent needs the vendor's manual installation workflow") from None
        plan = {"reference": reference, "argv": argv, "command": shlex.join(argv)}
    plan["reference"] = reference
    plan["requirements"] = installer_requirements(plan["argv"])
    plan["digest"] = hashlib.sha256(json.dumps(plan["argv"]).encode()).hexdigest()
    return plan


async def install_agent(service, project, reference, expected_digest, status):
    from .configuration import run_install_command

    plan = install_plan(service, project, reference)
    if plan["digest"] != expected_digest:
        raise ValueError("The installation plan changed. Review it again before installing.")
    reviewed_route = next((r for r in extra_routes(service, project) if r["id"] == reference), None)
    result = await run_install_command(plan["argv"], status)
    route = next((r for r in extra_routes(service, project) if r["id"] == reference), None)
    if route and reviewed_route and route["digest"] == reviewed_route["digest"]:
        service._write(
            "INSERT OR REPLACE INTO acp_install_receipts VALUES(?,?,?)",
            (reference, route["digest"], time.time()),
        )
    return result
