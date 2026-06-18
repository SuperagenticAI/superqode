"""`semantic_search` tool: gating, formatting, and the daemon client contract.

The cocoindex-code daemon and index are not exercised here; we inject a fake
``cocoindex_code.client`` module so the tests stay fast and deterministic.
Live result quality is validated separately via `ccc search`.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from superqode.tools.base import ToolContext
from superqode.tools.semantic_search import SemanticSearchTool, is_semantic_search_available


@dataclass
class _FakeResult:
    file_path: str
    language: str
    content: str
    start_line: int
    end_line: int
    score: float


@dataclass
class _FakeResponse:
    success: bool
    results: list
    total_returned: int = 0
    offset: int = 0
    message: str | None = None


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path)


@pytest.fixture
def fake_client(monkeypatch):
    """Install a fake cocoindex_code.client and report it as available."""
    calls = {}

    mod = types.ModuleType("cocoindex_code.client")
    mod.__spec__ = ModuleSpec("cocoindex_code.client", loader=None)

    def search(project_root, query, languages=None, paths=None, limit=5, offset=0, **kw):
        calls["search"] = dict(
            project_root=project_root,
            query=query,
            languages=languages,
            paths=paths,
            limit=limit,
            offset=offset,
        )
        return _FakeResponse(
            success=True,
            results=[
                _FakeResult(
                    file_path="src/superqode/agent/compaction.py",
                    language="python",
                    content="def compact(history):\n    return history[-10:]",
                    start_line=1,
                    end_line=2,
                    score=0.712,
                )
            ],
            total_returned=1,
        )

    def index(project_root, **kw):
        calls["index"] = project_root
        return None

    mod.search = search
    mod.index = index

    pkg = sys.modules.get("cocoindex_code") or types.ModuleType("cocoindex_code")
    pkg.__path__ = []  # mark as a package for importlib.util.find_spec
    pkg.__spec__ = ModuleSpec("cocoindex_code", loader=None, is_package=True)
    monkeypatch.setitem(sys.modules, "cocoindex_code", pkg)
    monkeypatch.setitem(sys.modules, "cocoindex_code.client", mod)

    # availability is lru_cached — clear around the test.
    is_semantic_search_available.cache_clear()
    yield calls
    is_semantic_search_available.cache_clear()


def test_unavailable_returns_install_hint(monkeypatch, tmp_path):
    # Force the import to fail regardless of environment.
    monkeypatch.setitem(sys.modules, "cocoindex_code.client", None)
    is_semantic_search_available.cache_clear()
    try:
        import asyncio

        res = asyncio.run(SemanticSearchTool().execute({"query": "x"}, _ctx(tmp_path)))
    finally:
        is_semantic_search_available.cache_clear()
    assert res.success is False
    assert "cocoindex-code" in res.error
    assert "superqode[semantic]" in res.error


def test_empty_query_rejected(tmp_path):
    import asyncio

    res = asyncio.run(SemanticSearchTool().execute({"query": "   "}, _ctx(tmp_path)))
    assert res.success is False
    assert "query is required" in res.error


def test_success_formats_results(fake_client, tmp_path):
    import asyncio

    res = asyncio.run(
        SemanticSearchTool().execute(
            {"query": "how is history compacted", "limit": 3}, _ctx(tmp_path)
        )
    )
    assert res.success is True
    assert res.metadata["matches"] == 1
    assert "compaction.py:1-2" in res.output
    assert "score 0.712" in res.output
    assert "[python]" in res.output
    assert "def compact(history)" in res.output
    # Query plumbed through to the daemon client verbatim.
    assert fake_client["search"]["query"] == "how is history compacted"
    assert fake_client["search"]["project_root"] == str(tmp_path)


def test_limit_is_clamped(fake_client, tmp_path):
    import asyncio

    asyncio.run(
        SemanticSearchTool().execute({"query": "q", "limit": 999}, _ctx(tmp_path))
    )
    assert fake_client["search"]["limit"] == SemanticSearchTool.MAX_LIMIT


def test_offset_is_forwarded(fake_client, tmp_path):
    import asyncio

    asyncio.run(
        SemanticSearchTool().execute({"query": "q", "offset": 7}, _ctx(tmp_path))
    )
    assert fake_client["search"]["offset"] == 7


def test_refresh_triggers_index(fake_client, tmp_path):
    import asyncio

    asyncio.run(
        SemanticSearchTool().execute({"query": "q", "refresh": True}, _ctx(tmp_path))
    )
    assert fake_client["index"] == str(tmp_path)


def test_refresh_index_error_fails(monkeypatch, fake_client, tmp_path):
    import asyncio
    import cocoindex_code.client as mod

    def fail_index(project_root):
        raise RuntimeError("bad index")

    monkeypatch.setattr(mod, "index", fail_index)
    res = asyncio.run(
        SemanticSearchTool().execute({"query": "q", "refresh": True}, _ctx(tmp_path))
    )
    assert res.success is False
    assert "bad index" in res.error
    assert "search" not in fake_client


def test_string_filters_are_coerced(fake_client, tmp_path):
    import asyncio

    asyncio.run(
        SemanticSearchTool().execute(
            {"query": "q", "languages": "python", "paths": "src/*"}, _ctx(tmp_path)
        )
    )
    assert fake_client["search"]["languages"] == ["python"]
    assert fake_client["search"]["paths"] == ["src/*"]


def test_invalid_filters_are_rejected(fake_client, tmp_path):
    import asyncio

    res = asyncio.run(
        SemanticSearchTool().execute({"query": "q", "languages": [1]}, _ctx(tmp_path))
    )
    assert res.success is False
    assert "languages must be a string or list of strings" in res.error


def test_failure_response_surfaces_message(monkeypatch, fake_client, tmp_path):
    import asyncio
    import cocoindex_code.client as mod

    monkeypatch.setattr(
        mod, "search", lambda **kw: _FakeResponse(success=False, results=[], message="no index")
    )
    res = asyncio.run(SemanticSearchTool().execute({"query": "q"}, _ctx(tmp_path)))
    assert res.success is False
    assert "no index" in res.error
