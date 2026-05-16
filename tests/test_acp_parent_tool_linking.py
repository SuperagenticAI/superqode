"""Tests for ACP tool-call parent linking (B6 from the fast-agent gap audit).

Covers two halves:

1. The local ContextVar (``acp_tool_call_context``) so nested tools spawned
   inside a SubAgentTool inherit the parent's tool_call_id as
   ``parentToolCallId``.
2. The ACP client side preserving ``_meta.parentToolCallId`` from incoming
   tool_call notifications, plus the late-arriving ``tool_call_update``
   synthesis fix (adjacent toad-audit Tier B #10).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from superqode.acp.client import ACPClient
from superqode.acp.tool_call_context import (
    ACPToolCallContext,
    acp_tool_call_context,
    get_acp_tool_call_context,
    get_acp_tool_call_meta,
    get_parent_tool_call_id,
)


# ---------------------------------------------------------------------------
# ContextVar — local side
# ---------------------------------------------------------------------------


def test_no_context_returns_none():
    """At the top level, every accessor must return ``None`` — emitting
    a ``parentToolCallId`` of ``None`` would mark every root tool call
    as a child of nothing, which serializes oddly."""
    assert get_acp_tool_call_context() is None
    assert get_acp_tool_call_meta() is None
    assert get_parent_tool_call_id() is None


def test_context_within_with_block_sets_parent():
    with acp_tool_call_context(parent_tool_call_id="abc-123"):
        assert get_parent_tool_call_id() == "abc-123"
        assert get_acp_tool_call_meta() == {"parentToolCallId": "abc-123"}


def test_context_resets_after_with_block():
    """ContextVar token reset must restore the prior state, not leak."""
    with acp_tool_call_context(parent_tool_call_id="abc"):
        assert get_parent_tool_call_id() == "abc"
    assert get_parent_tool_call_id() is None


def test_nested_contexts_override_only_what_they_specify():
    """The merge semantic matters: ACP servers may want to override
    only one field at a deeper level. Right now we only carry one field,
    so this proves the merge contract for when we add more."""
    with acp_tool_call_context(parent_tool_call_id="outer"):
        with acp_tool_call_context(parent_tool_call_id="inner"):
            assert get_parent_tool_call_id() == "inner"
        assert get_parent_tool_call_id() == "outer"


def test_to_meta_returns_none_when_empty():
    """An empty context must serialize to ``None`` — agents that
    receive ``_meta: {}`` and check truthiness would otherwise
    treat the field as set."""
    assert ACPToolCallContext().to_meta() is None


@pytest.mark.asyncio
async def test_context_propagates_into_create_task():
    """The whole reason for using ContextVar over a plain global is
    that asyncio.create_task copies the current context. SubAgentTool
    runs the child in a background task, so this propagation is the
    load-bearing behavior."""

    results: dict = {}

    async def child() -> None:
        results["parent"] = get_parent_tool_call_id()

    with acp_tool_call_context(parent_tool_call_id="call-42"):
        task = asyncio.create_task(child())
    await task

    assert results["parent"] == "call-42"


@pytest.mark.asyncio
async def test_concurrent_tasks_dont_see_each_others_context():
    """ContextVar isolation between concurrent tasks — if it leaked,
    parallel sub-agent runs would tag each others' tool calls."""

    seen: list = []

    async def child(parent_id: str) -> None:
        with acp_tool_call_context(parent_tool_call_id=parent_id):
            await asyncio.sleep(0.01)
            seen.append((parent_id, get_parent_tool_call_id()))

    await asyncio.gather(child("a"), child("b"), child("c"))
    # Each task saw its own parent id, not another's.
    for declared, observed in seen:
        assert declared == observed


# ---------------------------------------------------------------------------
# ACP client — receive side
# ---------------------------------------------------------------------------


def _client() -> ACPClient:
    """Build a client without starting a process — we only exercise
    the JSON-RPC update routing."""
    return ACPClient(project_root=Path.cwd(), command="(unused)")


@pytest.mark.asyncio
async def test_incoming_tool_call_preserves_parent_in_action_record():
    """When an agent emits a tool_call with ``_meta.parentToolCallId``,
    the action record we keep for stats/UI must surface that id without
    requiring consumers to dig into raw ``_meta``."""
    client = _client()
    await client._handle_session_update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "child-1",
            "title": "read_file",
            "kind": "read",
            "rawInput": {"path": "x"},
            "_meta": {"parentToolCallId": "parent-9"},
        }
    )
    assert client._tool_actions == [
        {
            "tool": "read_file",
            "kind": "read",
            "input": {"path": "x"},
            "tool_call_id": "child-1",
            "parent_tool_call_id": "parent-9",
        }
    ]
    # Raw dict is also kept (with _meta intact) for any downstream
    # consumer that wants the full payload.
    assert client._tool_calls["child-1"]["_meta"]["parentToolCallId"] == "parent-9"


@pytest.mark.asyncio
async def test_incoming_tool_call_without_meta_has_none_parent():
    """Top-level tool calls (no parent) get ``None`` so consumers can
    tell "no parent" apart from "parent unknown"."""
    client = _client()
    await client._handle_session_update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "root-1",
            "title": "read_file",
            "kind": "read",
            "rawInput": {},
        }
    )
    assert client._tool_actions[0]["parent_tool_call_id"] is None


@pytest.mark.asyncio
async def test_late_tool_call_update_synthesizes_placeholder():
    """Some agents (OpenHands, some Codex builds) skip the initial
    ``tool_call`` and emit only ``tool_call_update`` events. Before
    this fix we dropped them silently. Now we synthesize a placeholder
    and dispatch as a tool_call so the UI never loses an update."""
    client = _client()
    seen_calls: list = []
    seen_updates: list = []

    async def on_call(tc):
        seen_calls.append(tc)

    async def on_update(tc):
        seen_updates.append(tc)

    client.on_tool_call = on_call
    client.on_tool_update = on_update

    await client._handle_session_update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "orphan-1",
            "status": "in_progress",
            "title": "write_file",
        }
    )

    assert "orphan-1" in client._tool_calls
    synthesized = client._tool_calls["orphan-1"]
    assert synthesized["title"] == "write_file"
    assert synthesized["status"] == "in_progress"
    # First-time sighting routes through on_tool_call, not on_tool_update,
    # so the UI gets a chance to create the row.
    assert len(seen_calls) == 1
    assert seen_updates == []


@pytest.mark.asyncio
async def test_subsequent_tool_call_update_merges_normally():
    """Once a tool_call exists, follow-up updates merge — not synthesize
    a duplicate. Guards against accidentally treating every update as
    a brand-new tool call."""
    client = _client()
    await client._handle_session_update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "x",
            "title": "read_file",
            "kind": "read",
            "rawInput": {},
        }
    )
    await client._handle_session_update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "x",
            "status": "completed",
        }
    )
    assert client._tool_calls["x"]["status"] == "completed"
    assert client._tool_calls["x"]["title"] == "read_file"  # not clobbered
