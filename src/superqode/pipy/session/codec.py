"""Wire format for session files.

PiPy writes pi's exact JSON shape, so a PiPy session file is a valid pi session
file and vice versa. That means camelCase keys on the wire and snake_case
attributes in Python, with omitted rather than null optionals, matching what
``JSON.stringify`` produces for an undefined field.

Field names verified against ``packages/agent/src/harness/`` of
earendil-works/pi (MIT).
"""

from __future__ import annotations

from typing import Any

from ..messages import (
    AgentMessage,
    AssistantMessage,
    BranchSummaryMessage,
    CompactionSummaryMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from .entries import (
    ActiveToolsChangeEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionInfoEntry,
    SessionTreeEntry,
    ThinkingLevelChangeEntry,
)


class SessionCodecError(ValueError):
    """Raised when a session line cannot be decoded."""


def _prune(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None, matching JSON.stringify of undefined."""
    return {key: value for key, value in payload.items() if value is not None}


# --------------------------------------------------------------------------- #
# Content blocks
# --------------------------------------------------------------------------- #


def encode_content_block(block: Any) -> dict[str, Any]:
    if isinstance(block, TextContent):
        return _prune({"type": "text", "text": block.text, "textSignature": block.text_signature})
    if isinstance(block, ThinkingContent):
        return _prune(
            {
                "type": "thinking",
                "thinking": block.thinking,
                "thinkingSignature": block.thinking_signature,
                "redacted": block.redacted or None,
            }
        )
    if isinstance(block, ImageContent):
        return {"type": "image", "data": block.data, "mimeType": block.mime_type}
    if isinstance(block, ToolCall):
        return _prune(
            {
                "type": "toolCall",
                "id": block.id,
                "name": block.name,
                "arguments": dict(block.arguments),
                "thoughtSignature": block.thought_signature,
            }
        )
    raise SessionCodecError(f"Unsupported content block: {block!r}")


def decode_content_block(payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise SessionCodecError(f"Content block is not an object: {payload!r}")
    kind = payload.get("type")
    if kind == "text":
        return TextContent(
            text=str(payload.get("text") or ""),
            text_signature=payload.get("textSignature"),
        )
    if kind == "thinking":
        return ThinkingContent(
            thinking=str(payload.get("thinking") or ""),
            thinking_signature=payload.get("thinkingSignature"),
            redacted=bool(payload.get("redacted", False)),
        )
    if kind == "image":
        return ImageContent(
            data=str(payload.get("data") or ""),
            mime_type=str(payload.get("mimeType") or ""),
        )
    if kind == "toolCall":
        return ToolCall(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            arguments=dict(payload.get("arguments") or {}),
            thought_signature=payload.get("thoughtSignature"),
        )
    raise SessionCodecError(f"Unknown content block type: {kind!r}")


def _encode_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    return [encode_content_block(block) for block in content]


def _decode_content(payload: Any) -> Any:
    # A string stays a string. pi's user and custom-message content is
    # `string | block[]`, and normalising here would make encode(decode(x)) != x
    # for any file that used the string form. The message dataclasses normalise
    # for the roles that require a block list.
    if isinstance(payload, str):
        return payload
    return [decode_content_block(block) for block in payload or []]


# --------------------------------------------------------------------------- #
# Usage
# --------------------------------------------------------------------------- #


def encode_usage(usage: Usage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return _prune(
        {
            "input": usage.input,
            "output": usage.output,
            "cacheRead": usage.cache_read,
            "cacheWrite": usage.cache_write,
            "reasoning": usage.reasoning,
            "totalTokens": usage.total_tokens,
            "cost": {
                "input": usage.cost.input,
                "output": usage.cost.output,
                "cacheRead": usage.cost.cache_read,
                "cacheWrite": usage.cost.cache_write,
                "total": usage.cost.total,
            },
        }
    )


def decode_usage(payload: Any) -> Usage | None:
    if not isinstance(payload, dict):
        return None
    cost_payload = payload.get("cost") or {}
    return Usage(
        input=int(payload.get("input") or 0),
        output=int(payload.get("output") or 0),
        cache_read=int(payload.get("cacheRead") or 0),
        cache_write=int(payload.get("cacheWrite") or 0),
        reasoning=payload.get("reasoning"),
        total_tokens=int(payload.get("totalTokens") or 0),
        cost=UsageCost(
            input=float(cost_payload.get("input") or 0.0),
            output=float(cost_payload.get("output") or 0.0),
            cache_read=float(cost_payload.get("cacheRead") or 0.0),
            cache_write=float(cost_payload.get("cacheWrite") or 0.0),
            total=float(cost_payload.get("total") or 0.0),
        ),
    )


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


def encode_message(message: AgentMessage) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        return {
            "role": "user",
            "content": _encode_content(message.content),
            "timestamp": message.timestamp,
        }
    if isinstance(message, AssistantMessage):
        return _prune(
            {
                "role": "assistant",
                "content": _encode_content(message.content),
                "api": message.api,
                "provider": message.provider,
                "model": message.model,
                "usage": encode_usage(message.usage),
                "stopReason": message.stop_reason,
                "errorMessage": message.error_message,
                "timestamp": message.timestamp,
            }
        )
    if isinstance(message, ToolResultMessage):
        return _prune(
            {
                "role": "toolResult",
                "toolCallId": message.tool_call_id,
                "toolName": message.tool_name,
                "content": _encode_content(message.content),
                "details": message.details,
                "usage": encode_usage(message.usage),
                "addedToolNames": message.added_tool_names or None,
                "isError": message.is_error,
                "timestamp": message.timestamp,
            }
        )
    if isinstance(message, BranchSummaryMessage):
        return {
            "role": "branchSummary",
            "summary": message.summary,
            "fromId": message.from_id,
            "timestamp": message.timestamp,
        }
    if isinstance(message, CompactionSummaryMessage):
        return {
            "role": "compactionSummary",
            "summary": message.summary,
            "tokensBefore": message.tokens_before,
            "timestamp": message.timestamp,
        }
    raise SessionCodecError(f"Unsupported message: {message!r}")


def decode_message(payload: Any) -> AgentMessage:
    if not isinstance(payload, dict):
        raise SessionCodecError(f"Message is not an object: {payload!r}")
    role = payload.get("role")
    timestamp = int(payload.get("timestamp") or 0)
    if role == "user":
        return UserMessage(content=_decode_content(payload.get("content")), timestamp=timestamp)
    if role == "assistant":
        return AssistantMessage(
            content=_decode_content(payload.get("content")),
            api=str(payload.get("api") or "unknown"),
            provider=str(payload.get("provider") or "unknown"),
            model=str(payload.get("model") or "unknown"),
            usage=decode_usage(payload.get("usage")) or Usage(),
            stop_reason=payload.get("stopReason") or "stop",
            error_message=payload.get("errorMessage"),
            timestamp=timestamp,
        )
    if role == "toolResult":
        return ToolResultMessage(
            tool_call_id=str(payload.get("toolCallId") or ""),
            tool_name=str(payload.get("toolName") or ""),
            content=_decode_content(payload.get("content")),
            details=payload.get("details"),
            usage=decode_usage(payload.get("usage")),
            added_tool_names=payload.get("addedToolNames"),
            is_error=bool(payload.get("isError", False)),
            timestamp=timestamp,
        )
    if role == "branchSummary":
        return BranchSummaryMessage(
            summary=str(payload.get("summary") or ""),
            from_id=str(payload.get("fromId") or ""),
            timestamp=timestamp,
        )
    if role == "compactionSummary":
        return CompactionSummaryMessage(
            summary=str(payload.get("summary") or ""),
            tokens_before=int(payload.get("tokensBefore") or 0),
            timestamp=timestamp,
        )
    raise SessionCodecError(f"Unknown message role: {role!r}")


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #


def encode_entry(entry: SessionTreeEntry) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": entry.type,
        "id": entry.id,
        "parentId": entry.parent_id,
        "timestamp": entry.timestamp,
    }
    if isinstance(entry, MessageEntry):
        return {**base, "message": encode_message(entry.message)}
    if isinstance(entry, ThinkingLevelChangeEntry):
        return {**base, "thinkingLevel": entry.thinking_level}
    if isinstance(entry, ModelChangeEntry):
        return {**base, "provider": entry.provider, "modelId": entry.model_id}
    if isinstance(entry, ActiveToolsChangeEntry):
        return {**base, "activeToolNames": list(entry.active_tool_names)}
    if isinstance(entry, CompactionEntry):
        return {
            **base,
            **_prune(
                {
                    "summary": entry.summary,
                    "tokensBefore": entry.tokens_before,
                    "firstKeptEntryId": entry.first_kept_entry_id,
                    "retainedTail": (
                        [encode_message(message) for message in entry.retained_tail]
                        if entry.retained_tail is not None
                        else None
                    ),
                    "details": entry.details,
                    "usage": encode_usage(entry.usage),
                    "fromHook": entry.from_hook or None,
                }
            ),
        }
    if isinstance(entry, BranchSummaryEntry):
        return {
            **base,
            **_prune(
                {
                    "fromId": entry.from_id,
                    "summary": entry.summary,
                    "details": entry.details,
                    "usage": encode_usage(entry.usage),
                    "fromHook": entry.from_hook or None,
                }
            ),
        }
    if isinstance(entry, CustomEntry):
        return {**base, **_prune({"customType": entry.custom_type, "data": entry.data})}
    if isinstance(entry, CustomMessageEntry):
        return {
            **base,
            **_prune(
                {
                    "customType": entry.custom_type,
                    "content": _encode_content(entry.content),
                    "display": entry.display,
                    "details": entry.details,
                }
            ),
        }
    if isinstance(entry, LabelEntry):
        return {**base, **_prune({"targetId": entry.target_id, "label": entry.label})}
    if isinstance(entry, SessionInfoEntry):
        return {**base, "name": entry.name}
    if isinstance(entry, LeafEntry):
        return {**base, "targetId": entry.target_id}
    raise SessionCodecError(f"Unsupported entry: {entry!r}")


def decode_entry(payload: Any) -> SessionTreeEntry:
    if not isinstance(payload, dict):
        raise SessionCodecError("is not a valid session entry")
    kind = payload.get("type")
    if not isinstance(kind, str):
        raise SessionCodecError("is missing entry type")
    entry_id = payload.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise SessionCodecError("is missing entry id")
    parent_id = payload.get("parentId")
    if parent_id is not None and not isinstance(parent_id, str):
        raise SessionCodecError("has invalid parentId")
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise SessionCodecError("is missing timestamp")

    base = {"id": entry_id, "parent_id": parent_id, "timestamp": timestamp}

    if kind == "message":
        return MessageEntry(**base, message=decode_message(payload.get("message")))
    if kind == "thinking_level_change":
        return ThinkingLevelChangeEntry(
            **base, thinking_level=str(payload.get("thinkingLevel") or "off")
        )
    if kind == "model_change":
        return ModelChangeEntry(
            **base,
            provider=str(payload.get("provider") or ""),
            model_id=str(payload.get("modelId") or ""),
        )
    if kind == "active_tools_change":
        return ActiveToolsChangeEntry(
            **base, active_tool_names=list(payload.get("activeToolNames") or [])
        )
    if kind == "compaction":
        tail = payload.get("retainedTail")
        return CompactionEntry(
            **base,
            summary=str(payload.get("summary") or ""),
            tokens_before=int(payload.get("tokensBefore") or 0),
            first_kept_entry_id=payload.get("firstKeptEntryId"),
            retained_tail=[decode_message(item) for item in tail] if tail is not None else None,
            details=payload.get("details"),
            usage=decode_usage(payload.get("usage")),
            from_hook=bool(payload.get("fromHook", False)),
        )
    if kind == "branch_summary":
        return BranchSummaryEntry(
            **base,
            from_id=str(payload.get("fromId") or "root"),
            summary=str(payload.get("summary") or ""),
            details=payload.get("details"),
            usage=decode_usage(payload.get("usage")),
            from_hook=bool(payload.get("fromHook", False)),
        )
    if kind == "custom":
        return CustomEntry(
            **base, custom_type=str(payload.get("customType") or ""), data=payload.get("data")
        )
    if kind == "custom_message":
        return CustomMessageEntry(
            **base,
            custom_type=str(payload.get("customType") or ""),
            content=_decode_content(payload.get("content")),
            display=bool(payload.get("display", True)),
            details=payload.get("details"),
        )
    if kind == "label":
        return LabelEntry(
            **base, target_id=str(payload.get("targetId") or ""), label=payload.get("label")
        )
    if kind == "session_info":
        return SessionInfoEntry(**base, name=str(payload.get("name") or ""))
    if kind == "leaf":
        target = payload.get("targetId")
        if target is not None and not isinstance(target, str):
            raise SessionCodecError("has invalid targetId")
        return LeafEntry(**base, target_id=target)
    raise SessionCodecError(f"has unknown entry type {kind!r}")


__all__ = [
    "SessionCodecError",
    "decode_content_block",
    "decode_entry",
    "decode_message",
    "decode_usage",
    "encode_content_block",
    "encode_entry",
    "encode_message",
    "encode_usage",
]
