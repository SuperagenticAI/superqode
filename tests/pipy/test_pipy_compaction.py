"""Compaction and branch summarization (checklist H9)."""

from __future__ import annotations

import pytest
from conftest import MODEL

from superqode.pipy import AssistantMessage, TextContent, UserMessage
from superqode.pipy.ai import FakeStream, text_response
from superqode.pipy.compaction import (
    SUMMARIZATION_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT,
    UPDATE_SUMMARIZATION_PROMPT,
    CompactionSettings,
    calculate_context_tokens,
    estimate_message_tokens,
    get_last_assistant_usage,
    prepare_compaction,
    should_compact,
)
from superqode.pipy.harness import AgentHarness
from superqode.pipy.messages import Usage
from superqode.pipy.session import MemorySessionStorage, SessionRepository, create_session

# Small enough that a handful of short messages crosses the threshold.
TIGHT = CompactionSettings(keep_recent_tokens=2)


async def session_with(*texts: str):
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    for text in texts:
        await session.append_message(UserMessage(content=text))
    return session


def test_should_compact_respects_the_reserve():
    settings = CompactionSettings(reserve_tokens=1000)
    assert should_compact(9500, 10000, settings) is True
    assert should_compact(8000, 10000, settings) is False


def test_should_compact_off_when_disabled():
    settings = CompactionSettings(enabled=False, reserve_tokens=1000)
    assert should_compact(99999, 10000, settings) is False


def test_calculate_context_tokens_prefers_the_total():
    assert calculate_context_tokens(Usage(total_tokens=42, input=1)) == 42
    assert calculate_context_tokens(Usage(input=1, output=2, cache_read=3, cache_write=4)) == 10


async def test_last_assistant_usage_skips_failed_turns():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    await session.append_message(
        AssistantMessage(content=[TextContent(text="good")], usage=Usage(total_tokens=100))
    )
    await session.append_message(
        AssistantMessage(content=[], stop_reason="error", usage=Usage(total_tokens=999))
    )

    usage = get_last_assistant_usage(await session.get_branch())

    assert usage is not None and usage.total_tokens == 100


def test_estimate_counts_images_as_a_block_of_characters():
    from superqode.pipy.messages import ImageContent

    text_only = UserMessage(content=[TextContent(text="x" * 400)])
    with_image = UserMessage(content=[ImageContent(data="", mime_type="image/png")])

    assert estimate_message_tokens(text_only) == 100
    assert estimate_message_tokens(with_image) > estimate_message_tokens(text_only)


async def test_prepare_returns_none_for_a_short_session():
    session = await session_with("only one")
    assert prepare_compaction(await session.get_branch(), CompactionSettings()) is None


async def test_prepare_returns_none_when_already_compacted():
    session = await session_with("a", "b")
    await session.append_compaction("done", tokens_before=10)

    assert prepare_compaction(await session.get_branch(), TIGHT) is None


async def test_prepare_splits_history_from_the_recent_tail():
    session = await session_with("oldest", "middle", "newest")

    preparation = prepare_compaction(await session.get_branch(), TIGHT)

    assert preparation is not None
    summarized = [m.text for m in preparation.messages_to_summarize]
    retained = [m.text for m in preparation.retained_tail]
    assert summarized and retained
    assert summarized + retained == ["oldest", "middle", "newest"]
    assert preparation.tokens_before > 0


async def test_prepare_carries_the_previous_summary_forward():
    session = await session_with("a")
    await session.append_compaction("earlier summary", tokens_before=5)
    for text in ("b", "c", "d"):
        await session.append_message(UserMessage(content=text))

    preparation = prepare_compaction(await session.get_branch(), TIGHT)

    assert preparation is not None
    assert preparation.previous_summary == "earlier summary"
    # Messages before the earlier compaction are not summarized twice.
    assert "a" not in [m.text for m in preparation.messages_to_summarize]


# -- harness integration ---------------------------------------------------- #


async def build_harness(session, script):
    return AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=FakeStream(list(script)),
        system_prompt="p",
        compaction_settings=TIGHT,
    )


async def test_compact_appends_an_entry_and_shortens_context():
    session = await session_with("oldest", "middle", "newest")
    harness = await build_harness(session, [text_response("## Goal\nship it")])

    result = await harness.compact()

    assert result is not None
    assert result.summary.startswith("## Goal")
    context = await session.build_context()
    texts = [getattr(m, "summary", getattr(m, "text", "")) for m in context.messages]
    assert texts[0] == "## Goal\nship it"
    assert "oldest" not in texts


async def test_compact_keeps_the_full_history_in_the_tree():
    session = await session_with("oldest", "middle", "newest")
    harness = await build_harness(session, [text_response("summary")])
    before = len(await session.get_entries())

    await harness.compact()

    # Only the compaction entry was added; nothing was removed.
    assert len(await session.get_entries()) == before + 1
    entry_texts = [
        entry.message.text for entry in await session.get_entries() if hasattr(entry, "message")
    ]
    assert "oldest" in entry_texts

    # The model no longer sees the summarized part.
    visible = [
        getattr(m, "summary", getattr(m, "text", ""))
        for m in (await session.build_context()).messages
    ]
    assert "oldest" not in visible
    assert "summary" in visible


async def test_compact_uses_pi_summarization_prompts():
    session = await session_with("oldest", "middle", "newest")
    stream = FakeStream([text_response("summary")])
    harness = AgentHarness(
        session=session, model=MODEL, stream_fn=stream, system_prompt="p", compaction_settings=TIGHT
    )

    await harness.compact()

    assert stream.calls[0].system_prompt == SUMMARIZATION_SYSTEM_PROMPT
    assert stream.calls[0].messages[-1].text == SUMMARIZATION_PROMPT


async def test_compact_switches_to_the_update_prompt():
    session = await session_with("a")
    await session.append_compaction("earlier", tokens_before=5)
    for text in ("b", "c", "d"):
        await session.append_message(UserMessage(content=text))
    stream = FakeStream([text_response("updated")])
    harness = AgentHarness(
        session=session, model=MODEL, stream_fn=stream, system_prompt="p", compaction_settings=TIGHT
    )

    await harness.compact()

    instruction = stream.calls[0].messages[-1].text
    assert "<previous-summary>\nearlier\n</previous-summary>" in instruction
    assert UPDATE_SUMMARIZATION_PROMPT in instruction


async def test_compact_appends_custom_instructions():
    session = await session_with("oldest", "middle", "newest")
    stream = FakeStream([text_response("summary")])
    harness = AgentHarness(
        session=session, model=MODEL, stream_fn=stream, system_prompt="p", compaction_settings=TIGHT
    )

    await harness.compact("focus on the failing test")

    assert "focus on the failing test" in stream.calls[0].messages[-1].text


async def test_compact_returns_none_when_there_is_nothing_to_do():
    session = await session_with("only one")
    harness = AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=FakeStream([text_response("unused")]),
        system_prompt="p",
    )

    assert await harness.compact() is None
    assert harness.phase == "idle"


async def test_compact_survives_a_provider_failure():
    session = await session_with("oldest", "middle", "newest")

    def exploding(model, context, options):
        raise RuntimeError("summarizer down")

    harness = AgentHarness(
        session=session,
        model=MODEL,
        stream_fn=exploding,
        system_prompt="p",
        compaction_settings=TIGHT,
    )

    with pytest.raises(Exception) as error:
        await harness.compact()

    assert getattr(error.value, "code", "") == "compaction"
    assert harness.phase == "idle"
    # Nothing was written, so the session is untouched.
    assert len(await session.get_entries()) == 3


async def test_compact_round_trips_through_disk(tmp_path):
    repo = SessionRepository(tmp_path / "sessions")
    session, path = await repo.create(tmp_path)
    for text in ("oldest", "middle", "newest"):
        await session.append_message(UserMessage(content=text))
    harness = await build_harness(session, [text_response("## Goal\npersisted")])

    await harness.compact()
    reopened = await repo.open(path)

    texts = [
        getattr(m, "summary", getattr(m, "text", ""))
        for m in (await reopened.build_context()).messages
    ]
    assert texts[0] == "## Goal\npersisted"


# -- navigate_tree ---------------------------------------------------------- #


async def test_navigate_tree_moves_the_leaf_and_summarizes():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="explored a dead end"))
    harness = await build_harness(session, [text_response("tried X, did not work")])

    summary = await harness.navigate_tree(root)

    assert summary == "tried X, did not work"
    texts = [
        getattr(m, "summary", getattr(m, "text", ""))
        for m in (await session.build_context()).messages
    ]
    assert texts == ["root", "tried X, did not work"]


async def test_navigate_tree_without_summarizing():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="abandoned"))
    harness = await build_harness(session, [])

    summary = await harness.navigate_tree(root, summarize=False)

    assert summary is None
    assert [m.text for m in (await session.build_context()).messages] == ["root"]


async def test_navigate_tree_still_moves_when_summarizing_fails():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="abandoned"))

    def exploding(model, context, options):
        raise RuntimeError("summarizer down")

    harness = AgentHarness(session=session, model=MODEL, stream_fn=exploding, system_prompt="p")

    summary = await harness.navigate_tree(root)

    assert summary is None
    assert [m.text for m in (await session.build_context()).messages] == ["root"]


async def test_navigating_back_recovers_the_branch():
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    root = await session.append_message(UserMessage(content="root"))
    branch_leaf = await session.append_message(UserMessage(content="branch a"))
    harness = await build_harness(session, [text_response("s1"), text_response("s2")])

    await harness.navigate_tree(root)
    await session.append_message(UserMessage(content="branch b"))
    await harness.navigate_tree(branch_leaf)

    texts = [m.text for m in (await session.build_context()).messages if hasattr(m, "text")]
    assert "branch a" in texts
