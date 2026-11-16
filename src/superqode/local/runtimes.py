"""Shared contracts for explicit, loopback-only inference runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import ipaddress
import json
import os
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    name: str
    endpoint: str
    protocol: str = "openai"
    context: int = 8192
    tools: bool | None = None
    docs_url: str = ""
    template: str = "custom"
    include_usage: bool = True

    def public(self):
        return asdict(self)


TEMPLATES = (
    RuntimeSpec(
        "exo",
        "exo cluster",
        "http://127.0.0.1:52415/v1",
        docs_url="https://github.com/exo-explore/exo/blob/main/docs/api.md",
        include_usage=False,
    ),
    RuntimeSpec(
        "vllm-metal",
        "vLLM Metal",
        "http://127.0.0.1:8000/v1",
        docs_url="https://docs.vllm.ai/projects/vllm-metal/en/latest/recipes/",
    ),
    RuntimeSpec(
        "omlx", "oMLX", "http://127.0.0.1:8000/v1", docs_url="https://github.com/jundot/omlx"
    ),
    RuntimeSpec(
        "jan", "Jan", "http://127.0.0.1:1337/v1", docs_url="https://docs.jan.ai/desktop/api-server"
    ),
    RuntimeSpec(
        "gpt4all",
        "GPT4All",
        "http://127.0.0.1:4891/v1",
        tools=False,
        docs_url="https://docs.gpt4all.io/gpt4all_api_server/home.html",
    ),
    RuntimeSpec("custom", "Other compatible server", "http://127.0.0.1:8000/v1"),
)

TEMPLATES = tuple(replace(spec, template=spec.id) for spec in TEMPLATES)


def loopback_url(value):
    """Reject redirects, credentials and remote/DNS destinations before sending keys."""
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ValueError("Enter a local server base URL, such as http://127.0.0.1:8000/v1")
    try:
        url = urlsplit(value)
        port = url.port
        local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = False
    if (
        not local
        or url.scheme not in {"http", "https"}
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Use an HTTP(S) loopback URL without credentials, query or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Use a valid local port")
    path = url.path.rstrip("/")
    if path.endswith(("/models", "/chat/completions", "/responses")):
        raise ValueError("Enter the server base URL ending in /v1, not a request endpoint")
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def validate(data):
    identity = str(data.get("id") or "")
    if (
        not identity
        or len(identity) > 64
        or not all(c.isascii() and (c.isalnum() or c in "-_") for c in identity)
    ):
        raise ValueError("Use a runtime ID containing letters, numbers, hyphens or underscores")
    name = str(data.get("name") or identity).strip()
    context = data.get("context", 8192)
    tools = data.get("tools")
    if type(context) is not int or not 512 <= context <= 262144:
        raise ValueError("Choose context between 512 and 262144 tokens")
    include_usage = data.get("include_usage", True)
    if type(include_usage) is not bool:
        raise ValueError("Usage reporting must be enabled or disabled")
    if tools is not None and type(tools) is not bool:
        raise ValueError("Tool capability must be supported, unsupported or unknown")
    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError("Enter a runtime name up to 100 characters")
    if data.get("protocol", "openai") != "openai":
        raise ValueError("External profiles currently use the OpenAI chat-completions protocol")
    template = data.get(
        "template", identity if any(r.id == identity for r in TEMPLATES) else "custom"
    )
    if template not in {r.id for r in TEMPLATES}:
        raise ValueError("Choose a supported runtime setup template")
    docs = next((r.docs_url for r in TEMPLATES if r.id == template), "")
    return RuntimeSpec(
        identity,
        name,
        loopback_url(data.get("endpoint")),
        context=context,
        tools=tools,
        docs_url=docs,
        template=template,
        include_usage=include_usage,
    )


def selected_runtime():
    raw = os.environ.get("SUPERQODE_LOCAL_RUNTIME")
    if not raw:
        raise ValueError("Choose a saved local runtime in Local AI before starting this model")
    return validate(json.loads(raw))


def _exo_field(row, name):
    """Read an exo field in its camelCase wire form, or the snake_case model name."""
    if not isinstance(row, dict):
        return None
    head, *rest = name.split("_")
    camel = head + "".join(part.title() for part in rest)
    return row.get(camel, row.get(name))


def _exo_tagged(row):
    """exo serializes union members as {"ClassName": {...}}; return both parts."""
    if isinstance(row, dict) and len(row) == 1:
        tag, inner = next(iter(row.items()))
        if isinstance(inner, dict):
            return tag, inner
    return "", row if isinstance(row, dict) else {}


def _exo_bytes(value):
    if isinstance(value, dict):
        value = _exo_field(value, "in_bytes")
    return value if type(value) is int and value >= 0 else None


def _exo_headers(key):
    return {"Authorization": f"Bearer {key}"} if key else {}


def _exo_base(spec):
    if spec.template != "exo" or not spec.endpoint.endswith("/v1"):
        raise ValueError("Choose an exo loopback base URL ending in /v1")
    return spec.endpoint.removesuffix("/v1")


async def _exo_state(spec, key=None, *, transport=None):
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, transport=transport, timeout=3
    ) as client:
        async with client.stream(
            "GET", _exo_base(spec) + "/state", headers=_exo_headers(key)
        ) as response:
            response.raise_for_status()
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > 8_000_000:
                    raise ValueError("exo cluster state is too large")
    state = json.loads(payload)
    if not isinstance(state, dict) or not isinstance(state.get("instances"), dict):
        raise ValueError("The endpoint did not return exo cluster state")
    return state


def _exo_downloads(state, names):
    """Per model: downloaded on any node wins over a download still in progress."""
    downloads = _exo_field(state, "downloads")
    if not isinstance(downloads, dict):
        return None
    found = {}
    for node, rows in downloads.items():
        if not isinstance(rows, list):
            continue
        for item in rows:
            tag, row = _exo_tagged(item)
            _, shard = _exo_tagged(_exo_field(row, "shard_metadata"))
            card = _exo_field(shard, "model_card")
            model = _exo_field(card, "model_id")
            if not isinstance(model, str) or not model:
                continue
            if tag == "DownloadCompleted":
                status = "downloaded"
            elif tag == "DownloadOngoing" or (
                tag == "DownloadPending" and (_exo_bytes(_exo_field(row, "downloaded")) or 0) > 0
            ):
                status = "downloading"
            else:
                continue
            entry = found.setdefault(
                model,
                {
                    "status": status,
                    "nodes": [],
                    "progress": None,
                    "size_bytes": _exo_bytes(_exo_field(card, "storage_size")),
                },
            )
            if status == "downloaded" and entry["status"] != "downloaded":
                entry.update(status="downloaded", nodes=[], progress=None)
            if status != entry["status"]:
                continue
            entry["nodes"].append(names.get(node, node))
            if status == "downloading":
                progress = _exo_field(row, "download_progress") or row
                done = _exo_bytes(_exo_field(progress, "downloaded"))
                total = _exo_bytes(_exo_field(progress, "total"))
                if done is not None and total:
                    entry["progress"] = min(1.0, done / total)
    for entry in found.values():
        entry["nodes"] = sorted(set(entry["nodes"]))
    return found


async def exo_cluster(spec, key=None, *, transport=None):
    """Inspect a configured exo node. Inference may run across its network."""
    _exo_base(spec)
    state = await _exo_state(spec, key, transport=transport)
    memory = _exo_field(state, "node_memory") or {}
    identities = _exo_field(state, "node_identities") or {}
    if not isinstance(memory, dict) or not isinstance(identities, dict):
        raise ValueError("exo returned invalid node information")
    topology = _exo_field(state, "topology")
    listed = topology.get("nodes") if isinstance(topology, dict) else None
    if isinstance(listed, list) and listed and all(isinstance(node, str) for node in listed):
        node_ids = list(dict.fromkeys(listed))
    else:
        node_ids = sorted(set(memory) | set(identities))
    nodes = []
    names = {}
    for node in node_ids:
        identity = identities.get(node) if isinstance(identities.get(node), dict) else {}
        usage = memory.get(node) if isinstance(memory.get(node), dict) else {}
        name = _exo_field(identity, "friendly_name")
        name = name if isinstance(name, str) and name and name != "Unknown" else node
        chip = _exo_field(identity, "chip_id")
        names[node] = name
        nodes.append(
            {
                "id": node,
                "name": name,
                "chip": chip if isinstance(chip, str) and chip != "Unknown" else "",
                "ram_total_bytes": _exo_bytes(_exo_field(usage, "ram_total")),
                "ram_available_bytes": _exo_bytes(_exo_field(usage, "ram_available")),
            }
        )
    nodes.sort(key=lambda row: (row["name"].lower(), row["id"]))
    totals = [row["ram_total_bytes"] for row in nodes if row["ram_total_bytes"]]
    available = [row["ram_available_bytes"] for row in nodes if row["ram_available_bytes"]]
    deployed = set()
    for item in state["instances"].values():
        _, row = _exo_tagged(item)
        model = _exo_field(_exo_field(row, "shard_assignments"), "model_id")
        if isinstance(model, str) and model:
            deployed.add(model)
    return {
        "node_count": len(nodes),
        "nodes": nodes,
        "installed_memory_bytes": sum(totals) if totals else None,
        "available_memory_bytes": sum(available) if available else None,
        "deployed_models": sorted(deployed),
        "downloads": _exo_downloads(state, names),
        "location": "On your network",
    }


_EXO_ORDER = {"running": 0, "downloaded": 1, "downloading": 2}


def _context(spec, row):
    maximum = row.get("max_model_len") or row.get("context_length") or row.get("contextLength")
    known = type(maximum) is int and maximum >= 512
    return {
        "context": min(spec.context, maximum) if known else spec.context,
        "context_source": "server and configured cap"
        if known
        else "configured cap; loaded context unknown",
    }


def _chat_model(identity, row):
    if not 0 < len(identity) <= 4096 or any(
        w in identity.lower() for w in ("embedding", "reranker")
    ):
        return False
    tasks = row.get("tasks")
    return not isinstance(tasks, list) or not tasks or "TextGeneration" in tasks


async def _exo_catalog(spec, key, data, client, transport):
    try:
        cluster = await exo_cluster(spec, key, transport=transport)
    except (httpx.HTTPError, ValueError):
        # Never fall back to exo's whole catalogue: it lists models that are not on any node.
        return {
            "models": [],
            "exo_models": [],
            "cluster": None,
            "cluster_error": "exo answered, but its cluster state is unavailable. "
            "Start exo, join your cluster, then check again.",
        }
    downloads = cluster.pop("downloads")
    if downloads is None:
        # Older exo builds: ask exo for the models it has downloaded.
        response = await client.get(
            spec.endpoint + "/models", params={"status": "downloaded"}, headers=_exo_headers(key)
        )
        response.raise_for_status()
        downloads = {
            row["id"]: {"status": "downloaded", "nodes": [], "progress": None, "size_bytes": None}
            for row in response.json().get("data", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
    catalog = {
        row["id"]: row
        for row in data.get("data", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    rows = []
    for identity in set(downloads) | set(cluster["deployed_models"]):
        info = catalog.get(identity, {})
        if not _chat_model(identity, info):
            continue
        entry = downloads.get(identity) or {"nodes": [], "progress": None, "size_bytes": None}
        size = entry.get("size_bytes")
        megabytes = info.get("storage_size_megabytes")
        if size is None and type(megabytes) is int and megabytes > 0:
            size = megabytes * 1024 * 1024
        running = identity in cluster["deployed_models"]
        rows.append(
            {
                "id": identity,
                "status": "running" if running else entry["status"],
                "nodes": entry.get("nodes", []),
                "progress": None if running else entry.get("progress"),
                "size_bytes": size,
                **_context(spec, info),
                "tools": spec.tools,
            }
        )
    rows.sort(key=lambda row: (_EXO_ORDER[row["status"]], row["id"].lower()))
    return {
        "models": [row for row in rows if row["status"] == "running"],
        "exo_models": rows,
        "cluster": cluster,
        "cluster_error": None,
    }


async def model_catalog(spec, key=None, *, transport=None):
    headers = _exo_headers(key)
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, transport=transport, timeout=3
    ) as client:
        response = await client.get(spec.endpoint + "/models", headers=headers)
        if response.status_code in {401, 403}:
            raise ValueError(
                "The local server requires a valid API key. Review its authentication settings."
            )
        if response.is_redirect:
            raise ValueError(
                "The local server redirected the request. Enter its direct loopback base URL."
            )
        response.raise_for_status()
        data = response.json()
        if spec.template == "exo":
            return await _exo_catalog(spec, key, data, client, transport)
    rows = []
    for row in data.get("data", []):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        identity = row["id"]
        if not _chat_model(identity, {}):
            continue
        rows.append({"id": identity, **_context(spec, row), "tools": spec.tools})
    return {"models": rows, "cluster": None, "cluster_error": None}


async def exo_start(spec, model, key=None, *, transport=None, timeout=300, progress=None):
    """Start a downloaded model with exo's own placement API, then wait until it runs."""
    base = _exo_base(spec)
    if not isinstance(model, str) or not model or len(model) > 4096:
        raise ValueError("Choose a model downloaded in exo")
    if type(timeout) not in {int, float} or not 1 <= timeout <= 300:
        raise ValueError("Choose an exo start timeout up to 300 seconds")
    headers = _exo_headers(key)
    note = progress or (lambda _message: None)
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        transport=transport,
        timeout=httpx.Timeout(60, connect=5),
    ) as client:
        note("Asking exo where this model fits on your cluster")
        response = await client.get(
            base + "/instance/previews", params={"model_id": model}, headers=headers
        )
        response.raise_for_status()
        previews = response.json().get("previews")
        previews = (
            [row for row in previews if isinstance(row, dict)] if isinstance(previews, list) else []
        )
        chosen = next(
            (row for row in previews if not row.get("error") and row.get("instance")), None
        )
        if chosen is None:
            reason = next(
                (row["error"] for row in previews if isinstance(row.get("error"), str)), ""
            )
            raise ValueError(
                "exo found no placement for this model on your cluster"
                + (": " + reason if reason else ". Check free memory on your nodes.")
            )
        nodes = len(chosen.get("memory_delta_by_node") or {}) or 1
        note(f"Starting the model on {nodes} node" + ("" if nodes == 1 else "s"))
        response = await client.post(
            base + "/place_instance",
            json={
                "model_id": model,
                "sharding": chosen.get("sharding", "Pipeline"),
                "instance_meta": chosen.get("instance_meta", "MlxRing"),
                "min_nodes": nodes,
            },
            headers=headers,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise ValueError(
                "exo did not start the model"
                + (": " + detail if isinstance(detail, str) and detail else ".")
            )
        note("Waiting for exo to load the model")
        async with client.stream(
            "GET",
            base + "/instance/await",
            params={"model_id": model, "timeout_seconds": timeout},
            headers=headers,
            timeout=httpx.Timeout(timeout + 30, connect=5),
        ) as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if not line.startswith("data:"):
                    continue
                message = json.loads(line.removeprefix("data:").strip() or "{}")
                if message.get("type") == "ready":
                    return {"model": model, "nodes": nodes}
                if message.get("type") == "timeout":
                    raise ValueError(
                        "exo is still loading the model. Check the server again in a moment."
                    )
    raise ValueError("exo stopped answering before the model was ready")


async def models(spec, key=None, *, transport=None):
    """Models that can answer a request now. For exo that means a running instance."""
    catalog = await model_catalog(spec, key, transport=transport)
    if catalog["cluster_error"]:
        raise ValueError(catalog["cluster_error"])
    return catalog["models"]


async def stream(
    spec,
    messages,
    model,
    *,
    key=None,
    tools=None,
    max_tokens=None,
    temperature=None,
    transport=None,
    response_format=None,
    reasoning_effort=None,
    timeout=180,
):
    from superqode.providers.gateway.base import StreamChunk, Usage
    from superqode.providers.local.wire_stream import local_response
    from .context_contract import guard_request
    from contextlib import aclosing

    if tools and spec.tools is False:
        raise ValueError(
            "This runtime is configured without tool support. Choose Direct Chat or another model/runtime."
        )
    body_messages = [
        {k: v for k, v in asdict(message).items() if v is not None} for message in messages
    ]
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
        raise ValueError("Local output limit must be a positive integer")
    import math

    if temperature is not None and (
        type(temperature) not in {int, float} or not math.isfinite(temperature) or temperature < 0
    ):
        raise ValueError("Local temperature must be a finite, non-negative number")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise ValueError("Local request timeout must be between 1 and 1800 seconds")
    if response_format is not None and (
        not isinstance(response_format, dict)
        or response_format.get("type") not in {"text", "json_object", "json_schema"}
    ):
        raise ValueError("Use an OpenAI-compatible response_format dictionary for this runtime")
    if reasoning_effort is not None and reasoning_effort not in (
        "off",
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "max",
    ):
        raise ValueError("Choose a supported reasoning effort for the local server")
    # Explicit output bounds are honoured up to the available context. The
    # smaller quarter-window value is only the default, not a hidden override.
    output = max_tokens if max_tokens is not None else min(2048, max(128, spec.context // 4))
    from .context_contract import _launch_contract_value

    limit = _launch_contract_value("local-openai", model, "max_tokens", 128, 65536)
    if limit is not None:
        output = min(output, limit)
    tool_wire = [{"type": "function", "function": asdict(t)} for t in tools] if tools else None
    kept, output = guard_request(body_messages, tool_wire, spec.context, output)
    from .execution import annotate

    annotate(
        context=spec.context,
        context_source="configured cap; loaded context unknown",
        output_limit=output,
    )
    body_messages = [body_messages[i] for i in kept]
    body = {
        "model": model,
        "messages": body_messages,
        "max_tokens": output,
        "stream": True,
    }
    if spec.include_usage:
        body["stream_options"] = {"include_usage": True}
    if response_format is not None:
        body["response_format"] = response_format
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        body["temperature"] = temperature
    if tool_wire:
        body["tools"] = tool_wire
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=5),
    ) as client:
        async with client.stream(
            "POST", spec.endpoint + "/chat/completions", json=body, headers=headers
        ) as response:
            if response.is_redirect:
                raise ValueError(
                    "Local inference redirects are refused; use the direct loopback URL"
                )
            if response.status_code in {401, 403}:
                raise ValueError(
                    "The local server rejected its API key. Update this profile's key and retry."
                )
            if response.status_code == 404:
                raise ValueError(
                    "The selected model or API route was not found. Check the base URL and refresh the server's models."
                )
            if response.status_code == 400:
                raise ValueError(
                    "The local server rejected the request. Check context, tool parser, reasoning/structured-output options and usage reporting support."
                )
            response.raise_for_status()
            async with aclosing(local_response(response, protocol="openai", live=True)) as events:
                async for kind, payload in events:
                    if kind == "text":
                        yield StreamChunk(content=payload)
                    elif kind == "thinking":
                        yield StreamChunk(thinking_content=payload)
                    else:
                        data, displayed = payload
                        choice = (data.get("choices") or [{}])[0]
                        reason = choice.get("finish_reason")
                        if reason not in {"stop", "length", "tool_calls"}:
                            raise ValueError(
                                "Local inference ended without a valid completion reason"
                            )
                        message = choice.get("message") or {}
                        calls = message.get("tool_calls") or []
                        from uuid import uuid4

                        for call in calls:
                            call.setdefault("type", "function")
                            call.setdefault("id", uuid4().hex)
                        for call in calls:
                            args = call["function"].get("arguments", {})
                            if not isinstance(
                                json.loads(args) if isinstance(args, str) else args, dict
                            ):
                                raise ValueError("Local tool arguments must be a JSON object")
                        if not displayed and message.get("content"):
                            yield StreamChunk(content=message["content"])
                        usage = data.get("usage") or {}
                        yield StreamChunk(
                            finish_reason=reason,
                            tool_calls=calls or None,
                            usage=Usage(
                                prompt_tokens=usage.get("prompt_tokens", 0),
                                completion_tokens=usage.get("completion_tokens", 0),
                                total_tokens=usage.get(
                                    "total_tokens",
                                    usage.get("prompt_tokens", 0)
                                    + usage.get("completion_tokens", 0),
                                ),
                            )
                            if usage
                            else None,
                        )
