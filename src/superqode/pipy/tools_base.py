"""Pi-compatible tool definitions and execution results."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .messages import ImageContent, TextContent
from .types import JSONValue


class ToolCancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(slots=True)
class AgentToolResult:
    content: list[TextContent | ImageContent] = field(default_factory=list)
    details: JSONValue = None
    added_tool_names: list[str] | None = None
    terminate: bool | None = None

    def __post_init__(self) -> None:
        if isinstance(self.content, str):
            text = self.content
            object.__setattr__(
                self,
                "content",
                [TextContent(text=text)] if text else [],
            )

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextContent))

    def model_copy(self, *, deep: bool = False) -> AgentToolResult:
        del deep
        return AgentToolResult(
            content=list(self.content),
            details=self.details,
            added_tool_names=list(self.added_tool_names) if self.added_tool_names else None,
            terminate=self.terminate,
        )


ToolUpdateCallback = Callable[[AgentToolResult], None]
ToolExecutionMode = Literal["sequential", "parallel"]


class ToolExecutor(Protocol):
    def __call__(
        self,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> Awaitable[AgentToolResult]: ...


@dataclass(frozen=True, slots=True)
class AgentTool:
    name: str
    label: str
    description: str
    parameters: Mapping[str, JSONValue]
    execute_fn: ToolExecutor
    prompt_snippet: str | None = None
    prompt_guidelines: tuple[str, ...] = ()
    execution_mode: ToolExecutionMode = "parallel"

    @property
    def input_schema(self) -> Mapping[str, JSONValue]:
        return self.parameters

    async def execute(
        self,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        return await self.execute_fn(tool_call_id, arguments, signal, on_update)
