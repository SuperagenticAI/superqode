"""
Message ↔ Item Conversion.

Bidirectional conversion between OpenAI-style messages and Open Responses items.

OpenAI Format (messages):
    [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!", "tool_calls": [...]},
        {"role": "tool", "tool_call_id": "call_123", "content": "result"}
    ]

Open Responses Format (items):
    [
        {"type": "message", "role": "user", "content": "Hello"},
        {"type": "message", "role": "assistant", "content": [...]},
        {"type": "function_call", "call_id": "call_123", "name": "tool", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_123", "output": "result"}
    ]
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from ..schema.models import (
    ItemParam,
    UserMessageItemParam,
    AssistantMessageItemParam,
    SystemMessageItemParam,
    FunctionCallItemParam,
    FunctionCallOutputItemParam,
    TextContentParam,
    ImageContentParam,
)
from ...gateway.base import Message


def messages_to_items(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Convert OpenAI-style messages to Open Responses items.

    Handles:
    - User messages → UserMessageItemParam
    - Assistant messages → AssistantMessageItemParam + FunctionCallItemParam (if tool_calls)
    - System messages → SystemMessageItemParam
    - Tool messages → FunctionCallOutputItemParam

    Args:
        messages: List of Message objects

    Returns:
        List of Open Responses item dicts
    """
    items: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.role
        content = msg.content

        if role == "system":
            items.append(
                {
                    "type": "message",
                    "role": "system",
                    "content": content,
                }
            )

        elif role == "user":
            items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": _convert_content_to_items(content),
                }
            )

        elif role == "assistant":
            # Assistant message - may include tool calls
            if content:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": _convert_content_to_items(content),
                    }
                )

            # Convert tool calls to function_call items
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    func = tc.get("function", {})
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "arguments": func.get("arguments", "{}"),
                        }
                    )

        elif role == "tool":
            # Tool result → function_call_output
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id or "",
                    "output": content,
                }
            )

    return items


def items_to_messages(items: List[Dict[str, Any]]) -> List[Message]:
    """
    Convert Open Responses items to OpenAI-style messages.

    Handles:
    - message items → Message objects
    - function_call items → Assistant message with tool_calls
    - function_call_output items → Tool message

    Args:
        items: List of Open Responses item dicts

    Returns:
        List of Message objects
    """
    messages: List[Message] = []
    pending_tool_calls: List[Dict[str, Any]] = []

    for item in items:
        item_type = item.get("type", "")

        if item_type == "message":
            # Flush any pending tool calls first
            if pending_tool_calls:
                messages.append(
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=pending_tool_calls,
                    )
                )
                pending_tool_calls = []

            role = item.get("role", "user")
            content = _convert_items_to_content(item.get("content", ""))

            messages.append(
                Message(
                    role=role,
                    content=content,
                )
            )

        elif item_type == "function_call":
            # Accumulate tool calls for the assistant message
            pending_tool_calls.append(
                {
                    "id": item.get("call_id", ""),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }
            )

        elif item_type == "function_call_output":
            # Flush any pending tool calls first
            if pending_tool_calls:
                messages.append(
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=pending_tool_calls,
                    )
                )
                pending_tool_calls = []

            # Tool result
            messages.append(
                Message(
                    role="tool",
                    content=item.get("output", ""),
                    tool_call_id=item.get("call_id", ""),
                )
            )

    # Flush any remaining pending tool calls
    if pending_tool_calls:
        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=pending_tool_calls,
            )
        )

    return messages


def _convert_content_to_items(content: Union[str, List[Any]]) -> Union[str, List[Dict[str, Any]]]:
    """
    Convert message content to Open Responses format.

    Handles both string content and multi-part content (images, etc.).
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        items = []
        for part in content:
            if isinstance(part, str):
                items.append({"type": "input_text", "text": part})
            elif isinstance(part, dict):
                part_type = part.get("type", "")
                if part_type == "text":
                    items.append({"type": "input_text", "text": part.get("text", "")})
                elif part_type == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
                    items.append(
                        {
                            "type": "input_image",
                            "image_url": url,
                            "detail": image_url.get("detail", "auto")
                            if isinstance(image_url, dict)
                            else "auto",
                        }
                    )
                else:
                    # Pass through unknown types
                    items.append(part)
        return items

    return str(content)


def _convert_items_to_content(content: Union[str, List[Any]]) -> str:
    """
    Convert Open Responses content items to string content.

    For simplicity, concatenates all text parts.
    Image handling would require additional logic in the caller.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                part_type = part.get("type", "")
                if part_type in ("text", "input_text", "output_text"):
                    text_parts.append(part.get("text", ""))
                elif part_type == "refusal":
                    text_parts.append(f"[Refusal: {part.get('refusal', '')}]")
        return "".join(text_parts)

    return str(content)


def convert_output_to_message(output_items: List[Dict[str, Any]]) -> Message:
    """
    Convert Open Responses output items to a single assistant message.

    Extracts text content and tool calls from the output.

    Args:
        output_items: List of output items from a Response

    Returns:
        Message object with content and optional tool_calls
    """
    content_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    for item in output_items:
        item_type = item.get("type", "")

        if item_type == "message":
            # Extract text from message content
            item_content = item.get("content", [])
            if isinstance(item_content, str):
                content_parts.append(item_content)
            elif isinstance(item_content, list):
                for part in item_content:
                    if isinstance(part, dict):
                        part_type = part.get("type", "")
                        if part_type in ("text", "output_text"):
                            content_parts.append(part.get("text", ""))
                        elif part_type == "reasoning":
                            # Skip reasoning in main content
                            pass

        elif item_type == "function_call":
            tool_calls.append(
                {
                    "id": item.get("call_id", item.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }
            )

    return Message(
        role="assistant",
        content="".join(content_parts),
        tool_calls=tool_calls if tool_calls else None,
    )


def extract_reasoning_from_output(output_items: List[Dict[str, Any]]) -> Optional[str]:
    """
    Extract reasoning/thinking content from Open Responses output.

    Args:
        output_items: List of output items from a Response

    Returns:
        Reasoning text if found, None otherwise
    """
    reasoning_parts: List[str] = []

    for item in output_items:
        if item.get("type") == "message":
            item_content = item.get("content", [])
            if isinstance(item_content, list):
                for part in item_content:
                    if isinstance(part, dict) and part.get("type") == "reasoning":
                        reasoning_parts.append(part.get("text", ""))

    return "".join(reasoning_parts) if reasoning_parts else None
