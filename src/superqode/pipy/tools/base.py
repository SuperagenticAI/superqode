"""Pi-compatible tool definitions and execution results.

Ported from ``packages/agent/src/types.ts`` of earendil-works/pi (MIT). See NOTICE.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol

from ..messages import ImageContent, TextContent, Usage
from ..signals import AbortSignal
from ..types import JSONObject, JSONValue, ToolExecutionMode


@dataclass(slots=True)
class AgentToolResult:
    """Final or partial result produced by a tool."""

    #: Text or image content returned to the model.
    content: list[TextContent | ImageContent] = field(default_factory=list)
    #: Arbitrary structured payload for logs and UI rendering.
    details: JSONValue = None
    #: Usage from the tool execution itself, if any. Not part of LLM context
    #: accounting.
    usage: Usage | None = None
    #: Tools introduced by this result, available from this transcript point on.
    added_tool_names: list[str] | None = None
    #: Hint that the agent should stop after the current tool batch. The loop
    #: only honours it when every result in the batch sets it.
    terminate: bool | None = None

    def __post_init__(self) -> None:
        if isinstance(self.content, str):
            text = self.content
            self.content = [TextContent(text=text)] if text else []

    @property
    def text(self) -> str:
        return "".join(block.text for block in self.content if isinstance(block, TextContent))

    def copy(self) -> AgentToolResult:
        """Shallow copy with independent collections, for update snapshots."""
        return replace(
            self,
            content=list(self.content),
            added_tool_names=list(self.added_tool_names) if self.added_tool_names else None,
        )


#: Callback tools use to stream partial results. Scoped to one ``execute`` call;
#: calls made after the tool settles are ignored.
ToolUpdateCallback = Callable[[AgentToolResult], None]


class ToolExecutor(Protocol):
    """Callable implementing a tool body."""

    def __call__(
        self,
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> Awaitable[AgentToolResult]: ...


@dataclass(frozen=True, slots=True)
class AgentTool:
    """A tool the model can call."""

    name: str
    label: str
    description: str
    #: JSON Schema for the arguments. Validated before ``execute`` runs.
    parameters: Mapping[str, JSONValue]
    execute_fn: ToolExecutor
    #: One-line summary. A tool appears in the system prompt's tool list only
    #: when it has one, matching pi's ``buildSystemPrompt``.
    prompt_snippet: str | None = None
    #: Extra guideline bullets contributed to the system prompt.
    prompt_guidelines: tuple[str, ...] = ()
    #: Optional shim applied to raw arguments before schema validation.
    prepare_arguments: Callable[[JSONObject], JSONObject] | None = None
    #: Per-tool override of the loop's execution mode. ``sequential`` forces the
    #: whole batch to run one at a time.
    execution_mode: ToolExecutionMode | None = None

    @property
    def input_schema(self) -> Mapping[str, JSONValue]:
        return self.parameters

    async def execute(
        self,
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        """Run the tool. Raise on failure rather than encoding errors in content."""
        return await self.execute_fn(tool_call_id, args, signal, on_update)


__all__ = [
    "AgentTool",
    "AgentToolResult",
    "ToolExecutor",
    "ToolUpdateCallback",
]
