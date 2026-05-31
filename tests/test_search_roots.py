"""Tests for read-only search roots (SUPERQODE_SEARCH_ROOTS).

Lets DS4/local models search and read a repo downloaded outside the project
while keeping writes confined to the working directory.
"""

import tempfile
from pathlib import Path

import pytest

from superqode.tools.base import ToolContext
from superqode.tools.file_tools import ReadFileTool, WriteFileTool
from superqode.tools.search_tools import GrepTool, RepoSearchTool
from superqode.tools.validation import (
    get_configured_search_roots,
    validate_path_in_search_scope,
    validate_path_in_working_directory,
)


@pytest.fixture
def project_and_ref():
    """A working dir (project) and a separate ref repo outside it."""
    with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as ref:
        proj_p, ref_p = Path(proj), Path(ref)
        (proj_p / "a.py").write_text("def in_project():\n    return 1\n")
        (ref_p / "lib.py").write_text("def magic_helper():\n    return 42\n")
        yield proj_p, ref_p


def test_get_configured_search_roots_parses_env(monkeypatch, project_and_ref):
    _, ref = project_and_ref
    import os

    monkeypatch.setenv("SUPERQODE_SEARCH_ROOTS", f"{ref}{os.pathsep}/does/not/exist")
    roots = get_configured_search_roots()
    # Only existing directories survive; the bogus one is dropped. Paths are
    # abspath-normalized (symlinks not resolved), matching the validator.
    assert roots == [Path(os.path.abspath(ref))]


def test_get_configured_search_roots_empty(monkeypatch):
    monkeypatch.delenv("SUPERQODE_SEARCH_ROOTS", raising=False)
    assert get_configured_search_roots() == []


def test_scope_allows_cwd_and_roots_denies_outside(project_and_ref):
    proj, ref = project_and_ref
    # cwd file is allowed.
    assert validate_path_in_search_scope(str(proj / "a.py"), proj, [ref]) == proj / "a.py"
    # ref file is allowed when ref is a configured root.
    assert validate_path_in_search_scope(str(ref / "lib.py"), proj, [ref]) == ref / "lib.py"
    # Something outside both is denied.
    with pytest.raises(ValueError):
        validate_path_in_search_scope("/etc/hosts", proj, [ref])


def test_scope_with_no_roots_matches_strict_validator(project_and_ref):
    proj, ref = project_and_ref
    with pytest.raises(ValueError):
        validate_path_in_search_scope(str(ref / "lib.py"), proj, [])
    # And the strict validator agrees.
    with pytest.raises(ValueError):
        validate_path_in_working_directory(str(ref / "lib.py"), proj)


@pytest.mark.asyncio
async def test_read_allowed_in_root_write_denied(project_and_ref):
    proj, ref = project_and_ref
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])

    read = await ReadFileTool().execute({"path": str(ref / "lib.py")}, ctx)
    assert read.success and "magic_helper" in read.output

    # Writers ignore search_roots — must stay in the working directory.
    write = await WriteFileTool().execute(
        {"path": str(ref / "evil.py"), "content": "x"}, ctx
    )
    assert not write.success


@pytest.mark.asyncio
async def test_grep_finds_matches_in_root(project_and_ref):
    proj, ref = project_and_ref
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
    res = await GrepTool().execute({"pattern": "magic_helper", "path": str(ref)}, ctx)
    assert res.success
    assert "magic_helper" in res.output  # regression guard for the --git-ignore bug


@pytest.mark.asyncio
async def test_repo_search_spans_root(project_and_ref):
    proj, ref = project_and_ref
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
    res = await RepoSearchTool().execute({"query": "magic_helper", "path": str(ref)}, ctx)
    assert res.success and "magic_helper" in res.output


def test_grep_rg_command_has_no_bad_flag():
    # ripgrep has no --git-ignore flag; passing it made rg exit 2 / return nothing.
    cmd = GrepTool()._build_rg_command("foo", Path("/tmp"), None, False)
    assert "--git-ignore" not in cmd
    assert cmd.startswith("rg ")
