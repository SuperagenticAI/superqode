"""Tests for request_permissions, rubric grading, output-schema, HTML export,
and prompt-based tool calling (tool_call_format wiring)."""

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.rubric import parse_grader_response
from superqode.agent.structured_output import (
    check_output,
    correction_prompt,
    extract_json_document,
    load_schema,
    schema_instruction,
)
from superqode.agent.text_tool_calls import (
    extract_text_tool_calls,
    is_prompt_format,
    render_tool_catalog,
)
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager
from superqode.tools.request_permissions_tool import RequestPermissionsTool


# ---------------------------------------------------- request_permissions


def _manager_with_handler(approve: bool) -> PermissionManager:
    return PermissionManager(
        PermissionConfig(default=Permission.ASK),
        on_permission_request=lambda request: approve,
    )


@pytest.mark.asyncio
async def test_request_permissions_grants_session_allow(tmp_path):
    manager = _manager_with_handler(approve=True)
    ctx = ToolContext(session_id="t", working_directory=tmp_path, permission_manager=manager)
    result = await RequestPermissionsTool().execute(
        {"tools": ["web_fetch"], "justification": "need to read the upstream changelog"},
        ctx,
    )
    assert result.success, result.error
    assert "web_fetch" in result.metadata["granted"]
    # The grant upgrades ASK to ALLOW for the session...
    assert manager.check_permission("web_fetch", {}) == Permission.ALLOW
    # ...but clears with session approvals.
    manager.clear_session_approvals()
    assert manager.check_permission("web_fetch", {}) == Permission.ASK


@pytest.mark.asyncio
async def test_request_permissions_declined(tmp_path):
    manager = _manager_with_handler(approve=False)
    ctx = ToolContext(session_id="t", working_directory=tmp_path, permission_manager=manager)
    result = await RequestPermissionsTool().execute(
        {"tools": ["bash"], "justification": "want to run arbitrary commands freely"},
        ctx,
    )
    assert result.success is False
    assert "bash" in result.metadata["declined"]
    assert manager.check_permission("bash", {"command": "echo hi"}) != Permission.DENY


@pytest.mark.asyncio
async def test_request_permissions_requires_justification(tmp_path):
    manager = _manager_with_handler(approve=True)
    ctx = ToolContext(session_id="t", working_directory=tmp_path, permission_manager=manager)
    result = await RequestPermissionsTool().execute(
        {"tools": ["web_fetch"], "justification": "pls"}, ctx
    )
    assert result.success is False


def test_session_grant_never_overrides_deny():
    config = PermissionConfig(default=Permission.ASK)
    config.tools["dangerous_tool"] = Permission.DENY
    manager = PermissionManager(config)
    manager.grant_session_permission("dangerous_tool")
    assert manager.check_permission("dangerous_tool", {}) == Permission.DENY


# ------------------------------------------------------------ rubric


def test_parse_grader_response_variants():
    assert parse_grader_response('{"verdict": "needs_revision", "feedback": "add tests"}') == (
        "needs_revision",
        "add tests",
    )
    assert parse_grader_response('```json\n{"verdict": "satisfied", "feedback": ""}\n```') == (
        "satisfied",
        "",
    )
    # Fails open: garbage means satisfied (never trap a run).
    assert parse_grader_response("not json")[0] == "satisfied"
    assert parse_grader_response('{"verdict": "weird"}')[0] == "satisfied"


class RubricScriptedGateway(GatewayInterface):
    """Returns work answers and grader verdicts from separate scripts."""

    def __init__(self, answers: List[str], verdicts: List[Dict[str, str]]):
        self.answers = answers
        self.verdicts = verdicts
        self.grader_calls = 0

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        system = next((m for m in messages if m.role == "system"), None)
        if system is not None and "strict reviewer" in str(system.content):
            self.grader_calls += 1
            return GatewayResponse(content=json.dumps(self.verdicts.pop(0)))
        return GatewayResponse(content=self.answers.pop(0))

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        yield StreamChunk(content="x")

    async def test_connection(self, provider, model=None):
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.asyncio
async def test_rubric_revision_loop():
    gateway = RubricScriptedGateway(
        answers=["draft answer", "improved answer"],
        verdicts=[
            {"verdict": "needs_revision", "feedback": "cover the edge cases"},
            {"verdict": "satisfied", "feedback": "ok"},
        ],
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="t", model="m", rubric="must cover edge cases"),
    )
    response = await loop.run("do the work")
    assert response.content == "improved answer"
    assert gateway.grader_calls == 2


@pytest.mark.asyncio
async def test_rubric_round_cap():
    gateway = RubricScriptedGateway(
        answers=["a1", "a2", "a3"],
        verdicts=[{"verdict": "needs_revision", "feedback": "more"}] * 3,
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="t", model="m", rubric="r", max_rubric_rounds=2),
    )
    response = await loop.run("work")
    assert response.content == "a3"  # 2 revision rounds then accept
    assert gateway.grader_calls == 2


# ----------------------------------------------------- structured output


def test_extract_json_document_lenient():
    assert extract_json_document('{"a": 1}') == {"a": 1}
    assert extract_json_document('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_document('Here it is: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    assert extract_json_document("[1, 2]") == [1, 2]
    assert extract_json_document("no json") is None


def test_check_output_validates(tmp_path):
    schema = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}, "score": {"type": "number"}},
        "required": ["verdict", "score"],
    }
    payload, errors = check_output('{"verdict": "pass", "score": 0.9}', schema)
    assert errors == []
    assert payload["verdict"] == "pass"

    payload, errors = check_output('{"verdict": "pass"}', schema)
    assert errors and "score" in errors[0]

    payload, errors = check_output("just prose", schema)
    assert payload is None and errors


def test_schema_files_and_prompts(tmp_path):
    schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema))
    loaded = load_schema(path)
    assert loaded == schema
    assert "JSON Schema" in schema_instruction(loaded)
    assert "x" in correction_prompt(["<root>: 'x' is a required property"], loaded)
    with pytest.raises(ValueError):
        load_schema(tmp_path / "missing.json")


# ------------------------------------------------------------ HTML export


def test_html_export_renders_messages(tmp_path):
    from superqode.headless import _render_session_html

    metadata = SimpleNamespace(
        session_id="abc123",
        title="Fix the tests",
        provider="ollama",
        model="gemma4",
        created_at="2026-06-10",
        updated_at="2026-06-10",
        parent_session_id=None,
    )
    messages = [
        SimpleNamespace(role="user", content="hello <world>", tool_name=None),
        SimpleNamespace(role="tool", content="grep output & more", tool_name="grep"),
    ]
    html_doc = _render_session_html(metadata, messages)
    assert html_doc.startswith("<!DOCTYPE html>")
    assert "Fix the tests" in html_doc
    assert "hello &lt;world&gt;" in html_doc  # escaped
    assert "grep output &amp; more" in html_doc
    assert "Tool · grep" in html_doc


# ------------------------------------------------- prompt tool calling


def test_is_prompt_format():
    assert is_prompt_format("prompt") and is_prompt_format("xml")
    assert not is_prompt_format(None)
    assert not is_prompt_format("native")
    assert not is_prompt_format("compact-json")  # native arg-style hint


def test_render_tool_catalog_includes_schema():
    defs = [ToolDefinition(name="read_file", description="Read a file.", parameters={"type": "object"})]
    catalog = render_tool_catalog(defs)
    assert "<tool_call>" in catalog
    assert "read_file" in catalog
    assert '{"type":"object"}' in catalog
    assert render_tool_catalog([]) == ""


def test_extract_text_tool_calls_variants():
    content = 'Let me check.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
    cleaned, calls = extract_text_tool_calls(content)
    assert cleaned == "Let me check."
    assert calls[0]["function"]["name"] == "read_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "a.py"}

    # Python-style JSON inside the block is repaired.
    cleaned, calls = extract_text_tool_calls(
        "<tool_call>{'name': 'grep', 'arguments': {'pattern': 'x'}}</tool_call>"
    )
    assert calls and calls[0]["function"]["name"] == "grep"

    # Malformed blocks stay in the text; nothing extracted.
    cleaned, calls = extract_text_tool_calls("<tool_call>garbage</tool_call>")
    assert calls == []
    assert "<tool_call>" in cleaned

    assert extract_text_tool_calls("no calls here") == ("no calls here", [])


class _EchoTool(Tool):
    read_only = True

    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "Echo the given text back."

    @property
    def parameters(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, args, ctx):
        return ToolResult(success=True, output=f"echoed:{args.get('text', '')}")


class PromptToolGateway(GatewayInterface):
    """First response emits an in-text tool call; second gives the answer."""

    def __init__(self):
        self.calls: List[List[Message]] = []
        self.tools_seen: List[Any] = []
        self.responses = [
            GatewayResponse(
                content='<tool_call>{"name": "echo", "arguments": {"text": "hi"}}</tool_call>'
            ),
            GatewayResponse(content="done"),
        ]

    async def chat_completion(self, messages, model, provider=None, tools=None, **kwargs):
        self.calls.append(list(messages))
        self.tools_seen.append(tools)
        return self.responses.pop(0)

    async def stream_completion(self, messages, model, provider=None, tools=None, **kwargs):
        self.calls.append(list(messages))
        self.tools_seen.append(tools)
        response = self.responses.pop(0)
        yield StreamChunk(content=response.content)

    async def test_connection(self, provider, model=None):
        return {"ok": True}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


@pytest.mark.asyncio
async def test_prompt_tool_mode_end_to_end():
    gateway = PromptToolGateway()
    registry = ToolRegistry()
    registry.register(_EchoTool())
    loop = AgentLoop(
        gateway=gateway,
        tools=registry,
        config=AgentConfig(provider="t", model="m", tool_call_format="prompt"),
    )
    response = await loop.run("say hi")

    assert response.content == "done"
    assert response.tool_calls_made == 1
    # No native tools were ever sent...
    assert all(t is None for t in gateway.tools_seen)
    # ...but the system prompt carried the catalog and call format.
    system = next(m for m in gateway.calls[0] if m.role == "system")
    assert "<tool_call>" in str(system.content)
    assert "echo" in str(system.content)
    # The tool actually executed and its result reached the second call.
    assert any("echoed:hi" in str(m.content) for m in gateway.calls[1])


@pytest.mark.asyncio
async def test_native_mode_unchanged():
    gateway = PromptToolGateway()
    gateway.responses = [GatewayResponse(content="plain answer")]
    registry = ToolRegistry()
    registry.register(_EchoTool())
    loop = AgentLoop(
        gateway=gateway,
        tools=registry,
        config=AgentConfig(provider="t", model="m"),  # native default
    )
    response = await loop.run("inspect the repo and echo the result")
    assert response.content == "plain answer"
    assert gateway.tools_seen[0] is not None  # native tools sent
    system = next(m for m in gateway.calls[0] if m.role == "system")
    assert "<tool_call>" not in str(system.content)
