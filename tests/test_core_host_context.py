from types import SimpleNamespace

import pytest

from superqode.agent.loop import AgentLoop, AgentConfig, AgentMessage
from superqode.agent.hooks import HookRegistry
from superqode.tools.base import ToolRegistry
from superqode.harness.context_artifacts import ContextArtifactStore
from superqode.harness.core_context import prepare_core_context


def loop(tmp_path):
    core = AgentLoop.__new__(AgentLoop)
    core.config = AgentConfig(provider="fake", model="fixed", working_directory=tmp_path)
    core.session_id = "session"
    core.tools = ToolRegistry.empty()
    core.hooks = HookRegistry()
    core.on_thinking = None
    core._systemone_client = None
    core._current_iteration = 1
    core._tool_output_byte_cap = 4000
    return core


@pytest.mark.asyncio
async def test_core_projection_read_and_disabled_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_CONTEXT_STORE", str(tmp_path / "context.sqlite"))
    core = loop(tmp_path)
    core.config.harness_spec = SimpleNamespace(
        runtime=SimpleNamespace(config={"context": {"mode": "enforce", "recent_messages": 1}})
    )
    original = "body\n" * 4000
    messages = [
        AgentMessage("system", "Safety"),
        AgentMessage("user", "Investigate"),
        AgentMessage(
            "assistant",
            "",
            tool_calls=[
                {"id": "call", "function": {"name": "read_file", "arguments": '{"path":"app.py"}'}}
            ],
        ),
        AgentMessage("tool", original, tool_call_id="call", name="read_file"),
        AgentMessage("assistant", "Next"),
        AgentMessage("user", "Implement"),
    ]
    updated = await prepare_core_context(core, messages)
    assert messages[3].content == original
    assert len(updated[3].content) < len(original)
    reference = core.last_context_selection["decisions"][0]["reference"]
    assert core._context_page(reference, offset=11, limit=29).text == original[11:40]
    restarted = loop(tmp_path)
    await prepare_core_context(restarted, updated)
    assert restarted.tools.get("read_context_chunk") is not None
    assert restarted._context_page(reference, offset=11, limit=29).text == original[11:40]


def test_complete_output_captured_before_core_cap(tmp_path, monkeypatch):
    from superqode.tools.base import ToolResult

    monkeypatch.setenv("SUPERQODE_CONTEXT_STORE", str(tmp_path / "context.sqlite"))
    monkeypatch.setenv("SUPERQODE_CONTEXT_MODE", "shadow")
    core = loop(tmp_path)
    original = "API_KEY=secret\n" + "output" * 5000
    result = core._bound_tool_result(
        "read_file",
        ToolResult(True, original, metadata={"invocation_id": "call"}),
        arguments={"path": "app.py"},
    )
    assert len(result.output) < len(original)
    assert "secret" not in result.output
    reference = result.metadata["context_reference"]
    artifact = ContextArtifactStore(tmp_path / "context.sqlite").describe("session", reference)
    assert artifact.chars > 29_000
    assert "secret" not in core._context_page(reference).text
