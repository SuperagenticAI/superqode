"""Google Antigravity SDK runtime using a Gemini API key.

This is deliberately separate from the ``agy`` CLI.  The CLI uses Google
Sign-In/keyring credentials; Google's embeddable SDK supports AI Studio keys.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from .errors import RuntimeNotInstalledError


def _require_sdk() -> None:
    try:
        import google.antigravity  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "Antigravity SDK runtime requires the 'antigravity-sdk' extra. "
            "Install with: uv tool install 'superqode[antigravity-sdk]', then set "
            "GEMINI_API_KEY (or GOOGLE_API_KEY)."
        ) from exc


class AntigravitySDKRuntime:
    """Adapter from Google's async Agent API to SuperQode's runtime protocol."""

    name = "antigravity-sdk"
    harness_owner = "antigravity"

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "gemini-api-key",
            "structured_events": True,
        }

    def __init__(self, *, config: AgentConfig | None = None, **_unused: Any) -> None:
        _require_sdk()
        if config is None:
            raise ValueError("AntigravitySDKRuntime requires 'config'")
        self.config = config
        self._agent: Any = None
        self._cancelled = False

    @staticmethod
    def api_key() -> str:
        # The SDK officially reads GEMINI_API_KEY. SuperQode has historically
        # accepted GOOGLE_API_KEY too, so pass that alias explicitly.
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    async def _ensure_started(self) -> Any:
        if self._agent is not None:
            return self._agent
        from google.antigravity import Agent, LocalAgentConfig

        key = self.api_key()
        if not key:
            raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY before connecting")
        kwargs: dict[str, Any] = {
            "api_key": key,
            "workspaces": [str(self.config.working_directory)],
        }
        if self.config.model:
            kwargs["model"] = self.config.model
        system_prompt = getattr(self.config, "custom_system_prompt", None)
        if system_prompt:
            kwargs["system_instructions"] = system_prompt
        self._agent = Agent(LocalAgentConfig(**kwargs))
        await self._agent.__aenter__()
        return self._agent

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        self.reset_cancellation()
        agent = await self._ensure_started()
        response = await agent.chat(prompt)
        yield HarnessEvent(type="model_request", data={"runtime": self.name})
        if hasattr(response, "chunks"):
            async for chunk in response.chunks:
                if self._cancelled:
                    break
                kind = type(chunk).__name__
                if kind == "Text" and getattr(chunk, "text", ""):
                    yield HarnessEvent(type="model_delta", data={"text": chunk.text})
                elif kind == "Thought" and getattr(chunk, "text", ""):
                    yield HarnessEvent(type="thinking", data={"text": chunk.text})
                elif kind == "ToolCall":
                    name = getattr(chunk, "name", "tool")
                    yield HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": getattr(name, "value", name),
                            "tool_call_id": getattr(chunk, "id", None),
                            "args": dict(getattr(chunk, "args", {}) or {}),
                        },
                    )
                elif kind == "ToolResult":
                    name = getattr(chunk, "name", "tool")
                    error = getattr(chunk, "error", None)
                    exception = getattr(chunk, "exception", None)
                    failure = error or exception
                    yield HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": getattr(name, "value", name),
                            "tool_call_id": getattr(chunk, "id", None),
                            "success": not bool(failure),
                            "output": failure or getattr(chunk, "result", None),
                            "error": str(failure) if failure else None,
                        },
                    )
        else:
            # Compatibility with early SDK response implementations.
            async for token in response:
                if self._cancelled:
                    break
                if token:
                    yield HarnessEvent(type="model_delta", data={"text": str(token)})
        yield HarnessEvent(
            type="turn_complete",
            data={"status": "cancelled" if self._cancelled else "completed"},
        )
        yield HarnessEvent(type="model_result", data={"runtime": self.name})

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                yield str(event.data["text"])

    async def run(self, prompt: str) -> AgentResponse:
        chunks: list[str] = []
        tool_calls = 0
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                chunks.append(str(event.data["text"]))
            elif event.type == "tool_call":
                tool_calls += 1
        content = "".join(chunks)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason="cancelled" if self._cancelled else "complete",
            error=None,
        )

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def aclose(self) -> None:
        agent, self._agent = self._agent, None
        if agent is not None:
            await agent.__aexit__(None, None, None)


__all__ = ["AntigravitySDKRuntime"]
