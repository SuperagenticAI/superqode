"""Session tree semantics (checklist S1 to S6)."""

from __future__ import annotations

import asyncio

import pytest

from superqode.pipy import AssistantMessage, TextContent, UserMessage
from superqode.pipy.session import (
    CompactionEntry,
    MemorySessionStorage,
    MessageEntry,
    Session,
    SessionError,
    create_session,
    default_context_entry_transform,
)


async def new_session() -> Session:
    return await create_session(MemorySessionStorage(cwd="/repo"))


async def test_appends_build_a_branch():
    session = await new_session()
    await session.append_message(UserMessage(content="one"))
    await session.append_message(AssistantMessage(content=[TextContent(text="two")]))

    context = await session.build_context()

    assert [message.text for message in context.messages] == ["one", "two"]


async def test_parent_chain_is_linear():
    session = await new_session()
    first = await session.append_message(UserMessage(content="one"))
    second = await session.append_message(UserMessage(content="two"))

    entries = {entry.id: entry for entry in await session.get_entries()}

    assert entries[first].parent_id is None
    assert entries[second].parent_id == first
    assert await session.get_leaf_id() == second


async def test_concurrent_appends_do_not_share_a_parent():
    session = await new_session()
    await asyncio.gather(*(session.append_message(UserMessage(content=str(i))) for i in range(8)))

    entries = await session.get_entries()
    parents = [entry.parent_id for entry in entries]

    assert len(set(parents)) == len(parents)
    assert len((await session.build_context()).messages) == 8


async def test_move_to_branches_without_rewriting_history():
    session = await new_session()
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="branch a"))

    await session.move_to(root)
    await session.append_message(UserMessage(content="branch b"))

    context = await session.build_context()
    assert [message.text for message in context.messages] == ["root", "branch b"]

    # Nothing was deleted: the abandoned branch is still in the tree.
    all_messages = [
        entry.message.text
        for entry in await session.get_entries()
        if isinstance(entry, MessageEntry)
    ]
    assert "branch a" in all_messages


async def test_move_to_records_a_branch_summary():
    session = await new_session()
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="explored"))

    await session.move_to(root, {"summary": "tried the other approach"})

    context = await session.build_context()
    texts = [
        getattr(message, "summary", getattr(message, "text", "")) for message in context.messages
    ]
    assert "tried the other approach" in texts


async def test_move_to_unknown_entry_raises():
    session = await new_session()
    with pytest.raises(SessionError):
        await session.move_to("nope")


async def test_derived_state_follows_the_branch():
    session = await new_session()
    await session.append_thinking_level_change("high")
    await session.append_model_change("anthropic", "claude-x")
    await session.append_active_tools_change(["read", "bash"])

    context = await session.build_context()

    assert context.thinking_level == "high"
    assert context.model is not None and context.model.model_id == "claude-x"
    assert context.active_tool_names == ["read", "bash"]


async def test_assistant_message_updates_derived_model():
    session = await new_session()
    await session.append_message(
        AssistantMessage(content=[TextContent(text="hi")], provider="openai", model="gpt-x")
    )

    context = await session.build_context()

    assert context.model is not None
    assert (context.model.provider, context.model.model_id) == ("openai", "gpt-x")


async def test_compaction_with_retained_tail():
    session = await new_session()
    await session.append_message(UserMessage(content="ancient"))
    await session.append_compaction(
        "summary of the past",
        tokens_before=1000,
        retained_tail=[UserMessage(content="kept tail")],
    )
    await session.append_message(UserMessage(content="after"))

    context = await session.build_context()
    texts = [
        getattr(message, "summary", getattr(message, "text", "")) for message in context.messages
    ]

    assert texts == ["summary of the past", "kept tail", "after"]


async def test_compaction_with_first_kept_entry_id():
    session = await new_session()
    await session.append_message(UserMessage(content="dropped"))
    keep = await session.append_message(UserMessage(content="kept"))
    await session.append_compaction("summary", tokens_before=10, first_kept_entry_id=keep)
    await session.append_message(UserMessage(content="after"))

    context = await session.build_context()
    texts = [
        getattr(message, "summary", getattr(message, "text", "")) for message in context.messages
    ]

    assert texts == ["summary", "kept", "after"]


async def test_compaction_never_removes_entries_from_the_tree():
    session = await new_session()
    await session.append_message(UserMessage(content="dropped"))
    await session.append_compaction("summary", tokens_before=10)

    assert len(await session.get_entries()) == 2
    assert len((await session.build_context()).messages) == 1


async def test_only_the_latest_compaction_applies():
    session = await new_session()
    await session.append_message(UserMessage(content="a"))
    await session.append_compaction("first", tokens_before=1)
    await session.append_message(UserMessage(content="b"))
    await session.append_compaction("second", tokens_before=2)
    await session.append_message(UserMessage(content="c"))

    context = await session.build_context()
    texts = [
        getattr(message, "summary", getattr(message, "text", "")) for message in context.messages
    ]

    assert texts == ["second", "c"]


def test_transform_is_a_noop_without_compaction():
    entries = [
        MessageEntry(id="1", parent_id=None, timestamp="t", message=UserMessage(content="a")),
        MessageEntry(id="2", parent_id="1", timestamp="t", message=UserMessage(content="b")),
    ]
    assert default_context_entry_transform(entries) == entries


async def test_labels_and_names():
    session = await new_session()
    target = await session.append_message(UserMessage(content="a"))
    await session.append_label(target, "checkpoint")
    await session.append_session_name("  my\nsession  ")

    assert await session.get_label(target) == "checkpoint"
    assert await session.get_session_name() == "my session"


async def test_label_on_unknown_entry_raises():
    session = await new_session()
    with pytest.raises(SessionError):
        await session.append_label("nope", "x")


async def test_custom_entries_are_invisible_by_default():
    storage = MemorySessionStorage(cwd="/repo")
    session = Session(storage, None)
    await session.append_message(UserMessage(content="visible"))
    await session.append_custom_entry("telemetry", {"k": 1})

    assert len((await session.build_context()).messages) == 1


async def test_custom_entry_projector_makes_them_visible():
    storage = MemorySessionStorage(cwd="/repo")
    session = Session(
        storage,
        None,
        projectors={"telemetry": lambda entry: [UserMessage(content="projected")]},
    )
    await session.append_custom_entry("telemetry", {"k": 1})

    assert [m.text for m in (await session.build_context()).messages] == ["projected"]


async def test_custom_message_entries_reach_the_model():
    session = await new_session()
    await session.append_custom_message_entry("note", "remember this")

    assert [m.text for m in (await session.build_context()).messages] == ["remember this"]


async def test_stats():
    session = await new_session()
    await session.append_message(UserMessage(content="a"))
    await session.append_custom_entry("x")

    stats = await session.get_stats()
    assert (stats.entry_count, stats.message_count) == (2, 1)


async def test_reopening_resumes_at_the_leaf():
    storage = MemorySessionStorage(cwd="/repo")
    session = await create_session(storage)
    await session.append_message(UserMessage(content="first"))

    resumed = await create_session(storage)
    await resumed.append_message(UserMessage(content="second"))

    assert [m.text for m in (await resumed.build_context()).messages] == ["first", "second"]


def test_compaction_entry_defaults():
    entry = CompactionEntry(id="1", parent_id=None, timestamp="t", summary="s", tokens_before=5)
    assert entry.first_kept_entry_id is None
    assert entry.retained_tail is None
