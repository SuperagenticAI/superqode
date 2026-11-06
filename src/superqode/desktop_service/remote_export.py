"""Explicit portable evidence exports, containing visible conversation data only."""

import html
import json
import re


def export_run(access, request):
    service = access.service
    identity, project = request["id"], request["project"]
    format = request.get("format", "markdown")
    if format not in {"markdown", "json", "html"}:
        raise ValueError("Choose Markdown, JSON or HTML")
    detail = service.dispatch("jobs.get", {"id": identity})
    payload = {k: detail.get(k) for k in ("id", "kind", "status", "title", "result")}
    payload["connection"] = {
        k: detail.get("request", {}).get(k)
        for k in ("harness", "provider", "model", "interaction_mode")
    }
    if detail["kind"] == "task":
        payload["result"] = {
            k: (detail.get("result") or {}).get(k)
            for k in ("summary", "error", "usage", "cost_usd", "duration_seconds")
            if k in (detail.get("result") or {})
        }
        from .conversations import lineage, answer

        nodes = lineage(service, identity)
        if any(node["project"] != project for node in nodes):
            raise PermissionError("This conversation includes another project")
        payload["turns"] = [
            {
                "prompt": node["request"].get("prompt", ""),
                "response": answer(service, node["id"]),
                "status": node["status"],
            }
            for node in nodes[-100:]
        ]
        payload["omitted_turns"] = max(0, len(nodes) - 100)
    payload = access.clean(payload)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    truncated = len(raw) > 500_000
    if truncated:
        # Never produce invalid truncated JSON. Link the user to full Mac history.
        payload = {
            "id": identity,
            "kind": detail["kind"],
            "status": detail["status"],
            "message": "Evidence exceeds the mobile export limit. Export the complete recorded run on your Mac.",
            "truncated": True,
        }
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
    if format == "json":
        content, suffix, mime = raw, "json", "application/json"
    elif format == "html":
        content, suffix, mime = (
            "<!doctype html><meta charset=utf-8><title>SuperQode evidence</title><h1>SuperQode recorded evidence</h1><pre>"
            + html.escape(raw)
            + "</pre>",
            "html",
            "text/html",
        )
    else:
        if not truncated and "turns" in payload:
            body = "\n\n".join(
                "### You\n\n" + turn["prompt"] + "\n\n### Agent\n\n" + turn["response"]
                for turn in payload["turns"]
            )
            content = f"# SuperQode conversation\n\nRun: {identity}\nStatus: {detail['status']}\nOmitted earlier turns: {payload['omitted_turns']}\n\n{body}"
        else:
            content = "# SuperQode recorded evidence\n\n```json\n" + raw + "\n```"
        suffix, mime = "md", "text/markdown"
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", identity)[:64]
    return {
        "name": f"superqode-{safe}.{suffix}",
        "mime_type": mime,
        "content": content,
        "truncated": truncated,
    }
