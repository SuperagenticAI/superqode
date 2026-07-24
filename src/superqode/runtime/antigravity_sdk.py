"""Google Antigravity SDK runtime using a Gemini API key.

This is deliberately separate from the ``agy`` CLI.  The CLI uses Google
Sign-In/keyring credentials; Google's embeddable SDK supports AI Studio keys.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent
from .errors import RuntimeNotInstalledError


def _require_sdk() -> None:
    try:
        import google.antigravity  # noqa: F401
    except Exception as exc:
        detail = str(exc)
        compatibility = (
            " The installed wheel has an incompatible protobuf runtime; reinstall "
            "SuperQode's antigravity-sdk extra so protobuf 7.35+ is selected."
            if "Gencode/Runtime" in detail or "protobuf" in detail.lower()
            else ""
        )
        raise RuntimeNotInstalledError(
            "Antigravity SDK runtime requires the 'antigravity-sdk' extra. "
            "Install with: uv tool install 'superqode[antigravity-sdk]', then set "
            f"GEMINI_API_KEY (or GOOGLE_API_KEY).{compatibility}"
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
            "model": self.config.model or "sdk-default",
            "reasoning_effort": self._reasoning_effort,
            "conversation_id": self.conversation_id,
            "mcp_servers": self._mcp_server_count,
            "skills": list(self._skills_paths),
        }

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        approval_callback=None,
        include_mcp: bool = False,
        **_unused: Any,
    ) -> None:
        _require_sdk()
        if config is None:
            raise ValueError("AntigravitySDKRuntime requires 'config'")
        self.config = config
        self._approval_callback = approval_callback
        self._include_mcp = bool(include_mcp)
        self._reasoning_effort = _coerce_reasoning_effort(config.reasoning_effort)
        self._agent: Any = None
        self._active_response: Any = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._mcp_server_count = 0
        self._skills_paths = self._discover_skill_paths()
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
        policies = self._sdk_policies()
        if policies is not None:
            kwargs["policies"] = policies
        capabilities = self._sdk_capabilities()
        if capabilities is not None:
            kwargs["capabilities"] = capabilities
        model = self._sdk_model(key)
        if model is not None:
            kwargs["model"] = model
        system_prompt = getattr(self.config, "custom_system_prompt", None)
        if system_prompt:
            kwargs["system_instructions"] = system_prompt
        if self._skills_paths:
            kwargs["skills_paths"] = list(self._skills_paths)
        mcp_servers = self._sdk_mcp_servers()
        if mcp_servers:
            kwargs["mcp_servers"] = mcp_servers
        self._agent = Agent(LocalAgentConfig(**kwargs))
        await self._agent.__aenter__()
        return self._agent

    def _sdk_capabilities(self) -> Any:
        if self.config.tools_enabled:
            return None
        from google.antigravity import CapabilitiesConfig

        return CapabilitiesConfig(enable_subagents=False, enabled_tools=[])

    def _sdk_model(self, key: str) -> Any:
        """Return a model target when reasoning effort needs explicit options."""
        if not self._reasoning_effort:
            return self.config.model or None
        from google.antigravity import (
            GeminiAPIEndpoint,
            GeminiModelOptions,
            ModelTarget,
            ModelType,
            ThinkingLevel,
        )

        level = {
            "minimal": ThinkingLevel.MINIMAL,
            "low": ThinkingLevel.LOW,
            "medium": ThinkingLevel.MEDIUM,
            "high": ThinkingLevel.HIGH,
            "extra_high": ThinkingLevel.EXTRA_HIGH,
        }[self._reasoning_effort]
        return ModelTarget(
            name=self.config.model or "gemini-3.6-flash",
            types=[ModelType.TEXT],
            endpoint=GeminiAPIEndpoint(
                api_key=key,
                options=GeminiModelOptions(thinking_level=level),
            ),
        )

    def _sdk_policies(self) -> list[Any] | None:
        """Bridge SDK tool decisions into SuperQode's live approval mode."""
        try:
            from google.antigravity.hooks import policy
        except ImportError:
            # Keeps early SDK/test doubles working; current wheels provide this.
            return None
        # Agent deep-copies LocalAgentConfig. A bound runtime method would make
        # deepcopy traverse active event loops and async generators. Functions
        # are copied atomically, so keep only the callback in this closure.
        callback = self._approval_callback

        def approve(tool_call: Any) -> bool:
            return _approval_decision(tool_call, callback)

        return list(policy.safe_defaults(approve))

    def _approve_tool_call(self, tool_call: Any) -> bool:
        return _approval_decision(tool_call, self._approval_callback)

    def _discover_skill_paths(self) -> list[str]:
        root = Path(self.config.working_directory).expanduser().resolve()
        candidates = [
            root / ".agents" / "skills",
            root / ".superqode" / "skills",
        ]
        configured = os.environ.get("SUPERQODE_ANTIGRAVITY_SKILLS", "")
        candidates.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item)
        return [str(path.resolve()) for path in candidates if path.is_dir()]

    def _sdk_mcp_servers(self) -> list[Any]:
        if not self._include_mcp:
            self._mcp_server_count = 0
            return []
        from google.antigravity import types as antigravity_types
        from superqode.mcp.config import (
            MCPHttpConfig,
            MCPSSEConfig,
            MCPStdioConfig,
            load_mcp_config,
        )

        root = Path(self.config.working_directory).expanduser().resolve()
        project_config = root / ".superqode" / "mcp.json"
        servers = load_mcp_config(project_config if project_config.exists() else None)
        converted: list[Any] = []
        converted_names: set[str] = set()
        for server_id, server in servers.items():
            if not server.enabled:
                continue
            sdk_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", server_id).strip("-") or "mcp"
            config = server.config
            if isinstance(config, MCPStdioConfig):
                if not config.command:
                    continue
                _reserve_mcp_name(converted_names, sdk_name, server_id)
                converted.append(
                    antigravity_types.McpStdioServer(
                        name=sdk_name,
                        command=config.command,
                        args=list(config.args),
                        env=dict(config.env) or None,
                        timeout_seconds=max(1, int(config.timeout)),
                    )
                )
            elif isinstance(config, MCPHttpConfig):
                if not config.url:
                    continue
                _reserve_mcp_name(converted_names, sdk_name, server_id)
                converted.append(
                    antigravity_types.McpStreamableHttpServer(
                        name=sdk_name,
                        url=config.url,
                        headers=dict(config.headers) or None,
                        timeout=float(config.timeout),
                        sse_read_timeout=float(config.sse_read_timeout),
                        timeout_seconds=max(1, int(config.timeout)),
                    )
                )
            elif isinstance(config, MCPSSEConfig):
                raise RuntimeError(
                    f"Antigravity SDK does not support legacy SSE MCP server "
                    f"'{server_id}'; use Streamable HTTP or stdio."
                )
        self._mcp_server_count = len(converted)
        return converted

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        self.reset_cancellation()
        self._event_loop = asyncio.get_running_loop()
        agent = await self._ensure_started()
        response = await agent.chat(prompt)
        self._active_response = response
        try:
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
                                "server_name": getattr(chunk, "server_name", None),
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
                                "server_name": getattr(chunk, "server_name", None),
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
                data={
                    "status": "cancelled" if self._cancelled else "completed",
                    "usage": _usage_dict(getattr(response, "usage_metadata", None)),
                    "conversation_id": self.conversation_id,
                },
            )
            yield HarnessEvent(
                type="model_result",
                data={"runtime": self.name, "conversation_id": self.conversation_id},
            )
        finally:
            self._active_response = None

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
        response = self._active_response
        loop = self._event_loop
        if response is not None and loop is not None and loop.is_running():
            cancel = getattr(response, "cancel", None)
            if cancel is not None:

                def schedule_cancel() -> None:
                    asyncio.create_task(cancel())

                loop.call_soon_threadsafe(schedule_cancel)

    def reset_cancellation(self) -> None:
        self._cancelled = False

    async def aclose(self) -> None:
        agent, self._agent = self._agent, None
        if agent is not None:
            await agent.__aexit__(None, None, None)

    def set_reasoning_effort(self, effort: str | None) -> None:
        if self._agent is not None:
            raise RuntimeError(
                "Antigravity SDK reasoning effort must be set before the first turn; "
                "reconnect the SDK runtime to change it."
            )
        self._reasoning_effort = _coerce_reasoning_effort(effort)

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort

    def set_model(self, model: str | None) -> None:
        if self._agent is not None:
            raise RuntimeError(
                "Antigravity SDK model must be set before the first turn; "
                "reconnect the SDK runtime to change it."
            )
        value = str(model or "").strip()
        if value.lower() in {"", "auto", "default", "none"}:
            self.config.model = ""
            return
        if value.startswith("-") or any(char in value for char in "\x00\r\n"):
            raise ValueError("invalid Antigravity SDK model")
        self.config.model = value

    @property
    def conversation_id(self) -> str | None:
        return getattr(self._agent, "conversation_id", None) if self._agent is not None else None


def _coerce_reasoning_effort(effort: str | None) -> str | None:
    value = str(effort or "").strip().lower().replace("-", "_")
    aliases = {
        "": None,
        "auto": None,
        "off": "minimal",
        "none": "minimal",
        "minimal": "minimal",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "max": "extra_high",
        "xhigh": "extra_high",
        "extra_high": "extra_high",
    }
    if value not in aliases:
        raise ValueError("reasoning effort must be auto, minimal, low, medium, high, or extra-high")
    return aliases[value]


def _reserve_mcp_name(names: set[str], sdk_name: str, server_id: str) -> None:
    if sdk_name in names:
        raise RuntimeError(
            f"MCP server names '{server_id}' and another configured server "
            f"both normalize to '{sdk_name}' for the Antigravity SDK."
        )
    names.add(sdk_name)


def _approval_decision(tool_call: Any, callback: Any) -> bool:
    name = getattr(tool_call, "name", "tool")
    name = str(getattr(name, "value", name))
    args = dict(getattr(tool_call, "args", {}) or {})
    if callback is None:
        return False
    return bool(callback(name, args))


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "completion_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        "thinking_tokens": int(getattr(usage, "thoughts_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
        "cached_tokens": int(getattr(usage, "cached_content_token_count", 0) or 0),
    }


__all__ = ["AntigravitySDKRuntime"]
