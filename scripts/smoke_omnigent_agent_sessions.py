"""Smoke test Omnigent-style import plus delegated agent sessions.

This script is intentionally offline: it uses a fake gateway and does not
connect to the example MCP server. It proves the local plumbing that should not
require credentials:

- Omnigent-style YAML imports into HarnessSpec.
- MCP declarations are preserved in runtime and child-agent config.
- Agent-valued tools compile into delegated child AgentSpecs.
- agent_session can start, resume, send, and wait with retained child context.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.harness.omnigent_importer import import_omnigent_agent
from superqode.providers.gateway.base import GatewayInterface, GatewayResponse, StreamChunk
from superqode.tools import ToolContext, ToolRegistry
from superqode.tools.harness_agent_session import AgentSessionTool


class RecordingGateway(GatewayInterface):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.calls.append({"messages": list(messages), "model": model, "provider": provider})
        last_user = next((item for item in reversed(messages) if item.role == "user"), None)
        return GatewayResponse(content=f"{model}: {last_user.content if last_user else ''}")

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        yield StreamChunk(content="ok")

    async def test_connection(self, provider, model=None) -> dict[str, Any]:
        return {"ok": True}

    def get_model_string(self, provider, model) -> str:
        return f"{provider}/{model}"


def _agent_yaml() -> dict[str, Any]:
    return {
        "name": "smoke_supervisor",
        "prompt": "Coordinate specialist child agents.",
        "executor": {"harness": "builtin", "model": "parent-model"},
        "tools": {
            "docs": {
                "type": "mcp",
                "url": "https://example.com/mcp",
                "tools": ["search_docs"],
            },
            "researcher": {
                "type": "agent",
                "description": "Research context.",
                "prompt": "You are the researcher.",
                "executor": {"model": "research-model"},
                "tools": {
                    "repo_search": "inherit",
                    "docs": {
                        "type": "mcp",
                        "url": "https://example.com/mcp",
                        "tools": ["search_docs"],
                    },
                },
                "max_iterations": 4,
            },
            "coder": {
                "type": "agent",
                "description": "Implement changes.",
                "prompt": "You are the coder.",
                "executor": {"model": "coder-model"},
                "tools": {"read_file": "inherit"},
                "pass_history": True,
            },
            "reviewer": {
                "type": "agent",
                "description": "Review changes.",
                "prompt": "You are the reviewer.",
                "executor": {"model": "review-model"},
                "tools": {"repo_search": "inherit"},
                "pass_history": True,
            },
        },
    }


def _ctx(loop: AgentLoop, workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="parent",
        working_directory=workspace,
        harness_spec=loop.config.harness_spec,
        peer_manager=loop._get_peer_manager(),
    )


async def _exercise_sessions(spec, workspace: Path) -> None:
    first_gateway = RecordingGateway()
    first_loop = AgentLoop(
        gateway=first_gateway,
        tools=ToolRegistry.coding(),
        config=AgentConfig(
            provider="test",
            model="parent-model",
            harness_spec=spec,
            session_id="parent",
            session_storage_dir=str(workspace / "sessions"),
        ),
    )
    tool = AgentSessionTool()
    started = await tool.execute(
        {
            "action": "start",
            "agent": "researcher",
            "message": "first research pass",
            "session_id": "researcher-smoke",
        },
        _ctx(first_loop, workspace),
    )
    assert started.success, started.error
    waited = await tool.execute(
        {"action": "wait", "agent": "researcher-smoke", "timeout_s": 10},
        _ctx(first_loop, workspace),
    )
    assert waited.success, waited.error
    assert "research-model: first research pass" in waited.output
    await first_loop._get_peer_manager().close_all()

    second_gateway = RecordingGateway()
    second_loop = AgentLoop(
        gateway=second_gateway,
        tools=ToolRegistry.coding(),
        config=AgentConfig(
            provider="test",
            model="parent-model",
            harness_spec=spec,
            session_id="parent",
            session_storage_dir=str(workspace / "sessions"),
        ),
    )
    second_ctx = _ctx(second_loop, workspace)
    resumed = await tool.execute(
        {"action": "resume", "agent": "researcher", "session_id": "researcher-smoke"},
        second_ctx,
    )
    assert resumed.success, resumed.error
    sent = await tool.execute(
        {"action": "send", "agent": "researcher-smoke", "message": "follow up"},
        second_ctx,
    )
    assert sent.success, sent.error
    followup = await tool.execute(
        {"action": "wait", "agent": "researcher-smoke", "timeout_s": 10},
        second_ctx,
    )
    assert followup.success, followup.error
    assert "research-model: follow up" in followup.output
    messages = second_gateway.calls[0]["messages"]
    assert any(item.role == "user" and item.content == "first research pass" for item in messages)
    assert any(item.role == "user" and item.content == "follow up" for item in messages)
    await second_loop._get_peer_manager().close_all()


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="superqode-omnigent-smoke-") as tmp:
        workspace = Path(tmp)
        source = workspace / "agent.yaml"
        source.write_text(yaml.safe_dump(_agent_yaml(), sort_keys=False), encoding="utf-8")

        spec = import_omnigent_agent(source)
        assert not isinstance(spec, Path)
        assert spec.runtime.config["mcp_servers"]["docs"]["url"] == "https://example.com/mcp"
        assert spec.agents[0].delegates_to == ("researcher", "coder", "reviewer")

        researcher = next(agent for agent in spec.agents if agent.id == "researcher")
        assert researcher.tools == ("repo_search", "docs")
        assert researcher.config["mcp_servers"]["docs"]["tools"] == ["search_docs"]

        await _exercise_sessions(spec, workspace)

    print("Omnigent agent-session smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
