"""Tool-call state tracker, dual-keyed by id and index.

Providers disagree on how to identify in-flight tool calls during a stream:

- Anthropic streams reference calls by ``tool_use_id`` (string).
- OpenAI streams reference calls by ``index`` (integer) for deltas, then
  emit the final ``id`` later. Multiple deltas can arrive before the id.

If you only key by id, OpenAI deltas with no id yet get lost. If you only
key by index, Anthropic calls (which never have an index) don't fit.
:class:`ToolCallTracker` indexes by *both* so either provider style works.

Ported from fast-agent's ``llm/tool_tracking.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


ToolKind = Literal["tool", "server_tool", "web_search"]


def _is_generic_tool_name(value: str) -> bool:
    """A name is 'generic' if the provider hasn't told us the real one yet."""
    return not value or value == "tool"


@dataclass(slots=True)
class ToolCallState:
    """One open or completed tool call."""

    tool_use_id: str
    name: str
    kind: ToolKind = "tool"
    index: Optional[int] = None
    start_notified: bool = False


class ToolCallTracker:
    """Track open and completed tool calls for a single LLM stream.

    The tracker handles three real-world provider quirks:

    1. OpenAI emits index-only tool deltas before the final id is known.
    2. Anthropic emits id-only tool_use blocks with no index concept.
    3. Both providers may send tool name as a placeholder ('tool') first
       and then the real name in a later delta - the real name wins.
    """

    def __init__(self) -> None:
        self._open_by_id: Dict[str, ToolCallState] = {}
        self._open_by_index: Dict[int, ToolCallState] = {}
        self._completed_by_id: Dict[str, ToolCallState] = {}
        self._completed_by_index: Dict[int, ToolCallState] = {}

    def register(
        self,
        *,
        tool_use_id: str,
        name: str,
        index: Optional[int] = None,
        kind: ToolKind = "tool",
    ) -> ToolCallState:
        """Register or update a tool call.

        Calling ``register`` repeatedly for the same call (id or index)
        merges the new fields into the existing state - this is how OpenAI
        index-only deltas converge with the final id-bearing delta.
        """
        state = self._open_by_id.get(tool_use_id)
        if state is None and index is not None:
            state = self._open_by_index.get(index)
            if state is not None and state.tool_use_id != tool_use_id:
                self._rekey_open_state(state, tool_use_id)

        if state is None:
            state = ToolCallState(tool_use_id=tool_use_id, name=name, kind=kind, index=index)
            self._open_by_id[tool_use_id] = state
        else:
            # Real name beats generic placeholder. Specialized kind beats 'tool'.
            if not _is_generic_tool_name(name) or _is_generic_tool_name(state.name):
                state.name = name
            if state.kind == "tool" and kind != "tool":
                state.kind = kind

        if index is not None:
            self._attach_index(state, index)

        self._open_by_id[state.tool_use_id] = state
        return state

    def resolve_open(
        self,
        *,
        tool_use_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Optional[ToolCallState]:
        """Look up an open call by either key. Returns None if not open."""
        if tool_use_id is not None and tool_use_id in self._open_by_id:
            return self._open_by_id[tool_use_id]
        if index is not None and index in self._open_by_index:
            return self._open_by_index[index]
        return None

    def resolve(
        self,
        *,
        tool_use_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Optional[ToolCallState]:
        """Look up a call, open or completed."""
        state = self.resolve_open(tool_use_id=tool_use_id, index=index)
        if state is not None:
            return state
        if tool_use_id is not None and tool_use_id in self._completed_by_id:
            return self._completed_by_id[tool_use_id]
        if index is not None and index in self._completed_by_index:
            return self._completed_by_index[index]
        return None

    def close(
        self,
        *,
        tool_use_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> Optional[ToolCallState]:
        """Move an open call to the completed set. Returns the state, or None."""
        state = self.resolve_open(tool_use_id=tool_use_id, index=index)
        if state is None:
            return None

        self._open_by_id.pop(state.tool_use_id, None)
        if state.index is not None:
            self._open_by_index.pop(state.index, None)

        self._completed_by_id[state.tool_use_id] = state
        if state.index is not None:
            self._completed_by_index[state.index] = state
        return state

    def rekey_open(
        self,
        *,
        tool_use_id: str,
        new_tool_use_id: str,
    ) -> Optional[ToolCallState]:
        """Rename an open call's id (e.g. when OpenAI finally sends the real id)."""
        state = self._open_by_id.get(tool_use_id)
        if state is None:
            return None
        self._rekey_open_state(state, new_tool_use_id)
        return state

    def is_completed(
        self,
        *,
        tool_use_id: Optional[str] = None,
        index: Optional[int] = None,
    ) -> bool:
        if tool_use_id is not None and tool_use_id in self._completed_by_id:
            return True
        if index is not None and index in self._completed_by_index:
            return True
        return False

    def incomplete(self) -> List[ToolCallState]:
        """Open calls that haven't been closed yet."""
        return list(self._open_by_id.values())

    def completed(self) -> List[ToolCallState]:
        return list(self._completed_by_id.values())

    # --- internal -----------------------------------------------------------

    def _attach_index(self, state: ToolCallState, index: int) -> None:
        if state.index is not None and state.index != index:
            self._open_by_index.pop(state.index, None)
        state.index = index
        self._open_by_index[index] = state

    def _rekey_open_state(self, state: ToolCallState, new_tool_use_id: str) -> None:
        if state.tool_use_id == new_tool_use_id:
            return
        self._open_by_id.pop(state.tool_use_id, None)
        state.tool_use_id = new_tool_use_id
        self._open_by_id[new_tool_use_id] = state


__all__ = ["ToolCallState", "ToolCallTracker", "ToolKind"]
