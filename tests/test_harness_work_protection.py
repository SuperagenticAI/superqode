"""Developer saves must survive agent writes, across the built-in tool routes."""

import os
from pathlib import Path

import pytest

from superqode.file_observations import FileConflictError, FileObservations
from superqode.pipy.tools import create_all_tools
from superqode.tools.base import ToolContext
from superqode.tools.file_tools import ReadFileTool, WriteFileTool
from superqode.tools.edit_tools import EditFileTool


@pytest.mark.parametrize("route", ["pipy", "codegem", "core"])
async def test_developer_save_conflicts_then_reread_recovers(tmp_path, monkeypatch, route):
    monkeypatch.setenv("SUPERQODE_VERIFY_EDITS", "0")
    path = tmp_path / "note.txt"
    path.write_text("agent's original view\n")
    if route == "core":
        ctx = ToolContext(working_directory=tmp_path, session_id=str(tmp_path))

        async def read():
            assert (await ReadFileTool().execute({"path": "note.txt"}, ctx)).success

        async def write(content):
            return await WriteFileTool().execute({"path": "note.txt", "content": content}, ctx)
    else:
        if route == "codegem":
            from superqode.codegem.tools import create_tools

            tools = create_tools(tmp_path)
        else:
            tools = create_all_tools(tmp_path)
        by_name = {tool.name: tool for tool in tools}

        async def read():
            await by_name["read"].execute("read", {"path": "note.txt"})

        async def write(content):
            return await by_name["write"].execute("write", {"path": "note.txt", "content": content})

    await read()
    before = path.stat()
    path.write_text("developer's saved work\n")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    if route == "core":
        result = await write("stale rewrite")
        assert not result.success and "Re-read" in result.error
    else:
        with pytest.raises(FileConflictError, match="Re-read"):
            await write("stale rewrite")
    assert path.read_text() == "developer's saved work\n"
    await read()
    await write("developer's saved work\nagent addition\n")
    await write("developer's saved work\nagent addition\nsecond addition\n")
    assert path.read_text().endswith("second addition\n")


def test_unread_rewrite_requires_read(tmp_path):
    path = tmp_path / "file"
    path.write_text("valuable")
    with pytest.raises(FileConflictError, match="Read"):
        FileObservations().write(path, b"replacement", require_read=True)
    assert path.read_text() == "valuable"


def test_atomic_write_preserves_mode_and_symlink(tmp_path):
    path = tmp_path / "script"
    path.write_bytes(b"old\r\n")
    path.chmod(0o751)
    link = tmp_path / "link"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("Symlinks unavailable")
    seen = FileObservations()
    seen.record(link, path.read_bytes())
    seen.write(link, b"new\r\n", require_read=True)
    assert link.is_symlink()
    assert path.read_bytes() == b"new\r\n"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o751


def test_failed_replace_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "file"
    path.write_bytes(b"old")
    seen = FileObservations()
    seen.record(path, b"old")

    def fail(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        seen.write(path, b"new")
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


def test_create_race_does_not_overwrite(tmp_path, monkeypatch):
    path = tmp_path / "file"
    original_open = Path.open

    def racing_open(self, mode="r", *args, **kwargs):
        if self == path and mode == "xb":
            with original_open(self, "wb") as stream:
                stream.write(b"concurrent save")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(FileExistsError):
        FileObservations().write(path, b"new")
    assert path.read_bytes() == b"concurrent save"


async def test_targeted_edit_preserves_crlf_and_refreshes_observation(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"one\r\ntwo\r\n")
    tools = {tool.name: tool for tool in create_all_tools(tmp_path)}
    await tools["read"].execute("r", {"path": "file"})
    for old, new in [("one", "ONE"), ("two", "TWO")]:
        await tools["edit"].execute(
            "e", {"path": "file", "edits": [{"oldText": old, "newText": new}]}
        )
    assert path.read_bytes() == b"ONE\r\nTWO\r\n"


async def test_core_own_edit_does_not_cause_false_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VERIFY_EDITS", "0")
    path = tmp_path / "file"
    path.write_text("one two")
    ctx = ToolContext(working_directory=tmp_path, session_id=str(tmp_path))
    await ReadFileTool().execute({"path": "file"}, ctx)
    for old, new in [("one", "ONE"), ("two", "TWO")]:
        result = await EditFileTool().execute(
            {"path": "file", "old_text": old, "new_text": new}, ctx
        )
        assert result.success, result.error
    assert path.read_text() == "ONE TWO"
