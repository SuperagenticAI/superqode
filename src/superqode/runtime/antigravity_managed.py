"""Google-hosted Antigravity runtime over the Gemini Interactions API.

This adapter is intentionally separate from both local Antigravity routes:

* ``antigravity-cli`` delegates to the signed-in ``agy`` process.
* ``antigravity-sdk`` starts the SDK's bundled local harness.
* ``antigravity-managed`` runs the Antigravity harness in a Google-hosted
  sandbox and authenticates with a Gemini API key.

No Google account or local Antigravity credential store is accessed here.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..agent.loop import AgentConfig, AgentMessage, AgentResponse
from ..harness.events import HarnessEvent

DEFAULT_AGENT = "antigravity-preview-05-2026"
DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
IDENTITY_INSTRUCTION = """\
Runtime identity: You are Google's hosted Antigravity managed agent, invoked
through SuperQode runtime `antigravity-managed`. Antigravity owns the agent
loop, tools, and Google-hosted remote Linux sandbox; SuperQode is the local UI
and event adapter. The user's local SuperQode checkout is not automatically
mounted in your sandbox.

If the user asks which runtime, harness, agent, or execution environment is in
use, answer directly from this instruction without running tools or inspecting
environment variables or processes. Do not claim that SuperQode's `core`
harness owns this turn."""


class AntigravityManagedRuntime:
    """Stream a stateful Antigravity agent from Google's hosted sandbox."""

    name = "antigravity-managed"
    harness_owner = "antigravity"

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.name,
            "harness_owner": self.harness_owner,
            "authentication": "gemini-api-key",
            "execution_environment": "google-hosted",
            "structured_events": True,
            "agent": self._agent_id,
            "interaction_id": self._interaction_id,
            "environment_id": self._environment_id,
        }

    def __init__(self, *, config: AgentConfig | None = None, **_unused: Any) -> None:
        if config is None:
            raise ValueError("AntigravityManagedRuntime requires 'config'")
        self.config = config
        self._agent_id = os.environ.get("SUPERQODE_ANTIGRAVITY_AGENT", "").strip() or DEFAULT_AGENT
        # Keep Gemini API keys pinned to Google's documented API host. A
        # project-controlled endpoint override could otherwise exfiltrate them.
        self._api_base = DEFAULT_API_BASE
        self._interaction_id: str | None = None
        self._environment_id: str | None = None
        self._cancelled = False

    @staticmethod
    def api_key() -> str:
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    def _headers(self) -> dict[str, str]:
        key = self.api_key()
        if not key:
            raise RuntimeError(
                "Google's managed Antigravity agent requires GEMINI_API_KEY (or GOOGLE_API_KEY)."
            )
        return {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        }

    def _payload(self, prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent": self._agent_id,
            "input": prompt,
            "environment": self._environment_id or "remote",
            "stream": True,
        }
        if self._interaction_id:
            payload["previous_interaction_id"] = self._interaction_id

        agent_config: dict[str, Any] = {"type": "antigravity"}
        model = os.environ.get("SUPERQODE_ANTIGRAVITY_MODEL", "").strip()
        if not model and self.config.provider.strip().lower() == "google":
            model = self.config.model.strip()
        if model:
            agent_config["model"] = model
        max_tokens = self.config.max_tokens
        env_budget = os.environ.get("SUPERQODE_ANTIGRAVITY_MAX_TOTAL_TOKENS", "").strip()
        if env_budget:
            try:
                max_tokens = int(env_budget)
            except ValueError as exc:
                raise RuntimeError(
                    "SUPERQODE_ANTIGRAVITY_MAX_TOTAL_TOKENS must be an integer"
                ) from exc
        if max_tokens and max_tokens > 0:
            agent_config["max_total_tokens"] = max_tokens
        payload["agent_config"] = agent_config

        system_instruction = IDENTITY_INSTRUCTION
        if self.config.custom_system_prompt:
            system_instruction = (
                f"{system_instruction}\n\nUser-configured instructions:\n"
                f"{self.config.custom_system_prompt}"
            )
        if self.config.plan_mode:
            plan_instruction = (
                "Plan and explain the work, but do not modify files or execute "
                "commands that change state."
            )
            system_instruction = (
                f"{system_instruction}\n\n{plan_instruction}"
                if system_instruction
                else plan_instruction
            )
        payload["system_instruction"] = system_instruction
        return payload

    def _capture_interaction(self, event: dict[str, Any]) -> None:
        interaction = event.get("interaction")
        interaction_id = (
            interaction.get("id") if isinstance(interaction, dict) else event.get("interaction_id")
        )
        environment_id = (
            interaction.get("environment_id")
            if isinstance(interaction, dict)
            else event.get("environment_id")
        )
        if isinstance(interaction_id, str) and interaction_id:
            self._interaction_id = interaction_id
        if isinstance(environment_id, str) and environment_id:
            self._environment_id = environment_id

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        self.reset_cancellation()
        yield HarnessEvent(
            type="model_request",
            data={
                "runtime": self.name,
                "agent": self._agent_id,
                "environment": self._environment_id or "remote",
            },
        )

        completed = False
        async for event in _stream_interaction(
            f"{self._api_base}/interactions",
            self._payload(prompt),
            headers=self._headers(),
            timeout=600.0,
        ):
            if self._cancelled:
                break
            self._capture_interaction(event)
            event_type = str(event.get("event_type") or event.get("type") or "")

            if event_type == "step.start":
                step = event.get("step")
                if isinstance(step, dict):
                    step_type = str(step.get("type") or "")
                    if step_type == "function_call" or step_type.endswith("_call"):
                        yield HarnessEvent(
                            type="tool_call",
                            data={
                                "tool_name": str(step.get("name") or step_type),
                                "tool_call_id": step.get("id"),
                                "args": dict(step.get("arguments") or {}),
                                "provider_step": step_type,
                            },
                        )
                    elif step_type.endswith("_result"):
                        yield HarnessEvent(
                            type="tool_result",
                            data={
                                "tool_name": step_type.removesuffix("_result"),
                                "tool_call_id": step.get("id"),
                                "success": not bool(step.get("is_error")),
                                "output": step,
                                "error": step.get("error"),
                            },
                        )
            elif event_type == "step.delta":
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_type = str(delta.get("type") or "")
                if delta_type == "text" and delta.get("text"):
                    yield HarnessEvent(type="model_delta", data={"text": str(delta["text"])})
                elif delta_type in {"thought_summary", "thought"}:
                    text = _delta_text(delta)
                    if text:
                        yield HarnessEvent(type="thinking", data={"text": text})
                elif delta_type.endswith("_result"):
                    yield HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": delta_type.removesuffix("_result"),
                            "tool_call_id": delta.get("id"),
                            "success": not bool(delta.get("is_error")),
                            "output": delta,
                            "error": delta.get("error"),
                        },
                    )
            elif event_type == "interaction.completed":
                completed = True
                interaction = event.get("interaction")
                status = (
                    str(interaction.get("status") or "completed")
                    if isinstance(interaction, dict)
                    else "completed"
                )
                yield HarnessEvent(
                    type="turn_complete",
                    data={
                        "status": status,
                        "interaction_id": self._interaction_id,
                        "environment_id": self._environment_id,
                        "usage": (
                            dict(interaction.get("usage") or {})
                            if isinstance(interaction, dict)
                            else {}
                        ),
                    },
                )
            elif event_type == "error":
                error = event.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or error)
                else:
                    detail = str(error or "managed Antigravity stream failed")
                raise RuntimeError(detail)

        if not completed:
            yield HarnessEvent(
                type="turn_complete",
                data={"status": "cancelled" if self._cancelled else "incomplete"},
            )
        yield HarnessEvent(
            type="model_result",
            data={
                "runtime": self.name,
                "interaction_id": self._interaction_id,
                "environment_id": self._environment_id,
            },
        )

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                yield str(event.data["text"])

    async def run(self, prompt: str) -> AgentResponse:
        chunks: list[str] = []
        tool_calls = 0
        status = "complete"
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta" and event.data.get("text"):
                chunks.append(str(event.data["text"]))
            elif event.type == "tool_call":
                tool_calls += 1
            elif event.type == "turn_complete":
                status = str(event.data.get("status") or status)
        content = "".join(chunks)
        return AgentResponse(
            content=content,
            messages=[
                AgentMessage(role="user", content=prompt),
                AgentMessage(role="assistant", content=content),
            ],
            tool_calls_made=tool_calls,
            iterations=1,
            stopped_reason="cancelled" if self._cancelled else status,
            error=None,
        )

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancellation(self) -> None:
        self._cancelled = False


async def _stream_interaction(
    endpoint: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded Gemini Interactions API SSE events."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"managed Antigravity HTTP {response.status_code}: {body[:1000]}"
                )
            event_name = ""
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if not line:
                    decoded = _decode_sse_event(event_name, data_lines)
                    event_name, data_lines = "", []
                    if decoded is not None:
                        yield decoded
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            decoded = _decode_sse_event(event_name, data_lines)
            if decoded is not None:
                yield decoded


def _decode_sse_event(event_name: str, data_lines: list[str]) -> dict[str, Any] | None:
    if not data_lines:
        return None
    raw = "\n".join(data_lines)
    if raw == "[DONE]":
        return None
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid managed Antigravity SSE event: {raw[:500]}") from exc
    if not isinstance(event, dict):
        return {"event_type": event_name or "message", "value": event}
    if event_name and not event.get("event_type"):
        event["event_type"] = event_name
    return event


def _delta_text(delta: dict[str, Any]) -> str:
    if isinstance(delta.get("text"), str):
        return str(delta["text"])
    content = delta.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return str(content["text"])
    return ""


__all__ = ["AntigravityManagedRuntime"]
