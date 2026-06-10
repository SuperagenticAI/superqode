"""Tests for opt-in automatic memory recall (SUPERQODE_AUTO_RECALL)."""

from typing import Any, Dict, List

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.reminders import AUTO_RECALL_ENV, collect_reminders
from superqode.memory.providers import LocalAgentMemoryProvider
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
)
from superqode.tools.base import ToolRegistry


@pytest.fixture()
def memory_home(tmp_path, monkeypatch):
    """Isolate the user-level memory store under a temp HOME."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SUPERQODE_REMINDERS", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    return project


def _remember(project, content, kind="fact"):
    LocalAgentMemoryProvider(project_root=project).remember(content, kind=kind)


def _collect(project, prompt, state=None):
    return collect_reminders(
        session_id="t",
        working_directory=project,
        iteration=1,
        state=state if state is not None else {},
        user_message=prompt,
    )


def test_recall_disabled_by_default(memory_home, monkeypatch):
    monkeypatch.delenv(AUTO_RECALL_ENV, raising=False)
    _remember(memory_home, "This repo uses pnpm, never npm for package management")
    assert _collect(memory_home, "install the package manager dependencies") == []


def test_recall_surfaces_relevant_memory(memory_home, monkeypatch):
    monkeypatch.setenv(AUTO_RECALL_ENV, "1")
    _remember(
        memory_home, "This repo uses pnpm, never npm for package management", kind="preference"
    )
    out = _collect(memory_home, "install the package manager dependencies for this repo")
    assert out, "expected a recall reminder"
    assert "pnpm" in out[0]
    assert "[preference]" in out[0]
    assert "verify before relying" in out[0]


def test_recall_fires_once_per_prompt(memory_home, monkeypatch):
    monkeypatch.setenv(AUTO_RECALL_ENV, "1")
    _remember(memory_home, "Tests require the DS4 server running on port 8000")
    state: Dict[str, Any] = {}
    first = _collect(memory_home, "run the tests against the DS4 server", state)
    second = _collect(memory_home, "run the tests against the DS4 server", state)
    assert first and not second
    # A different prompt recalls again.
    third = _collect(memory_home, "now check the DS4 server tests once more please", state)
    assert third


def test_recall_skips_irrelevant_memories(memory_home, monkeypatch):
    monkeypatch.setenv(AUTO_RECALL_ENV, "1")
    _remember(memory_home, "The deployment pipeline publishes to the staging bucket")
    assert _collect(memory_home, "refactor the date parsing helper functions") == []


def test_recall_safe_with_empty_store(memory_home, monkeypatch):
    monkeypatch.setenv(AUTO_RECALL_ENV, "1")
    assert _collect(memory_home, "anything at all happening here today") == []


class ScriptedGateway(GatewayInterface):
    def __init__(self):
        self.calls: List[List[Message]] = []

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append(list(messages))
        return GatewayResponse(content="done")

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append(list(messages))
        yield StreamChunk(content="done")

    async def test_connection(self, provider, model=None):
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.asyncio
async def test_loop_injects_recall_into_request_not_history(memory_home, monkeypatch):
    monkeypatch.setenv(AUTO_RECALL_ENV, "1")
    _remember(memory_home, "This repo uses pnpm, never npm for package management")

    gateway = ScriptedGateway()
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="t", model="m", working_directory=memory_home),
    )
    response = await loop.run("update the package manager dependencies in this repo")

    sent = [str(m.content) for m in gateway.calls[0]]
    assert any("<system-reminder>" in c and "pnpm" in c for c in sent)
    # History stays clean of the synthetic reminder.
    assert not any("<system-reminder>" in str(m.content) for m in response.messages)
