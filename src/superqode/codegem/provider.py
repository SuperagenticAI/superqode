"""Google-native signed content and local Gemma tool conversations.

Gemini text can stream live, but the model turn is stored exactly as the
signed parts arrived. Function arguments execute only after a successful,
complete model response.
No parsing of prose or raw Python as a tool call is allowed.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import email.utils
import json
import logging
import os
import random
import re
import time
from uuid import uuid4

import httpx

from superqode.pipy.messages import (
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ToolResultMessage,
    TextContent,
    ThinkingContent,
    ImageContent,
    ToolCall,
    Usage,
    UsageCost,
)
from superqode.pipy.provider_events import (
    AssistantStartEvent,
    AssistantDoneEvent,
    AssistantErrorEvent,
    TextStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    ThinkingStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ToolCallStartEvent,
    ToolCallEndEvent,
)
from superqode.pipy.signals import is_aborted
from .profiles import resolve_profile

# Google's latest-model guide for Gemini 4: "Remove temperature, top_p, top_k,
# and candidate_count ... sampling parameters are ignored".
_SAMPLING_KEYS = ("temperature", "top_p", "top_k", "candidate_count")
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def _thinking_config(raw: dict, model_id: str, profile) -> dict | None:
    """Return a thinkingConfig Google accepts.

    Google: thinkingBudget is deprecated for Gemini 4, and "sending
    thinkingBudget and thinkingLevel together returns a 400 error".
    """
    config = dict(raw)
    budget_keys = [k for k in ("thinkingBudget", "thinking_budget") if k in config]
    has_level = any(k in config for k in ("thinkingLevel", "thinking_level"))
    if budget_keys and (has_level or profile.generation == 4):
        for k in budget_keys:
            config.pop(k)
        if has_level:
            _warn_once(
                f"budget+level:{model_id}",
                "CodeGem dropped thinkingBudget for %s: Google rejects it together "
                "with thinkingLevel; keeping thinkingLevel",
                model_id,
            )
        else:
            _warn_once(
                f"budget:{model_id}",
                "CodeGem dropped thinkingBudget for %s: it is deprecated for Gemini 4; "
                "use thinkingLevel instead",
                model_id,
            )
    if profile.generation == 4 and not has_level and profile.thinking_level:
        config["thinkingLevel"] = profile.thinking_level.upper()
    return config or None


logger = logging.getLogger("superqode.codegem")

# Google's troubleshooting and API errors pages recommend retrying 429 and 5xx.
# 499 means the client closed the request ("No action needed"), so it is final.
_RETRY_STATUS = {429, 500, 502, 503, 504}
# Gemini 4 Argon: Google asks for at least 20 minutes per call, and a
# per-request output cap of 32,768 tokens on non-streaming REST calls.
_ARGON_TIMEOUT = 1200.0
_NON_STREAMING_CAP = 32768
# Long decode guide: "REST streamGenerateContent 64K" default for Gemini 4.
_STREAMING_CAP = 65536
_BLOCK_REASONS = {
    "SAFETY": "Gemini blocked the response for safety reasons",
    "RECITATION": "Gemini stopped because the response closely recited existing content",
    "BLOCKLIST": "Gemini stopped because the response contained a blocklisted term",
    "PROHIBITED_CONTENT": "Gemini blocked the response as prohibited content",
    "SPII": "Gemini stopped because the response may contain sensitive personal information",
    "IMAGE_SAFETY": "Gemini blocked a generated image for safety reasons",
    "LANGUAGE": "Gemini stopped because the response language is unsupported",
}
_KNOWN_PART_KEYS = {"text", "functionCall"}


class GeminiRetryableResponse(Exception):
    """A complete HTTP response that Google documents as worth one retry."""


class _StreamDropped(Exception):
    """A Gemini SSE stream closed before its finish reason."""


async def parse_sse(lines):
    """Yield the JSON payload of each server-sent event from an async line iterator.

    Gemini's streamGenerateContent?alt=sse sends one GenerateContentResponse
    per event as "data: {...}" lines separated by a blank line. Multi-line
    data fields are joined with newlines; comments and other fields are
    ignored.
    """
    data = []
    async for line in lines:
        line = line.rstrip("\r")
        if not line:
            if data:
                yield json.loads("\n".join(data))
                data = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield json.loads("\n".join(data))


async def _response_chunks(response):
    """Stream chunks from SSE, or accept a JSON body (object or array) as-is."""
    if "json" in response.headers.get("content-type", ""):
        payload = json.loads(await response.aread())
        for chunk in payload if isinstance(payload, list) else [payload]:
            yield chunk
        return
    async for chunk in parse_sse(response.aiter_lines()):
        yield chunk


class _PartAssembler:
    """Turn Gemini parts into display blocks, live or after the fact.

    The signed parts themselves are kept verbatim in provider_content; this
    only builds message.content. Adjacent text parts (and adjacent thought
    parts) merge into one block, so streamed chunks form one block per run.
    With live set, text and thinking events are returned as parts arrive.
    """

    def __init__(self, message, *, live: bool):
        self.message = message
        self.live = live
        self.open = None

    def close(self):
        if self.open is None:
            return []
        index, self.open = self.open, None
        block = self.message.content[index]
        if not self.live:
            return []
        if isinstance(block, ThinkingContent):
            return [ThinkingEndEvent(index, block.thinking, self.message)]
        return [TextEndEvent(index, block.text, self.message)]

    def rebuild(self, parts):
        """Reset to a committed prefix after a stream resumes from a checkpoint."""
        live, self.live = self.live, False
        self.message.content.clear()
        self.open = None
        for part in parts:
            self.add(part)
        self.live = live

    def add(self, part):
        events = []
        content = self.message.content
        signature = part.get("thoughtSignature")
        if "functionCall" in part:
            events += self.close()
            call = part["functionCall"]
            arguments = call.get("args", {})
            if not isinstance(arguments, dict):
                raise ValueError("Gemini function arguments must be an object")
            content.append(
                ToolCall(
                    call.get("id") or uuid4().hex,
                    call["name"],
                    arguments,
                    thought_signature=signature,
                )
            )
        elif "text" in part:
            thought = bool(part.get("thought"))
            kind = ThinkingContent if thought else TextContent
            text = part["text"]
            if self.open is not None and isinstance(content[self.open], kind):
                index = self.open
                block = content[index]
                if thought:
                    block.thinking += text
                    block.thinking_signature = signature or block.thinking_signature
                else:
                    block.text += text
                    block.text_signature = signature or block.text_signature
                if text and self.live:
                    events.append(
                        ThinkingDeltaEvent(index, text, self.message)
                        if thought
                        else TextDeltaEvent(index, text, self.message)
                    )
            elif text:
                # An empty text part carries only a signature; it stays in
                # provider_content and needs no display block.
                events += self.close()
                content.append(
                    ThinkingContent(text, thinking_signature=signature)
                    if thought
                    else TextContent(text, text_signature=signature)
                )
                self.open = index = len(content) - 1
                if self.live:
                    events += (
                        [
                            ThinkingStartEvent(index, self.message),
                            ThinkingDeltaEvent(index, text, self.message),
                        ]
                        if thought
                        else [
                            TextStartEvent(index, self.message),
                            TextDeltaEvent(index, text, self.message),
                        ]
                    )
        elif set(part) - {"thoughtSignature", "thought"}:
            # Unknown part kinds stay in provider_content, exactly as signed,
            # and are skipped for display instead of aborting the turn.
            logger.info(
                "CodeGem skipped an unsupported Gemini part: %s",
                ", ".join(sorted(set(part) - {"thoughtSignature", "thought"})),
            )
        return events


def _retry_delay_from(response) -> float | None:
    """Read google.rpc.RetryInfo retryDelay or the Retry-After header, in seconds."""
    try:
        details = (response.json().get("error") or {}).get("details") or []
    except Exception:
        details = []
    for detail in details:
        if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("RetryInfo"):
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(detail.get("retryDelay", "")))
            if match:
                return float(match[1])
    header = response.headers.get("retry-after")
    if header:
        header = header.strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", header):
            return float(header)
        try:
            when = email.utils.parsedate_to_datetime(header)
            return max(0.0, when.timestamp() - time.time())
        except (TypeError, ValueError):
            return None
    return None


def _safety_detail(candidate_or_feedback) -> str:
    ratings = [
        r.get("category", "UNKNOWN").replace("HARM_CATEGORY_", "").lower()
        for r in candidate_or_feedback.get("safetyRatings") or []
        if r.get("blocked") or r.get("probability") in {"HIGH", "MEDIUM"}
    ]
    return f" (categories: {', '.join(ratings)})" if ratings else ""


_TOOL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content", "tool_calls"],
    "additionalProperties": False,
}


def _system(context):
    prompts = [context.system_prompt]
    sections = {}
    for message in context.messages:
        if isinstance(message, SystemMessage):
            prompts.append(message.text)
            for key, value in (message.sections or {}).items():
                if value is None:
                    sections.pop(key, None)
                else:
                    sections[key] = value
    return "\n\n".join(filter(None, [*prompts, *sections.values()]))


def _reconcile_tools(messages):
    """Close interrupted tool batches without replaying an uncertain mutation.

    Results pair with calls by tool_call_id, in any order. A result whose call
    is not pending becomes user text, emitted after the open batch closes so
    it never splits a batch. A call without a result gets an error result.
    """
    pending = {}
    deferred = []

    def interrupted():
        return [
            ToolResultMessage(
                call.id,
                call.name,
                "Tool execution was interrupted; its outcome is unknown. Inspect current files before retrying.",
                is_error=True,
            )
            for call in pending.values()
        ]

    def close():
        yield from interrupted()
        pending.clear()
        yield from deferred
        deferred.clear()

    for message in messages:
        if isinstance(message, (UserMessage, AssistantMessage)) and (pending or deferred):
            yield from close()
        if isinstance(message, AssistantMessage) and message.stop_reason not in {
            "error",
            "aborted",
            "length",
        }:
            pending.update({c.id: c for c in message.tool_calls})
        if isinstance(message, ToolResultMessage):
            if message.tool_call_id not in pending:
                orphan = UserMessage(f"Earlier {message.tool_name} tool result: {message.text}")
                if pending:
                    deferred.append(orphan)
                else:
                    yield orphan
                continue
            pending.pop(message.tool_call_id)
        yield message
    yield from close()


def gemini_contents(messages, model):
    """Keep original part order, IDs and opaque signatures across disk resume."""
    contents = []
    for message in _reconcile_tools(messages):
        if isinstance(message, UserMessage):
            blocks = (
                [TextContent(message.content)]
                if isinstance(message.content, str)
                else message.content
            )
            parts = []
            for block in blocks:
                if isinstance(block, TextContent):
                    parts.append({"text": block.text})
                elif isinstance(block, ImageContent):
                    parts.append({"inlineData": {"mimeType": block.mime_type, "data": block.data}})
            if contents and contents[-1]["role"] == "user":
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": "user", "parts": parts})
        elif isinstance(message, AssistantMessage):
            if message.stop_reason in {"error", "aborted", "length"}:
                continue
            if message.model != model.id and message.tool_calls:
                raise ValueError(
                    "Start a new CodeGem session when switching Gemini models with signed tool history"
                )
            if message.provider_content:
                contents.append(copy.deepcopy(message.provider_content))
            else:
                if message.tool_calls:
                    raise ValueError(
                        "Gemini tool history is missing native signed content; start a new session"
                    )
                if message.text:
                    contents.append({"role": "model", "parts": [{"text": message.text}]})
        elif isinstance(message, ToolResultMessage):
            # Newer Gemini versions return call IDs; only echo an ID the model sent.
            call_id = None
            for prior in reversed(contents):
                for part in prior.get("parts", []):
                    call = part.get("functionCall", {})
                    if call.get("id") == message.tool_call_id:
                        call_id = message.tool_call_id
                        break
                if call_id:
                    break
            response = {
                "name": message.tool_name,
                "response": {
                    "error" if message.is_error else "output": message.text or "(no output)"
                },
            }
            if call_id:
                response["id"] = call_id
            part = {"functionResponse": response}
            images = [
                {"inlineData": {"mimeType": block.mime_type, "data": block.data}}
                for block in message.content
                if isinstance(block, ImageContent)
            ]
            if (
                contents
                and contents[-1]["role"] == "user"
                and any("functionResponse" in p for p in contents[-1]["parts"])
            ):
                contents[-1]["parts"].append(part)
                contents[-1]["parts"].extend(images)
            else:
                contents.append({"role": "user", "parts": [part, *images]})
    return contents


# Ollama's official gemma3 and gemma4 model parameters (ollama.com/library).
_GEMMA_SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 64}


def _gemma_sampling(config) -> dict:
    """Official defaults only when the user set none of the three; otherwise
    send exactly what the user set and let the server default the rest."""
    chosen = {k: config[k] for k in _GEMMA_SAMPLING if k in config}
    return chosen or dict(_GEMMA_SAMPLING)


def _gemma_thinking(config, profile) -> bool | None:
    """One thinking value for every local route.

    An explicit runtime "thinking" wins. Otherwise Gemma 4 sends the
    documented default, off: the official chat template uses
    enable_thinking | default(false) and Ollama's gemma4 renderer defaults
    thinking to false. Models without thinking get nothing.
    """
    if "thinking" in config:
        return bool(config["thinking"])
    return False if profile.thinking else None


def _batch_ordered(messages):
    """Order each tool-result batch by its assistant's call order, keyed by ID.

    _reconcile_tools has already paired every result with a pending call by
    tool_call_id (orphans become user text, missing results are synthesised),
    so results that arrived out of order are only re-sequenced here. Servers
    that pair by ID and servers that pair by position then agree.
    """
    messages = list(messages)
    out = []
    index = 0
    while index < len(messages):
        message = messages[index]
        out.append(message)
        index += 1
        if isinstance(message, AssistantMessage) and message.tool_calls:
            batch = []
            while index < len(messages) and isinstance(messages[index], ToolResultMessage):
                batch.append(messages[index])
                index += 1
            order = {call.id: n for n, call in enumerate(message.tool_calls)}
            out.extend(sorted(batch, key=lambda r: order.get(r.tool_call_id, len(order))))
    return out


def template_messages(wire):
    """What a server hands the Gemma chat template for Chat Completions messages.

    The OpenAI spec puts tool-call arguments on the wire as JSON strings; the
    Gemma 4 template rejects strings and needs objects. vLLM
    (_postprocess_messages) and llama.cpp (func_args_not_string) parse them
    back to objects before rendering. This mirrors that conversion so tests
    can render CodeGem's wire messages through the official template.
    """
    out = copy.deepcopy(wire)
    for entry in out:
        for call in entry.get("tool_calls") or []:
            arguments = call.get("function", {}).get("arguments")
            if isinstance(arguments, str):
                call["function"]["arguments"] = json.loads(arguments)
    return out


def _data_url(block: ImageContent) -> str:
    return f"data:{block.mime_type};base64,{block.data}"


def ollama_messages(
    context,
    *,
    native: bool,
    system_role: bool,
    route: str = "ollama",
    tool_images: bool = True,
):
    """Build local Gemma chat messages for Ollama native or OpenAI-compatible routes.

    route="ollama" emits Ollama /api/chat messages: tool-call arguments are
    JSON objects, calls and results carry id / tool_call_id, and tool images
    sit in the tool message's images field (Ollama's gemma4 renderer renders
    them inside the tool response). route="openai" emits Chat Completions
    messages: arguments stay JSON strings as the OpenAI spec requires (vLLM
    and llama.cpp parse them back to objects before rendering the Gemma
    template), and images are image_url content parts.

    With tool_images, tool-returned images stay inside the tool message (the
    Gemma 4 template renders tool image parts inside the tool response);
    otherwise they follow the batch in one user message.

    Without a system role (Gemma 3), the system text is folded into the first
    user turn. Thinking is kept only on assistant tool-call turns after the
    last user message, matching the Gemma 4 template's thinking gate.
    """
    openai = route == "openai"
    messages = []
    pending_images = []
    system = _system(context)
    if not native and context.tools:
        declarations = [
            {"name": t.name, "description": t.description, "parameters": dict(t.parameters)}
            for t in context.tools
        ]
        system += (
            "\nReturn only a JSON object with content (string) and tool_calls (array). "
            "Each tool call has name and arguments (object). Use an empty array when done. "
            "Do not describe an action instead of calling its tool.\nTools: "
            + json.dumps(declarations)
        )
    history = _batch_ordered(_reconcile_tools(context.messages))
    last_user = max((n for n, m in enumerate(history) if isinstance(m, UserMessage)), default=-1)

    def user_entry(text, images):
        if not images:
            return {"role": "user", "content": text}
        if openai:
            parts = [{"type": "text", "text": text}] if text else []
            parts += [{"type": "image_url", "image_url": {"url": _data_url(b)}} for b in images]
            return {"role": "user", "content": parts}
        return {"role": "user", "content": text, "images": [b.data for b in images]}

    def flush_images():
        nonlocal pending_images
        if pending_images:
            messages.append(user_entry("Images returned by the preceding tools.", pending_images))
            pending_images = []

    for position, message in enumerate(history):
        if not isinstance(message, ToolResultMessage):
            flush_images()
        if isinstance(message, UserMessage):
            blocks = message.content if isinstance(message.content, list) else []
            images = [b for b in blocks if isinstance(b, ImageContent)]
            messages.append(user_entry(message.text, images))
        elif isinstance(message, AssistantMessage):
            if message.stop_reason in {"error", "aborted", "length"}:
                continue
            entry = {"role": "assistant", "content": message.text}
            if native:
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(dict(c.arguments))
                                if openai
                                else dict(c.arguments),
                            },
                        }
                        for c in message.tool_calls
                    ]
                    if message.thinking_text and position > last_user:
                        entry["reasoning_content" if openai else "thinking"] = message.thinking_text
            elif context.tools:
                entry["content"] = json.dumps(
                    {
                        "content": message.text,
                        "tool_calls": [
                            {"name": c.name, "arguments": dict(c.arguments)}
                            for c in message.tool_calls
                        ],
                    }
                )
            messages.append(entry)
        elif isinstance(message, ToolResultMessage):
            images = [b for b in message.content if isinstance(b, ImageContent)]
            if not native:
                pending_images.extend(images)
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "tool_result": message.tool_name,
                                "error": message.is_error,
                                "output": message.text,
                            }
                        ),
                    }
                )
                continue
            entry = {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.text}
            if not openai:
                entry["tool_name"] = message.tool_name
            if images and tool_images:
                if openai:
                    entry["content"] = [{"type": "text", "text": message.text}] + [
                        {"type": "image_url", "image_url": {"url": _data_url(b)}} for b in images
                    ]
                else:
                    entry["images"] = [b.data for b in images]
            else:
                pending_images.extend(images)
            messages.append(entry)
    flush_images()
    if system_role:
        messages.insert(0, {"role": "system", "content": system})
    elif system:
        # Gemma 3 has no system role: prepend the instructions to the first user turn.
        first = next((m for m in messages if m["role"] == "user"), None)
        if first is None:
            messages.insert(0, {"role": "user", "content": system})
        elif isinstance(first["content"], list):
            first["content"].insert(0, {"type": "text", "text": system + "\n\n"})
        else:
            first["content"] = system + "\n\n" + first["content"] if first["content"] else system
    return messages


def gemini_cost(model_id: str, usage: Usage, prompt_tokens: int = 0, on: str | None = None):
    """Estimate cost from Google's published prices (not a billing receipt).

    Thinking tokens bill at the output rate. Cached prompt tokens bill at the
    published context-cache rate; a model without one falls back to the input
    rate. Prompts above the long-context threshold use that tier, and dated
    price changes apply from their effective day.
    """
    from superqode.providers.models import get_model_info, price_schedule

    info = get_model_info("google", model_id)
    if info is None:
        return UsageCost()
    input_price, output_price, cached_price = price_schedule(info, prompt_tokens, on)
    if cached_price is None:
        cached_price = input_price
    cached = min(usage.cache_read, usage.input)
    input_cost = max(0, usage.input - cached) * input_price / 1_000_000
    output_cost = (usage.output + (usage.reasoning or 0)) * output_price / 1_000_000
    cache_cost = cached * cached_price / 1_000_000
    return UsageCost(
        input=input_cost,
        output=output_cost,
        cache_read=cache_cost,
        total=input_cost + output_cost + cache_cost,
    )


# Defaults match providers/registry.py.
_COMPATIBLE_SERVERS = {
    "lmstudio": ("LMSTUDIO_HOST", "http://localhost:1234/v1"),
    "llamacpp": ("LLAMACPP_HOST", "http://localhost:8080/v1"),
    "vllm": ("VLLM_HOST", "http://localhost:8000/v1"),
}


def compatible_base_url(provider: str, config) -> str:
    env_name, default = _COMPATIBLE_SERVERS[provider]
    base = str(config.get("base_url") or os.environ.get(env_name) or default).rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


async def discover_server_context(provider: str, config, model_id: str, *, transport=None):
    """Read the context size a running server actually allocated, if it says.

    vLLM: GET /v1/models, ModelCard.max_model_len (set by --max-model-len).
    llama.cpp: GET /props, default_generation_settings.n_ctx.
    Returns None when the server is unreachable or does not report it.
    """
    if provider not in {"vllm", "llamacpp"}:
        return None
    base = compatible_base_url(provider, config)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=5.0) as client:
            if provider == "vllm":
                response = await client.get(f"{base}/models")
                response.raise_for_status()
                cards = response.json().get("data") or []
                card = next((c for c in cards if c.get("id") == model_id), None)
                if card is None and len(cards) == 1:
                    card = cards[0]
                value = (card or {}).get("max_model_len")
            else:
                response = await client.get(f"{base[: -len('/v1')]}/props")
                response.raise_for_status()
                value = (response.json().get("default_generation_settings") or {}).get("n_ctx")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return int(value) if isinstance(value, int) and value > 0 else None


class CodeGemStream:
    def __init__(self, config=None, *, transport=None):
        self.config = dict(config or {})
        self.transport = transport
        self._capabilities = {}
        self._json_tool_compat = set()

    async def _sleep(self, seconds, signal):
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            if is_aborted(signal):
                raise asyncio.CancelledError("CodeGem request aborted")
            await asyncio.sleep(min(0.05, remaining))

    async def _send(self, client, method, url, *, signal=None, stream=False, **kwargs):
        if stream:
            coro = client.send(client.build_request(method, url, **kwargs), stream=True)
        else:
            coro = client.request(method, url, **kwargs)
        task = asyncio.create_task(coro)
        try:
            while not task.done():
                if is_aborted(signal):
                    raise asyncio.CancelledError("CodeGem request aborted")
                await asyncio.wait((task,), timeout=0.05)
            response = await task
            if stream and response.is_error:
                # Read the error body so retry hints and messages are available.
                await response.aread()
                await response.aclose()
            response.raise_for_status()
            return response
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _request(self, client, method, url, *, signal=None, retry=False, **kwargs):
        """Send once, or with bounded jittered exponential backoff when retry is set.

        Retries cover HTTP 429 and 5xx plus transient network errors. A
        server-supplied RetryInfo retryDelay or Retry-After wins over backoff,
        unless it exceeds retry_max_delay, in which case the error is final.
        """
        attempts = max(1, int(self.config.get("max_attempts", 4))) if retry else 1
        initial = float(self.config.get("retry_initial_delay", 1.0))
        ceiling = float(self.config.get("retry_max_delay", 60.0))
        for attempt in range(1, attempts + 1):
            try:
                response = await self._send(client, method, url, signal=signal, **kwargs)
                if attempt > 1:
                    logger.info("CodeGem request succeeded on attempt %d/%d", attempt, attempts)
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in _RETRY_STATUS or attempt == attempts:
                    exc.codegem_attempts = attempt
                    raise
                delay = _retry_delay_from(exc.response)
                if delay is not None and delay > ceiling:
                    exc.codegem_attempts = attempt
                    raise
                reason = f"HTTP {status}"
            except httpx.TransportError as exc:
                if attempt == attempts:
                    exc.codegem_attempts = attempt
                    raise
                delay, reason = None, type(exc).__name__
            if delay is None:
                delay = min(ceiling, initial * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
            logger.warning(
                "CodeGem provider %s; retrying in %.1fs (attempt %d/%d)",
                reason,
                delay,
                attempt + 1,
                attempts,
            )
            await self._sleep(delay, signal)
        raise AssertionError("unreachable")

    def _tool_images(self, profile) -> bool:
        return bool(
            self.config.get(
                "tool_images_in_tool_message", profile.family == "gemma" and profile.generation == 4
            )
        )

    async def __call__(self, model, context, options):
        message = AssistantMessage(model=model.id, provider=model.provider, api=model.api)
        yield AssistantStartEvent(message)
        try:
            from superqode.providers.models import retired_google_model

            replacement = retired_google_model(model.id) if model.provider == "google" else None
            if replacement:
                model = dataclasses.replace(model, id=replacement)
            profile = resolve_profile(model.id, model.provider)
            if is_aborted(options.signal):
                raise asyncio.CancelledError("CodeGem request aborted")
            live = set()  # Content indices already streamed to the caller.
            default_timeout = (
                _ARGON_TIMEOUT if profile.family == "gemini" and profile.generation == 4 else 180
            )
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=float(self.config.get("timeout", default_timeout)),
            ) as client:
                if profile.family == "gemini" or model.provider in {"google", "gemini"}:
                    async for event in self._gemini(
                        client, model, context, options, profile, message
                    ):
                        if isinstance(event, (TextEndEvent, ThinkingEndEvent)):
                            live.add(event.content_index)
                        yield event
                elif model.provider == "ollama":
                    await self._ollama(client, model, context, options, profile, message)
                else:
                    await self._compatible(client, model, context, options, profile, message)
            if message.stop_reason == "stop" and not message.text:
                raise ValueError("CodeGem model returned no answer or tool call")
            if len(message.tool_calls) > int(self.config.get("max_tool_calls_per_turn", 16)):
                raise ValueError("CodeGem model exceeded the tool-call batch limit")
            call_ids = [call.id for call in message.tool_calls]
            if len(call_ids) != len(set(call_ids)):
                raise ValueError("CodeGem model returned duplicate tool call IDs")
            for index, block in enumerate(message.content):
                if index in live:
                    continue
                if isinstance(block, TextContent) and block.text:
                    yield TextStartEvent(index, message)
                    yield TextDeltaEvent(index, block.text, message)
                    yield TextEndEvent(index, block.text, message)
                elif isinstance(block, ToolCall):
                    yield ToolCallStartEvent(index, message)
                    yield ToolCallEndEvent(index, block, message)
                elif isinstance(block, ThinkingContent) and block.thinking:
                    yield ThinkingStartEvent(index, message)
                    yield ThinkingDeltaEvent(index, block.thinking, message)
                    yield ThinkingEndEvent(index, block.thinking, message)
            yield AssistantDoneEvent(message.stop_reason, message)
        except (Exception, asyncio.CancelledError) as exc:
            message.stop_reason = (
                "aborted"
                if is_aborted(options.signal) or isinstance(exc, asyncio.CancelledError)
                else "error"
            )
            # HTTP errors never expose request URLs/headers containing credentials.
            message.error_message = (
                f"CodeGem provider HTTP {exc.response.status_code}: {exc.response.text[:800]}"
                if isinstance(exc, httpx.HTTPStatusError)
                else str(exc) or type(exc).__name__
            )
            attempts = getattr(exc, "codegem_attempts", None)
            if attempts and attempts > 1:
                message.error_message += f" (after {attempts} attempts)"
            yield AssistantErrorEvent(message.stop_reason, message)

    async def _gemini(self, client, model, context, options, profile, message):
        """Gemini API turn (Gemini models and Gemma 4 on the google provider).

        An async generator: with streaming on it yields live text and
        thinking events; the final turn keeps every part exactly as received.
        """
        key = (
            options.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        if not key:
            from superqode.providers.credentials import provider_api_key
            from superqode.providers.registry import PROVIDERS

            key = provider_api_key(PROVIDERS["google"])
        if not key:
            raise ValueError("Set GEMINI_API_KEY or GOOGLE_API_KEY to run CodeGem with Gemini")
        gemma = profile.family == "gemma"
        gemini4 = profile.family == "gemini" and profile.generation == 4
        stream = bool(self.config.get("stream", True))
        generation = {}
        if gemma:
            # Google documents no Gemma output limit on the Gemini API, so
            # only an explicit max_output_tokens is sent.
            if "max_output_tokens" in self.config:
                generation["maxOutputTokens"] = int(self.config["max_output_tokens"])
        else:
            # Gemini 4: "The default is 64K for streaming and SDK calls, and
            # 32K for non-streaming REST calls" (long decode guide). Other
            # models keep the 32,768 default.
            cap = _STREAMING_CAP if stream and gemini4 else _NON_STREAMING_CAP
            generation["maxOutputTokens"] = int(self.config.get("max_output_tokens", cap))
        if gemini4:
            ignored = [k for k in _SAMPLING_KEYS if k in self.config]
            if ignored:
                _warn_once(
                    f"sampling:{model.id}",
                    "CodeGem ignores %s for %s: Google says sampling parameters are "
                    "ignored for Gemini 4",
                    ", ".join(ignored),
                    model.id,
                )
        elif gemma:
            names = {"temperature": "temperature", "top_p": "topP", "top_k": "topK"}
            for name, value in _gemma_sampling(self.config).items():
                generation[names[name]] = value
        else:
            generation["temperature"] = self.config.get("temperature", profile.temperature)
        raw_thinking = dict(self.config.get("thinking_config") or {})
        if gemma and not raw_thinking and "thinking" in self.config:
            # Gemma on the Gemini API: "high" for enabled, "minimal" for disabled.
            raw_thinking = {"thinkingLevel": "HIGH" if self.config["thinking"] else "MINIMAL"}
        thinking = _thinking_config(raw_thinking, model.id, profile)
        if thinking:
            generation["thinkingConfig"] = thinking
        # Otherwise no thinking level is sent: Google's per-model default applies.
        body = {
            "contents": gemini_contents(context.messages, model),
            "systemInstruction": {"parts": [{"text": _system(context)}]},
            "generationConfig": generation,
        }
        if context.tools:
            # parametersJsonSchema accepts the existing JSON Schema verbatim.
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parametersJsonSchema": dict(t.parameters),
                        }
                        for t in context.tools
                    ]
                }
            ]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        base = self.config.get(
            "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        url = (
            f"{base}/models/{model.id}:streamGenerateContent?alt=sse"
            if stream
            else f"{base}/models/{model.id}:generateContent"
        )
        headers = {"x-goog-api-key": key}
        # One extra request for MALFORMED_FUNCTION_CALL or an empty candidate.
        # A retry after streamed output restarts the turn; the live view may
        # then show the first attempt's text before the retried answer.
        for invalid_attempt in (1, 2):
            assembler = _PartAssembler(message, live=stream)
            message.content.clear()
            done = None
            try:
                async for item in self._gemini_hops(
                    client, url, body, headers, options.signal, profile, stream
                ):
                    if item[0] == "parts":
                        for part in item[1]:
                            for event in assembler.add(part):
                                yield event
                    elif item[0] == "reset":
                        assembler.rebuild(item[1])
                    else:
                        done = item
                break
            except GeminiRetryableResponse as exc:
                for event in assembler.close():
                    yield event
                if invalid_attempt == 2:
                    raise ValueError(f"{exc} (after one retry)") from None
                logger.warning("CodeGem %s; retrying once", exc)
        _, parts, usage, reason = done
        if not stream:
            for part in parts:
                assembler.add(part)
        for event in assembler.close():
            yield event
        content = {"role": "model", "parts": parts}
        message.provider_content = copy.deepcopy(content)
        message.usage = Usage(
            input=usage["input"],
            output=usage["output"],
            cache_read=usage["cache_read"],
            reasoning=usage["reasoning"],
            total_tokens=usage["total"],
        )
        message.usage.cost = gemini_cost(model.id, message.usage, usage.get("first_prompt") or 0)
        message.stop_reason = (
            "length" if reason == "MAX_TOKENS" else "toolUse" if message.tool_calls else "stop"
        )

    async def _gemini_hops(self, client, url, body, headers, signal, profile, stream=False):
        """Run (stream)GenerateContent, following long-decode continuation tokens.

        Per Google's long decode guide, each hop resends the same request plus
        only the latest continuationToken while finishReason is CONTINUATION,
        and the parts of all hops form one model turn. On MAX_TOKENS with a
        token, the request resumes with a higher maxOutputTokens, up to
        max_output_tokens_ceiling. Usage fields are summed across hops for
        cost; the context size uses the first hop's prompt.

        An async generator: yields ("parts", new_parts) as streamed parts
        arrive, ("reset", committed_parts) when a dropped stream resumes from
        a checkpoint, and finally ("done", parts, usage, finish_reason).
        """
        parts = []
        totals = {"input": 0, "output": 0, "cache_read": 0, "reasoning": None, "total": 0}
        first_prompt = None
        hops = 0
        token = None
        request = copy.deepcopy(body)
        generation = request["generationConfig"]
        ceiling = int(
            self.config.get(
                "max_output_tokens_ceiling",
                131072
                if profile.family == "gemini" and profile.generation == 4
                else generation.get("maxOutputTokens", 0),
            )
        )
        max_hops = int(self.config.get("max_continuation_hops", 64))
        for _hop in range(max_hops):
            if token:
                request["continuationToken"] = token
            else:
                request.pop("continuationToken", None)
            if stream:
                data = None
                async for item in self._stream_hop(client, url, request, headers, signal, parts):
                    if item[0] == "hop":
                        data = item[1]
                    else:
                        yield item
            else:
                response = await self._request(
                    client, "POST", url, signal=signal, retry=True, json=request, headers=headers
                )
                data = response.json()
            usage = data.get("usageMetadata", {})
            if first_prompt is None:
                first_prompt = usage.get("promptTokenCount", 0)
            totals["input"] += usage.get("promptTokenCount", 0)
            totals["output"] += usage.get("candidatesTokenCount", 0)
            totals["cache_read"] += usage.get("cachedContentTokenCount", 0)
            if usage.get("thoughtsTokenCount") is not None:
                totals["reasoning"] = (totals["reasoning"] or 0) + usage["thoughtsTokenCount"]
            candidates = data.get("candidates") or []
            if not candidates:
                feedback = data.get("promptFeedback") or {}
                block = feedback.get("blockReason")
                if block:
                    raise ValueError(
                        f"Gemini blocked the prompt ({block}){_safety_detail(feedback)}. "
                        "Rephrase the request or remove the flagged content."
                    )
                if parts:
                    raise ValueError("Gemini returned no candidate during long decode")
                raise GeminiRetryableResponse("Gemini returned no candidate")
            candidate = candidates[0]
            reason = candidate.get("finishReason")
            hop_parts = (candidate.get("content") or {}).get("parts") or []
            parts.extend(copy.deepcopy(hop_parts))
            token = candidate.get("continuationToken")
            if reason == "CONTINUATION" and token:
                hops += 1
                continue
            if (
                reason == "MAX_TOKENS"
                and token
                and generation.get("maxOutputTokens")
                and generation["maxOutputTokens"] < ceiling
            ):
                raised = min(ceiling, generation["maxOutputTokens"] * 2)
                logger.info(
                    "Gemini reached maxOutputTokens=%d; resuming with %d",
                    generation["maxOutputTokens"],
                    raised,
                )
                generation["maxOutputTokens"] = raised
                hops += 1
                continue
            if reason == "MALFORMED_FUNCTION_CALL":
                raise GeminiRetryableResponse("Gemini returned a malformed function call")
            if reason in _BLOCK_REASONS:
                raise ValueError(f"{_BLOCK_REASONS[reason]} ({reason}){_safety_detail(candidate)}.")
            if reason not in {"STOP", "MAX_TOKENS"}:
                raise ValueError(f"Gemini stopped without a complete response: {reason}")
            if reason == "STOP" and not any(p.get("functionCall") or p.get("text") for p in parts):
                raise GeminiRetryableResponse("Gemini returned an empty candidate")
            hops += 1
            if hops == 1:
                totals["total"] = usage.get("totalTokenCount", 0)
            else:
                # Context size: the first hop's prompt plus all generated tokens.
                totals["total"] = first_prompt + totals["output"] + (totals["reasoning"] or 0)
            totals["first_prompt"] = first_prompt
            yield ("done", parts, totals, reason)
            return
        raise ValueError(f"Gemini long decode exceeded {max_hops} continuation hops")

    async def _stream_hop(self, client, url, request, headers, signal, earlier):
        """One streamGenerateContent hop, folded into a generateContent shape.

        Google's long decode guide: "Keep new chunks in a pending list. When a
        chunk has a continuation_token, move the pending chunks to your
        committed output and save the token. If the stream drops, discard the
        pending chunks and resume from the last token." Usage is cumulative
        within a stream, so the last value of each stream is kept and the
        values are added across streams. Retries happen only before the first
        chunk; a drop after output but before any checkpoint is an error.

        Yields ("parts", parts), ("reset", earlier + committed) and finally
        ("hop", response) where response has the assembled candidate.
        """
        committed, pending = [], []
        checkpoint = None
        usage_sum = {}
        usage_at_checkpoint = {}
        final = None
        feedback = None
        body = request
        attempts = max(1, int(self.config.get("max_attempts", 4)))
        quiet_drops = 0
        resumes = 0

        def add_usage(usage):
            for k, v in usage.items():
                if isinstance(v, int):
                    usage_sum[k] = usage_sum.get(k, 0) + v

        while True:
            received = False
            last_usage = {}
            # Opening the stream uses the normal retry policy (429, 5xx, network).
            response = await self._request(
                client,
                "POST",
                url,
                signal=signal,
                retry=True,
                json=body,
                headers=headers,
                stream=True,
            )
            try:
                try:
                    async for chunk in _response_chunks(response):
                        received = True
                        if is_aborted(signal):
                            raise asyncio.CancelledError("CodeGem request aborted")
                        if chunk.get("usageMetadata"):
                            last_usage = chunk["usageMetadata"]
                        if chunk.get("promptFeedback"):
                            feedback = chunk["promptFeedback"]
                        candidates = chunk.get("candidates") or []
                        if not candidates:
                            continue
                        candidate = candidates[0]
                        new = copy.deepcopy((candidate.get("content") or {}).get("parts") or [])
                        pending.extend(new)
                        if new:
                            yield ("parts", new)
                        if candidate.get("finishReason"):
                            final = candidate
                        if candidate.get("continuationToken") and not candidate.get("finishReason"):
                            committed.extend(pending)
                            pending = []
                            checkpoint = candidate["continuationToken"]
                            usage_at_checkpoint = dict(last_usage)
                finally:
                    await response.aclose()
                if final is None and (not received or pending or committed or checkpoint):
                    raise _StreamDropped("Gemini stream ended without a finish reason")
            except (httpx.TransportError, _StreamDropped) as exc:
                if checkpoint and resumes < int(self.config.get("max_stream_resumes", 8)):
                    resumes += 1
                    add_usage(usage_at_checkpoint)
                    pending = []
                    usage_at_checkpoint = {}
                    logger.warning("CodeGem stream dropped (%s); resuming from checkpoint", exc)
                    yield ("reset", [*earlier, *committed])
                    body = {**request, "continuationToken": checkpoint}
                    checkpoint = None
                    continue
                if not received and not committed and quiet_drops + 1 < attempts:
                    quiet_drops += 1
                    delay = min(
                        float(self.config.get("retry_max_delay", 60.0)),
                        float(self.config.get("retry_initial_delay", 1.0)) * 2 ** (quiet_drops - 1),
                    )
                    logger.warning(
                        "CodeGem stream dropped before the first chunk (%s); retrying in %.1fs",
                        exc,
                        delay,
                    )
                    await self._sleep(delay, signal)
                    continue
                if received or committed:
                    raise ValueError(
                        "Gemini stream dropped after output began and before a checkpoint; "
                        "the partial turn was discarded"
                    ) from exc
                raise
            add_usage(last_usage)
            candidate = dict(final or {})
            candidate["content"] = {"role": "model", "parts": [*committed, *pending]}
            hop = {"usageMetadata": usage_sum, "candidates": [candidate] if final else []}
            if feedback:
                hop["promptFeedback"] = feedback
            yield ("hop", hop)
            return

    async def _ollama(self, client, model, context, options, profile, message):
        base = self.config.get(
            "ollama_base_url", os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        ).rstrip("/")
        mode = self.config.get("tool_mode", "auto")
        if mode not in {"auto", "native", "json"}:
            raise ValueError("CodeGem tool_mode must be auto, native, or json")
        capabilities = None
        if mode == "auto":
            if model.id not in self._capabilities:
                response = await self._request(
                    client,
                    "POST",
                    f"{base}/api/show",
                    signal=options.signal,
                    json={"model": model.id},
                )
                self._capabilities[model.id] = response.json().get("capabilities", [])
            capabilities = self._capabilities[model.id]
        native = mode == "native" or (mode == "auto" and "tools" in capabilities)
        has_images = any(
            isinstance(block, ImageContent)
            for m in context.messages
            for block in (m.content if isinstance(getattr(m, "content", None), list) else [])
        )
        if has_images and capabilities is not None and "vision" not in capabilities:
            raise ValueError("This local Gemma server does not advertise vision support")
        body = {
            "model": model.id,
            "stream": False,
            "messages": ollama_messages(
                context,
                native=native,
                system_role=self.config.get("system_role", profile.system_role),
                tool_images=self._tool_images(profile),
            ),
            "options": {
                **_gemma_sampling(self.config),
                "num_predict": int(self.config.get("max_output_tokens", 8192)),
                **({"num_ctx": model.context_window} if model.context_window else {}),
            },
        }
        think = _gemma_thinking(self.config, profile)
        if think is not None and (
            "thinking" in self.config or capabilities is None or "thinking" in capabilities
        ):
            body["think"] = think
        if native and context.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": dict(t.parameters),
                    },
                }
                for t in context.tools
            ]
        elif context.tools:
            body["format"] = "json"
        response = await self._request(
            client, "POST", f"{base}/api/chat", signal=options.signal, json=body
        )
        data = response.json()
        if data.get("error"):
            raise ValueError(data["error"])
        if not data.get("done"):
            raise ValueError("Ollama response is incomplete; tool calls will not execute")
        result = data.get("message", {})
        text = result.get("content") or ""
        calls = result.get("tool_calls") or []
        length = data.get("done_reason") == "length"
        if not native and context.tools and not length:
            result = json.loads(text)
            if not isinstance(result, dict) or set(result) - {"content", "tool_calls"}:
                raise ValueError("Gemma JSON response must contain content and tool_calls")
            text = result.get("content", "")
            calls = [{"function": call} for call in result.get("tool_calls", [])]
        if not isinstance(text, str):
            raise ValueError("Gemma response content must be a string")
        if text:
            message.content.append(TextContent(text))
        if native and result.get("thinking"):
            message.content.append(ThinkingContent(result["thinking"]))
        for raw in calls:
            call = raw["function"]
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Gemma function arguments must be an object")
            message.content.append(ToolCall(raw.get("id") or uuid4().hex, call["name"], arguments))
        message.usage = Usage(
            input=data.get("prompt_eval_count", 0), output=data.get("eval_count", 0)
        )
        message.usage.total_tokens = message.usage.input + message.usage.output
        message.stop_reason = "length" if length else "toolUse" if message.tool_calls else "stop"

    async def _compatible(self, client, model, context, options, profile, message):
        """Gemma over LM Studio, llama.cpp or vLLM, retaining IDs and tool thinking."""
        base = compatible_base_url(model.provider, self.config)
        mode = self.config.get("tool_mode", "auto")
        if mode not in {"auto", "native", "json"}:
            raise ValueError("CodeGem tool_mode must be auto, native, or json")
        fallback_key = (model.provider, base, model.id)
        native = mode != "json" and not (mode == "auto" and fallback_key in self._json_tool_compat)
        # Arguments stay JSON strings on the Chat Completions wire (OpenAI
        # spec); vLLM and llama.cpp convert them to objects for the template.
        wire = ollama_messages(
            context,
            native=native,
            system_role=self.config.get("system_role", profile.system_role),
            route="openai",
            tool_images=self._tool_images(profile),
        )
        body = {
            "model": model.id,
            "messages": wire,
            "stream": False,
            **_gemma_sampling(self.config),
            "max_tokens": int(self.config.get("max_output_tokens", 8192)),
        }
        if native and context.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": dict(t.parameters),
                    },
                }
                for t in context.tools
            ]
            body["tool_choice"] = "auto"
        elif context.tools:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "codegem_tool_response",
                    "strict": True,
                    "schema": _TOOL_RESPONSE_SCHEMA,
                },
            }
        think = _gemma_thinking(self.config, profile)
        if think is not None:
            body["chat_template_kwargs"] = {"enable_thinking": think}
        try:
            response = await self._request(
                client, "POST", f"{base}/chat/completions", json=body, signal=options.signal
            )
        except httpx.HTTPStatusError as exc:
            # Some compatible servers can answer Gemma prompts but fail while
            # rendering the native tool template. Fall back only for that
            # explicit template error, then remember the endpoint/model pair.
            if (
                mode == "auto"
                and native
                and model.provider in {"lmstudio", "llamacpp", "vllm"}
                and "error rendering prompt with jinja template" in exc.response.text.lower()
            ):
                self._json_tool_compat.add(fallback_key)
                await self._compatible(client, model, context, options, profile, message)
                return
            raise
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        finish = choice.get("finish_reason")
        if finish not in {"stop", "tool_calls", "length"}:
            raise ValueError(f"Local Gemma response is incomplete or blocked: {finish}")
        raw = choice.get("message") or {}
        text = raw.get("content") or ""
        tool_calls = raw.get("tool_calls") or []
        if not native and context.tools and finish != "length":
            parsed = json.loads(text)
            if not isinstance(parsed, dict) or set(parsed) - {"content", "tool_calls"}:
                raise ValueError("Gemma JSON response must contain content and tool_calls")
            text = parsed.get("content", "")
            tool_calls = [{"function": c} for c in parsed.get("tool_calls", [])]
        if not isinstance(text, str):
            raise ValueError("Gemma response content must be a string")
        if text:
            message.content.append(TextContent(text))
        thinking = raw.get("reasoning_content") or raw.get("reasoning")
        if thinking:
            message.content.append(ThinkingContent(thinking))
        for raw_call in tool_calls:
            call = raw_call["function"]
            args = call.get("arguments", {})
            args = json.loads(args) if isinstance(args, str) else args
            if not isinstance(args, dict):
                raise ValueError("Gemma function arguments must be an object")
            message.content.append(ToolCall(raw_call.get("id") or uuid4().hex, call["name"], args))
        usage = data.get("usage", {})
        message.usage = Usage(
            input=usage.get("prompt_tokens", 0),
            output=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
        message.stop_reason = (
            "length" if finish == "length" else "toolUse" if message.tool_calls else "stop"
        )
