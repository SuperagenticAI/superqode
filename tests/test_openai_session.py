"""Tests for SuperQodeSession (the openai-agents SessionABC adapter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.runtime.errors import RuntimeNotInstalledError

pytest.importorskip("agents", reason="openai-agents not installed")

from superqode.runtime.openai_session import make_session_class  # noqa: E402


@pytest.fixture
def session_cls():
    return make_session_class()


@pytest.fixture
def tmp_session(tmp_path: Path, session_cls):
    return session_cls(session_id="t1", storage_dir=tmp_path)


@pytest.mark.asyncio
async def test_empty_session_returns_empty_list(tmp_session):
    items = await tmp_session.get_items()
    assert items == []


@pytest.mark.asyncio
async def test_add_then_get_roundtrips(tmp_session):
    items_in = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    await tmp_session.add_items(items_in)
    items_out = await tmp_session.get_items()
    assert items_out == items_in


@pytest.mark.asyncio
async def test_get_items_respects_limit(tmp_session):
    await tmp_session.add_items([{"role": "user", "content": f"msg{i}"} for i in range(5)])
    last_two = await tmp_session.get_items(limit=2)
    assert [m["content"] for m in last_two] == ["msg3", "msg4"]


@pytest.mark.asyncio
async def test_pop_item_returns_most_recent(tmp_session):
    await tmp_session.add_items(
        [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    )
    popped = await tmp_session.pop_item()
    assert popped == {"role": "user", "content": "b"}
    remaining = await tmp_session.get_items()
    assert remaining == [{"role": "user", "content": "a"}]


@pytest.mark.asyncio
async def test_pop_on_empty_returns_none(tmp_session):
    assert await tmp_session.pop_item() is None


@pytest.mark.asyncio
async def test_clear_session_removes_all(tmp_session):
    await tmp_session.add_items([{"role": "user", "content": "hi"}])
    await tmp_session.clear_session()
    assert await tmp_session.get_items() == []


@pytest.mark.asyncio
async def test_two_sessions_in_same_dir_are_isolated(tmp_path, session_cls):
    a = session_cls(session_id="a", storage_dir=tmp_path)
    b = session_cls(session_id="b", storage_dir=tmp_path)
    await a.add_items([{"role": "user", "content": "for-a"}])
    await b.add_items([{"role": "user", "content": "for-b"}])
    assert await a.get_items() == [{"role": "user", "content": "for-a"}]
    assert await b.get_items() == [{"role": "user", "content": "for-b"}]


def test_make_session_class_without_sdk(monkeypatch):
    """If agents.memory.session is not importable, we surface a clean install hint."""
    import sys

    saved = sys.modules.pop("agents.memory.session", None)
    sys.modules["agents.memory.session"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeNotInstalledError):
            make_session_class()
    finally:
        sys.modules.pop("agents.memory.session", None)
        if saved is not None:
            sys.modules["agents.memory.session"] = saved
