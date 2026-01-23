"""
Open Responses Provider - Unified API Integration.

Implements the Open Responses specification for a consistent API across
multiple AI providers. Supports:
- Streaming with 45+ event types
- Reasoning/thinking content
- Built-in tools (apply_patch, code_interpreter, file_search)
- Message ↔ Item conversion

Usage:
    from superqode.providers.openresponses import OpenResponsesGateway

    gateway = OpenResponsesGateway(base_url="http://localhost:8080")
    response = await gateway.chat_completion(messages, model="qwen3:8b")
"""

from .schema.models import (
    # Request/Response types
    ResponseRequest,
    Response,
    ResponseUsage,
    # Item types
    ItemParam,
    UserMessageItemParam,
    AssistantMessageItemParam,
    SystemMessageItemParam,
    FunctionCallItemParam,
    FunctionCallOutputItemParam,
    # Content types
    TextContentParam,
    ImageContentParam,
    # Tool types
    FunctionToolParam,
    CodeInterpreterToolParam,
    FileSearchToolParam,
    ApplyPatchToolParam,
    # Streaming events
    StreamingEvent,
    ResponseCreatedEvent,
    ResponseInProgressEvent,
    ResponseCompletedEvent,
    ResponseOutputTextDeltaEvent,
    ResponseReasoningDeltaEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
)

from .converters.messages import (
    messages_to_items,
    items_to_messages,
)

from .converters.tools import (
    convert_tools_to_openresponses,
    convert_tools_from_openresponses,
)

__all__ = [
    # Schema types
    "ResponseRequest",
    "Response",
    "ResponseUsage",
    "ItemParam",
    "UserMessageItemParam",
    "AssistantMessageItemParam",
    "SystemMessageItemParam",
    "FunctionCallItemParam",
    "FunctionCallOutputItemParam",
    "TextContentParam",
    "ImageContentParam",
    "FunctionToolParam",
    "CodeInterpreterToolParam",
    "FileSearchToolParam",
    "ApplyPatchToolParam",
    "StreamingEvent",
    "ResponseCreatedEvent",
    "ResponseInProgressEvent",
    "ResponseCompletedEvent",
    "ResponseOutputTextDeltaEvent",
    "ResponseReasoningDeltaEvent",
    "ResponseFunctionCallArgumentsDeltaEvent",
    # Converters
    "messages_to_items",
    "items_to_messages",
    "convert_tools_to_openresponses",
    "convert_tools_from_openresponses",
]
