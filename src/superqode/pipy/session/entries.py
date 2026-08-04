"""Session tree entry types.

Ported from ``packages/agent/src/harness/types.ts`` of earendil-works/pi (MIT).

A session is an append-only tree. Nothing is ever rewritten: moving the current
leaf, renaming, labelling and compacting are all new entries. Phase 3 persists
these as JSONL; phase 2 keeps them in memory behind the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..messages import AgentMessage, ImageContent, TextContent, Usage
from ..types import JSONValue


def current_timestamp() -> str:
    """ISO-8601 timestamp, the on-disk format pi uses for tree entries."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class _EntryBase:
    id: str
    parent_id: str | None
    timestamp: str


@dataclass(slots=True)
class MessageEntry(_EntryBase):
    message: AgentMessage
    type: Literal["message"] = "message"


@dataclass(slots=True)
class ThinkingLevelChangeEntry(_EntryBase):
    thinking_level: str
    type: Literal["thinking_level_change"] = "thinking_level_change"


@dataclass(slots=True)
class ModelChangeEntry(_EntryBase):
    provider: str
    model_id: str
    type: Literal["model_change"] = "model_change"


@dataclass(slots=True)
class ActiveToolsChangeEntry(_EntryBase):
    active_tool_names: list[str]
    type: Literal["active_tools_change"] = "active_tools_change"


@dataclass(slots=True)
class CompactionEntry(_EntryBase):
    summary: str
    tokens_before: int
    #: Everything before this entry is dropped from context, except the tail
    #: starting at this id when it is set.
    first_kept_entry_id: str | None = None
    #: Messages replayed verbatim after the summary, when compaction chose to
    #: retain a tail rather than an entry cut point.
    retained_tail: list[AgentMessage] | None = None
    details: JSONValue = None
    usage: Usage | None = None
    from_hook: bool = False
    type: Literal["compaction"] = "compaction"


@dataclass(slots=True)
class BranchSummaryEntry(_EntryBase):
    from_id: str
    summary: str = ""
    details: JSONValue = None
    usage: Usage | None = None
    from_hook: bool = False
    type: Literal["branch_summary"] = "branch_summary"


@dataclass(slots=True)
class CustomEntry(_EntryBase):
    """An application entry that is invisible to the model by default."""

    custom_type: str
    data: JSONValue = None
    type: Literal["custom"] = "custom"


@dataclass(slots=True)
class CustomMessageEntry(_EntryBase):
    """An application entry that does reach the model, as a user message."""

    custom_type: str
    content: str | list[TextContent | ImageContent] = ""
    display: bool = True
    details: JSONValue = None
    type: Literal["custom_message"] = "custom_message"


@dataclass(slots=True)
class LabelEntry(_EntryBase):
    target_id: str
    label: str | None = None
    type: Literal["label"] = "label"


@dataclass(slots=True)
class SessionInfoEntry(_EntryBase):
    name: str = ""
    type: Literal["session_info"] = "session_info"


@dataclass(slots=True)
class LeafEntry(_EntryBase):
    """Moves the current leaf. This is how branching happens without a rewrite."""

    target_id: str | None = None
    type: Literal["leaf"] = "leaf"


SessionTreeEntry = (
    MessageEntry
    | ThinkingLevelChangeEntry
    | ModelChangeEntry
    | ActiveToolsChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | CustomEntry
    | CustomMessageEntry
    | LabelEntry
    | SessionInfoEntry
    | LeafEntry
)


@dataclass(slots=True)
class SessionMetadata:
    id: str
    cwd: str
    timestamp: str = field(default_factory=current_timestamp)
    parent_session: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionModelRef:
    provider: str
    model_id: str


@dataclass(slots=True)
class SessionContext:
    """Model-visible state derived from the current branch."""

    messages: list[AgentMessage] = field(default_factory=list)
    thinking_level: str = "off"
    model: SessionModelRef | None = None
    active_tool_names: list[str] | None = None


@dataclass(slots=True)
class SessionStats:
    entry_count: int = 0
    message_count: int = 0


__all__ = [
    "ActiveToolsChangeEntry",
    "BranchSummaryEntry",
    "CompactionEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "LabelEntry",
    "LeafEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "SessionContext",
    "SessionInfoEntry",
    "SessionMetadata",
    "SessionModelRef",
    "SessionStats",
    "SessionTreeEntry",
    "ThinkingLevelChangeEntry",
    "current_timestamp",
]
