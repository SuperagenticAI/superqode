"""Tests for the post-edit verification loop (format + diagnostics feedback)."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.tools.file_tools import WriteFileTool

ruff_missing = shutil.which("ruff") is None


def _ctx(d: Path):
    return SimpleNamespace(working_directory=d, search_roots=None)


@pytest.mark.asyncio
async def test_clean_python_edit_is_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VERIFY_EDITS", raising=False)
    res = await WriteFileTool().execute(
        {"path": "ok.py", "content": "x = 1\nprint(x)\n"}, _ctx(tmp_path)
    )
    assert res.success
    assert "issue(s) detected" not in res.output
    assert res.metadata.get("post_edit_findings") in (None, 0)


@pytest.mark.asyncio
async def test_syntax_error_surfaced(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VERIFY_EDITS", raising=False)
    res = await WriteFileTool().execute(
        {"path": "bad.py", "content": "def f(:\n    pass\n"}, _ctx(tmp_path)
    )
    assert res.success  # the write itself succeeds
    assert "issue(s) detected" in res.output
    assert res.metadata.get("post_edit_findings", 0) >= 1
    # Path is shown relative to cwd, not absolute.
    assert "bad.py" in res.output
    assert str(tmp_path) not in res.output


@pytest.mark.asyncio
@pytest.mark.skipif(ruff_missing, reason="ruff not installed")
async def test_lint_unused_import_surfaced(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VERIFY_EDITS", raising=False)
    res = await WriteFileTool().execute(
        {"path": "lint.py", "content": "import os\nx = 1\n"}, _ctx(tmp_path)
    )
    assert "F401" in res.output  # unused import


@pytest.mark.asyncio
async def test_invalid_json_surfaced(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VERIFY_EDITS", raising=False)
    res = await WriteFileTool().execute(
        {"path": "bad.json", "content": '{"a": 1,}'}, _ctx(tmp_path)
    )
    assert "invalid JSON" in res.output


@pytest.mark.asyncio
async def test_verification_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VERIFY_EDITS", "0")
    res = await WriteFileTool().execute(
        {"path": "bad.py", "content": "def f(:\n    pass\n"}, _ctx(tmp_path)
    )
    assert res.success
    assert "issue(s) detected" not in res.output


@pytest.mark.asyncio
async def test_unsupported_extension_passes_through(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_VERIFY_EDITS", raising=False)
    res = await WriteFileTool().execute(
        {"path": "notes.txt", "content": "anything goes here"}, _ctx(tmp_path)
    )
    assert res.success
    assert "issue(s) detected" not in res.output
