from pathlib import Path

import pytest

from superqode.agent.loop import AgentResponse
from superqode.harness import HarnessBackendResult, HarnessSpec, MemoryHarnessStore
from superqode.tools import DynamicWorkflowScriptTool, DynamicWorkflowTool, ToolContext, ToolRegistry
from superqode.tools.dynamic_workflow import compile_dynamic_workflow_script


class FakeDynamicBackend:
    name = "fake-dynamic"

    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        response = AgentResponse(
            content=f"summary for {request.metadata.get('recursive_child_id')}",
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


def test_coding_registry_includes_dynamic_workflow():
    registry = ToolRegistry.coding()
    assert registry.get("dynamic_workflow") is not None
    assert registry.get("dynamic_workflow_script") is not None


def test_dynamic_workflow_script_compiles_literal_dsl():
    plan = compile_dynamic_workflow_script(
        """
workflow("diagnose ci", max_children=4, max_depth=1)
step("logs", task="scan log chunks", context_handle="file:ci.log", fanout=True, max_chunks=3)
"""
    )

    assert plan["objective"] == "diagnose ci"
    assert plan["max_children"] == 4
    assert plan["steps"][0]["id"] == "logs"
    assert plan["steps"][0]["fanout"] is True


def test_dynamic_workflow_script_rejects_arbitrary_python():
    with pytest.raises(ValueError, match="only contain"):
        compile_dynamic_workflow_script("for item in range(3):\n    step(task='x')")

    with pytest.raises(ValueError, match="literal"):
        compile_dynamic_workflow_script(
            "workflow('x')\nstep('bad', task='scan ' + 'repo')"
        )


@pytest.mark.asyncio
async def test_dynamic_workflow_runs_kernel_child_steps(monkeypatch, tmp_path: Path):
    backend = FakeDynamicBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = MemoryHarnessStore()
    spec = HarnessSpec(name="dynamic")
    parent = store.start_run(
        session_id="dynamic-parent",
        spec=spec,
        provider="local",
        model="qwen",
        runtime="builtin",
        prompt="parent",
    )
    ctx = ToolContext(
        session_id="dynamic-parent",
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

    result = await DynamicWorkflowTool().execute(
        {
            "objective": "audit checkout",
            "steps": [
                {"id": "payment", "task": "scan payment code"},
                {"id": "ledger", "task": "scan ledger code"},
            ],
            "max_children": 4,
        },
        ctx,
    )

    assert result.success is True
    assert result.metadata["steps"] == 2
    assert len(result.metadata["child_run_ids"]) == 2
    assert len(backend.requests) == 2
    assert all(request.metadata["parent_run_id"] == parent.run_id for request in backend.requests)
    assert "payment" in result.output
    assert "ledger" in result.output


@pytest.mark.asyncio
async def test_dynamic_workflow_script_dry_run_compiles_plan(tmp_path: Path):
    ctx = ToolContext(session_id="script-dry-run", working_directory=tmp_path)

    result = await DynamicWorkflowScriptTool().execute(
        {
            "script": """
workflow(objective="audit checkout", max_children=4)
step(id="payment", task="scan payment code")
""",
            "dry_run": True,
        },
        ctx,
    )

    assert result.success is True
    assert result.metadata["script_compiled"] is True
    assert result.metadata["plan"]["objective"] == "audit checkout"
    assert "payment" in result.output


@pytest.mark.asyncio
async def test_dynamic_workflow_script_executes_compiled_plan(
    monkeypatch, tmp_path: Path
):
    backend = FakeDynamicBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    store = MemoryHarnessStore()
    spec = HarnessSpec(name="dynamic-script")
    parent = store.start_run(
        session_id="dynamic-script-parent",
        spec=spec,
        provider="local",
        model="qwen",
        runtime="builtin",
        prompt="parent",
    )
    ctx = ToolContext(
        session_id="dynamic-script-parent",
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

    result = await DynamicWorkflowScriptTool().execute(
        {
            "script": """
workflow("audit checkout", max_children=4)
step("payment", task="scan payment code")
step("ledger", task="scan ledger code")
""",
        },
        ctx,
    )

    assert result.success is True
    assert result.metadata["script_compiled"] is True
    assert len(result.metadata["child_run_ids"]) == 2
    assert len(backend.requests) == 2


@pytest.mark.asyncio
async def test_dynamic_workflow_step_can_fanout_context_handle(
    monkeypatch, tmp_path: Path
):
    backend = FakeDynamicBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    (tmp_path / "ci.log").write_text(
        "\n".join(f"line {index} failure cluster" for index in range(220)),
        encoding="utf-8",
    )
    store = MemoryHarnessStore()
    spec = HarnessSpec(name="dynamic")
    parent = store.start_run(
        session_id="dynamic-fanout-parent",
        spec=spec,
        provider="local",
        model="qwen",
        runtime="builtin",
        prompt="parent",
    )
    ctx = ToolContext(
        session_id="dynamic-fanout-parent",
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

    result = await DynamicWorkflowTool().execute(
        {
            "objective": "diagnose ci failure",
            "steps": [
                {
                    "id": "log-map",
                    "task": "scan this chunk for root-cause evidence",
                    "context_handle": "file:ci.log",
                    "fanout": True,
                    "chunk_chars": 1000,
                    "max_chunks": 3,
                    "max_parallel": 2,
                }
            ],
            "max_children": 4,
        },
        ctx,
    )

    assert result.success is True
    assert result.metadata["steps"] == 1
    assert len(result.metadata["child_run_ids"]) == 3
    assert len(backend.requests) == 3
    assert all("Chunk text:" in request.prompt for request in backend.requests)
