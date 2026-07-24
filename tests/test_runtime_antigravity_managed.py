from __future__ import annotations

import asyncio
from pathlib import Path

from superqode.agent.loop import AgentConfig


def test_managed_runtime_streams_typed_events_and_resumes(monkeypatch):
    calls = []

    async def fake_stream(endpoint, payload, *, headers, timeout):
        calls.append((endpoint, payload, headers, timeout))
        yield {
            "event_type": "interaction.created",
            "interaction": {
                "id": "interaction-1",
                "environment_id": "environment-1",
                "status": "in_progress",
            },
        }
        yield {
            "event_type": "step.start",
            "index": 0,
            "step": {"type": "code_execution_call", "id": "tool-1"},
        }
        yield {
            "event_type": "step.delta",
            "index": 1,
            "delta": {
                "type": "thought_summary",
                "content": {"type": "text", "text": "Checking the project."},
            },
        }
        yield {
            "event_type": "step.delta",
            "index": 2,
            "delta": {"type": "text", "text": "Done."},
        }
        yield {
            "event_type": "interaction.completed",
            "interaction": {
                "id": "interaction-1",
                "environment_id": "environment-1",
                "status": "completed",
                "usage": {"total_tokens": 42},
            },
        }

    monkeypatch.setattr("superqode.runtime.antigravity_managed._stream_interaction", fake_stream)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    from superqode.runtime.antigravity_managed import AntigravityManagedRuntime

    runtime = AntigravityManagedRuntime(
        config=AgentConfig(
            provider="google",
            model="gemini-3.6-flash",
            max_tokens=5000,
            working_directory=Path.cwd(),
        )
    )

    async def collect():
        return [event async for event in runtime.run_harness_events("inspect")]

    events = asyncio.run(collect())
    assert [event.type for event in events] == [
        "model_request",
        "tool_call",
        "thinking",
        "model_delta",
        "turn_complete",
        "model_result",
    ]
    assert events[3].data["text"] == "Done."
    assert runtime.metadata["interaction_id"] == "interaction-1"
    assert runtime.metadata["environment_id"] == "environment-1"

    endpoint, payload, headers, timeout = calls[0]
    assert endpoint.endswith("/v1beta/interactions")
    assert payload["agent"] == "antigravity-preview-05-2026"
    assert payload["environment"] == "remote"
    assert payload["agent_config"] == {
        "type": "antigravity",
        "model": "gemini-3.6-flash",
        "max_total_tokens": 5000,
    }
    assert "runtime `antigravity-managed`" in payload["system_instruction"]
    assert "answer directly" in payload["system_instruction"]
    assert headers["x-goog-api-key"] == "test-key"
    assert timeout == 600.0

    asyncio.run(collect())
    assert calls[1][1]["previous_interaction_id"] == "interaction-1"
    assert calls[1][1]["environment"] == "environment-1"


def test_managed_runtime_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from superqode.runtime.antigravity_managed import AntigravityManagedRuntime

    runtime = AntigravityManagedRuntime(
        config=AgentConfig(provider="google", model="", working_directory=Path.cwd())
    )

    async def consume():
        return [event async for event in runtime.run_harness_events("inspect")]

    try:
        asyncio.run(consume())
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing API key should fail closed")


def test_managed_runtime_ignores_unrelated_default_provider_model(monkeypatch):
    monkeypatch.delenv("SUPERQODE_ANTIGRAVITY_MODEL", raising=False)

    from superqode.runtime.antigravity_managed import AntigravityManagedRuntime

    runtime = AntigravityManagedRuntime(
        config=AgentConfig(provider="openai", model="gpt-default", working_directory=Path.cwd())
    )

    assert runtime._payload("inspect")["agent_config"] == {"type": "antigravity"}


def test_managed_runtime_preserves_identity_with_custom_instructions():
    from superqode.runtime.antigravity_managed import AntigravityManagedRuntime

    runtime = AntigravityManagedRuntime(
        config=AgentConfig(
            provider="google",
            model="",
            custom_system_prompt="Use concise answers.",
            working_directory=Path.cwd(),
        )
    )

    instruction = runtime._payload("identify yourself")["system_instruction"]
    assert "Google's hosted Antigravity managed agent" in instruction
    assert "without running tools" in instruction
    assert "User-configured instructions:\nUse concise answers." in instruction


def test_sse_decoder_supports_named_events_and_done():
    from superqode.runtime.antigravity_managed import _decode_sse_event

    event = _decode_sse_event(
        "step.delta",
        ['{"index":0,"delta":{"type":"text","text":"hi"}}'],
    )
    assert event is not None
    assert event["event_type"] == "step.delta"
    assert _decode_sse_event("done", ["[DONE]"]) is None
