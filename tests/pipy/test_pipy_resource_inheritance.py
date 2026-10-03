"""Nested project instructions, prompt precedence and reload at model dispatch."""

import pytest

from superqode.pipy import CodingSessionOptions, Model, PiPyCodingSession
from superqode.pipy.ai import FakeStream, text_response
from superqode.pipy.resources import load_context_files


def test_global_ancestors_local_override_and_symlink_deduplication(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("SUPERQODE_PIPY_DIR", str(global_dir))
    (global_dir / "AGENTS.md").write_text("global")
    (tmp_path / "AGENTS.md").write_text("parent")
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("shadowed")
    (project / "AGENTS.override.md").write_text("\ufeffoverride", encoding="utf-8")
    child = project / "child"
    child.mkdir()
    (child / "CLAUDE.md").write_text("child")
    assert [f.content for f in load_context_files(child)] == [
        "global",
        "parent",
        "override",
        "child",
    ]
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    monkeypatch.setenv("SUPERQODE_PIPY_DIR", str(alias))
    files = load_context_files(child)
    assert sum(f.content == "override" for f in files) == 1
    (global_dir / "AGENTS.md").unlink()
    (global_dir / "AGENTS.md").symlink_to(project / "AGENTS.override.md")
    monkeypatch.setenv("SUPERQODE_PIPY_DIR", str(global_dir))
    assert sum(f.content == "override" for f in load_context_files(child)) == 1


def test_invalid_utf8_context_does_not_break_discovery(tmp_path):
    (tmp_path / "AGENTS.md").write_bytes(b"\xff")
    (tmp_path / "CLAUDE.md").write_text("fallback")
    assert load_context_files(tmp_path)[-1].content == "fallback"


@pytest.mark.asyncio
async def test_prompt_files_precedence_reload_and_explicit_sdk_options(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    monkeypatch.setenv("SUPERQODE_PIPY_DIR", str(global_dir))
    (global_dir / "SYSTEM.md").write_text("global system")
    (global_dir / "APPEND_SYSTEM.md").write_text("global append")
    project = tmp_path / "repo"
    (project / ".pi").mkdir(parents=True)
    (project / ".pi" / "SYSTEM.md").write_text("project system")
    stream = FakeStream([text_response("one"), text_response("two"), text_response("three")])
    options = CodingSessionOptions(
        cwd=project,
        model=Model(id="fixture", provider="fixture"),
        stream_fn=stream,
        session_root=tmp_path / "sessions",
    )
    session = await PiPyCodingSession.create(options)
    await session.prompt("first")
    assert stream.calls[0].system_prompt.startswith("project system")
    assert "global append" in stream.calls[0].system_prompt
    (project / ".pi" / "APPEND_SYSTEM.md").write_text("project append")
    (project / ".pi" / "SYSTEM.md").write_text("reloaded system")
    session.reload_resources()
    await session.prompt("second")
    assert stream.calls[1].system_prompt.startswith("reloaded system")
    assert "project append" in stream.calls[1].system_prompt
    assert "global append" not in stream.calls[1].system_prompt
    options.custom_prompt = "explicit system"
    options.append_system_prompt = ""
    await session.prompt("third")
    assert stream.calls[2].system_prompt.startswith("explicit system")
    assert "project append" not in stream.calls[2].system_prompt


@pytest.mark.asyncio
async def test_sdk_can_disable_all_instruction_file_loading(tmp_path):
    (tmp_path / "AGENTS.md").write_text("excluded context")
    (tmp_path / ".pi").mkdir()
    (tmp_path / ".pi" / "SYSTEM.md").write_text("excluded system")
    stream = FakeStream([text_response("one")])
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=Model(id="fixture", provider="fixture"),
            stream_fn=stream,
            session_root=tmp_path / "sessions",
            include_context_files=False,
            include_system_prompt_files=False,
        )
    )
    session.reload_resources()
    await session.prompt("first")
    assert not session.context_files
    assert "excluded" not in stream.calls[0].system_prompt
