"""No model runs: fake gateways exercise the actual native loop boundaries."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from superqode.agent.local_reliability import (
    LEAN_TOOLS,
    ToolRetryBudget,
    compact_schema,
    extract_local_calls,
    lean_profile,
    repair_arguments,
)
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.loop_guard import DoomLoopAbort
from superqode.agent.system_prompts import SystemPromptLevel
from superqode.local.diagnostics import counters
from superqode.providers.gateway.base import GatewayResponse, StreamChunk
from superqode.tools.base import ToolRegistry

SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"path":"x.py"}\n```',
        '{"path":"x.py",}',
        "{'path':'x.py'}",
        '{"file_path":"x.py"}',
        '{"filename":"x.py"}',
    ],
)
def test_each_argument_repair_case(raw):
    args, error, fixed = repair_arguments(raw, SCHEMA)
    assert args == {"path": "x.py"} and error is None and fixed


def test_trailing_comma_repair_preserves_string_contents():
    args, error, fixed = repair_arguments(
        '{"path":",}", "flag":true,}',
        {"type": "object", "properties": {"path": {"type": "string"}, "flag": {"type": "boolean"}}},
    )
    assert args == {"path": ",}", "flag": True} and error is None and fixed


@pytest.mark.parametrize(
    "raw", ['{"path":1}', "{}", '{"unknown":"x"}', '{"path":"x","file_path":"y"}']
)
def test_invalid_or_conflicting_arguments_stay_invalid(raw):
    assert repair_arguments(raw, SCHEMA)[1]


def test_ambiguous_alias_is_not_guessed():
    schema = {"type": "object", "properties": {"path": {}, "file_path": {}}}
    assert repair_arguments('{"filename":"x"}', schema)[1]


@pytest.mark.parametrize(
    "content",
    [
        '{"name":"read_file","arguments":{"path":"x.py"}}',
        '```json\n{"name":"read_file","arguments":{"path":"x.py",}}\n```',
        '<tool_call>{"function":{"name":"read_file","arguments":"{\\"path\\":\\"x.py\\"}"}}</tool_call>',
    ],
)
def test_text_emitted_tool_calls(content):
    text, calls = extract_local_calls(content)
    assert text == "" and len(calls) == 1
    function = calls[0]["function"]
    assert function["name"] == "read_file"
    assert repair_arguments(function["arguments"], SCHEMA)[0] == {"path": "x.py"}


def test_explanatory_prose_and_arbitrary_json_are_not_executed():
    for content in [
        'Here is an example: {"name":"read_file","arguments":{"path":"x"}}',
        '```json\n{"greeting":"hello"}\n```',
        '{"name":"read_file","arguments":{"path":"x"}} then an example {"other":1}',
    ]:
        assert extract_local_calls(content) == (content, [])


def test_invalid_explicit_text_call_is_not_dropped_or_emptied():
    _, calls = extract_local_calls(
        '<tool_call>{"name":"read_file","arguments":"broken"}</tool_call>'
    )
    assert calls[0]["function"]["arguments"] == "broken"
    assert repair_arguments(calls[0]["function"]["arguments"], SCHEMA)[1]


@pytest.mark.parametrize(
    "provider,model,context,expected",
    [
        ("ollama", "qwen3.5:4b", 32768, True),
        ("lmstudio", "qwen/qwen3.5-9b", 32768, True),
        ("ollama", "some-7b-q4", 32768, True),
        ("lmstudio", "loaded-alias", 8192, True),
        ("ollama", "qwen3.6:35b", 16384, False),
        ("remote", "some-4b", 4096, False),
    ],
)
def test_profile_selection(provider, model, context, expected):
    assert lean_profile(provider, model, context) is expected


def test_compact_schema_preserves_constraints_and_source():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer", "minimum": 2, "description": "x" * 200}},
        "required": ["x"],
        "additionalProperties": False,
    }
    compact = compact_schema(schema)
    assert len(compact["properties"]["x"]["description"]) == 96
    assert len(schema["properties"]["x"]["description"]) == 200
    assert compact["required"] == ["x"] and compact["additionalProperties"] is False
    assert compact["properties"]["x"]["minimum"] == 2


def test_retry_budget_is_capped_at_two():
    budget = ToolRetryBudget()
    assert [budget.correction() for _ in range(5)] == [True, True, False, False, False]
    assert budget.used == 2


def make_loop(tmp_path, **options):
    config = AgentConfig(
        provider="ollama",
        model="qwen3.5:4b",
        context_window=8192,
        working_directory=tmp_path,
        enable_session_storage=False,
        **options,
    )
    loop = AgentLoop(gateway=MagicMock(), tools=ToolRegistry.default(), config=config)
    loop._effective_context_window = lambda: 8192
    loop._ensure_context_window = AsyncMock(return_value=8192)
    return loop


def call(arguments, name="read_file"):
    return {"id": "one", "type": "function", "function": {"name": name, "arguments": arguments}}


def test_native_loop_uses_compact_tools_preserves_custom_prompt_and_counts_schemas(tmp_path):
    from superqode.local.context_contract import estimate_tokens

    loop = make_loop(
        tmp_path,
        system_prompt_level=SystemPromptLevel.FULL,
        custom_system_prompt="Keep this user instruction.",
    )
    tools = loop._get_tool_definitions()
    assert set(t.name for t in tools) <= LEAN_TOOLS
    assert len(tools) < len(loop.tools.list())
    assert "Keep this user instruction." in loop._system_prompt_for_run()
    assert "Work in small steps." in loop._system_prompt_for_run()
    messages = [{"role": "user", "content": "edit a file"}]
    assert estimate_tokens(messages, [vars(t) for t in tools]) > estimate_tokens(messages)


@pytest.mark.asyncio
async def test_invalid_batch_never_executes_valid_sibling_and_stops_on_third(tmp_path):
    loop = make_loop(tmp_path)
    loop._execute_tool = AsyncMock()
    batch = [call('{"path":"x"}'), call('{"path":5}')]
    for _ in range(2):
        results = await loop._execute_tool_batch(batch)
        assert all(not r[3].success for r in results)
    with pytest.raises(DoomLoopAbort, match="two corrective retries"):
        await loop._execute_tool_batch(batch)
    loop._execute_tool.assert_not_awaited()
    assert counters()["corrective_retries"] == 2
    assert counters()["retry_limit_hits"] == 1


@pytest.mark.asyncio
async def test_hidden_tool_cannot_execute_even_via_nested_dispatch(tmp_path):
    loop = make_loop(tmp_path)
    result = await loop._execute_tool("batch", {})
    assert not result.success and "lean mode" in result.error


@pytest.mark.parametrize("mode", ["disabled", "plan"])
def test_text_repair_does_not_enable_tools_in_no_tool_modes(tmp_path, mode):
    loop = make_loop(tmp_path, tools_enabled=mode != "disabled", plan_mode=mode == "plan")
    content = '<tool_call>{"name":"read_file","arguments":{"path":"x"}}</tool_call>'
    assert loop._extract_prompt_tool_calls(content, None) == (content, None)


@pytest.mark.asyncio
async def test_non_streaming_loop_retries_exactly_twice(tmp_path):
    loop = make_loop(tmp_path, max_iterations=10)
    loop.gateway.chat_completion = AsyncMock(
        side_effect=[GatewayResponse(content="", tool_calls=[call("broken")]) for _ in range(5)]
    )
    response = await loop.run("Read solution.py using read_file")
    assert loop.gateway.chat_completion.await_count == 3
    assert response.stopped_reason == "loop_detected"
    assert "two corrective retries" in response.error


@pytest.mark.asyncio
async def test_streaming_loop_retries_exactly_twice(tmp_path):
    loop = make_loop(tmp_path, max_iterations=10)
    count = 0

    async def stream(*args, **kwargs):
        nonlocal count
        count += 1
        yield StreamChunk(tool_calls=[call("broken")])

    loop.gateway.stream_completion = stream
    output = "".join(
        [part async for part in loop.run_streaming("Read solution.py using read_file")]
    )
    assert count == 3
    assert "two corrective retries" in output


def test_counters_are_local_aggregate_only_and_visible_in_context_status(tmp_path):
    counters("repaired_calls")
    loop = make_loop(tmp_path)
    data = loop._context_status()["local_reliability"]
    assert data["lean_mode"] is True and data["counters"]["repaired_calls"] == 1
    saved = (tmp_path / ".superqode/local-reliability.json").read_text()
    assert "qwen" not in saved and "prompt" not in saved
    assert json.loads(saved)["repaired_calls"] == 1


def test_lean_profile_keeps_allowed_deferred_helpers_but_not_broad_discovery(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_DEFERRED_TOOLS", "all")
    loop = make_loop(tmp_path)
    from superqode.tools.shell_session import ShellSessionTool
    from superqode.tools.request_permissions_tool import RequestPermissionsTool

    loop.tools.register(ShellSessionTool())
    loop.tools.register(RequestPermissionsTool())
    loop.tools.defer("shell_session", "request_permissions")
    names = {d.name for d in loop._get_tool_definitions()}
    assert {"read_file", "edit_file", "shell_session", "request_permissions"} <= names
    assert "tool_search" not in names and "mcp_execute" not in names


@pytest.mark.asyncio
async def test_repaired_arguments_reach_execution_and_live_history(tmp_path):
    loop = make_loop(tmp_path)
    from superqode.tools.base import ToolResult

    loop._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="fixture"))
    tc = call('```json\n{"file_path":"solution.py",}\n```')
    result = await loop._execute_tool_batch([tc])
    assert result[0][3].success
    assert json.loads(tc["function"]["arguments"]) == {"path": "solution.py"}
    assert loop._execute_tool.call_args.args[1] == {"path": "solution.py"}


def test_schema_compaction_never_changes_literal_instance_data():
    literal = {"description": "x" * 220, "other": [1, 2]}
    schema = {
        "type": "object",
        "const": literal,
        "default": literal,
        "enum": [literal],
        "properties": {"description": {"const": "z" * 220, "description": "y" * 220}},
    }
    result = compact_schema(schema)
    assert (
        result["const"] == literal and result["default"] == literal and result["enum"] == [literal]
    )
    assert result["properties"]["description"]["const"] == "z" * 220
    assert len(result["properties"]["description"]["description"]) == 96


def test_non_json_literal_values_and_remote_schema_references_are_not_accepted():
    assert repair_arguments("{'x': {1, 2}}", {"type": "object", "additionalProperties": True})[1]
    assert repair_arguments('{"x": NaN}', {"type": "object", "additionalProperties": True})[1]
    assert repair_arguments('{"path":"x"}', {"$ref": "https://example.com/schema.json"})[1]


def test_literal_reference_is_not_treated_as_a_schema_fetch():
    value = {"$ref": "https://example.com/not-a-schema-fetch"}
    schema = {"type": "object", "properties": {"$ref": {"type": "string"}}, "const": value}
    args, error, _ = repair_arguments(value, schema)
    assert args == value and error is None


def test_prompt_mode_parser_preserves_invalid_arguments_for_correction():
    from superqode.agent.text_tool_calls import extract_text_tool_calls

    _, calls = extract_text_tool_calls(
        '<tool_call>{"name":"get_context_remaining","arguments":"broken"}</tool_call>'
    )
    assert calls[0]["function"]["arguments"] == "broken"


def test_scoped_file_tool_aliases_remain_in_the_lean_catalog(tmp_path):
    from types import SimpleNamespace

    loop = make_loop(tmp_path)
    loop.tools = ToolRegistry.empty()
    for name in ("read", "edit"):
        loop.tools.register(
            SimpleNamespace(name=name, description="Scoped file operation", parameters=SCHEMA)
        )
    loop._cached_tool_defs_version = -1
    assert {d.name for d in loop._get_tool_definitions()} == {"read", "edit"}
    assert loop._prepare_tool_call(call('{"path":"fixture.txt"}', name="read"))[3] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_invalid_batch_accepts_sync_and_async_observer_callbacks(tmp_path, asynchronous):
    from unittest.mock import Mock

    loop = make_loop(tmp_path)
    observer = AsyncMock if asynchronous else Mock
    loop.on_tool_call = observer(return_value=None)
    loop.on_tool_result = observer(return_value=None)
    results = await loop._execute_tool_batch([call("invalid json")])
    assert not results[0][3].success
    loop.on_tool_call.assert_called_once()
    loop.on_tool_result.assert_called_once()
