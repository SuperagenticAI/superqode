"""Tests for in-run steering, finish_reason=length auto-continue, and reminders."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.reminders import collect_reminders, format_reminder_message
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.tools.base import ToolRegistry
from superqode.tools.file_tracking import record_file_read


class ScriptedGateway(GatewayInterface):
    def __init__(self, responses: List[GatewayResponse]):
        self.responses = responses
        self.calls: List[List[Message]] = []

    async def chat_completion(self, messages, model, provider=None, **kwargs) -> GatewayResponse:
        self.calls.append(list(messages))
        if not self.responses:
            return GatewayResponse(content="done")
        return self.responses.pop(0)

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append(list(messages))
        response = self.responses.pop(0) if self.responses else GatewayResponse(content="done")
        yield StreamChunk(
            content=response.content,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
        )

    async def test_connection(self, provider, model=None) -> Dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider, model) -> str:
        return f"{provider}/{model}"


def _loop(gateway, **config_kwargs) -> AgentLoop:
    config = AgentConfig(provider="test", model="test-model", **config_kwargs)
    return AgentLoop(gateway=gateway, tools=ToolRegistry.empty(), config=config)


# ----------------------------------------------------------------- steering


@pytest.mark.asyncio
async def test_pre_queued_steering_joins_first_call():
    gateway = ScriptedGateway([GatewayResponse(content="answer", finish_reason="stop")])
    loop = _loop(gateway)
    loop.steer("also check the README")

    response = await loop.run("do the thing")

    # Queued before the run: drained into the very first request.
    assert len(gateway.calls) == 1
    assert response.content == "answer"
    assert any("also check the README" in str(m.content) for m in gateway.calls[0])


@pytest.mark.asyncio
async def test_mid_run_steering_extends_run():
    """A message steered while the model is responding keeps the run going."""
    gateway = ScriptedGateway(
        [
            GatewayResponse(content="first answer", finish_reason="stop"),
            GatewayResponse(content="answer to steering", finish_reason="stop"),
        ]
    )
    loop = _loop(gateway)

    original = gateway.chat_completion
    fired = {"done": False}

    async def steer_during_first_call(messages, model, provider=None, **kwargs):
        result = await original(messages, model, provider=provider, **kwargs)
        if not fired["done"]:
            fired["done"] = True
            loop.steer("also check the README")  # user types while model works
        return result

    gateway.chat_completion = steer_during_first_call

    response = await loop.run("do the thing")

    assert len(gateway.calls) == 2
    assert response.content == "answer to steering"
    assert any("also check the README" in str(m.content) for m in gateway.calls[1])


@pytest.mark.asyncio
async def test_steer_reports_run_state():
    gateway = ScriptedGateway([GatewayResponse(content="ok")])
    loop = _loop(gateway)
    assert loop.steer("queued while idle") is False  # not active yet
    await loop.run("task")
    assert loop.run_active is False


@pytest.mark.asyncio
async def test_streaming_mid_run_steering_extends_run():
    gateway = ScriptedGateway(
        [
            GatewayResponse(content="first ", finish_reason="stop"),
            GatewayResponse(content="second", finish_reason="stop"),
        ]
    )
    loop = _loop(gateway)

    original = gateway.stream_completion
    fired = {"done": False}

    async def steer_during_first_stream(messages, model, provider=None, **kwargs):
        async for chunk in original(messages, model, provider=provider, **kwargs):
            yield chunk
        if not fired["done"]:
            fired["done"] = True
            loop.steer("follow-up")

    gateway.stream_completion = steer_during_first_stream

    chunks = [c async for c in loop.run_streaming("task")]
    assert "".join(chunks) == "first second"
    assert len(gateway.calls) == 2


# ------------------------------------------------------------ auto-continue


@pytest.mark.asyncio
async def test_length_cut_auto_continues_and_joins():
    gateway = ScriptedGateway(
        [
            GatewayResponse(content="part one, ", finish_reason="length"),
            GatewayResponse(content="part two.", finish_reason="stop"),
        ]
    )
    loop = _loop(gateway)
    response = await loop.run("write something long")
    assert response.content == "part one, part two."
    assert len(gateway.calls) == 2
    # The continue nudge was sent as a user message.
    nudges = [m for m in gateway.calls[1] if m.role == "user" and "cut off" in str(m.content)]
    assert nudges


@pytest.mark.asyncio
async def test_auto_continue_respects_cap():
    gateway = ScriptedGateway(
        [GatewayResponse(content=f"part {i} ", finish_reason="length") for i in range(5)]
    )
    loop = _loop(gateway, max_auto_continues=2)
    response = await loop.run("write")
    # initial + 2 continues = 3 calls; gives up at the cap.
    assert len(gateway.calls) == 3
    assert response.content == "part 0 part 1 part 2 "


@pytest.mark.asyncio
async def test_auto_continue_disabled():
    gateway = ScriptedGateway([GatewayResponse(content="partial", finish_reason="length")])
    loop = _loop(gateway, max_auto_continues=0)
    response = await loop.run("write")
    assert len(gateway.calls) == 1
    assert response.content == "partial"


@pytest.mark.asyncio
async def test_streaming_length_cut_auto_continues():
    gateway = ScriptedGateway(
        [
            GatewayResponse(content="alpha ", finish_reason="length"),
            GatewayResponse(content="omega", finish_reason="stop"),
        ]
    )
    loop = _loop(gateway)
    chunks = [c async for c in loop.run_streaming("write")]
    assert "".join(chunks) == "alpha omega"
    assert len(gateway.calls) == 2


# --------------------------------------------------------------- reminders


def test_changed_file_reminder_fires_once(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_REMINDERS", raising=False)
    target = tmp_path / "watched.py"
    target.write_text("v1")
    record_file_read("rem-session", str(target), target.stat().st_mtime)

    state: Dict[str, Any] = {}
    # Unchanged: no reminder.
    assert (
        collect_reminders(
            session_id="rem-session", working_directory=tmp_path, iteration=1, state=state
        )
        == []
    )

    # External change: one reminder, then silence for the same change.
    import os
    import time

    target.write_text("v2")
    os.utime(target, (time.time() + 5, time.time() + 5))
    first = collect_reminders(
        session_id="rem-session", working_directory=tmp_path, iteration=2, state=state
    )
    assert first and "watched.py" in first[0]
    again = collect_reminders(
        session_id="rem-session", working_directory=tmp_path, iteration=3, state=state
    )
    assert again == []


def test_reminders_disabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_REMINDERS", "0")
    assert (
        collect_reminders(session_id="x", working_directory=tmp_path, iteration=1, state={}) == []
    )


def test_format_reminder_message_tags():
    msg = format_reminder_message(["note one", "note two"])
    assert msg.startswith("<system-reminder>")
    assert msg.endswith("</system-reminder>")
    assert "note one" in msg and "note two" in msg


@pytest.mark.asyncio
async def test_reminders_attached_to_request_not_history(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_REMINDERS", raising=False)
    gateway = ScriptedGateway([GatewayResponse(content="ok")])
    config = AgentConfig(provider="test", model="test-model", working_directory=tmp_path)
    loop = AgentLoop(gateway=gateway, tools=ToolRegistry.empty(), config=config)

    target = tmp_path / "tracked.txt"
    target.write_text("v1")
    record_file_read(loop.session_id, str(target), target.stat().st_mtime)
    import os
    import time

    target.write_text("v2")
    os.utime(target, (time.time() + 5, time.time() + 5))

    response = await loop.run("task")
    sent = [str(m.content) for m in gateway.calls[0]]
    assert any("<system-reminder>" in c for c in sent)
    # History (response.messages) stays clean of synthetic reminders.
    assert not any("<system-reminder>" in str(m.content) for m in response.messages)
