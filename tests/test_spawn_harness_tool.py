from pathlib import Path

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import HarnessBackendResult, HarnessSpec, MemoryHarnessStore
from superqode.tools import SpawnHarnessTool, ToolContext


class FakeKernelBackend:
    name = "fake-kernel"

    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        response = AgentResponse(
            content="child summary",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=request.runtime or "builtin",
        )


@pytest.mark.asyncio
async def test_spawn_harness_runs_child_with_read_only_tools(tmp_path: Path):
    calls = []

    async def runner(task, metadata):
        calls.append((task, metadata))
        return "found one issue"

    tool = SpawnHarnessTool()
    ctx = ToolContext(
        session_id="s",
        working_directory=tmp_path,
        sub_agent_runner=runner,
    )

    result = await tool.execute(
        {
            "task": "scan checkout code",
            "context_handle": "repo:checkout",
            "max_depth": 1,
            "max_children": 2,
        },
        ctx,
    )

    assert result.success is True
    assert "found one issue" in result.output
    assert calls
    assert calls[0][1]["delegation_depth"] == 1
    assert "read_file" in calls[0][1]["allowed_tools"]
    assert calls[0][1]["context_handle"] == "repo:checkout"


@pytest.mark.asyncio
async def test_spawn_harness_enforces_depth_limit(tmp_path: Path):
    async def runner(task, metadata):  # pragma: no cover - should not run
        return "unexpected"

    tool = SpawnHarnessTool()
    ctx = ToolContext(
        session_id="depth",
        working_directory=tmp_path,
        sub_agent_runner=runner,
        delegation_depth=1,
    )

    result = await tool.execute(
        {"task": "scan", "max_depth": 1},
        ctx,
    )

    assert result.success is False
    assert "exceeds max_depth" in (result.error or "")


@pytest.mark.asyncio
async def test_spawn_harness_uses_kernel_child_run_when_harness_context_exists(
    monkeypatch, tmp_path: Path
):
    backend = FakeKernelBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = MemoryHarnessStore()
    spec = HarnessSpec(name="recursive")
    parent = store.start_run(
        session_id="parent-session",
        spec=spec,
        provider="local",
        model="qwen",
        runtime="builtin",
        prompt="parent",
    )
    tool = SpawnHarnessTool()
    ctx = ToolContext(
        session_id="parent-session",
        working_directory=tmp_path,
        harness_store=store,
        harness_spec=spec,
        harness_run_id=parent.run_id,
        harness_root_run_id=parent.run_id,
        harness_runtime="builtin",
        harness_provider="local",
        harness_model="qwen",
        harness_sandbox_backend="docker",
    )

    result = await tool.execute(
        {
            "task": "scan a fragment",
            "context_handle": "file:ci.log",
            "max_depth": 1,
            "max_children": 2,
        },
        ctx,
    )

    assert result.success is True
    child_run_id = result.metadata["child_run_id"]
    child = store.get_run(child_run_id)
    assert child is not None
    assert child.parent_run_id == parent.run_id
    assert child.root_run_id == parent.run_id
    assert child.status == "succeeded"
    assert backend.requests
    assert backend.requests[0].metadata["parent_run_id"] == parent.run_id
    assert backend.requests[0].metadata["delegation_depth"] == 1
    assert "read_file" in backend.requests[0].metadata["agent_tools"]
    assert any(event.type == "recursive.child.completed" for event in store.get_events(parent.run_id))


@pytest.mark.asyncio
async def test_spawn_harness_fanout_chunks_context_into_kernel_children(
    monkeypatch, tmp_path: Path
):
    backend = FakeKernelBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    (tmp_path / "ci.log").write_text(
        "\n".join(f"line {index} ROOT_CAUSE" for index in range(260)),
        encoding="utf-8",
    )
    store = MemoryHarnessStore()
    spec = HarnessSpec(name="recursive")
    parent = store.start_run(
        session_id="fanout-parent",
        spec=spec,
        provider="local",
        model="qwen",
        runtime="builtin",
        prompt="parent",
    )
    tool = SpawnHarnessTool()
    ctx = ToolContext(
        session_id="fanout-parent",
        working_directory=tmp_path,
        harness_store=store,
        harness_spec=spec,
        harness_run_id=parent.run_id,
        harness_root_run_id=parent.run_id,
        harness_runtime="builtin",
        harness_provider="local",
        harness_model="qwen",
        harness_sandbox_backend="docker",
    )

    result = await tool.execute(
        {
            "task": "scan chunk for root cause",
            "context_handle": "file:ci.log",
            "fanout": True,
            "chunk_chars": 1000,
            "max_chunks": 3,
            "max_children": 4,
            "max_parallel": 2,
        },
        ctx,
    )

    assert result.success is True
    assert result.metadata["fanout"] is True
    assert result.metadata["chunks"] == 3
    assert len(result.metadata["child_run_ids"]) == 3
    assert len(backend.requests) == 3
    assert all(request.metadata["parent_run_id"] == parent.run_id for request in backend.requests)
    assert all("Chunk text:" in request.prompt for request in backend.requests)
    child_runs = [store.get_run(run_id) for run_id in result.metadata["child_run_ids"]]
    assert all(run is not None and run.parent_run_id == parent.run_id for run in child_runs)
