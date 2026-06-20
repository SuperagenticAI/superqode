"""Tests for read-only search roots (SUPERQODE_SEARCH_ROOTS).

Lets DS4/local models search and read a repo downloaded outside the project
while keeping writes confined to the working directory.
"""

import tempfile
from pathlib import Path

import pytest

from superqode.tools.base import ToolContext
from superqode.tools.file_tools import ReadFileTool, WriteFileTool
from superqode.tools.search_tools import GrepTool, LocalCodeSearchTool, RepoSearchTool
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
    write = await WriteFileTool().execute({"path": str(ref / "evil.py"), "content": "x"}, ctx)
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
    # Args are now an argv list (no shell) with structured --json output.
    args = GrepTool._build_rg_args("rg", "foo", [Path("/tmp")], None, False)
    assert "--git-ignore" not in args
    assert args[0] == "rg"
    assert "--json" in args
    assert "--no-config" in args
    # Pattern is passed after `--` so regex metacharacters are never shell-parsed.
    assert args[-2:] == ["foo", "/tmp"]
    assert "--" in args


def test_grep_rg_args_fan_out_multiple_roots():
    # Multiple roots are passed in one invocation (ripgrep is multi-threaded).
    args = GrepTool._build_rg_args("rg", "foo", [Path("/a"), Path("/b")], None, False)
    assert args[-3:] == ["foo", "/a", "/b"]


@pytest.mark.asyncio
async def test_grep_all_repos_fans_out_and_labels(project_and_ref):
    proj, ref = project_and_ref
    (proj / "a.py").write_text("shared_token = 1\n")
    (ref / "lib.py").write_text("use(shared_token)\n")
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
    res = await GrepTool().execute({"pattern": "shared_token", "all_repos": True}, ctx)
    assert res.success
    assert res.metadata.get("repos") == 2
    # Matches from both repos are labeled by repo name.
    assert f"{proj.name}/a.py" in res.output
    assert f"{ref.name}/lib.py" in res.output


@pytest.mark.asyncio
async def test_local_code_search_all_repos_fans_out_and_labels(project_and_ref):
    proj, ref = project_and_ref
    (proj / "a.py").write_text("def shared_token_project():\n    return 1\n")
    (ref / "lib.py").write_text("def shared_token_reference():\n    return 2\n")
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])

    res = await LocalCodeSearchTool().execute(
        {"query": "shared_token", "all_repos": True},
        ctx,
    )

    assert res.success
    assert res.metadata["repos"] == 2
    assert f"{proj.name}/a.py" in res.output
    assert f"{ref.name}/lib.py" in res.output
    assert "Symbols:" in res.output


@pytest.mark.asyncio
async def test_grep_absolute_path_in_scope_allowed(project_and_ref):
    proj, ref = project_and_ref
    ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
    # Absolute path to a registered root is honored silently.
    res = await GrepTool().execute({"pattern": "magic_helper", "path": str(ref)}, ctx)
    assert res.success and "magic_helper" in res.output


@pytest.mark.asyncio
async def test_grep_absolute_path_out_of_scope_blocked(project_and_ref, monkeypatch):
    proj, ref = project_and_ref
    monkeypatch.delenv("SUPERQODE_ALLOW_EXTERNAL_SEARCH", raising=False)
    with tempfile.TemporaryDirectory() as outside:
        outside_p = Path(outside)
        (outside_p / "secret.py").write_text("magic_helper\n")
        ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
        res = await GrepTool().execute({"pattern": "magic_helper", "path": str(outside_p)}, ctx)
        assert res.success is False
        assert ":workspace add" in (res.error or "")


@pytest.mark.asyncio
async def test_local_code_search_absolute_path_out_of_scope_blocked(project_and_ref, monkeypatch):
    proj, ref = project_and_ref
    monkeypatch.delenv("SUPERQODE_ALLOW_EXTERNAL_SEARCH", raising=False)
    with tempfile.TemporaryDirectory() as outside:
        outside_p = Path(outside)
        (outside_p / "secret.py").write_text("def shared_token_secret():\n    return 0\n")
        ctx = ToolContext(session_id="t", working_directory=proj, search_roots=[ref])
        res = await LocalCodeSearchTool().execute(
            {"query": "shared_token", "path": str(outside_p)},
            ctx,
        )
        assert res.success is False
        assert ":workspace add" in (res.error or "")


def test_workspace_registry_roundtrip(tmp_path, monkeypatch):
    import superqode.search_registry as reg

    monkeypatch.setattr(reg, "WORKSPACE_FILE", tmp_path / "workspace.json")
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()

    reg.add_workspace_root(str(r1))
    reg.add_workspace_root(str(r2))
    reg.add_workspace_root(str(r1))  # duplicate ignored
    assert len(reg.list_workspace_roots()) == 2
    assert reg.remove_workspace_root(str(r1)) is True
    assert len(reg.list_workspace_roots()) == 1
    with pytest.raises(ValueError):
        reg.add_workspace_root(str(tmp_path / "does_not_exist"))
