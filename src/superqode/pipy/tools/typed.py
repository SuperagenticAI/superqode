"""Pydantic tool inputs through PiPy's existing execution and recovery path."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from ..signals import AbortSignal
from ..types import ToolExecutionMode
from ..validation import validate_tool_arguments
from .base import AgentTool, AgentToolResult, ToolUpdateCallback

if TYPE_CHECKING:
    from pydantic import BaseModel

Arguments = TypeVar("Arguments", bound="BaseModel")


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Host-owned call identity, cancellation and streaming for a typed tool."""

    tool_call_id: str
    signal: AbortSignal | None = None
    on_update: ToolUpdateCallback | None = None

    def check_cancelled(self) -> None:
        if self.signal is not None:
            self.signal.throw_if_aborted()

    def emit(self, result: AgentToolResult) -> None:
        self.check_cancelled()
        if self.on_update is not None:
            self.on_update(result)


def create_typed_tool(
    name: str,
    description: str,
    arguments: type[Arguments],
    execute: Callable[[Arguments, ToolContext], Awaitable[AgentToolResult]],
    *,
    label: str | None = None,
    prompt_snippet: str | None = None,
    prompt_guidelines: tuple[str, ...] = (),
    execution_mode: ToolExecutionMode | None = None,
    replay_safe: bool = False,
) -> AgentTool:
    """Create a tool with one schema shared by the model and Python executor.

    Pydantic field and model validators run before user code, even for direct
    SDK calls. The executor must be async and return AgentToolResult, retaining
    images, usage and termination hints. Replay safety is an explicit promise
    from the author; typing never grants it.
    """
    from pydantic import BaseModel

    if not isinstance(arguments, type) or not issubclass(arguments, BaseModel):
        raise TypeError("arguments must be a Pydantic BaseModel subclass")
    schema = arguments.model_json_schema()

    async def run(tool_call_id, args, signal=None, on_update=None):
        context = ToolContext(tool_call_id, signal, on_update)
        context.check_cancelled()
        validated = validate_tool_arguments(name, schema, args)
        typed_arguments = arguments.model_validate(validated)
        result = await execute(typed_arguments, context)
        if not isinstance(result, AgentToolResult):
            raise TypeError("Typed tool executor must return AgentToolResult")
        return result

    return AgentTool(
        name=name,
        label=label or name,
        description=description,
        parameters=schema,
        execute_fn=run,
        prompt_snippet=prompt_snippet or description,
        prompt_guidelines=prompt_guidelines,
        execution_mode=execution_mode,
        replay_safe=replay_safe,
    )


__all__ = ["ToolContext", "create_typed_tool"]
