from pathlib import Path

import pytest

from superqode.harness.context_handles import (
    chunk_context_handle,
    grep_context_handle,
    peek_context_handle,
    resolve_context_handle,
)
from superqode.tools import ContextHandleTool, ToolContext


def test_context_handle_file_peek_grep_and_chunk(tmp_path: Path):
    path = tmp_path / "ci.log"
    path.write_text("start\nERROR first\nmiddle\nERROR second\nend\n", encoding="utf-8")

    assert "ERROR first" in resolve_context_handle("file:ci.log", tmp_path)
    assert peek_context_handle("file:ci.log", tmp_path, offset=6, limit=5) == "ERROR"

    matches = grep_context_handle("file:ci.log", "error", tmp_path)
    assert [item["line"] for item in matches] == [2, 4]

    chunks = chunk_context_handle("file:ci.log", tmp_path, chunk_chars=1000)
    assert chunks[0].chunk_id.startswith("file-ci.log")
    assert "ERROR second" in chunks[0].text


def test_context_handle_repo_glob_stays_inside_workspace(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def alpha(): pass\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("ignore\n", encoding="utf-8")

    text = resolve_context_handle("repo:src/*.py", tmp_path)

    assert "--- src/a.py ---" in text
    assert "alpha" in text
    assert "b.txt" not in text


def test_context_handle_rejects_outside_file(tmp_path: Path):
    with pytest.raises(ValueError, match="outside the workspace"):
        resolve_context_handle("file:../secret.txt", tmp_path)


@pytest.mark.asyncio
async def test_context_handle_tool_grep(tmp_path: Path):
    (tmp_path / "ci.log").write_text("ok\nboom\n", encoding="utf-8")
    tool = ContextHandleTool()
    ctx = ToolContext(session_id="s", working_directory=tmp_path)

    result = await tool.execute(
        {"action": "grep", "handle": "file:ci.log", "pattern": "boom"},
        ctx,
    )

    assert result.success is True
    assert "2:boom" in result.output
    assert result.metadata["matches"] == 1
