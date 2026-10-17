"""Google-native signed content and Ollama-native Gemma tool conversations.

Gemini responses are buffered per model turn to retain exact signed Content.
Function arguments execute only after a successful, complete model response.
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
    """Close interrupted tool batches without replaying an uncertain mutation."""
    pending = {}

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

    for message in messages:
        if isinstance(message, (UserMessage, AssistantMessage)) and pending:
            yield from interrupted()
            pending.clear()
        if isinstance(message, AssistantMessage) and message.stop_reason not in {
            "error",
            "aborted",
            "length",
        }:
            pending.update({c.id: c for c in message.tool_calls})
        if isinstance(message, ToolResultMessage):
            if message.tool_call_id not in pending:
                yield UserMessage(f"Earlier {message.tool_name} tool result: {message.text}")
                continue
            pending.pop(message.tool_call_id)
        yield message
    yield from interrupted()


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


def ollama_messages(context, *, native: bool, system_role: bool):
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
    messages.append({"role": "system" if system_role else "user", "content": system})
    for message in _reconcile_tools(context.messages):
        if not isinstance(message, ToolResultMessage) and pending_images:
            messages.append(
                {
                    "role": "user",
                    "content": "Images returned by the preceding tools.",
                    "images": pending_images,
                }
            )
            pending_images = []
        if isinstance(message, UserMessage):
            blocks = message.content if isinstance(message.content, list) else []
            entry = {"role": "user", "content": message.text}
            images = [b.data for b in blocks if isinstance(b, ImageContent)]
            if images:
                entry["images"] = images
            messages.append(entry)
        elif isinstance(message, AssistantMessage):
            if message.stop_reason in {"error", "aborted", "length"}:
                continue
            calls = [
                {"function": {"name": c.name, "arguments": dict(c.arguments)}}
                for c in message.tool_calls
            ]
            entry = {"role": "assistant", "content": message.text}
            if native:
                if calls:
                    entry["tool_calls"] = calls
                if message.thinking_text and calls:
                    entry["thinking"] = message.thinking_text
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
            pending_images.extend(b.data for b in message.content if isinstance(b, ImageContent))
            messages.append(
                {
                    "role": "tool" if native else "user",
                    "content": message.text
                    if native
                    else json.dumps(
                        {
                            "tool_result": message.tool_name,
                            "error": message.is_error,
                            "output": message.text,
                        }
                    ),
                    **({"tool_name": message.tool_name} if native else {}),
                }
            )
    if pending_images:
        messages.append(
            {
                "role": "user",
                "content": "Images returned by the preceding tools.",
                "images": pending_images,
            }
        )
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

    async def _send(self, client, method, url, *, signal=None, **kwargs):
        task = asyncio.create_task(client.request(method, url, **kwargs))
        try:
            while not task.done():
                if is_aborted(signal):
                    raise asyncio.CancelledError("CodeGem request aborted")
                await asyncio.wait((task,), timeout=0.05)
            response = await task
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
            default_timeout = (
                _ARGON_TIMEOUT if profile.family == "gemini" and profile.generation == 4 else 180
            )
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=float(self.config.get("timeout", default_timeout)),
            ) as client:
                if profile.family == "gemini":
                    await self._gemini(client, model, context, options, profile, message)
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
        key = (
            options.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        if not key:
            from superqode.providers.credentials import provider_api_key
            from superqode.providers.registry import PROVIDERS

            key = provider_api_key(PROVIDERS["google"])
        if not key:
            raise ValueError("Set GEMINI_API_KEY or GOOGLE_API_KEY to run CodeGem with Gemini")
        generation = {
            # Non-streaming REST is capped at 32,768 per request; long decode and
            # MAX_TOKENS resume carry Gemini 4 output beyond it.
            "maxOutputTokens": int(self.config.get("max_output_tokens", _NON_STREAMING_CAP)),
        }
        if profile.generation == 4:
            ignored = [k for k in _SAMPLING_KEYS if k in self.config]
            if ignored:
                _warn_once(
                    f"sampling:{model.id}",
                    "CodeGem ignores %s for %s: Google says sampling parameters are "
                    "ignored for Gemini 4",
                    ", ".join(ignored),
                    model.id,
                )
        else:
            generation["temperature"] = self.config.get("temperature", profile.temperature)
        thinking = _thinking_config(self.config.get("thinking_config") or {}, model.id, profile)
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
        url = f"{base}/models/{model.id}:generateContent"
        headers = {"x-goog-api-key": key}
        # One extra request for MALFORMED_FUNCTION_CALL or an empty candidate.
        for invalid_attempt in (1, 2):
            try:
                parts, usage, reason = await self._gemini_hops(
                    client, url, body, headers, options.signal, profile
                )
                break
            except GeminiRetryableResponse as exc:
                if invalid_attempt == 2:
                    raise ValueError(f"{exc} (after one retry)") from None
                logger.warning("CodeGem %s; retrying once", exc)
        content = {"role": "model", "parts": parts}
        message.provider_content = copy.deepcopy(content)
        for part in parts:
            signature = part.get("thoughtSignature")
            if "functionCall" in part:
                call = part["functionCall"]
                arguments = call.get("args", {})
                if not isinstance(arguments, dict):
                    raise ValueError("Gemini function arguments must be an object")
                message.content.append(
                    ToolCall(
                        call.get("id") or uuid4().hex,
                        call["name"],
                        arguments,
                        thought_signature=signature,
                    )
                )
            elif "text" in part:
                message.content.append(
                    ThinkingContent(part["text"], thinking_signature=signature)
                    if part.get("thought")
                    else TextContent(part["text"], text_signature=signature)
                )
            elif not set(part) - {"thoughtSignature"}:
                continue  # A bare signature part is replayed verbatim from provider_content.
            else:
                # Unknown part kinds stay in provider_content, exactly as signed,
                # and are skipped for display instead of aborting the turn.
                logger.info(
                    "CodeGem skipped an unsupported Gemini part: %s",
                    ", ".join(sorted(set(part) - {"thoughtSignature", "thought"})),
                )
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

    async def _gemini_hops(self, client, url, body, headers, signal, profile):
        """Run generateContent, following Gemini long-decode continuation tokens.

        Per Google's long decode guide, each hop resends the same request plus
        only the latest continuationToken while finishReason is CONTINUATION,
        and the parts of all hops form one model turn. On MAX_TOKENS with a
        token, the request resumes with a higher maxOutputTokens, up to
        max_output_tokens_ceiling. Usage fields are summed across hops for
        cost; the context size uses the first hop's prompt.
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
                131072 if profile.generation == 4 else generation["maxOutputTokens"],
            )
        )
        max_hops = int(self.config.get("max_continuation_hops", 64))
        for _hop in range(max_hops):
            if token:
                request["continuationToken"] = token
            else:
                request.pop("continuationToken", None)
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
            if reason == "MAX_TOKENS" and token and generation["maxOutputTokens"] < ceiling:
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
            return parts, totals, reason
        raise ValueError(f"Gemini long decode exceeded {max_hops} continuation hops")

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
            ),
            "options": {
                "temperature": self.config.get("temperature", profile.temperature),
                "top_p": self.config.get("top_p", 0.95),
                "top_k": self.config.get("top_k", 64),
                "num_predict": int(self.config.get("max_output_tokens", 8192)),
                **({"num_ctx": model.context_window} if model.context_window else {}),
            },
        }
        if "thinking" in self.config:
            body["think"] = bool(self.config["thinking"])
        elif profile.thinking and (capabilities is None or "thinking" in capabilities):
            body["think"] = True
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
        """Gemma over LM Studio or llama.cpp, retaining IDs and tool thinking."""
        default = (
            "http://localhost:1234/v1"
            if model.provider == "lmstudio"
            else "http://localhost:8080/v1"
        )
        env_name = "LMSTUDIO_HOST" if model.provider == "lmstudio" else "LLAMACPP_HOST"
        base = str(self.config.get("base_url") or os.environ.get(env_name) or default).rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        mode = self.config.get("tool_mode", "auto")
        if mode not in {"auto", "native", "json"}:
            raise ValueError("CodeGem tool_mode must be auto, native, or json")
        fallback_key = (model.provider, base, model.id)
        native = mode != "json" and not (mode == "auto" and fallback_key in self._json_tool_compat)
        wire = ollama_messages(context, native=native, system_role=profile.system_role)
        calls = [
            c
            for m in _reconcile_tools(context.messages)
            if isinstance(m, AssistantMessage)
            and m.stop_reason not in {"error", "aborted", "length"}
            for c in m.tool_calls
        ]
        cursor = 0
        result_ids = iter(
            m.tool_call_id
            for m in _reconcile_tools(context.messages)
            if isinstance(m, ToolResultMessage)
        )
        for entry in wire:
            for raw in entry.get("tool_calls", []):
                call = calls[cursor]
                cursor += 1
                raw.update({"id": call.id, "type": "function"})
                raw["function"]["arguments"] = json.dumps(raw["function"]["arguments"])
            if entry["role"] == "tool":
                entry["tool_call_id"] = next(result_ids)
                entry.pop("tool_name", None)
            if "thinking" in entry:
                entry["reasoning_content"] = entry.pop("thinking")
            if entry.get("images"):
                raise ValueError(
                    "CodeGem OpenAI-compatible image transport is not enabled; use the Gemini or Ollama image route"
                )
        body = {
            "model": model.id,
            "messages": wire,
            "stream": False,
            "temperature": self.config.get("temperature", profile.temperature),
            "top_p": self.config.get("top_p", 0.95),
            "top_k": self.config.get("top_k", 64),
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
        if "thinking" in self.config:
            body["chat_template_kwargs"] = {"enable_thinking": bool(self.config["thinking"])}
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
                and model.provider in {"lmstudio", "llamacpp"}
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
