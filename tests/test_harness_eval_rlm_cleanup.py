"""Disposable RLM evaluation lifecycle; ordinary sessions keep their behavior."""

import asyncio

import pytest

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.rlm import RLMHarnessBackend
from superqode.harness.events import HarnessEvent
from superqode.harness.templates import get_harness_template


class FixtureAdapter:
    def __init__(self, *, resident=True, failure=None, entered=None):
        self.resident = resident
        self.failure = failure
        self.entered = entered
        self.closed = []

    async def resume(self, ref):
        return ref

    async def send(self, ref, message):
        if self.entered:
            self.entered.set()
            await asyncio.Event().wait()
        if self.failure:
            raise self.failure
        yield HarnessEvent(type="model_delta", data={"text": "fixture output"})

    async def close(self, ref):
        self.closed.append(ref.session_id)


def request(tmp_path, *, disposable=True):
    return HarnessBackendRequest(
        spec=get_harness_template("rlm"),
        prompt="fixture",
        provider="fixture",
        model="fixture",
        working_directory=tmp_path,
        session_id="fixture-session",
        metadata={"_evaluation_disposable": True} if disposable else {},
    )


async def test_default_evaluation_adapter_uses_nonresident_mode_and_closes(monkeypatch, tmp_path):
    adapters = []

    def factory(**kwargs):
        adapter = FixtureAdapter(**kwargs)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr("superqode.harness.backends.rlm.RLMHarnessProtocolAdapter", factory)
    backend = RLMHarnessBackend()
    result = await backend.run(request(tmp_path))
    assert result.response.content == "fixture output"
    assert adapters[-1].resident is False
    assert adapters[-1].closed == ["fixture-session"]
    assert adapters[0].resident is True and adapters[0].closed == []


async def test_ordinary_rlm_session_is_not_closed_after_one_turn(tmp_path):
    adapter = FixtureAdapter()
    backend = RLMHarnessBackend(adapter=adapter)
    await backend.run(request(tmp_path, disposable=False))
    assert adapter.closed == []


async def test_disposable_session_closes_after_backend_exception(tmp_path):
    adapter = FixtureAdapter(failure=RuntimeError("injected failure"))
    with pytest.raises(RuntimeError, match="injected failure"):
        await RLMHarnessBackend(adapter=adapter).run(request(tmp_path))
    assert adapter.closed == ["fixture-session"]


async def test_disposable_session_closes_after_task_cancellation(tmp_path):
    entered = asyncio.Event()
    adapter = FixtureAdapter(entered=entered)
    run = asyncio.create_task(RLMHarnessBackend(adapter=adapter).run(request(tmp_path)))
    await asyncio.wait_for(entered.wait(), timeout=5)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert adapter.closed == ["fixture-session"]
