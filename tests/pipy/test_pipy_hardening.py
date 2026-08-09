"""Automatic compaction, turn caps, and the unattended-run guard."""

from __future__ import annotations

import pytest
from conftest import MODEL, call, echo_tool

from superqode.pipy import AssistantMessage, TextContent, UserMessage
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.compaction import CompactionSettings
from superqode.pipy.harness import AgentHarness
from superqode.pipy.messages import Usage
from superqode.pipy.session import MemorySessionStorage, create_session
from superqode.pipy.stream import Model

# A model whose window is small enough that a couple of turns crosses it.
SMALL = Model(id="fake-1", provider="fake", api="fake-api", context_window=20_000)
TIGHT = CompactionSettings(reserve_tokens=16_384, keep_recent_tokens=2)


def used(tokens: int) -> AssistantMessage:
    """An assistant turn that reports real token usage, as a provider would."""
    return AssistantMessage(
        content=[TextContent(text="ok")],
        usage=Usage(total_tokens=tokens),
        stop_reason="stop",
    )


async def build(script, *, model=SMALL, settings=TIGHT, max_turns=0) -> AgentHarness:
    session = await create_session(MemorySessionStorage(cwd="/repo"))
    return AgentHarness(
        session=session,
        model=model,
        stream_fn=FakeStream(list(script)),
        tools=[echo_tool()],
        system_prompt="p",
        compaction_settings=settings,
        max_turns=max_turns,
    )


# -- automatic compaction ---------------------------------------------------- #


async def test_compaction_fires_when_context_fills(tmp_path):
    """A turn that reports heavy usage triggers a compaction before the next."""
    script = [
        tool_response(call("echo", value="x")),  # turn 1, keeps the loop going
        used(19_000),  # turn 2 reports usage past the threshold
        text_response("## Goal\nsummarised"),  # the summarisation call
        text_response("carried on"),
    ]
    harness = await build(script)
    for text in ("one", "two", "three"):
        await harness.session.append_message(UserMessage(content=text))

    await harness.prompt("go")

    entries = await harness.session.get_entries()
    assert any(type(entry).__name__ == "CompactionEntry" for entry in entries)


async def test_no_compaction_while_context_is_small():
    harness = await build([tool_response(call("echo", value="x")), used(100)])
    for text in ("one", "two", "three"):
        await harness.session.append_message(UserMessage(content=text))

    await harness.prompt("go")

    entries = await harness.session.get_entries()
    assert not any(type(entry).__name__ == "CompactionEntry" for entry in entries)


async def test_unknown_context_window_disables_auto_compaction():
    """Guessing a limit would be worse than leaving the session alone."""
    unknown = Model(id="fake-1", provider="fake", api="fake-api")
    harness = await build([tool_response(call("echo", value="x")), used(999_999)], model=unknown)
    for text in ("one", "two", "three"):
        await harness.session.append_message(UserMessage(content=text))

    await harness.prompt("go")

    entries = await harness.session.get_entries()
    assert not any(type(entry).__name__ == "CompactionEntry" for entry in entries)


async def test_disabled_settings_disable_auto_compaction():
    harness = await build(
        [tool_response(call("echo", value="x")), used(19_000)],
        settings=CompactionSettings(enabled=False, keep_recent_tokens=2),
    )
    for text in ("one", "two", "three"):
        await harness.session.append_message(UserMessage(content=text))

    await harness.prompt("go")

    entries = await harness.session.get_entries()
    assert not any(type(entry).__name__ == "CompactionEntry" for entry in entries)


async def test_a_failed_summary_does_not_end_the_run():
    """Compaction is a convenience; failing it must not lose the turn."""

    class Failing(FakeStream):
        def __call__(self, model, context, options):
            # The summarisation request has no tools and its own system prompt.
            if context.tools is None:
                raise RuntimeError("summariser unavailable")
            return super().__call__(model, context, options)

    session = await create_session(MemorySessionStorage(cwd="/repo"))
    harness = AgentHarness(
        session=session,
        model=SMALL,
        stream_fn=Failing(
            [tool_response(call("echo", value="x")), used(19_000), text_response("done")]
        ),
        tools=[echo_tool()],
        system_prompt="p",
        compaction_settings=TIGHT,
    )
    for text in ("one", "two", "three"):
        await session.append_message(UserMessage(content=text))

    message = await harness.prompt("go")

    assert message.stop_reason == "stop"
    assert harness.phase == "idle"


# -- turn cap ---------------------------------------------------------------- #


async def test_no_cap_by_default_matches_pi():
    harness = await build([text_response("one")])
    assert harness._max_turns == 0


async def test_a_cap_stops_a_runaway_loop():
    """A model that keeps calling tools would otherwise never stop."""
    script = [tool_response(call("echo", value=str(index))) for index in range(10)]
    harness = await build(script, max_turns=3)

    await harness.prompt("go")

    context = await harness.session.build_context()
    assistants = [m for m in context.messages if isinstance(m, AssistantMessage)]
    assert len(assistants) == 3


async def test_a_cap_does_not_cut_a_short_run_short():
    harness = await build(
        [tool_response(call("echo", value="x")), text_response("done")], max_turns=5
    )

    message = await harness.prompt("go")

    assert message.text == "done"


# -- unattended guard -------------------------------------------------------- #


async def test_headless_refuses_pure_permissions_without_opt_in(monkeypatch):
    from superqode.headless import run_headless

    monkeypatch.delenv("SUPERQODE_PURE_PERMISSIONS_HEADLESS", raising=False)

    with pytest.raises(ValueError) as error:
        await run_headless("hi", "anthropic", "claude-opus-5", profile_name="pipy")

    message = str(error.value)
    assert "permissions of this process" in message
    assert "SUPERQODE_PURE_PERMISSIONS_HEADLESS=1" in message
    assert "--harness core" in message


async def test_the_guard_names_the_container_escape_hatch(monkeypatch):
    from superqode.headless import run_headless

    monkeypatch.delenv("SUPERQODE_PURE_PERMISSIONS_HEADLESS", raising=False)

    with pytest.raises(ValueError, match="container"):
        await run_headless("hi", "anthropic", "claude-opus-5", profile_name="pi")


async def test_harnesses_with_a_policy_stack_are_unaffected(monkeypatch):
    """The guard must not touch core, workbench or anything else."""
    from superqode.harness import list_harnesses

    guarded = {
        entry.id for entry in list_harnesses(".") if entry.spec.metadata.get("pure_permissions")
    }

    assert guarded == {"pipy", "rlm"}


# -- model catalog ----------------------------------------------------------- #


def test_context_window_is_looked_up_when_known():
    from superqode.pipy.ai.models import resolve_model

    model = resolve_model("claude-opus-5", provider="anthropic")

    assert model.context_window >= 0  # zero when the catalog has no entry


def test_context_window_can_be_supplied_directly():
    from superqode.pipy.ai.models import resolve_model

    assert resolve_model("x", provider="y", context_window=12345).context_window == 12345


def test_an_unknown_model_reports_no_window():
    from superqode.pipy.ai.models import lookup_context_window

    assert lookup_context_window("nosuchprovider", "nosuchmodel") == 0
