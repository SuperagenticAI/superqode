"""Tests for MCP tool availability in native runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.mcp.types import (
    MCPPrompt,
    MCPPromptArgument,
    MCPPromptMessage,
    MCPPromptResult,
    MCPResource,
    MCPResourceContent,
    MCPTool,
    MCPToolResult,
)
from superqode.providers.gateway.base import GatewayResponse
from superqode.tools.base import ToolRegistry, ToolContext
from superqode.tools.mcp_tools import (
    MCPExecuteTool,
    MCPGetPromptTool,
    MCPListPromptsTool,
    MCPListResourcesTool,
    MCPReadResourceTool,
    MCPSearchTool,
)


class _Gateway:
    async def chat_completion(self, *args, **kwargs):
        return GatewayResponse(content="done")

    async def stream_completion(self, *args, **kwargs):
        if False:
            yield None


@dataclass
class _FakeManager:
    executed: tuple[str, str, dict] | None = None

    def list_all_tools(self):
        return [
            MCPTool(
                name="lookup",
                description="Look up project docs",
                input_schema={"type": "object", "properties": {}},
                server_id="docs",
            )
        ]

    def list_all_resources(self):
        return [
            MCPResource(
                uri="file:///docs/readme.md",
                name="README",
                description="Project README",
                mime_type="text/markdown",
                server_id="docs",
            )
        ]

    async def read_resource(self, server, uri):
        if (server, uri) == ("docs", "file:///docs/readme.md"):
            return MCPResourceContent(uri=uri, mime_type="text/markdown", text="# README")
        return None

    def list_all_prompts(self):
        return [
            MCPPrompt(
                name="review",
                description="Review code",
                arguments=[MCPPromptArgument(name="path", required=True)],
                server_id="docs",
            )
        ]

    async def get_prompt(self, server, prompt, arguments):
        if (server, prompt) == ("docs", "review"):
            return MCPPromptResult(
                description="Review code",
                messages=[MCPPromptMessage(role="user", content=f"Review {arguments['path']}")],
            )
        return None

    async def execute_tool(self, server, tool, arguments):
        self.executed = (server, tool, arguments)
        return MCPToolResult(
            content=[{"type": "text", "text": "found"}],
            is_error=False,
        )


def test_agent_loop_include_mcp_adds_search_and_execute_definitions(tmp_path):
    loop = AgentLoop(
        gateway=_Gateway(),
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="test",
            model="test-model",
            working_directory=tmp_path,
            enable_session_storage=False,
        ),
        include_mcp=True,
    )

    names = {definition.name for definition in loop._get_tool_definitions()}

    assert {
        "mcp_search",
        "mcp_execute",
        "mcp_list_resources",
        "mcp_read_resource",
        "mcp_list_prompts",
        "mcp_get_prompt",
    }.issubset(names)


@pytest.mark.asyncio
async def test_mcp_search_tool_accepts_async_manager_getter(tmp_path):
    manager = _FakeManager()

    async def getter():
        return manager

    result = await MCPSearchTool(getter).execute(
        {"query": "docs"},
        ToolContext(session_id="t", working_directory=tmp_path),
    )

    assert result.success
    assert result.metadata["count"] == 1
    assert result.metadata["tools"][0]["server"] == "docs"


@pytest.mark.asyncio
async def test_mcp_execute_tool_accepts_async_manager_getter(tmp_path):
    manager = _FakeManager()

    async def getter():
        return manager

    result = await MCPExecuteTool(getter).execute(
        {"server": "docs", "tool": "lookup", "arguments": {"q": "x"}},
        ToolContext(session_id="t", working_directory=tmp_path),
    )

    assert result.success
    assert result.output == "found"
    assert manager.executed == ("docs", "lookup", {"q": "x"})


@pytest.mark.asyncio
async def test_mcp_resource_tools_list_and_read_resources(tmp_path):
    manager = _FakeManager()

    async def getter():
        return manager

    ctx = ToolContext(session_id="t", working_directory=tmp_path)
    listed = await MCPListResourcesTool(getter).execute({"server": "docs"}, ctx)
    read = await MCPReadResourceTool(getter).execute(
        {"server": "docs", "uri": "file:///docs/readme.md"},
        ctx,
    )

    assert listed.success
    assert listed.metadata["count"] == 1
    assert listed.metadata["resources"][0]["uri"] == "file:///docs/readme.md"
    assert read.success
    assert read.output == "# README"


@pytest.mark.asyncio
async def test_mcp_prompt_tools_list_and_get_prompts(tmp_path):
    manager = _FakeManager()

    async def getter():
        return manager

    ctx = ToolContext(session_id="t", working_directory=tmp_path)
    listed = await MCPListPromptsTool(getter).execute({"server": "docs"}, ctx)
    prompt = await MCPGetPromptTool(getter).execute(
        {"server": "docs", "prompt": "review", "arguments": {"path": "src/app.py"}},
        ctx,
    )

    assert listed.success
    assert listed.metadata["count"] == 1
    assert listed.metadata["prompts"][0]["arguments"] == ["path"]
    assert prompt.success
    assert "user: Review src/app.py" in prompt.output
