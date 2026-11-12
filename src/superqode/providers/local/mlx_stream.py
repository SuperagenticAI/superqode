"""Incremental MLX deltas; complete tool arguments only reach the terminal chunk."""

import json
import re

from superqode.providers.gateway.base import StreamChunk, Usage, GatewayError


class MLXStream:
    def __init__(self, gateway, model):
        self.gateway, self.model = gateway, model
        self.parts = []
        self.emitted = 0
        self.pending = ""
        self.held = False
        self.calls = {}
        self.finish_reason = None
        self.usage = None
        self.markers = ("<tool_call>", "```tool_call", "```json", "```tool")

    def visible(self, content):
        self.parts.append(content)
        if self.held:
            return ""
        self.pending += content
        starts = [self.pending.find(marker) for marker in self.markers if marker in self.pending]
        if starts:
            index = min(starts)
            result, self.pending = self.pending[:index], self.pending[index:]
            self.held = True
            self.pending = ""
        elif self.pending.lstrip().startswith("{") and (
            re.match(r'^\s*\{\s*"(?:name|function_name)"', self.pending)
            or (len(self.pending) < 256 and not re.search(r'^\s*\{\s*"[^"\\]+"', self.pending))
        ):
            if re.match(r'^\s*\{\s*"(?:name|function_name)"', self.pending):
                self.held = True
                self.pending = ""
            return ""
        else:
            keep = max(
                (
                    size
                    for marker in self.markers
                    for size in range(1, len(marker))
                    if self.pending.endswith(marker[:size])
                ),
                default=0,
            )
            result = self.pending[:-keep] if keep else self.pending
            self.pending = self.pending[-keep:] if keep else ""
        self.emitted += len(result)
        return result

    def feed(self, packet):
        if not isinstance(packet, dict):
            raise GatewayError("Invalid MLX stream response", provider="mlx", model=self.model)
        if packet.get("error"):
            raise GatewayError(
                "MLX server reported a stream error", provider="mlx", model=self.model
            )
        usage = packet.get("usage")
        if isinstance(usage, dict) and usage:
            self.usage = Usage(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
            )
        chunks = []
        for choice in packet.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            legacy = "message" in choice
            delta = choice.get("message") if legacy else choice.get("delta")
            delta = delta or {}
            self.finish_reason = choice.get("finish_reason") or self.finish_reason
            for position, item in enumerate(delta.get("tool_calls") or []):
                index = item.get("index", position)
                call = self.calls.setdefault(
                    index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if item.get("id"):
                    call["id"] = item["id"]
                fn = item.get("function") or {}
                call["function"]["name"] += fn.get("name") or ""
                arguments = fn.get("arguments")
                if isinstance(arguments, dict):
                    call["function"]["arguments"] = json.dumps(arguments)
                elif isinstance(arguments, str):
                    call["function"]["arguments"] += arguments
            content = delta.get("content") or ""
            visible = self.visible(content) if isinstance(content, str) else ""
            thinking = (
                delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking")
            )
            if visible or thinking:
                chunks.append(
                    StreamChunk(content=visible, role=delta.get("role"), thinking_content=thinking)
                )
        return chunks

    def final(self):
        if not self.finish_reason:
            raise GatewayError(
                "MLX stream ended without a finish reason; the request was not replayed",
                provider="mlx",
                model=self.model,
            )
        text = "".join(self.parts)
        calls = self.gateway._normalize_tool_calls(list(self.calls.values()))
        if not calls:
            cleaned, calls = self.gateway._extract_inline_tool_calls(text)
            remaining = (
                cleaned[self.emitted :]
                if calls and cleaned.startswith(text[: self.emitted])
                else ""
                if calls
                else text[self.emitted :]
            )
        else:
            remaining = text[self.emitted :]
        reason = self.finish_reason
        if calls and reason not in {"length", "max_tokens", "content_filter", "error"}:
            reason = "tool_calls"
        return StreamChunk(
            content=remaining, finish_reason=reason, tool_calls=calls, usage=self.usage
        )
