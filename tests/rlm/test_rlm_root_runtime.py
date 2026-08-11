"""Resident root ownership and attach/replay contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path

from superqode.harness.events import HarnessEvent
from superqode.harness.protocol import HarnessCreateRequest, HarnessSessionRef
from superqode.harness.rlm_adapter import RLMHarnessProtocolAdapter
from superqode.harness.store import MemoryHarnessStore
from superqode.rlm.root_runtime import RootRuntimeClient, _atomic_json
from superqode.rlm.root_worker import ResidentRootWorker


class _Session:
    def __init__(self, path: Path) -> None:
        self.session_path = path


class _Adapter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self._sessions = {}
        self.resumed: HarnessSessionRef | None = None

    async def resume(self, ref: HarnessSessionRef) -> HarnessSessionRef:
        self.resumed = ref
        self._sessions[ref.session_id] = _Session(self.path)
        return HarnessSessionRef(
            session_id=ref.session_id,
            harness_id="rlm",
            external_session_id="external-root",
            metadata=ref.metadata,
        )

    async def send(self, ref, message):
        del ref, message
        self.started.set()
        yield HarnessEvent(type="model_delta", data={"text": "before detach"})
        await self.release.wait()
        yield HarnessEvent(type="model_delta", data={"text": " after attach"})

    async def steer(self, ref, message) -> None:
        del ref, message

    async def cancel(self, ref) -> None:
        del ref
        self.release.set()


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_resident_root_replays_after_client_detaches(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_RLM_DIR", str(tmp_path / "agent"))
    client = RootRuntimeClient(
        "root-session",
        {
            "session_id": "root-session",
            "provider": "fake",
            "model": "fake-model",
            "working_directory": str(tmp_path),
            "metadata": {"rlm_config": {"durable_children": True}},
        },
    )
    client.directory.mkdir(parents=True)
    _atomic_json(client.manifest_path, client.manifest)
    adapter = _Adapter(tmp_path / "root.jsonl")
    worker = ResidentRootWorker(client.manifest_path, "generation-1", adapter=adapter)
    worker_task = asyncio.create_task(worker.run())
    await _wait_until(lambda: client.status().state == "ready")

    command_id = await client.submit("send", {"content": "continue without the TUI"})
    await adapter.started.wait()
    first_connection = client.events(command_id)
    first = await anext(first_connection)
    assert first.data["text"] == "before detach"
    await first_connection.aclose()

    # Closing the event consumer is a detach, not cancellation. The worker
    # finishes and a replacement client replays the full command from disk.
    adapter.release.set()
    replay = [event async for event in client.events(command_id)]
    assert [event.data["text"] for event in replay] == [
        "before detach",
        " after attach",
    ]
    assert adapter.resumed is not None
    assert adapter.resumed.metadata["rlm_config"]["durable_children"] is False
    assert client.status().external_session_id == "external-root"

    stop_id = await client.submit("stop")
    assert [event async for event in client.events(stop_id)] == []
    assert await worker_task == 0
    assert client.status().state == "stopped"


async def test_released_adapter_starts_a_real_resident_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_RLM_DIR", str(tmp_path / "agent"))
    adapter = RLMHarnessProtocolAdapter()
    ref = await adapter.create(
        HarnessCreateRequest(
            harness_id="rlm",
            provider="fake",
            model="fake-model",
            working_directory=tmp_path,
            session_id="process-contract",
            metadata={
                "_harness_store": MemoryHarnessStore(),
                "rlm_config": {"max_depth": 2},
            },
        )
    )
    client = adapter._runtime_clients[ref.session_id]
    try:
        status = client.status()
        assert status.alive is True
        assert status.state == "ready"
        assert status.session_path
        assert "_harness_store" not in client.manifest["metadata"]
        assert client.manifest["metadata"]["rlm_config"] == {"max_depth": 2}

        events = await client.request("admin", {"command": "status"})
        assert events[0].type == "runtime.result"
        lines = [line["text"] for line in events[0].data["lines"]]
        assert any("one resident root worker owns every descendant" in line for line in lines)
    finally:
        await client.control("stop")
        await _wait_until(lambda: client.status().state == "stopped")
