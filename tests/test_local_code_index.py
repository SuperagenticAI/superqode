from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local.code_index import build_code_index, search_code_index
from superqode.tools.base import ToolContext
from superqode.tools.search_tools import LocalCodeSearchTool


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    (repo / "service.py").write_text(
        "class MagicService:\n"
        "    def shared_token_lookup(self):\n"
        "        return 'shared-token'\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("shared-token documentation\n", encoding="utf-8")
    return repo


def _build_or_skip(repo: Path, roots: list[Path]):
    report = build_code_index(workspace_root=repo, roots=roots)
    if not report.ok and "fts5" in report.error.lower():
        pytest.skip("SQLite FTS5 is unavailable in this Python build")
    assert report.ok, report.error
    return report


def test_build_and_search_sqlite_code_index(tmp_path):
    repo = _make_repo(tmp_path, "work")
    ref = _make_repo(tmp_path, "ref")
    report = _build_or_skip(repo, [repo, ref])

    assert Path(report.index_path).exists()
    assert report.files_indexed >= 4
    assert report.symbols_indexed >= 2

    search = search_code_index(
        workspace_root=repo,
        roots=[repo, ref],
        query="MagicService",
    )

    assert search.covered, search.error
    assert search.content
    assert search.symbols

    path_search = search_code_index(
        workspace_root=repo,
        roots=[repo, ref],
        query="service",
        mode="path",
    )
    assert any(item.rel_path == "service.py" for item in path_search.files)


@pytest.mark.asyncio
async def test_local_code_search_uses_forced_index_backend(tmp_path):
    repo = _make_repo(tmp_path, "work")
    ref = _make_repo(tmp_path, "ref")
    _build_or_skip(repo, [repo, ref])
    ctx = ToolContext(session_id="t", working_directory=repo, search_roots=[ref])

    result = await LocalCodeSearchTool().execute(
        {"query": "MagicService", "all_repos": True, "backend": "index"},
        ctx,
    )

    assert result.success
    assert result.metadata["backend"] == "sqlite-fts5"
    assert "Indexed local code search results" in result.output
    assert f"{repo.name}/service.py" in result.output
    assert f"{ref.name}/service.py" in result.output


@pytest.mark.asyncio
async def test_local_code_search_forced_index_reports_missing_index(tmp_path):
    repo = _make_repo(tmp_path, "work")
    ctx = ToolContext(session_id="t", working_directory=repo)

    result = await LocalCodeSearchTool().execute(
        {"query": "MagicService", "backend": "index"},
        ctx,
    )

    assert result.success is False
    assert "Local code index is unavailable" in (result.error or "")


def test_airplane_index_cli_builds_index(tmp_path):
    repo = _make_repo(tmp_path, "work")
    ref = _make_repo(tmp_path, "ref")

    result = CliRunner().invoke(
        local,
        ["airplane", "index", "--repo", str(repo), "--ref", str(ref), "--json"],
    )

    assert result.exit_code == 0, result.output
    assert '"files_indexed"' in result.output
    assert (repo / ".superqode" / "code-search.sqlite3").exists()
