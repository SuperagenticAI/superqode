"""The coding session: wiring, resources and commands (checklist C1 to C12)."""

from __future__ import annotations

import json

import pytest
from conftest import MODEL

from superqode.pipy import ToolCall, ToolResultMessage, UserMessage
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.coding_session import (
    SLASH_COMMANDS,
    CodingSessionOptions,
    PiPyCodingSession,
)
from superqode.pipy.harness_events import AgentHarnessError


def options(tmp_path, script=(), **kwargs) -> CodingSessionOptions:
    return CodingSessionOptions(
        cwd=tmp_path,
        model=MODEL,
        stream_fn=FakeStream(list(script)),
        session_root=tmp_path / ".sessions",
        **kwargs,
    )


async def open_session(tmp_path, script=(), **kwargs) -> PiPyCodingSession:
    return await PiPyCodingSession.create(options(tmp_path, script, **kwargs))


# -- construction ------------------------------------------------------------ #


async def test_create_writes_a_session_file(tmp_path):
    session = await open_session(tmp_path)

    assert session.session_path.is_file()
    header = json.loads(session.session_path.read_text().splitlines()[0])
    assert header["version"] == 3
    assert header["cwd"] == str(tmp_path.resolve())


async def test_default_tools_are_pis_four(tmp_path):
    session = await open_session(tmp_path)

    assert [tool.name for tool in session.tools] == ["read", "bash", "edit", "write"]


async def test_all_seven_tools_can_be_selected(tmp_path):
    session = await open_session(
        tmp_path, tool_names=("read", "bash", "edit", "write", "grep", "find", "ls")
    )

    assert len(session.tools) == 7


async def test_project_resources_are_loaded(tmp_path):
    (tmp_path / "AGENTS.md").write_text("house rules\n")
    skills = tmp_path / ".pi/skills/review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: review\ndescription: Review a diff\n---\nsteps\n")
    prompts = tmp_path / ".pi/prompts"
    prompts.mkdir(parents=True)
    (prompts / "fix.md").write_text("---\ndescription: Fix\n---\nFix $1\n")

    session = await open_session(tmp_path)

    assert [f.content.strip() for f in session.context_files] == ["house rules"]
    assert [s.name for s in session.skills] == ["review"]
    assert [t.name for t in session.prompt_templates] == ["fix"]


async def test_reload_picks_up_a_new_context_file(tmp_path):
    session = await open_session(tmp_path)
    assert session.context_files == []

    (tmp_path / "AGENTS.md").write_text("added later\n")
    session.reload_resources()

    assert [f.content.strip() for f in session.context_files] == ["added later"]


# -- the system prompt is built per turn ------------------------------------- #


async def test_system_prompt_includes_tools_and_project_context(tmp_path):
    (tmp_path / "AGENTS.md").write_text("always run the tests\n")
    stream = FakeStream([text_response("ok")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path, model=MODEL, stream_fn=stream, session_root=tmp_path / ".sessions"
        )
    )

    await session.prompt("hi")

    prompt = stream.calls[0].system_prompt
    assert "- read: Read file contents" in prompt
    assert "always run the tests" in prompt
    assert prompt.endswith(f"Current working directory: {tmp_path.resolve()}")


async def test_system_prompt_tracks_the_active_tool_set(tmp_path):
    stream = FakeStream([text_response("one"), text_response("two")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / ".sessions",
            tool_names=("read", "bash"),
        )
    )

    await session.prompt("first")
    await session.harness.set_active_tools(["read"])
    await session.prompt("second")

    assert "- bash:" in stream.calls[0].system_prompt
    assert "- bash:" not in stream.calls[1].system_prompt


async def test_skills_reach_the_prompt(tmp_path):
    skills = tmp_path / ".pi/skills/review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: review\ndescription: Review a diff\n---\nsteps\n")
    stream = FakeStream([text_response("ok")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path, model=MODEL, stream_fn=stream, session_root=tmp_path / ".sessions"
        )
    )

    await session.prompt("hi")

    assert "<available_skills>" in stream.calls[0].system_prompt
    assert "<name>review</name>" in stream.calls[0].system_prompt


# -- running ----------------------------------------------------------------- #


async def test_a_turn_is_persisted(tmp_path):
    session = await open_session(tmp_path, [text_response("hello")])

    message = await session.prompt("hi")

    assert message.text == "hello"
    reopened = await PiPyCodingSession.resume(options(tmp_path), session_path=session.session_path)
    context = await reopened.session.build_context()
    assert [m.text for m in context.messages] == ["hi", "hello"]


async def test_a_real_tool_runs_against_the_working_directory(tmp_path):
    (tmp_path / "target.txt").write_text("before\n")
    script = [
        tool_response(
            ToolCall(
                id="c1",
                name="write",
                arguments={"path": "target.txt", "content": "after\n"},
            )
        ),
        text_response("done"),
    ]
    session = await open_session(tmp_path, script)

    await session.prompt("overwrite the file")

    assert (tmp_path / "target.txt").read_text() == "after\n"
    context = await session.session.build_context()
    assert any(isinstance(m, ToolResultMessage) for m in context.messages)


# -- resume and new ---------------------------------------------------------- #


async def test_resume_reopens_the_latest_session(tmp_path):
    first = await open_session(tmp_path, [text_response("one")])
    await first.prompt("remember this")

    resumed = await PiPyCodingSession.resume(options(tmp_path, [text_response("two")]))

    assert resumed.session_path == first.session_path
    context = await resumed.session.build_context()
    assert [m.text for m in context.messages] == ["remember this", "one"]


async def test_resume_creates_one_when_there_is_nothing_to_resume(tmp_path):
    resumed = await PiPyCodingSession.resume(options(tmp_path))

    assert resumed.session_path.is_file()
    assert (await resumed.session.build_context()).messages == []


async def test_new_starts_a_separate_session(tmp_path):
    first = await open_session(tmp_path, [text_response("one")])
    await first.prompt("in the first")

    second = await first.new()

    assert second.session_path != first.session_path
    assert (await second.session.build_context()).messages == []
    assert len(second.list_sessions()) == 2


async def test_list_sessions_is_newest_first(tmp_path):
    await open_session(tmp_path)
    latest = await open_session(tmp_path)

    records = latest.list_sessions()

    assert len(records) == 2
    assert records[0].created_at >= records[1].created_at


# -- commands ---------------------------------------------------------------- #


def test_slash_command_surface():
    names = {command.name for command in SLASH_COMMANDS}

    assert {"compact", "tree", "fork", "resume", "new", "name", "model", "session"} <= names
    assert all(command.summary for command in SLASH_COMMANDS)


async def test_name_and_info(tmp_path):
    session = await open_session(tmp_path, [text_response("ok")])
    await session.prompt("hi")
    await session.rename("my  session\n")

    info = await session.info()

    assert info.name == "my session"
    assert info.cwd == str(tmp_path.resolve())
    assert info.model == MODEL.id
    assert info.message_count == 2
    assert info.tools == ["read", "bash", "edit", "write"]


async def test_fork_leaves_the_source_alone(tmp_path):
    session = await open_session(tmp_path, [text_response("shared")])
    await session.prompt("common ground")
    before = session.session_path.read_text()

    forked = await session.fork()
    await forked.harness.append_message(UserMessage(content="only in the fork"))

    assert forked.session_path != session.session_path
    assert session.session_path.read_text() == before
    texts = [m.text for m in (await forked.session.build_context()).messages]
    assert texts == ["common ground", "shared", "only in the fork"]


async def test_compact_shortens_the_context(tmp_path):
    from superqode.pipy.compaction import CompactionSettings

    script = [text_response("a"), text_response("b"), text_response("## Goal\nsummarised")]
    session = await open_session(
        tmp_path, script, compaction_settings=CompactionSettings(keep_recent_tokens=2)
    )
    await session.prompt("first")
    await session.prompt("second")

    result = await session.compact()

    assert result is not None
    texts = [
        getattr(m, "summary", getattr(m, "text", ""))
        for m in (await session.session.build_context()).messages
    ]
    assert texts[0] == "## Goal\nsummarised"
    assert "first" not in texts


async def test_tree_navigation_writes_a_branch_summary(tmp_path):
    session = await open_session(
        tmp_path, [text_response("first"), text_response("explored"), text_response("a dead end")]
    )
    await session.prompt("start here")
    entries = await session.session.get_entries()
    root = entries[0].id
    await session.prompt("try something")

    summary = await session.navigate_tree(root)

    assert summary == "a dead end"
    texts = [
        getattr(m, "summary", getattr(m, "text", ""))
        for m in (await session.session.build_context()).messages
    ]
    assert texts == ["start here", "a dead end"]


async def test_set_model_is_recorded(tmp_path):
    from superqode.pipy.stream import Model

    session = await open_session(tmp_path)

    await session.set_model(Model(id="other-1", provider="openai", api="openai-completions"))

    context = await session.session.build_context()
    assert context.model is not None and context.model.model_id == "other-1"


# -- skills and templates ---------------------------------------------------- #


async def test_invoke_skill_expands_it_into_the_prompt(tmp_path):
    skills = tmp_path / ".pi/skills/review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review a diff\n---\nCheck the tests first.\n"
    )
    stream = FakeStream([text_response("reviewing")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path, model=MODEL, stream_fn=stream, session_root=tmp_path / ".sessions"
        )
    )

    await session.invoke_skill("review", "focus on the parser")

    sent = stream.calls[0].messages[-1].text
    assert sent.startswith('<skill name="review"')
    assert "Check the tests first." in sent
    assert sent.endswith("focus on the parser")


async def test_unknown_skill_lists_what_is_available(tmp_path):
    session = await open_session(tmp_path)

    with pytest.raises(AgentHarnessError) as error:
        await session.invoke_skill("nope")
    assert "Unknown skill 'nope'" in str(error.value)


async def test_invoke_prompt_template_substitutes_arguments(tmp_path):
    prompts = tmp_path / ".pi/prompts"
    prompts.mkdir(parents=True)
    (prompts / "fix.md").write_text("---\ndescription: Fix\n---\nFix $1 in $2\n")
    stream = FakeStream([text_response("fixing")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path, model=MODEL, stream_fn=stream, session_root=tmp_path / ".sessions"
        )
    )

    await session.invoke_prompt_template("fix", ["the crash", "main.py"])

    assert stream.calls[0].messages[-1].text.strip() == "Fix the crash in main.py"


async def test_unknown_template_lists_what_is_available(tmp_path):
    session = await open_session(tmp_path)

    with pytest.raises(AgentHarnessError, match="Unknown prompt template"):
        await session.invoke_prompt_template("nope")


# -- export ------------------------------------------------------------------ #


async def test_export_renders_the_branch_as_markdown(tmp_path):
    script = [
        tool_response(ToolCall(id="c1", name="read", arguments={"path": "a.txt"})),
        text_response("here is what I found"),
    ]
    (tmp_path / "a.txt").write_text("file body\n")
    session = await open_session(tmp_path, script)
    await session.rename("investigation")
    await session.prompt("what is in a.txt?")

    markdown = await session.export_markdown()

    assert markdown.startswith("# investigation")
    assert "## User\n\nwhat is in a.txt?" in markdown
    assert "### Tool call: `read`" in markdown
    assert "### Tool result: `read`" in markdown
    assert "here is what I found" in markdown


async def test_export_of_an_empty_session(tmp_path):
    session = await open_session(tmp_path)

    markdown = await session.export_markdown()

    assert markdown.startswith("# PiPy session")


# -- steering ---------------------------------------------------------------- #


async def test_steering_reaches_the_next_turn(tmp_path):
    stream = FakeStream([text_response("one"), text_response("two")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path, model=MODEL, stream_fn=stream, session_root=tmp_path / ".sessions"
        )
    )
    await session.steer("actually, do it this way")

    await session.prompt("go")

    assert "actually, do it this way" in [m.text for m in stream.calls[0].messages]


async def test_sessions_for_different_directories_stay_separate(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    first = await open_session(tmp_path, [text_response("in first")])
    await first.prompt("first repo")

    second = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=other,
            model=MODEL,
            stream_fn=FakeStream([text_response("in second")]),
            session_root=tmp_path / ".sessions",
        )
    )

    assert second.session_path.parent != first.session_path.parent
    assert len(second.list_sessions()) == 1
