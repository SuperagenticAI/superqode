"""Provider layer: transcript repair, gateway bridge, model resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from conftest import config, context, echo_tool

from superqode.pipy import (
    AbortController,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    run_agent_loop,
)
from superqode.pipy.ai import (
    NO_RESULT_TEXT,
    GatewayStream,
    map_stop_reason,
    resolve_model,
    transform_messages,
)
from superqode.pipy.stream import Context, Model, StreamOptions

MODEL = Model(id="gpt-x", provider="openai", api="openai-completions")


# --------------------------------------------------------------------------- #
# P1 to P3: transcript repair at the boundary
# --------------------------------------------------------------------------- #


def assistant_with_calls(*calls: ToolCall, stop_reason: str = "toolUse") -> AssistantMessage:
    return AssistantMessage(content=list(calls), stop_reason=stop_reason)  # type: ignore[arg-type]


def test_orphaned_tool_call_gets_a_synthetic_result():
    messages = [
        UserMessage(content="go"),
        assistant_with_calls(ToolCall(id="c1", name="read")),
    ]

    result = transform_messages(messages)

    assert isinstance(result[-1], ToolResultMessage)
    assert result[-1].tool_call_id == "c1"
    assert result[-1].text == NO_RESULT_TEXT
    assert result[-1].is_error is True


def test_answered_tool_call_is_left_alone():
    messages = [
        assistant_with_calls(ToolCall(id="c1", name="read")),
        ToolResultMessage(tool_call_id="c1", tool_name="read", content="body"),
    ]

    result = transform_messages(messages)

    assert len(result) == 2
    assert result[1].text == "body"


def test_partially_answered_batch_only_fills_the_gap():
    messages = [
        assistant_with_calls(ToolCall(id="c1", name="read"), ToolCall(id="c2", name="ls")),
        ToolResultMessage(tool_call_id="c1", tool_name="read", content="body"),
        UserMessage(content="never mind"),
    ]

    result = transform_messages(messages)

    synthetic = [m for m in result if isinstance(m, ToolResultMessage) and m.is_error]
    assert [m.tool_call_id for m in synthetic] == ["c2"]
    # The repair lands before the user message, not after it.
    assert isinstance(result[-1], UserMessage)


def test_synthetic_results_are_inserted_before_the_next_assistant_turn():
    messages = [
        assistant_with_calls(ToolCall(id="c1", name="read")),
        AssistantMessage(content=[TextContent(text="moving on")]),
    ]

    result = transform_messages(messages)

    assert [type(m).__name__ for m in result] == [
        "AssistantMessage",
        "ToolResultMessage",
        "AssistantMessage",
    ]


@pytest.mark.parametrize("stop_reason", ["error", "aborted"])
def test_failed_assistant_turns_are_dropped(stop_reason):
    messages = [
        UserMessage(content="go"),
        AssistantMessage(content=[TextContent(text="partial")], stop_reason=stop_reason),
        UserMessage(content="try again"),
    ]

    result = transform_messages(messages)

    assert [type(m).__name__ for m in result] == ["UserMessage", "UserMessage"]


def test_empty_assistant_turns_are_dropped():
    messages = [UserMessage(content="go"), AssistantMessage(content=[])]

    assert [type(m).__name__ for m in transform_messages(messages)] == ["UserMessage"]


def test_a_failed_turn_does_not_orphan_the_previous_batch():
    messages = [
        assistant_with_calls(ToolCall(id="c1", name="read")),
        AssistantMessage(content=[TextContent(text="")], stop_reason="error"),
    ]

    result = transform_messages(messages)

    assert [type(m).__name__ for m in result] == ["AssistantMessage", "ToolResultMessage"]


def test_transform_is_a_noop_for_a_clean_transcript():
    messages = [
        UserMessage(content="go"),
        AssistantMessage(content=[TextContent(text="done")]),
    ]

    assert transform_messages(messages) == messages


def test_history_is_not_mutated():
    messages = [assistant_with_calls(ToolCall(id="c1", name="read"))]
    before = list(messages)

    transform_messages(messages)

    assert messages == before


# --------------------------------------------------------------------------- #
# Stop reason mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "stop"),
        ("end_turn", "stop"),
        ("length", "length"),
        ("max_tokens", "length"),
        ("tool_calls", "toolUse"),
        ("tool_use", "toolUse"),
        ("function_call", "toolUse"),
        ("content_filter", "error"),
        ("something_new", "stop"),
    ],
)
def test_stop_reason_mapping(finish_reason, expected):
    assert map_stop_reason(finish_reason, has_tool_calls=False) == expected


def test_missing_finish_reason_infers_from_tool_calls():
    assert map_stop_reason(None, has_tool_calls=True) == "toolUse"
    assert map_stop_reason(None, has_tool_calls=False) == "stop"


@pytest.mark.parametrize("finish_reason", [None, "stop", "end_turn", "stop_sequence"])
def test_tool_calls_win_over_a_plain_stop(finish_reason):
    """Observed against ollama: the call arrives, then a bare stop follows.

    Recording that turn as `stop` would write the wrong stop reason into the
    session file, which is a wire-format break against pi.
    """
    assert map_stop_reason(finish_reason, has_tool_calls=True) == "toolUse"


@pytest.mark.parametrize("finish_reason", ["length", "max_tokens"])
def test_truncation_still_wins_over_tool_calls(finish_reason):
    """The loop refuses tool calls from a truncated message, so length must survive."""
    assert map_stop_reason(finish_reason, has_tool_calls=True) == "length"


def test_an_error_still_wins_over_tool_calls():
    assert map_stop_reason("content_filter", has_tool_calls=True) == "error"


# --------------------------------------------------------------------------- #
# Gateway bridge
# --------------------------------------------------------------------------- #


@dataclass
class Chunk:
    content: str = ""
    role: str | None = None
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: Any = None
    cost: Any = None
    thinking_content: str | None = None


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class FakeCost:
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0


@dataclass
class FakeGateway:
    """Stands in for the LiteLLM gateway, recording what it was asked for.

    ``chunks`` answers the first request. Later requests get an empty stream,
    which reads as a ``stop`` turn. That matters because the agent loop is
    unbounded by design, exactly like pi's: a double that replayed the same
    tool call on every request would spin forever.
    """

    chunks: list[Chunk] = field(default_factory=list)
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def stream_completion(self, **kwargs):
        first_request = not self.calls
        self.calls.append(kwargs)
        chunks = self.chunks if first_request else []
        error = self.error

        async def generate():
            if error is not None:
                raise error
            for chunk in chunks:
                yield chunk

        return generate()


async def collect(stream, model=MODEL, ctx=None, options=None):
    events = []
    async for event in stream(model, ctx or Context("sys", []), options or StreamOptions()):
        events.append(event)
    return events


async def test_text_stream_produces_pi_events():
    gateway = FakeGateway(chunks=[Chunk(content="Hel"), Chunk(content="lo", finish_reason="stop")])

    events = await collect(GatewayStream(gateway))

    assert [e.type for e in events] == [
        "start",
        "text_start",
        "text_delta",
        "text_delta",
        "text_end",
        "done",
    ]
    final = events[-1].message
    assert final.text == "Hello"
    assert final.stop_reason == "stop"
    assert final.provider == "openai" and final.model == "gpt-x"


async def test_thinking_is_streamed_before_text():
    gateway = FakeGateway(
        chunks=[
            Chunk(thinking_content="let me see"),
            Chunk(content="answer", finish_reason="stop"),
        ]
    )

    events = await collect(GatewayStream(gateway))

    assert [e.type for e in events] == [
        "start",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "text_start",
        "text_delta",
        "text_end",
        "done",
    ]
    assert events[-1].message.thinking_text == "let me see"


async def test_tool_call_assembled_from_argument_deltas():
    gateway = FakeGateway(
        chunks=[
            Chunk(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "read"}}]),
            Chunk(tool_calls=[{"index": 0, "function": {"arguments": '{"path"'}}]),
            Chunk(
                tool_calls=[{"index": 0, "function": {"arguments": ': "a.py"}'}}],
                finish_reason="tool_calls",
            ),
        ]
    )

    events = await collect(GatewayStream(gateway))

    final = events[-1].message
    assert final.stop_reason == "toolUse"
    assert len(final.tool_calls) == 1
    call = final.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("c1", "read", {"path": "a.py"})


async def test_multiple_tool_calls_keep_their_order():
    gateway = FakeGateway(
        chunks=[
            Chunk(
                tool_calls=[
                    {"index": 0, "id": "c1", "function": {"name": "read", "arguments": "{}"}},
                    {"index": 1, "id": "c2", "function": {"name": "ls", "arguments": "{}"}},
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    events = await collect(GatewayStream(gateway))

    assert [c.name for c in events[-1].message.tool_calls] == ["read", "ls"]


async def test_unparsable_tool_arguments_do_not_crash_the_stream():
    gateway = FakeGateway(
        chunks=[
            Chunk(
                tool_calls=[
                    {"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"pa'}}
                ],
                finish_reason="length",
            )
        ]
    )

    events = await collect(GatewayStream(gateway))

    final = events[-1].message
    assert final.stop_reason == "length"
    assert final.tool_calls[0].arguments == {}


async def test_usage_and_cost_are_carried_onto_the_final_message():
    gateway = FakeGateway(
        chunks=[
            Chunk(content="hi"),
            Chunk(
                finish_reason="stop",
                usage=FakeUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                cost=FakeCost(input_cost=0.01, output_cost=0.02, total_cost=0.03),
            ),
        ]
    )

    events = await collect(GatewayStream(gateway))

    usage = events[-1].message.usage
    assert (usage.input, usage.output, usage.total_tokens) == (10, 4, 14)
    assert usage.cost.total == 0.03


async def test_provider_failure_becomes_an_error_event_not_an_exception():
    gateway = FakeGateway(error=RuntimeError("rate limited"))

    events = await collect(GatewayStream(gateway))

    assert events[-1].type == "error"
    assert events[-1].error.stop_reason == "error"
    assert events[-1].error.error_message == "rate limited"


async def test_partial_text_is_preserved_when_the_provider_fails_mid_stream():
    class Failing(FakeGateway):
        def stream_completion(self, **kwargs):
            async def generate():
                yield Chunk(content="partial")
                raise RuntimeError("connection reset")

            return generate()

    events = await collect(GatewayStream(Failing()))

    assert events[-1].type == "error"
    assert events[-1].error.text == "partial"


async def test_abort_before_the_request():
    controller = AbortController()
    controller.abort()

    events = await collect(
        GatewayStream(FakeGateway()), options=StreamOptions(signal=controller.signal)
    )

    assert events[-1].type == "error"
    assert events[-1].error.stop_reason == "aborted"


async def test_abort_mid_stream():
    controller = AbortController()

    class Aborting(FakeGateway):
        def stream_completion(self, **kwargs):
            async def generate():
                yield Chunk(content="one")
                controller.abort()
                yield Chunk(content="two")

            return generate()

    events = await collect(
        GatewayStream(Aborting()), options=StreamOptions(signal=controller.signal)
    )

    assert events[-1].type == "error"
    assert events[-1].error.stop_reason == "aborted"
    assert events[-1].error.text == "one"


# -- request construction ---------------------------------------------------- #


async def test_system_prompt_and_transcript_are_sent():
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])
    ctx = Context(
        "you are a test agent",
        [
            UserMessage(content="hello"),
            AssistantMessage(content=[TextContent(text="hi")]),
            UserMessage(content="again"),
        ],
    )

    await collect(GatewayStream(gateway), ctx=ctx)

    sent = gateway.calls[0]["messages"]
    assert [(m.role, m.content) for m in sent] == [
        ("system", "you are a test agent"),
        ("user", "hello"),
        ("assistant", "hi"),
        ("user", "again"),
    ]


async def test_tool_definitions_are_forwarded():
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])
    ctx = Context("sys", [], tools=[echo_tool()])

    await collect(GatewayStream(gateway), ctx=ctx)

    tools = gateway.calls[0]["tools"]
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].parameters["type"] == "object"
    assert gateway.calls[0]["tool_choice"] == "auto"


async def test_no_tools_means_no_tool_choice():
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])

    await collect(GatewayStream(gateway))

    assert gateway.calls[0]["tools"] is None
    assert gateway.calls[0]["tool_choice"] is None


async def test_tool_results_are_sent_with_their_call_id():
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])
    ctx = Context(
        "sys",
        [
            AssistantMessage(content=[ToolCall(id="c1", name="read")], stop_reason="toolUse"),
            ToolResultMessage(tool_call_id="c1", tool_name="read", content="body"),
        ],
    )

    await collect(GatewayStream(gateway), ctx=ctx)

    sent = gateway.calls[0]["messages"]
    assistant = next(m for m in sent if m.role == "assistant")
    assert assistant.tool_calls[0]["id"] == "c1"
    assert assistant.tool_calls[0]["function"]["name"] == "read"
    tool = next(m for m in sent if m.role == "tool")
    assert (tool.tool_call_id, tool.content) == ("c1", "body")


async def test_the_boundary_repair_runs_on_the_way_out():
    """An interrupted transcript is repaired before it reaches the provider."""
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])
    ctx = Context(
        "sys",
        [
            UserMessage(content="go"),
            AssistantMessage(content=[ToolCall(id="c1", name="read")], stop_reason="toolUse"),
        ],
    )

    await collect(GatewayStream(gateway), ctx=ctx)

    sent = gateway.calls[0]["messages"]
    assert sent[-1].role == "tool"
    assert sent[-1].content == NO_RESULT_TEXT


async def test_an_empty_tool_result_still_has_content():
    gateway = FakeGateway(chunks=[Chunk(content="ok", finish_reason="stop")])
    ctx = Context(
        "sys",
        [
            AssistantMessage(content=[ToolCall(id="c1", name="bash")], stop_reason="toolUse"),
            ToolResultMessage(tool_call_id="c1", tool_name="bash", content=""),
        ],
    )

    await collect(GatewayStream(gateway), ctx=ctx)

    tool = next(m for m in gateway.calls[0]["messages"] if m.role == "tool")
    assert tool.content == "(no output)"


# --------------------------------------------------------------------------- #
# End to end through the loop
# --------------------------------------------------------------------------- #


async def test_the_loop_runs_a_tool_through_the_gateway(recorder):
    gateway = FakeGateway(
        chunks=[
            Chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "c1",
                        "function": {"name": "echo", "arguments": '{"value": "x"}'},
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    stream = GatewayStream(gateway)

    messages = await run_agent_loop(
        [UserMessage(content="go")],
        context(tools=[echo_tool()]),
        config(MODEL),
        recorder,
        None,
        stream,
    )

    assert "tool_execution_end" in recorder.types
    result = next(m for m in messages if isinstance(m, ToolResultMessage))
    assert result.text == "echo:x"
    # The second request gets an empty stream, so the run ends there.
    assert recorder.types[-1] == "agent_end"
    assert len(gateway.calls) == 2


async def test_a_gateway_failure_ends_the_run_cleanly(recorder):
    stream = GatewayStream(FakeGateway(error=RuntimeError("provider down")))

    await run_agent_loop(
        [UserMessage(content="go")], context(), config(MODEL), recorder, None, stream
    )

    assert recorder.types[-2:] == ["turn_end", "agent_end"]
    final = recorder.of_type("message_end")[-1].message
    assert final.stop_reason == "error"
    assert final.error_message == "provider down"


# --------------------------------------------------------------------------- #
# Model resolution
# --------------------------------------------------------------------------- #


def test_resolve_model_splits_a_prefixed_id():
    model = resolve_model("anthropic/claude-x")

    assert (model.provider, model.id) == ("anthropic", "claude-x")
    assert model.api == "anthropic-messages"
    assert model.supports_reasoning is True


def test_explicit_provider_wins_over_a_prefix():
    model = resolve_model("some/model", provider="ollama")

    assert model.provider == "ollama"
    assert model.id == "some/model"


def test_unknown_provider_defaults_to_openai_completions():
    model = resolve_model("mystery-1", provider="whoknows")

    assert model.api == "openai-completions"
    assert model.supports_reasoning is False


def test_reasoning_support_can_be_forced():
    assert resolve_model("m", provider="whoknows", supports_reasoning=True).supports_reasoning


def test_gateway_bridge_defers_its_provider_imports():
    """The bridge must reach for the gateway inside functions, not at import.

    Asserted against the module's own imports rather than ``sys.modules``,
    because ``superqode/__init__.py`` already pulls the provider package in for
    its own reasons. What PiPy controls is its own import graph.
    """
    import ast
    import pathlib

    import superqode.pipy.ai.gateway as bridge

    tree = ast.parse(pathlib.Path(bridge.__file__).read_text(encoding="utf-8"))
    module_level = {
        name.name if isinstance(node, ast.Import) else node.module
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (node.names if isinstance(node, ast.Import) else [node])
    }

    offenders = {
        name
        for name in module_level
        if name and (name == "superqode" or name.startswith("superqode."))
    }
    assert offenders == set()


def test_importing_pipy_does_not_load_litellm():
    """The expensive dependency stays out until a real request is made."""
    import os
    import subprocess
    import sys

    # A bare subprocess inherits the interpreter but not the parent's sys.path,
    # so without this an uninstalled checkout reads as a litellm regression.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    code = "import sys, superqode.pipy;assert 'litellm' not in sys.modules, 'litellm was imported'"
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )

    assert "ModuleNotFoundError" not in completed.stderr, (
        f"superqode was not importable in the subprocess, so this test proved nothing:\n"
        f"{completed.stderr}"
    )
    assert completed.returncode == 0, completed.stderr
