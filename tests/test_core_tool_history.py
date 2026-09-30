"""Core multi-turn requests must keep provider-valid tool IDs across JSONL history."""

import json

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage, repair_dangling_tool_calls
from superqode.providers.gateway.base import GatewayInterface, GatewayResponse, StreamChunk
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
from superqode.tools.base import Tool, ToolRegistry, ToolResult


CALL = {
    "id": "call_echo_1",
    "type": "function",
    "function": {"name": "echo", "arguments": '{"text":"project version"}'},
}


class Echo(Tool):
    name = "echo"
    description = "Return text."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, args, ctx):
        return ToolResult(success=True, output=args["text"])


class StrictGateway(GatewayInterface):
    def __init__(self):
        self.calls = []

    def validate(self, messages):
        wire = LiteLLMGateway()._convert_messages(messages)
        pending = set()
        for message in wire:
            if message["role"] == "assistant":
                pending = {call["id"] for call in message.get("tool_calls", [])}
            elif message["role"] == "tool":
                identifier = message.get("tool_call_id")
                assert isinstance(identifier, str) and identifier.strip(), wire
                assert identifier in pending, wire
                pending.remove(identifier)
        self.calls.append(wire)

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.validate(messages)
        return (
            GatewayResponse(content="", tool_calls=[CALL])
            if len(self.calls) == 1
            else GatewayResponse(content="done")
        )

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        self.validate(messages)
        if len(self.calls) == 1:
            yield StreamChunk(tool_calls=[dict(CALL, index=0)], finish_reason="tool_calls")
        else:
            yield StreamChunk(content="done", finish_reason="stop")

    async def test_connection(self, provider, model=None):
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.parametrize("streaming", [False, True])
async def test_three_turns_keep_tool_ids_and_reload_from_disk(tmp_path, streaming):
    registry = ToolRegistry()
    registry.register(Echo())
    gateway = StrictGateway()
    config = AgentConfig(
        provider="openrouter",
        model="test/model",
        enable_session_storage=True,
        session_storage_dir=str(tmp_path / "sessions"),
        session_id="multi-turn",
    )
    loop = AgentLoop(gateway=gateway, tools=registry, config=config)

    async def turn(agent, text):
        if streaming:
            content = "".join([chunk async for chunk in agent.run_streaming(text)])
            assert content == "done"
        else:
            result = await agent.run(text)
            assert result.content == "done" and not result.error

    await turn(loop, "Use echo to inspect the project version")
    stored = loop._session_manager.get_messages()
    tool_result = next(message for message in stored if message.role == "tool")
    assert tool_result.tool_call_id == "call_echo_1"
    await turn(loop, "What is the current version of this project?")
    reloaded = AgentLoop(gateway=gateway, tools=registry, config=config)
    await turn(reloaded, "Tell me the version again")
    assert len(gateway.calls) == 4


def test_legacy_idless_result_is_repaired_without_mutating_history():
    source = [
        AgentMessage("assistant", "", tool_calls=[CALL]),
        AgentMessage("tool", "old result", name="echo"),
    ]
    repaired = repair_dangling_tool_calls(source)
    assert repaired[1].tool_call_id == "call_echo_1"
    assert repaired[1].content == "old result"
    assert source[1].tool_call_id is None
    assert repair_dangling_tool_calls(repaired) == repaired


async def test_legacy_jsonl_session_can_continue(tmp_path):
    config = AgentConfig(
        provider="openrouter",
        model="test/model",
        enable_session_storage=True,
        session_storage_dir=str(tmp_path),
        session_id="legacy",
    )
    gateway = StrictGateway()
    loop = AgentLoop(gateway=gateway, tools=ToolRegistry(), config=config)
    loop._session_manager.add_user_message("Inspect the project")
    loop._session_manager.add_assistant_message("", [CALL])
    loop._session_manager.add_tool_result("echo", "old version")
    loop._session_manager.add_assistant_message("done")
    # Simulate an older JSONL record with no newly introduced field.
    path = tmp_path / "legacy.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row.pop("tool_call_id", None)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    gateway.calls.append([])  # This turn should answer, rather than request a new tool.
    result = await loop.run("What is the current version?")
    assert result.content == "done" and not result.error
    assert any(message.get("tool_call_id") == "call_echo_1" for message in gateway.calls[-1])


@pytest.mark.parametrize("missing", [None, "", " "])
def test_legacy_parallel_results_match_names_and_keep_existing_ids(missing):
    other = {
        "id": "call_other",
        "type": "function",
        "function": {"name": "other", "arguments": "{}"},
    }
    source = [
        AgentMessage("assistant", "", tool_calls=[CALL, other]),
        AgentMessage("tool", "second tool output", name="other", tool_call_id=missing),
        AgentMessage("tool", "first tool output", name="echo", tool_call_id="call_echo_1"),
    ]
    repaired = repair_dangling_tool_calls(source)
    assert [(item.tool_call_id, item.content) for item in repaired[1:]] == [
        ("call_other", "second tool output"),
        ("call_echo_1", "first tool output"),
    ]
    assert source[1].tool_call_id == missing


def test_orphaned_result_from_truncated_history_is_retained_as_context():
    source = [
        AgentMessage("tool", "earlier project version", tool_call_id="lost-call", name="read")
    ]
    repaired = repair_dangling_tool_calls(source)
    assert repaired[0].role == "user"
    assert repaired[0].content == "earlier project version"
    assert source[0].role == "tool"


async def test_mechanical_compaction_preserves_protocol_metadata(monkeypatch):
    monkeypatch.setenv("SUPERQODE_JEV_CONTEXT", "off")
    monkeypatch.setenv("SUPERQODE_AUTO_COMPACT", "1")
    loop = AgentLoop(
        gateway=StrictGateway(),
        tools=ToolRegistry(),
        config=AgentConfig(provider="openrouter", model="test/model", context_window=8192),
    )
    messages = [
        AgentMessage("system", "instructions"),
        AgentMessage("user", "inspect project"),
        AgentMessage("assistant", "", tool_calls=[CALL], reasoning_content="inspect"),
        AgentMessage("tool", "old version", tool_call_id="call_echo_1", name="echo"),
        AgentMessage("assistant", "done"),
    ]

    async def no_summary(*args, **kwargs):
        return None

    monkeypatch.setattr("superqode.agent.compaction.compact_history", no_summary)
    monkeypatch.setattr(loop.context_manager, "count_tokens", lambda messages: 100000)
    monkeypatch.setattr(loop.context_manager, "prune_history", lambda messages: messages)
    compacted = await loop._maybe_summarize(messages)
    tool = next(item for item in compacted if item.role == "tool")
    assert tool.tool_call_id == "call_echo_1" and tool.name == "echo"
    assert next(item for item in compacted if item.tool_calls).reasoning_content == "inspect"
    StrictGateway().validate(loop._convert_messages(compacted))
