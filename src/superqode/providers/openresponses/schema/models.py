"""
Open Responses Schema Models.

Core Pydantic models for the Open Responses specification.
Based on the OpenAPI spec at: public/openapi/openapi.json

These models cover the essential types needed for:
- Request/Response handling
- Message/Item conversion
- Tool definitions
- Streaming events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union


# =============================================================================
# Enums
# =============================================================================


class ResponseStatus(str, Enum):
    """Status of a response."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemType(str, Enum):
    """Type of an input/output item."""

    MESSAGE = "message"
    FUNCTION_CALL = "function_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"
    REASONING = "reasoning"


class ContentType(str, Enum):
    """Type of content in a message."""

    TEXT = "text"
    INPUT_TEXT = "input_text"
    OUTPUT_TEXT = "output_text"
    INPUT_IMAGE = "input_image"
    INPUT_FILE = "input_file"
    REFUSAL = "refusal"


class ToolType(str, Enum):
    """Type of tool."""

    FUNCTION = "function"
    CODE_INTERPRETER = "code_interpreter"
    FILE_SEARCH = "file_search"
    APPLY_PATCH = "apply_patch"
    WEB_SEARCH = "web_search"
    COMPUTER_USE_PREVIEW = "computer_use_preview"
    MCP = "mcp"


class ReasoningEffort(str, Enum):
    """Reasoning effort level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TruncationStrategy(str, Enum):
    """Truncation strategy for context."""

    AUTO = "auto"
    DISABLED = "disabled"


# =============================================================================
# Content Types
# =============================================================================


@dataclass
class TextContentParam:
    """Text content in a message."""

    type: Literal["text", "input_text"] = "text"
    text: str = ""


@dataclass
class ImageContentParam:
    """Image content in a message."""

    type: Literal["input_image"] = "input_image"
    image_url: str = ""
    detail: Literal["auto", "low", "high"] = "auto"


@dataclass
class FileContentParam:
    """File content in a message."""

    type: Literal["input_file"] = "input_file"
    file_id: str = ""
    filename: Optional[str] = None


ContentParam = Union[TextContentParam, ImageContentParam, FileContentParam, str]


# =============================================================================
# Item Types (Input)
# =============================================================================


@dataclass
class UserMessageItemParam:
    """User message input item."""

    type: Literal["message"] = "message"
    role: Literal["user"] = "user"
    content: Union[str, List[ContentParam]] = ""


@dataclass
class AssistantMessageItemParam:
    """Assistant message input item."""

    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: Union[str, List[ContentParam]] = ""


@dataclass
class SystemMessageItemParam:
    """System message input item."""

    type: Literal["message"] = "message"
    role: Literal["system"] = "system"
    content: Union[str, List[ContentParam]] = ""


@dataclass
class FunctionCallItemParam:
    """Function call input item."""

    type: Literal["function_call"] = "function_call"
    call_id: str = ""
    name: str = ""
    arguments: str = "{}"


@dataclass
class FunctionCallOutputItemParam:
    """Function call output input item."""

    type: Literal["function_call_output"] = "function_call_output"
    call_id: str = ""
    output: str = ""


ItemParam = Union[
    UserMessageItemParam,
    AssistantMessageItemParam,
    SystemMessageItemParam,
    FunctionCallItemParam,
    FunctionCallOutputItemParam,
]


# =============================================================================
# Output Item Types
# =============================================================================


@dataclass
class TextOutput:
    """Text output content."""

    type: Literal["output_text"] = "output_text"
    text: str = ""
    annotations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ReasoningOutput:
    """Reasoning/thinking output content."""

    type: Literal["reasoning"] = "reasoning"
    text: str = ""


@dataclass
class RefusalOutput:
    """Refusal output content."""

    type: Literal["refusal"] = "refusal"
    refusal: str = ""


@dataclass
class FunctionCallOutput:
    """Function call output item."""

    type: Literal["function_call"] = "function_call"
    id: str = ""
    call_id: str = ""
    name: str = ""
    arguments: str = "{}"
    status: Literal["in_progress", "completed", "incomplete"] = "completed"


@dataclass
class MessageOutput:
    """Message output item."""

    type: Literal["message"] = "message"
    id: str = ""
    role: Literal["assistant"] = "assistant"
    content: List[Union[TextOutput, ReasoningOutput, RefusalOutput]] = field(default_factory=list)
    status: Literal["in_progress", "completed", "incomplete"] = "completed"


OutputItem = Union[MessageOutput, FunctionCallOutput]


# =============================================================================
# Tool Types
# =============================================================================


@dataclass
class FunctionDefinition:
    """Function definition for a tool."""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    strict: bool = False


@dataclass
class FunctionToolParam:
    """Function tool definition."""

    type: Literal["function"] = "function"
    function: FunctionDefinition = field(default_factory=FunctionDefinition)


@dataclass
class CodeInterpreterToolParam:
    """Code interpreter tool definition."""

    type: Literal["code_interpreter"] = "code_interpreter"
    container: Optional[str] = None


@dataclass
class FileSearchToolParam:
    """File search tool definition."""

    type: Literal["file_search"] = "file_search"
    vector_store_ids: List[str] = field(default_factory=list)
    max_num_results: int = 20
    ranking_options: Optional[Dict[str, Any]] = None


@dataclass
class ApplyPatchToolParam:
    """Apply patch tool definition."""

    type: Literal["apply_patch"] = "apply_patch"


@dataclass
class WebSearchToolParam:
    """Web search tool definition."""

    type: Literal["web_search"] = "web_search"
    user_location: Optional[Dict[str, Any]] = None
    search_context_size: Literal["low", "medium", "high"] = "medium"


ToolParam = Union[
    FunctionToolParam,
    CodeInterpreterToolParam,
    FileSearchToolParam,
    ApplyPatchToolParam,
    WebSearchToolParam,
]


# =============================================================================
# Tool Choice
# =============================================================================


@dataclass
class SpecificFunctionToolChoice:
    """Specific function tool choice."""

    type: Literal["function"] = "function"
    name: str = ""


ToolChoiceParam = Union[
    Literal["auto", "none", "required"],
    SpecificFunctionToolChoice,
]


# =============================================================================
# Reasoning Configuration
# =============================================================================


@dataclass
class ReasoningConfig:
    """Configuration for reasoning/thinking."""

    effort: ReasoningEffort = ReasoningEffort.MEDIUM
    summary: Optional[Literal["auto", "concise", "detailed"]] = None


# =============================================================================
# Request/Response
# =============================================================================


@dataclass
class ResponseRequest:
    """Request to create a response."""

    model: str = ""
    input: Union[str, List[ItemParam]] = field(default_factory=list)
    instructions: Optional[str] = None
    tools: List[ToolParam] = field(default_factory=list)
    tool_choice: ToolChoiceParam = "auto"
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: bool = False
    reasoning: Optional[ReasoningConfig] = None
    truncation: TruncationStrategy = TruncationStrategy.AUTO
    metadata: Dict[str, str] = field(default_factory=dict)
    store: bool = False
    parallel_tool_calls: bool = True


@dataclass
class ResponseUsage:
    """Token usage information."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_details: Optional[Dict[str, int]] = None
    output_tokens_details: Optional[Dict[str, int]] = None


@dataclass
class ResponseError:
    """Error information."""

    code: str = ""
    message: str = ""


@dataclass
class IncompleteDetails:
    """Details about why a response is incomplete."""

    reason: Literal["max_output_tokens", "content_filter"] = "max_output_tokens"


@dataclass
class Response:
    """Response from the API."""

    id: str = ""
    object: Literal["response"] = "response"
    created_at: int = 0
    model: str = ""
    status: ResponseStatus = ResponseStatus.COMPLETED
    output: List[OutputItem] = field(default_factory=list)
    usage: Optional[ResponseUsage] = None
    error: Optional[ResponseError] = None
    incomplete_details: Optional[IncompleteDetails] = None
    metadata: Dict[str, str] = field(default_factory=dict)


# =============================================================================
# Streaming Events
# =============================================================================


@dataclass
class ResponseCreatedEvent:
    """Response created streaming event."""

    type: Literal["response.created"] = "response.created"
    response: Response = field(default_factory=Response)


@dataclass
class ResponseInProgressEvent:
    """Response in progress streaming event."""

    type: Literal["response.in_progress"] = "response.in_progress"
    response: Response = field(default_factory=Response)


@dataclass
class ResponseCompletedEvent:
    """Response completed streaming event."""

    type: Literal["response.completed"] = "response.completed"
    response: Response = field(default_factory=Response)


@dataclass
class ResponseFailedEvent:
    """Response failed streaming event."""

    type: Literal["response.failed"] = "response.failed"
    response: Response = field(default_factory=Response)


@dataclass
class ResponseIncompleteEvent:
    """Response incomplete streaming event."""

    type: Literal["response.incomplete"] = "response.incomplete"
    response: Response = field(default_factory=Response)


@dataclass
class ResponseOutputItemAddedEvent:
    """Output item added streaming event."""

    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int = 0
    item: OutputItem = field(default_factory=MessageOutput)


@dataclass
class ResponseOutputItemDoneEvent:
    """Output item done streaming event."""

    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int = 0
    item: OutputItem = field(default_factory=MessageOutput)


@dataclass
class ResponseContentPartAddedEvent:
    """Content part added streaming event."""

    type: Literal["response.content_part.added"] = "response.content_part.added"
    output_index: int = 0
    content_index: int = 0
    part: Union[TextOutput, ReasoningOutput] = field(default_factory=TextOutput)


@dataclass
class ResponseContentPartDoneEvent:
    """Content part done streaming event."""

    type: Literal["response.content_part.done"] = "response.content_part.done"
    output_index: int = 0
    content_index: int = 0
    part: Union[TextOutput, ReasoningOutput] = field(default_factory=TextOutput)


@dataclass
class ResponseOutputTextDeltaEvent:
    """Output text delta streaming event."""

    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    output_index: int = 0
    content_index: int = 0
    delta: str = ""


@dataclass
class ResponseOutputTextDoneEvent:
    """Output text done streaming event."""

    type: Literal["response.output_text.done"] = "response.output_text.done"
    output_index: int = 0
    content_index: int = 0
    text: str = ""


@dataclass
class ResponseReasoningDeltaEvent:
    """Reasoning delta streaming event."""

    type: Literal["response.reasoning.delta"] = "response.reasoning.delta"
    output_index: int = 0
    content_index: int = 0
    delta: str = ""


@dataclass
class ResponseReasoningDoneEvent:
    """Reasoning done streaming event."""

    type: Literal["response.reasoning.done"] = "response.reasoning.done"
    output_index: int = 0
    content_index: int = 0
    text: str = ""


@dataclass
class ResponseFunctionCallArgumentsDeltaEvent:
    """Function call arguments delta streaming event."""

    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    output_index: int = 0
    call_id: str = ""
    delta: str = ""


@dataclass
class ResponseFunctionCallArgumentsDoneEvent:
    """Function call arguments done streaming event."""

    type: Literal["response.function_call_arguments.done"] = "response.function_call_arguments.done"
    output_index: int = 0
    call_id: str = ""
    name: str = ""
    arguments: str = ""


# Union of all streaming events
StreamingEvent = Union[
    ResponseCreatedEvent,
    ResponseInProgressEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseReasoningDeltaEvent,
    ResponseReasoningDoneEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
]


# =============================================================================
# Event Type Mapping
# =============================================================================

STREAMING_EVENT_TYPES = {
    "response.created": ResponseCreatedEvent,
    "response.in_progress": ResponseInProgressEvent,
    "response.completed": ResponseCompletedEvent,
    "response.failed": ResponseFailedEvent,
    "response.incomplete": ResponseIncompleteEvent,
    "response.output_item.added": ResponseOutputItemAddedEvent,
    "response.output_item.done": ResponseOutputItemDoneEvent,
    "response.content_part.added": ResponseContentPartAddedEvent,
    "response.content_part.done": ResponseContentPartDoneEvent,
    "response.output_text.delta": ResponseOutputTextDeltaEvent,
    "response.output_text.done": ResponseOutputTextDoneEvent,
    "response.reasoning.delta": ResponseReasoningDeltaEvent,
    "response.reasoning.done": ResponseReasoningDoneEvent,
    "response.function_call_arguments.delta": ResponseFunctionCallArgumentsDeltaEvent,
    "response.function_call_arguments.done": ResponseFunctionCallArgumentsDoneEvent,
}
