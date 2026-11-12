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


async def models(spec, key=None, *, transport=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
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
    rows = []
    for row in data.get("data", []):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        identity = row["id"]
        if not 0 < len(identity) <= 4096 or any(
            w in identity.lower() for w in ("embedding", "reranker")
        ):
            continue
        maximum = row.get("max_model_len") or row.get("context_length")
        rows.append(
            {
                "id": identity,
                "context": min(spec.context, maximum)
                if type(maximum) is int and maximum >= 512
                else spec.context,
                "context_source": "server and configured cap"
                if type(maximum) is int and maximum >= 512
                else "configured cap; loaded context unknown",
                "tools": spec.tools,
            }
        )
    return rows


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
