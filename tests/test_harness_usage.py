from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop, AgentResponse
from superqode.harness import (
    FileHarnessStore,
    HarnessBackendResult,
    get_harness_template,
    init_harness,
    run_harness_eval,
)
from superqode.providers.gateway.base import (
    Cost,
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
    Usage,
)
from superqode.tools.base import ToolRegistry


class UsageGateway(GatewayInterface):
    async def chat_completion(
        self,
        messages: list[Message],
        model: str,
        provider: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> GatewayResponse:
        return GatewayResponse(
            content="ok",
            usage=Usage(prompt_tokens=12, completion_tokens=5, total_tokens=17),
            cost=Cost(input_cost=0.0012, output_cost=0.001, total_cost=0.0022),
        )

    async def stream_completion(
        self,
        messages: list[Message],
        model: str,
        provider: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        yield StreamChunk(content="ok")

    async def test_connection(self, provider: str, model: str | None = None) -> dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"


class UsageBackend:
    name = "usage-backend"

    async def run(self, request):
        response = AgentResponse(
            content="ok",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
            input_tokens=20,
            output_tokens=7,
            total_tokens=27,
            cost_usd=0.0034,
            cost_currency="USD",
        )
        return HarnessBackendResult(response=response, backend=self.name, runtime="fake")


@pytest.mark.asyncio
async def test_agent_loop_aggregates_gateway_usage():
    loop = AgentLoop(
        gateway=UsageGateway(),
        tools=ToolRegistry.default(),
        config=AgentConfig(provider="test", model="model", max_iterations=1),
    )

    response = await loop.run("say ok")

    assert response.content == "ok"
    assert response.input_tokens == 12
    assert response.output_tokens == 5
    assert response.total_tokens == 17
    assert response.cost_usd == 0.0022
    assert response.cost_currency == "USD"


@pytest.mark.asyncio
async def test_harness_run_end_emits_usage_metadata(monkeypatch, tmp_path: Path):
    backend = UsageBackend()
    events = []
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    kernel = await init_harness(
        get_harness_template("no-tool"),
        event_callback=events.append,
        store=FileHarnessStore(tmp_path / "store"),
    )
    session = await kernel.session("usage-session")

    result = await session.prompt(
        "say ok", provider="test", model="model", working_directory=tmp_path
    )

    assert result.tokens_in == 20
    assert result.tokens_out == 7
    assert result.total_tokens == 27
    assert result.cost_usd == 0.0034
    run_end = events[-1]
    assert run_end.type == "run_end"
    assert run_end.data["tokens_in"] == 20
    assert run_end.data["tokens_out"] == 7
    assert run_end.data["total_tokens"] == 27
    assert run_end.data["cost_usd"] == 0.0034


@pytest.mark.asyncio
async def test_harness_eval_aggregates_usage(monkeypatch, tmp_path: Path):
    backend = UsageBackend()
    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: backend)
    spec_path = tmp_path / "harness.yaml"
    tasks_path = tmp_path / "tasks.yaml"
    spec_path.write_text("name: demo\ninherits: no-tool\n", encoding="utf-8")
    tasks_path.write_text(
        "tasks:\n  - id: smoke\n    prompt: say ok\n    expect_contains: ok\n",
        encoding="utf-8",
    )

    payload = await run_harness_eval(
        spec_paths=[spec_path],
        tasks_path=tasks_path,
        provider="test",
        model="model",
        working_dir=tmp_path,
        live=True,
    )

    variant = payload["variants"][0]
    task = variant["tasks"][0]
    assert task["usage"]["total_tokens"] == 27
    assert task["cost_usd"] == 0.0034
    assert variant["usage"]["tokens_in"] == 20
    assert variant["usage"]["tokens_out"] == 7
    assert variant["usage"]["total_tokens"] == 27
    assert variant["usage"]["cost_usd"] == 0.0034
    assert variant["tokens_per_success"] == 27.0
    assert variant["cost_per_success"] == 0.0034
