"""The session tree the harness reads its context from.

Ported from ``packages/agent/src/harness/session/session.ts`` of
earendil-works/pi (MIT).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any
from uuid import uuid4

from ..messages import (
    AgentMessage,
    BranchSummaryMessage,
    CompactionSummaryMessage,
    ImageContent,
    TextContent,
    UserMessage,
    Usage,
    AssistantMessage,
    ToolResultMessage,
    SystemMessage,
)
from ..types import JSONValue
from .entries import (
    ActiveToolsChangeEntry,
    BranchSummaryEntry,
    CompactionEntry,
    ContextEditEntry,
    UsageEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionContext,
    SessionInfoEntry,
    SessionMetadata,
    SessionModelRef,
    SessionStats,
    SessionTreeEntry,
    ThinkingLevelChangeEntry,
    current_timestamp,
)
from .storage import SessionError, SessionStorage

#: Projects a custom entry onto model-visible messages. Custom entries are
#: omitted from context unless a projector is registered for their type.
CustomEntryProjector = Callable[[CustomEntry], Sequence[AgentMessage]]


def derive_session_state(path: Sequence[SessionTreeEntry]) -> SessionContext:
    """Replay a branch to recover the model, thinking level and active tools."""
    state = SessionContext()

    def apply_tools(message: SystemMessage) -> None:
        if message.tools_added is not None or message.tools_removed is not None:
            names = dict.fromkeys(state.active_tool_names or [])
            for tool in message.tools_removed or []:
                names.pop(tool["name"], None)
            for tool in message.tools_added or []:
                names[tool["name"]] = None
            state.active_tool_names = list(names)

    for entry in path:
        if isinstance(entry, ThinkingLevelChangeEntry):
            state.thinking_level = entry.thinking_level
        elif isinstance(entry, ModelChangeEntry):
            state.model = SessionModelRef(provider=entry.provider, model_id=entry.model_id)
        elif isinstance(entry, MessageEntry):
            message = entry.message
            if getattr(message, "role", "") == "assistant":
                state.model = SessionModelRef(provider=message.provider, model_id=message.model)
            if isinstance(message, SystemMessage):
                apply_tools(message)
        elif isinstance(entry, CompactionEntry) and entry.system_message is not None:
            apply_tools(entry.system_message)
        elif isinstance(entry, ActiveToolsChangeEntry):
            state.active_tool_names = list(entry.active_tool_names)
    return state


def default_context_entry_transform(
    path: Sequence[SessionTreeEntry],
) -> list[SessionTreeEntry]:
    """Apply the most recent compaction cut to a branch.

    Everything before the compaction is dropped, except a retained tail or an
    explicit first-kept entry. The entries themselves are never removed from the
    tree, so compaction changes what the model sees and nothing else.
    """
    compaction: CompactionEntry | None = None
    for entry in path:
        if isinstance(entry, CompactionEntry):
            compaction = entry
    if compaction is None:
        return list(path)

    index = next(i for i, entry in enumerate(path) if entry is compaction)
    entries: list[SessionTreeEntry] = [compaction]

    if compaction.retained_tail:
        entries.extend(path[index + 1 :])
        return entries

    if compaction.first_kept_entry_id:
        keeping = False
        for entry in path[:index]:
            if entry.id == compaction.first_kept_entry_id:
                keeping = True
            if keeping:
                entries.append(entry)

    entries.extend(path[index + 1 :])
    return entries


def entry_to_context_messages(
    entry: SessionTreeEntry,
    projectors: dict[str, CustomEntryProjector] | None = None,
) -> list[AgentMessage]:
    """Project one tree entry onto the messages the model sees."""
    if isinstance(entry, MessageEntry):
        return [entry.message]
    if isinstance(entry, CustomMessageEntry):
        content = entry.content
        blocks: list[TextContent | ImageContent] = (
            [TextContent(text=content)] if isinstance(content, str) else list(content)
        )
        return [UserMessage(content=blocks)]
    if isinstance(entry, CompactionEntry):
        summary = CompactionSummaryMessage(
            summary=entry.summary,
            tokens_before=entry.tokens_before,
        )
        return [
            *([entry.system_message] if entry.system_message else []),
            summary,
            *(entry.retained_tail or []),
        ]
    if isinstance(entry, BranchSummaryEntry) and entry.summary:
        return [BranchSummaryMessage(summary=entry.summary, from_id=entry.from_id)]
    if isinstance(entry, CustomEntry):
        projector = (projectors or {}).get(entry.custom_type)
        return list(projector(entry)) if projector else []
    return []


def build_session_context(
    path: Sequence[SessionTreeEntry],
    projectors: dict[str, CustomEntryProjector] | None = None,
) -> SessionContext:
    """Build the full model-visible context from a branch."""
    state = derive_session_state(path)
    entries = default_context_entry_transform(path)
    edits = {entry.target_id: entry for entry in entries if isinstance(entry, ContextEditEntry)}
    messages: list[AgentMessage] = []
    for index, entry in enumerate(entries):
        # Retained ranges can include an older compaction; only the latest
        # boundary supplies its summary and checkpoint.
        if isinstance(entry, CompactionEntry) and index > 0:
            continue
        projected = entry_to_context_messages(entry, projectors)
        edit = edits.get(entry.id)
        if edit is not None:
            if edit.replacement is None:
                projected = []
            else:
                content = edit.replacement["content"]
                projected = [
                    replace(
                        message,
                        content=(
                            [TextContent(text=content)]
                            if isinstance(content, str)
                            and isinstance(message, (AssistantMessage, ToolResultMessage))
                            else content
                        ),
                    )
                    if isinstance(message, (UserMessage, AssistantMessage, ToolResultMessage))
                    else message
                    for message in projected
                ]
        messages.extend(projected)
    # Usage is accounting over the original branch, not edited model context.
    for entry in path:
        usage = getattr(entry, "usage", None)
        if isinstance(entry, MessageEntry):
            usage = getattr(entry.message, "usage", None)
        if usage is not None:
            for name in ("input", "output", "cache_read", "cache_write", "total_tokens"):
                setattr(state.usage, name, getattr(state.usage, name) + getattr(usage, name))
            if usage.reasoning is not None:
                state.usage.reasoning = (state.usage.reasoning or 0) + usage.reasoning
            for name in ("input", "output", "cache_read", "cache_write", "total"):
                setattr(
                    state.usage.cost,
                    name,
                    getattr(state.usage.cost, name) + getattr(usage.cost, name),
                )
    state.messages = messages
    return state


class Session:
    """One conversation as an append-only tree over a storage backend."""

    def __init__(
        self,
        storage: SessionStorage,
        leaf_id: str | None = None,
        *,
        projectors: dict[str, CustomEntryProjector] | None = None,
    ) -> None:
        self._storage = storage
        self._leaf_id = leaf_id
        self._projectors = dict(projectors or {})
        # Appends are serialised so that concurrent writers cannot interleave
        # and produce two entries claiming the same parent.
        self._append_lock = asyncio.Lock()

    # -- reads ------------------------------------------------------------ #

    async def get_metadata(self) -> SessionMetadata:
        return self._storage.metadata

    async def get_leaf_id(self) -> str | None:
        return self._leaf_id

    async def get_entry(self, entry_id: str) -> SessionTreeEntry | None:
        return await self._storage.read_entry(entry_id)

    async def get_entries(self) -> list[SessionTreeEntry]:
        return await self._storage.read_entries()

    async def get_branch(self) -> list[SessionTreeEntry]:
        """Entries from the root to the current leaf."""
        return await self._storage.read_path_to_root(self._leaf_id)

    async def get_branch_from(self, entry_id: str | None) -> list[SessionTreeEntry]:
        """Entries from the root to an arbitrary entry."""
        return await self._storage.read_path_to_root(entry_id)

    async def build_context(self) -> SessionContext:
        return build_session_context(await self.get_branch(), self._projectors)

    async def get_label(self, entry_id: str) -> str | None:
        return await self._storage.get_label(entry_id)

    async def get_session_name(self) -> str | None:
        return await self._storage.get_name()

    async def get_stats(self) -> SessionStats:
        return await self._storage.get_stats()

    # -- writes ----------------------------------------------------------- #

    async def _create_entry_id(self) -> str:
        for _ in range(100):
            candidate = uuid4().hex[-8:]
            if await self._storage.read_entry(candidate) is None:
                return candidate
        return uuid4().hex

    async def _append(self, build: Callable[[str, str | None, str], SessionTreeEntry]) -> str:
        async with self._append_lock:
            entry = build(await self._create_entry_id(), self._leaf_id, current_timestamp())
            await self._storage.append_entry(entry)
            self._leaf_id = entry.target_id if isinstance(entry, LeafEntry) else entry.id
            return entry.id

    async def append_message(self, message: AgentMessage) -> str:
        return await self._append(
            lambda entry_id, parent, ts: MessageEntry(
                id=entry_id, parent_id=parent, timestamp=ts, message=message
            )
        )

    async def append_context_edit(self, target_id: str, replacement: dict[str, Any] | None) -> str:
        if await self._storage.read_entry(target_id) is None:
            raise SessionError("unknown_entry", f"Unknown context edit target: {target_id}")
        return await self._append(
            lambda ident, parent, ts: ContextEditEntry(
                id=ident,
                parent_id=parent,
                timestamp=ts,
                target_id=target_id,
                replacement=replacement,
            )
        )

    async def append_usage(
        self, *, kind: str, provider: str, model: str, usage: Usage, note: str | None = None
    ) -> str:
        return await self._append(
            lambda ident, parent, ts: UsageEntry(
                id=ident,
                parent_id=parent,
                timestamp=ts,
                kind=kind,
                provider=provider,
                model=model,
                usage=usage,
                note=note,
            )
        )

    async def append_thinking_level_change(self, thinking_level: str) -> str:
        return await self._append(
            lambda entry_id, parent, ts: ThinkingLevelChangeEntry(
                id=entry_id, parent_id=parent, timestamp=ts, thinking_level=thinking_level
            )
        )

    async def append_model_change(self, provider: str, model_id: str) -> str:
        return await self._append(
            lambda entry_id, parent, ts: ModelChangeEntry(
                id=entry_id, parent_id=parent, timestamp=ts, provider=provider, model_id=model_id
            )
        )

    async def append_active_tools_change(self, active_tool_names: Sequence[str]) -> str:
        return await self._append(
            lambda entry_id, parent, ts: ActiveToolsChangeEntry(
                id=entry_id,
                parent_id=parent,
                timestamp=ts,
                active_tool_names=list(active_tool_names),
            )
        )

    async def append_compaction(
        self,
        summary: str,
        *,
        tokens_before: int,
        first_kept_entry_id: str | None = None,
        retained_tail: list[AgentMessage] | None = None,
        details: JSONValue = None,
        usage: Usage | None = None,
        from_hook: bool = False,
    ) -> str:
        return await self._append(
            lambda entry_id, parent, ts: CompactionEntry(
                id=entry_id,
                parent_id=parent,
                timestamp=ts,
                summary=summary,
                tokens_before=tokens_before,
                first_kept_entry_id=first_kept_entry_id,
                retained_tail=retained_tail,
                details=details,
                usage=usage,
                from_hook=from_hook,
            )
        )

    async def append_custom_entry(self, custom_type: str, data: JSONValue = None) -> str:
        return await self._append(
            lambda entry_id, parent, ts: CustomEntry(
                id=entry_id, parent_id=parent, timestamp=ts, custom_type=custom_type, data=data
            )
        )

    async def append_custom_message_entry(
        self,
        custom_type: str,
        content: str | list[TextContent | ImageContent],
        *,
        display: bool = True,
        details: JSONValue = None,
    ) -> str:
        return await self._append(
            lambda entry_id, parent, ts: CustomMessageEntry(
                id=entry_id,
                parent_id=parent,
                timestamp=ts,
                custom_type=custom_type,
                content=content,
                display=display,
                details=details,
            )
        )

    async def append_label(self, target_id: str, label: str | None) -> str:
        if await self._storage.read_entry(target_id) is None:
            raise SessionError("not_found", f"Entry {target_id} not found")
        return await self._append(
            lambda entry_id, parent, ts: LabelEntry(
                id=entry_id, parent_id=parent, timestamp=ts, target_id=target_id, label=label
            )
        )

    async def append_session_name(self, name: str) -> str:
        sanitized = " ".join(name.replace("\r", " ").replace("\n", " ").split())
        return await self._append(
            lambda entry_id, parent, ts: SessionInfoEntry(
                id=entry_id, parent_id=parent, timestamp=ts, name=sanitized
            )
        )

    async def move_to(
        self,
        entry_id: str | None,
        summary: dict[str, Any] | None = None,
    ) -> str | None:
        """Move the current leaf, optionally recording a branch summary.

        The summary describes the branch being left, so a later turn can tell
        the model what happened on the path it came back from.
        """
        if entry_id is not None and await self._storage.read_entry(entry_id) is None:
            raise SessionError("not_found", f"Entry {entry_id} not found")

        await self._append(
            lambda new_id, parent, ts: LeafEntry(
                id=new_id, parent_id=parent, timestamp=ts, target_id=entry_id
            )
        )
        if not summary:
            return None
        return await self._append(
            lambda new_id, parent, ts: BranchSummaryEntry(
                id=new_id,
                parent_id=parent,
                timestamp=ts,
                from_id=entry_id or "root",
                summary=str(summary.get("summary") or ""),
                details=summary.get("details"),
                usage=summary.get("usage"),
                from_hook=bool(summary.get("from_hook", False)),
            )
        )


async def create_session(
    storage: SessionStorage,
    *,
    projectors: dict[str, CustomEntryProjector] | None = None,
) -> Session:
    """Open a session at the storage's current head."""
    return Session(storage, await storage.read_head(), projectors=projectors)


__all__ = [
    "CustomEntryProjector",
    "Session",
    "build_session_context",
    "create_session",
    "default_context_entry_transform",
    "derive_session_state",
    "entry_to_context_messages",
]
