"""Shared fixtures for the PiPy harness tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from superqode.pipy import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentTool,
    AgentToolResult,
    Model,
    TextContent,
    ToolCall,
    event_type,
)
from superqode.pipy.ai import FakeStream

MODEL = Model(id="fake-1", provider="fake", api="fake-api")


@pytest.fixture
def model() -> Model:
    return MODEL


@pytest.fixture
def recorder() -> "EventRecorder":
    return EventRecorder()


class EventRecorder:
    """Collects loop events and exposes the assertions the tests need."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    async def async_sink(self, event: AgentEvent) -> None:
        self.events.append(event)

    @property
    def types(self) -> list[str]:
        return [event_type(event) for event in self.events]

    def of_type(self, name: str) -> list[AgentEvent]:
        return [event for event in self.events if event_type(event) == name]

    def tool_names(self, name: str) -> list[str]:
        return [event.tool_name for event in self.of_type(name)]


def context(*, tools: list[AgentTool] | None = None, messages: list | None = None) -> AgentContext:
    return AgentContext(
        system_prompt="You are a test agent.",
        messages=list(messages or []),
        tools=list(tools or []),
    )


def config(model: Model = MODEL, **overrides) -> AgentLoopConfig:
    return AgentLoopConfig(model=model, **overrides)


def call(name: str, call_id: str = "call-1", **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def echo_tool(
    name: str = "echo",
    *,
    body: Callable | None = None,
    execution_mode: str | None = None,
    required: tuple[str, ...] = ("value",),
) -> AgentTool:
    """A tool that echoes its ``value`` argument, or runs a custom body."""

    async def default_body(tool_call_id, args, signal=None, on_update=None):
        return AgentToolResult(
            content=[TextContent(text=f"{name}:{args.get('value')}")],
            details={"value": args.get("value")},
        )

    return AgentTool(
        name=name,
        label=name,
        description=f"Echo the {name} value",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": list(required),
            "additionalProperties": False,
        },
        execute_fn=body or default_body,
        execution_mode=execution_mode,  # type: ignore[arg-type]
    )


def slow_tool(name: str, delay: float, order: list[str]) -> AgentTool:
    """A tool that sleeps, then records its completion order."""

    async def body(tool_call_id, args, signal=None, on_update=None):
        await asyncio.sleep(delay)
        order.append(name)
        return AgentToolResult(content=[TextContent(text=name)], details={})

    return AgentTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}, "additionalProperties": True},
        execute_fn=body,
    )


__all__ = [
    "EventRecorder",
    "FakeStream",
    "call",
    "config",
    "context",
    "echo_tool",
    "slow_tool",
]
