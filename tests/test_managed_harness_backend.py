from pathlib import Path

import pytest

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.managed import ManagedAgentHarnessBackend
from superqode.harness.spec import HarnessSpec, RemoteHarnessSpec, RuntimeSpec


def _request(spec: HarnessSpec) -> HarnessBackendRequest:
    return HarnessBackendRequest(
        spec=spec,
        prompt="diagnose the failing checkout tests",
        provider="managed",
        model="remote-agent",
        working_directory=Path("."),
        session_id="s1",
        runtime=spec.runtime.backend,
        sandbox_backend="managed",
    )


@pytest.mark.asyncio
async def test_managed_backend_fails_closed_without_endpoint(monkeypatch):
    monkeypatch.delenv("SUPERQODE_GOOGLE_AGENT_ENDPOINT", raising=False)
    monkeypatch.delenv("GOOGLE_AGENT_ENDPOINT", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    spec = HarnessSpec(
        name="remote",
        runtime=RuntimeSpec(backend="google-agent-engine"),
        remote_harness=RemoteHarnessSpec(enabled=True, provider="google-agent-engine"),
    )

    result = await ManagedAgentHarnessBackend("google-agent-engine").run(_request(spec))

    assert result.response.stopped_reason == "error"
    assert result.metadata["configured"] is False
    assert "requires Gemini credentials" in (result.response.error or "")


@pytest.mark.asyncio
async def test_google_managed_backend_defaults_to_gemini_generate_content(monkeypatch):
    calls = []

    def fake_post(endpoint, payload, *, headers, timeout):
        calls.append((endpoint, payload, headers, timeout))
        return {
            "candidates": [
                {"content": {"parts": [{"text": "remote google agent answer"}]}}
            ]
        }

    monkeypatch.setattr("superqode.harness.backends.managed._post_json", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "test-google-token")
    spec = HarnessSpec(
        name="remote",
        runtime=RuntimeSpec(backend="google-agent-engine"),
        remote_harness=RemoteHarnessSpec(
            enabled=True,
            provider="google-agent-engine",
            config={"base_agent": "gemini-flash-latest", "api_revision": "2026-05-20"},
        ),
    )

    result = await ManagedAgentHarnessBackend("google-agent-engine").run(_request(spec))

    assert result.response.content == "remote google agent answer"
    assert result.metadata["configured"] is True
    endpoint, payload, headers, timeout = calls[0]
    assert endpoint == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-flash-latest:generateContent"
    )
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"].startswith(
        "diagnose the failing checkout tests"
    )
    assert payload["systemInstruction"]["parts"][0]["text"]
    assert headers["x-goog-api-key"] == "test-google-token"
    assert headers["Api-Revision"] == "2026-05-20"
    assert timeout == 300


@pytest.mark.asyncio
async def test_google_managed_backend_supports_interaction_payload(monkeypatch):
    calls = []

    def fake_post(endpoint, payload, *, headers, timeout):
        calls.append((endpoint, payload, headers, timeout))
        return {"outputText": "managed interaction answer"}

    monkeypatch.setattr("superqode.harness.backends.managed._post_json", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "test-google-token")
    spec = HarnessSpec(
        name="remote",
        runtime=RuntimeSpec(backend="google-agent-engine"),
        remote_harness=RemoteHarnessSpec(
            enabled=True,
            provider="google-agent-engine",
            agent_id="projects/p/locations/us/agents/a",
            config={
                "mode": "persisted",
                "api_base": "https://example.googleapis.com/v1",
                "environment": {"type": "remote", "sources": []},
                "tools": [{"type": "code_execution"}],
                "stream": True,
            },
        ),
    )

    result = await ManagedAgentHarnessBackend("google-agent-engine").run(_request(spec))

    assert result.response.content == "managed interaction answer"
    endpoint, payload, headers, _timeout = calls[0]
    assert endpoint == "https://example.googleapis.com/v1/interactions"
    assert payload["agent"] == "projects/p/locations/us/agents/a"
    assert payload["input"][0]["type"] == "user_input"
    assert payload["environment"] == {"type": "remote", "sources": []}
    assert payload["tools"] == [{"type": "code_execution"}]
    assert payload["stream"] is True
    assert headers["x-goog-api-key"] == "test-google-token"


@pytest.mark.asyncio
async def test_google_managed_backend_supports_bearer_auth(monkeypatch):
    calls = []

    def fake_post(endpoint, payload, *, headers, timeout):
        calls.append((endpoint, payload, headers, timeout))
        return {"text": "bearer answer"}

    monkeypatch.setattr("superqode.harness.backends.managed._post_json", fake_post)
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "oauth-token")
    spec = HarnessSpec(
        name="remote",
        runtime=RuntimeSpec(backend="google-agent-engine"),
        remote_harness=RemoteHarnessSpec(
            enabled=True,
            provider="google-agent-engine",
            config={"auth_type": "bearer"},
        ),
    )

    result = await ManagedAgentHarnessBackend("google-agent-engine").run(_request(spec))

    assert result.response.content == "bearer answer"
    _endpoint, _payload, headers, _timeout = calls[0]
    assert headers["Authorization"] == "Bearer oauth-token"
    assert "x-goog-api-key" not in headers


@pytest.mark.asyncio
async def test_anthropic_managed_backend_uses_anthropic_key_header(monkeypatch):
    calls = []

    def fake_post(endpoint, payload, *, headers, timeout):
        calls.append((endpoint, payload, headers, timeout))
        return {"messages": [{"content": "remote anthropic agent answer"}]}

    monkeypatch.setattr("superqode.harness.backends.managed._post_json", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    spec = HarnessSpec(
        name="remote",
        runtime=RuntimeSpec(backend="anthropic-managed"),
        remote_harness=RemoteHarnessSpec(
            enabled=True,
            provider="anthropic-managed",
            agent_id="agent_123",
            config={
                "endpoint": "https://api.anthropic.com/v1/managed-agents/agent_123/runs",
                "timeout_seconds": 60,
            },
        ),
    )

    result = await ManagedAgentHarnessBackend("anthropic-managed").run(_request(spec))

    assert result.response.content == "remote anthropic agent answer"
    endpoint, payload, headers, timeout = calls[0]
    assert endpoint == "https://api.anthropic.com/v1/managed-agents/agent_123/runs"
    assert payload["agent_id"] == "agent_123"
    assert headers["x-api-key"] == "test-anthropic-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert timeout == 60
