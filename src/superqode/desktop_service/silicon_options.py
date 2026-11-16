"""Harness Studio toggles for Silicon MCP, Monty Code Mode and Apple Container checks.

The draft YAML stays the source of truth. These helpers read the current
settings from a resolved Studio draft and return an edited draft plus a diff.
Nothing is saved here; Studio's validate and save path still applies.
"""

from __future__ import annotations

import copy
import difflib
import platform
import re
import shutil

import yaml

from . import studio

APPLE_TOOL_LIMIT = 5
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_SERVER = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _load(text):
    if not isinstance(text, str) or len(text.encode()) > 250_000:
        raise ValueError("Use a HarnessSpec smaller than 250 KB")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Enter a YAML HarnessSpec mapping")
    wrapped = "harness" in data and isinstance(data["harness"], dict)
    inner = data["harness"] if wrapped else data
    if "inherits" in inner or "extends" in inner:
        raise ValueError("Load a resolved preset before editing an inherited definition")
    if (inner.get("model_policy") or {}).get("profile") != "silicon":
        raise ValueError("Silicon options apply to harnesses based on Silicon")
    return data, inner


def _dump(data):
    return yaml.safe_dump(data, sort_keys=False)


def _section(data, key):
    value = data.get(key)
    if not isinstance(value, dict):
        value = {}
        data[key] = value
    return value


def _agent_tools(inner):
    agents = inner.get("agents")
    if not isinstance(agents, list) or not agents or not isinstance(agents[0], dict):
        raise ValueError("Silicon options need a first agent with a tool list")
    tools = agents[0].get("tools")
    if not isinstance(tools, list):
        tools = []
        agents[0]["tools"] = tools
    return tools


def container_support():
    """Report whether this Mac can run Apple Container checks, without running them."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return {"available": False, "reason": "Apple Container checks need an Apple Silicon Mac."}
    major = platform.mac_ver()[0].partition(".")[0]
    if not major.isdecimal() or int(major) < 26:
        return {"available": False, "reason": "Apple Container checks need macOS 26 or later."}
    if not shutil.which("container"):
        return {
            "available": False,
            "reason": "Install Apple's container tool to run checks in Apple Container.",
        }
    return {"available": True, "reason": ""}


def monty_support():
    from superqode.tools.monty_tool import is_monty_available

    if is_monty_available():
        return {"available": True, "reason": ""}
    return {"available": False, "reason": "Monty is not installed in this copy of SuperQode."}


def mcp_servers(root, config):
    from superqode.mcp.config import resolve_mcp_config

    try:
        resolution = resolve_mcp_config(config, cwd=root)
    except ValueError as exc:
        return [], [str(exc)]
    return [
        {"id": sid, "source": str(resolution.sources.get(sid, ""))}
        for sid in sorted(resolution.servers)
    ], list(resolution.errors)


def _state(root, inner):
    tools = list(_agent_tools(inner))
    config = (inner.get("runtime") or {}).get("config") or {}
    allowlist = config.get("silicon_mcp") or {}
    if not isinstance(allowlist, dict):
        allowlist = {}
    checks = inner.get("checks") or {}
    steps = []
    for index, step in enumerate(checks.get("custom_steps") or []):
        if not isinstance(step, dict):
            continue
        container = (
            step.get("apple_container") if isinstance(step.get("apple_container"), dict) else None
        )
        steps.append(
            {
                "index": index,
                "name": str(step.get("name") or f"step-{index + 1}"),
                "command": str(step.get("command") or ""),
                "apple_container": bool(container),
                "image": str((container or {}).get("image") or ""),
                "files": [str(path) for path in (container or {}).get("files") or []],
            }
        )
    servers, errors = mcp_servers(root, config)
    count = len(tools)
    warnings = list(errors)
    if count > APPLE_TOOL_LIMIT:
        warnings.append(
            f"This harness exposes {count} tools. Apple on-device runs allow at most {APPLE_TOOL_LIMIT}."
        )
    return {
        "tools": tools,
        "tool_count": count,
        "tool_limit": APPLE_TOOL_LIMIT,
        "mcp": {
            "enabled": bool(allowlist) and "execute" in tools,
            "allowlist": {
                str(k): [str(t) for t in v] for k, v in allowlist.items() if isinstance(v, list)
            },
            "servers": servers,
        },
        "code_mode": config.get("silicon_mcp_code") is True,
        "checks": {
            "enabled": bool(checks.get("enabled", False)),
            "fail_on_error": bool(checks.get("fail_on_error", False)),
            "steps": steps,
        },
        "allow_network": bool((inner.get("execution_policy") or {}).get("allow_network", False)),
        "support": {"apple_container": container_support(), "monty": monty_support()},
        "warnings": warnings,
    }


def read(service, params):
    root = service.project(params["project"])
    _, inner = _load(params.get("yaml"))
    return _state(root, inner)


def _files(raw):
    if not isinstance(raw, list) or not raw or len(raw) > 64:
        raise ValueError("List between 1 and 64 project files for the Apple Container check")
    out = []
    for path in raw:
        if not isinstance(path, str):
            raise ValueError("Apple Container files must be project-relative paths")
        path = path.strip()
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(c) < 32 for c in path)
        ):
            raise ValueError("Apple Container files must be literal project-relative paths")
        out.append(path)
    if len(set(out)) != len(out):
        raise ValueError("List each Apple Container file once")
    return out


def _apply_mcp(inner, mcp, configured):
    tools = _agent_tools(inner)
    runtime = _section(inner, "runtime")
    config = _section(runtime, "config")
    policy = _section(inner, "execution_policy")
    rules = policy.get("permission_rules")
    rules = list(rules) if isinstance(rules, list) else []
    old = config.get("silicon_mcp") if isinstance(config.get("silicon_mcp"), dict) else {}
    stale = {"execute"} | {
        f"mcp_{server}_{tool}"
        for server, names in old.items()
        if isinstance(names, list)
        for tool in names
    }

    def keep(rule):
        return not (
            isinstance(rule, dict)
            and rule.get("tool") in stale
            and str(rule.get("action", "")).lower() == "allow"
            and rule.get("pattern") in (None, "", "*")
            and not rule.get("argument")
        )

    rules = [rule for rule in rules if keep(rule)]
    if not mcp or not mcp.get("enabled"):
        if "execute" in tools:
            tools.remove("execute")
        config.pop("silicon_mcp", None)
        config.pop("silicon_mcp_code", None)
        if old:
            policy["allow_network"] = False
    else:
        allowlist = mcp.get("allowlist")
        if not isinstance(allowlist, dict) or not allowlist:
            raise ValueError("Choose at least one MCP server and tool to expose")
        clean = {}
        for server, names in allowlist.items():
            if not isinstance(server, str) or not _SERVER.fullmatch(server):
                raise ValueError("Use a configured MCP server ID")
            if server not in configured:
                raise ValueError(f"MCP server {server!r} is not configured for this project")
            if not isinstance(names, list):
                raise ValueError("List the MCP tools to expose for each server")
            names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
            if not names:
                raise ValueError(f"Enter at least one tool name for {server}")
            if any(not _TOOL_NAME.fullmatch(n) for n in names) or len(set(names)) != len(names):
                raise ValueError(
                    "Use distinct MCP tool names with letters, numbers, dots, dashes or underscores"
                )
            clean[server] = names
        if "execute" not in tools:
            tools.append("execute")
        config["silicon_mcp"] = clean
        policy["allow_network"] = True
        rules.append({"tool": "execute", "action": "allow"})
        rules += [
            {"tool": f"mcp_{server}_{tool}", "action": "allow"}
            for server, names in clean.items()
            for tool in names
        ]
    if rules:
        policy["permission_rules"] = rules
    else:
        policy.pop("permission_rules", None)
    if not config:
        runtime.pop("config", None)


def _apply_code_mode(inner, enabled):
    config = _section(_section(inner, "runtime"), "config")
    if enabled:
        if not config.get("silicon_mcp"):
            raise ValueError("Turn on MCP before Monty Code Mode")
        config["silicon_mcp_code"] = True
    else:
        config.pop("silicon_mcp_code", None)
    if not config:
        inner["runtime"].pop("config", None)


def _apply_checks(inner, checks):
    from superqode.sandbox.apple_container import _IMAGE

    section = _section(inner, "checks")
    steps = section.get("custom_steps")
    steps = steps if isinstance(steps, list) else []
    section["custom_steps"] = steps
    for added in checks.get("add") or []:
        if not isinstance(added, dict):
            raise ValueError("Describe the new check with a name and command")
        name = str(added.get("name") or "").strip()
        command = str(added.get("command") or "").strip()
        timeout = added.get("timeout", 60)
        if not name or not command or len(name) > 120 or len(command) > 4000:
            raise ValueError("Give the new check a short name and a command")
        if any(ord(c) < 32 for c in name) or "\n" in command:
            raise ValueError("Use a single-line check name and command")
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError("Use a check timeout between 1 and 3,600 seconds")
        steps.append({"name": name, "command": command, "timeout": timeout})
        section["enabled"] = True
    for change in checks.get("steps") or []:
        index = change.get("index") if isinstance(change, dict) else None
        if (
            type(index) is not int
            or not 0 <= index < len(steps)
            or not isinstance(steps[index], dict)
        ):
            raise ValueError("That check step is no longer in the draft. Reload the options")
        step = steps[index]
        if not change.get("apple_container"):
            step.pop("apple_container", None)
            continue
        image = str(change.get("image") or "").strip()
        if not _IMAGE.fullmatch(image):
            raise ValueError(
                "Use a local image pinned by digest, for example name@sha256:<64 hex characters>"
            )
        step["apple_container"] = {"image": image, "files": _files(change.get("files"))}
    if "enabled" in checks:
        section["enabled"] = bool(checks["enabled"])
    if "fail_on_error" in checks:
        section["fail_on_error"] = bool(checks["fail_on_error"])


def apply(service, params):
    """Return an edited draft and its diff. Studio still validates and saves it."""
    root = service.project(params["project"])
    data, inner = _load(params.get("yaml"))
    before = _dump(data)
    edited = copy.deepcopy(data)
    target = (
        edited["harness"] if "harness" in edited and isinstance(edited["harness"], dict) else edited
    )
    options = params.get("options") or {}
    if not isinstance(options, dict):
        raise ValueError("Choose Silicon options to apply")
    config = (target.get("runtime") or {}).get("config") or {}
    servers, _ = mcp_servers(root, config)
    if "mcp" in options:
        _apply_mcp(target, options["mcp"], {row["id"] for row in servers})
    if "code_mode" in options:
        _apply_code_mode(target, bool(options["code_mode"]))
    if isinstance(options.get("checks"), dict):
        _apply_checks(target, options["checks"])
    text = _dump(edited)
    # Reject drafts the loader would refuse, before the user reviews them.
    studio.parse(text, params.get("name") or str(target.get("name") or "my-harness"))
    state = _state(root, target)
    if state["code_mode"] and not state["support"]["monty"]["available"]:
        state["warnings"].append("Monty Code Mode is on, but Monty is not installed here.")
    if (
        any(step["apple_container"] for step in state["checks"]["steps"])
        and not state["support"]["apple_container"]["available"]
    ):
        state["warnings"].append(state["support"]["apple_container"]["reason"])
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            text.splitlines(keepends=True),
            "draft",
            "with Silicon options",
        )
    )
    return {"yaml": text, "diff": diff, "changed": text != before, "state": state}
