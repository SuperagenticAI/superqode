import json
import sys

import pytest

from superqode.providers.request_metrics import measure_request_payload
from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.tools.base import ToolRegistry
from superqode.tools.tool_search import ToolSearchTool
from superqode.tools.composition import ToolComposition
from superqode.harness.pipy_mcp import PiPyMCPTools
from superqode.mcp.client import MCPClientManager
from superqode.benchmarks import (
    BenchmarkTarget,
    BenchmarkTask,
    run_benchmark_suite,
    benchmark_scorecard,
)
from superqode.harness.eval import _aggregate_usage_dicts


def test_deferred_schema_payload_does_not_scale_with_unused_catalog():
    from test_tool_composition import Lookup

    sizes = []
    for count in (0, 10, 100, 1000):
        registry = ToolRegistry()
        registry.register(ToolSearchTool())
        registry.register(Lookup())
        for i in range(count):

            class Extra(Lookup):
                name = f"unused_{i}"

            registry.register(Extra())
            registry.defer(f"unused_{i}")
        tools = [
            ToolDefinition(name=t.name, description=t.description, parameters=t.parameters)
            for t in registry.active_tools()
        ]
        metrics = measure_request_payload(
            [
                Message(role="system", content="fixture instructions"),
                Message(role="user", content="secret prompt"),
            ],
            tools,
        )
        assert "secret prompt" not in str(metrics)
        assert metrics["provider_input_tokens"] is None
        sizes.append(metrics["tool_schema_bytes"])
    assert len(set(sizes)) == 1


def test_pipy_mcp_entry_schema_is_catalog_independent():
    bridge = PiPyMCPTools(MCPClientManager())
    assert len(bridge.tools) == 2
    assert len(json.dumps([dict(t.parameters) for t in bridge.tools])) < 2000


def test_benchmark_uses_fresh_workspaces_and_grades_checks(tmp_path):
    (tmp_path / "counter").write_text("0")
    command = [
        sys.executable,
        "-c",
        'from pathlib import Path; p=Path("counter"); print("start",p.read_text()); p.write_text("1")',
    ]
    task = BenchmarkTask(
        "fixture",
        "go",
        tmp_path,
        expected_text="start 0",
        checks=(
            (
                sys.executable,
                "-c",
                'from pathlib import Path; assert Path("counter").read_text()=="1"',
            ),
        ),
    )
    rows = run_benchmark_suite(
        [task], [BenchmarkTarget("a", command), BenchmarkTarget("b", command)]
    )
    assert all(row["status"] == "passed" and row["workspace_isolated"] for row in rows)
    assert (tmp_path / "counter").read_text() == "0"
    scorecard = benchmark_scorecard(rows)
    assert scorecard["targets"]["a"]["cost_per_solved_task"] is None


def test_incomplete_usage_never_becomes_total_spend():
    usage = _aggregate_usage_dicts(
        [{"tokens_in": 2, "tokens_out": 3, "total_tokens": 5, "cost_usd": 0.1}, {}]
    )
    assert usage["total_tokens"] is None and usage["cost_usd"] is None
    assert usage["observed_cost_usd"] == 0.1
    rows = [
        {"target": "same", "task_id": "case", "status": "failed", "cost_usd": 0.1},
        {"target": "same", "task_id": "case", "status": "passed", "cost_usd": 0.2},
    ]
    assert benchmark_scorecard(rows)["targets"]["same"]["cost_per_solved_task"] == pytest.approx(
        0.3
    )


@pytest.mark.asyncio
async def test_actual_core_gateway_payload_stays_bounded_when_catalog_is_deferred(tmp_path):
    from superqode.agent.loop import AgentLoop, AgentConfig
    from test_harness_usage import UsageGateway
    from test_tool_composition import Lookup

    payloads = []
    for count in (0, 10, 100, 1000):
        registry = ToolRegistry()
        registry.register(ToolSearchTool())
        registry.register(Lookup())
        for i in range(count):

            class Extra(Lookup):
                name = f"unused_{i}"

            registry.register(Extra())
            registry.defer(f"unused_{i}")
        loop = AgentLoop(
            gateway=UsageGateway(),
            tools=registry,
            config=AgentConfig(
                provider="openai", model="gpt-4o-mini", working_directory=tmp_path, max_iterations=1
            ),
        )
        response = await loop.run("Read the repository and report whether any code needs changing.")
        assert response.total_tokens == 17
        payloads.append(loop.last_request_payload)
    assert len({p["tool_schema_bytes"] for p in payloads}) == 1
    assert len({p["system_content_bytes"] for p in payloads}) == 1


def test_partial_token_breakdown_does_not_turn_missing_input_into_zero():
    usage = _aggregate_usage_dicts([{"total_tokens": 5, "tokens_out": 2, "cost_usd": 0.01}])
    assert usage["tokens_in"] is None and usage["tokens_out"] == 2
    assert usage["total_tokens"] == 5
    from superqode.workorders.usage import usage_from_result
    from superqode.workorders import WorkOrderTask

    normalized = usage_from_result(
        {"tokens_out": 2}, task=WorkOrderTask(task_id="task", title="task", goal="task")
    )
    assert normalized.total_tokens is None
