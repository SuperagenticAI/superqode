"""PiPy: a native Python coding-agent harness for SuperQode.

PiPy follows the architecture of pi: an event-first loop, mid-run steering, a
session tree, and a small tool surface. It runs with the
permissions of the process that launched it, matching pi and deliberately
unlike SuperQode's other native harnesses. See ``NOTICE`` for attribution.

Layering, mirroring pi: ``superqode.app`` -> ``superqode.harness`` ->
``superqode.pipy`` -> ``superqode.pipy.ai``. Nothing in this package may import
Textual, the approval manager, or the workbench tool registry.
"""

from .coding_session import (
    SLASH_COMMANDS,
    CodingSessionOptions,
    PiPyCodingSession,
    SessionInfo,
    SlashCommand,
)
from .event_stream import EventStream
from .harness import AgentHarness, HarnessPhase, HarnessResources, TurnState
from .harness_events import AbortResult, AgentHarnessError
from .session import MemorySessionStorage, Session, SessionError, create_session
from .events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
    event_type,
)
from .loop import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentLoopConfig,
    AgentLoopTurnUpdate,
    BeforeToolCallContext,
    BeforeToolCallResult,
    TurnContext,
    agent_loop,
    agent_loop_continue,
    run_agent_loop,
    run_agent_loop_continue,
)
from .prompt_templates import (
    PromptTemplate,
    format_prompt_template_invocation,
    load_prompt_templates,
    substitute_args,
)
from .resources import ContextFile, load_context_files
from .skills import Skill, format_skill_invocation, format_skills_for_prompt, load_skills
from .system_prompt import SelfDocs, SystemPromptOptions, build_system_prompt
from .messages import (
    AgentMessage,
    AssistantMessage,
    ImageContent,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
    default_convert_to_llm,
)
from .signals import AbortController, AbortError, AbortSignal
from .stream import Context, Model, StreamFn, StreamOptions
from .tools.base import AgentTool, AgentToolResult
from .validation import ToolArgumentError, validate_tool_arguments

__all__ = [
    "SLASH_COMMANDS",
    "AbortController",
    "AbortError",
    "AbortResult",
    "AbortSignal",
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEndEvent",
    "AgentEvent",
    "AgentHarness",
    "AgentHarnessError",
    "AgentLoopConfig",
    "AgentLoopTurnUpdate",
    "AgentMessage",
    "AgentStartEvent",
    "AgentTool",
    "AgentToolResult",
    "AssistantMessage",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "CodingSessionOptions",
    "Context",
    "ContextFile",
    "EventStream",
    "HarnessPhase",
    "HarnessResources",
    "ImageContent",
    "MemorySessionStorage",
    "Message",
    "MessageEndEvent",
    "MessageStartEvent",
    "MessageUpdateEvent",
    "Model",
    "PiPyCodingSession",
    "Session",
    "SessionError",
    "SessionInfo",
    "SlashCommand",
    "StreamFn",
    "StreamOptions",
    "TextContent",
    "ThinkingContent",
    "ToolArgumentError",
    "ToolCall",
    "ToolExecutionEndEvent",
    "ToolExecutionStartEvent",
    "ToolExecutionUpdateEvent",
    "ToolResultMessage",
    "TurnContext",
    "TurnEndEvent",
    "TurnStartEvent",
    "TurnState",
    "Usage",
    "UserMessage",
    "agent_loop",
    "agent_loop_continue",
    "build_system_prompt",
    "create_session",
    "default_convert_to_llm",
    "event_type",
    "format_prompt_template_invocation",
    "format_skill_invocation",
    "format_skills_for_prompt",
    "load_context_files",
    "load_prompt_templates",
    "load_skills",
    "run_agent_loop",
    "run_agent_loop_continue",
    "substitute_args",
    "validate_tool_arguments",
]
