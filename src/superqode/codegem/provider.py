"""Google-native signed content and Ollama-native Gemma tool conversations.

Gemini responses are buffered per model turn to retain exact signed Content.
Function arguments execute only after a successful, complete model response.
No parsing of prose or raw Python as a tool call is allowed.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
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


class CodeGemStream:
    def __init__(self, config=None, *, transport=None):
        self.config = dict(config or {})
        self.transport = transport
        self._capabilities = {}
        self._json_tool_compat = set()

    async def _request(self, client, method, url, *, signal=None, **kwargs):
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

    async def __call__(self, model, context, options):
        message = AssistantMessage(model=model.id, provider=model.provider, api=model.api)
        yield AssistantStartEvent(message)
        try:
            profile = resolve_profile(model.id, model.provider)
            if is_aborted(options.signal):
                raise asyncio.CancelledError("CodeGem request aborted")
            async with httpx.AsyncClient(
                transport=self.transport, timeout=float(self.config.get("timeout", 180))
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
            "temperature": self.config.get("temperature", profile.temperature),
            "maxOutputTokens": int(self.config.get("max_output_tokens", 32768)),
        }
        if "thinking_config" in self.config:
            generation["thinkingConfig"] = dict(self.config["thinking_config"])
        elif profile.thinking_level:
            generation["thinkingConfig"] = {"thinkingLevel": profile.thinking_level.upper()}
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
        response = await self._request(
            client,
            "POST",
            f"{base}/models/{model.id}:generateContent",
            signal=options.signal,
            json=body,
            headers={"x-goog-api-key": key},
        )
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError(f"Gemini returned no candidate: {data.get('promptFeedback', {})}")
        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason not in {"STOP", "MAX_TOKENS"}:
            raise ValueError(f"Gemini stopped without a complete response: {reason}")
        content = candidate.get("content") or {}
        message.provider_content = copy.deepcopy(content)
        for part in content.get("parts", []):
            signature = part.get("thoughtSignature")
            if "text" in part:
                message.content.append(
                    ThinkingContent(part["text"], thinking_signature=signature)
                    if part.get("thought")
                    else TextContent(part["text"], text_signature=signature)
                )
            elif "functionCall" in part:
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
            else:
                raise ValueError("Gemini returned an unsupported coding response part")
        usage = data.get("usageMetadata", {})
        message.usage = Usage(
            input=usage.get("promptTokenCount", 0),
            output=usage.get("candidatesTokenCount", 0),
            cache_read=usage.get("cachedContentTokenCount", 0),
            reasoning=usage.get("thoughtsTokenCount"),
            total_tokens=usage.get("totalTokenCount", 0),
        )
        from superqode.providers.models import get_model_info

        info = get_model_info("google", model.id)
        if info is not None:
            # Catalog prices are estimates, not a provider billing receipt.
            # Google bills thinking tokens at the output rate. Argon's
            # announced introductory cached-input rate is 95% below input.
            cached = min(message.usage.cache_read, message.usage.input)
            input_cost = max(0, message.usage.input - cached) * info.input_price / 1_000_000
            output_cost = (
                (message.usage.output + (message.usage.reasoning or 0))
                * info.output_price
                / 1_000_000
            )
            cache_cost = (
                cached
                * info.input_price
                * (0.05 if model.id == "gemini-4-argon" else 1.0)
                / 1_000_000
            )
            message.usage.cost = UsageCost(
                input=input_cost,
                output=output_cost,
                cache_read=cache_cost,
                total=input_cost + output_cost + cache_cost,
            )
        message.stop_reason = (
            "length" if reason == "MAX_TOKENS" else "toolUse" if message.tool_calls else "stop"
        )

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
