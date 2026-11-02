"""Small, credential-free agent identities derived from recorded execution routes."""

import json

from superqode.providers.acp_registry import REGISTRY_SHORT_NAMES

RUNTIME_ICONS = {
    "codex-cli": "codex",
    "codex-sdk": "codex",
    "claude-agent-sdk": "claude",
    "copilot-sdk": "copilot",
    "gemini-cli": "gemini",
}


def request_identity(request):
    saved = request.get("_thread_harness") or {}
    route = request.get("_desktop_route") or request.get("_desktop_connection") or {}
    reference = str(request.get("harness") or "core")
    runtime = str(saved.get("runtime") or route.get("runtime") or "")
    agent = str(route.get("agent_id") or route.get("subscription_vendor") or "")
    if not agent and reference.startswith(("acp:", "connection:", "attach:", "vendor-key:")):
        agent = reference.split(":", 1)[1]
    icon = REGISTRY_SHORT_NAMES.get(agent, agent) or RUNTIME_ICONS.get(runtime, "")
    if not icon and reference in {"core", "pipy", "codegem", "systemone"}:
        icon = "superqode"
    return {
        "id": reference,
        "name": str(saved.get("name") or route.get("name") or reference)[:160],
        "icon_key": icon,
    }


def thread_harnesses(service, conversations):
    """Aggregate full history, including turns outside the recent-jobs window."""
    if not conversations:
        return {}
    rows = service._all(
        "SELECT t.project,t.conversation,"
        "json_extract(j.request,'$.harness') AS harness,"
        "json_extract(j.request,'$._thread_harness') AS saved,"
        "json_extract(j.request,'$._desktop_route') AS route,"
        "json_extract(j.request,'$._desktop_connection') AS connection "
        "FROM thread_runs t JOIN jobs j ON j.id=t.job WHERE t.conversation IN ("
        + ",".join("?" for _ in conversations)
        + ") ORDER BY j.created,j.id",
        conversations,
    )
    result = {}
    for row in rows:
        identity = request_identity(
            {
                "harness": row["harness"],
                "_thread_harness": json.loads(row["saved"]) if row["saved"] else {},
                "_desktop_route": json.loads(row["route"]) if row["route"] else {},
                "_desktop_connection": json.loads(row["connection"]) if row["connection"] else {},
            }
        )
        group = result.setdefault((row["project"], row["conversation"]), {})
        group[identity["id"]] = identity
    return {key: list(values.values()) for key, values in result.items()}
