"""Tests for ACP session persistence (A3 from the fast-agent gap audit).

Three layers:

1. The SQLite-backed ``ACPSessionStore`` — round-trips, upsert semantics,
   listing scoped to agent + cwd, deletion, corruption tolerance.
2. ``ACPClient._persist_current_session`` — wiring from session lifecycle
   into the store.
3. ``ACPClient.start()`` resume flow — capability gating, fallback to
   ``session/new`` when resume fails.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from superqode.acp.client import ACPClient
from superqode.acp.session_store import (
    ACPSessionStore,
    StoredSession,
    default_sessions_db_path,
)


# ---------------------------------------------------------------------------
# Store unit tests
# ---------------------------------------------------------------------------


def test_default_path_honors_superqode_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    assert default_sessions_db_path() == tmp_path / "sessions.db"


def test_default_path_falls_back_to_dot_superqode(monkeypatch):
    monkeypatch.delenv("SUPERQODE_HOME", raising=False)
    assert default_sessions_db_path() == Path.home() / ".superqode" / "sessions.db"


@pytest.mark.asyncio
async def test_record_then_get_round_trip(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    rec = await store.record(
        "opencode.ai",
        "sess-1",
        "/proj/a",
        name="My session",
        metadata={"model": "claude-sonnet-4"},
    )
    assert rec is not None
    assert rec.session_id == "sess-1"
    assert rec.cwd == "/proj/a"
    assert rec.metadata == {"model": "claude-sonnet-4"}

    fetched = await store.get("opencode.ai", "sess-1")
    assert fetched is not None
    assert fetched.id == rec.id
    assert fetched.name == "My session"


@pytest.mark.asyncio
async def test_record_upserts_on_same_session_id(tmp_path):
    """Re-recording the same ``(agent, session_id)`` must update, not
    create a duplicate row. Without this, every resume would leak a
    duplicate into the listing."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a")
    await store.record("opencode.ai", "sess-1", "/proj/a", name="Renamed")
    rows = await store.list_for_agent("opencode.ai", cwd="/proj/a")
    assert len(rows) == 1
    assert rows[0].name == "Renamed"


@pytest.mark.asyncio
async def test_record_preserves_existing_name_when_new_is_empty(tmp_path):
    """Upserting with an empty name field shouldn't clobber a name set
    earlier — that's how ``touch_only`` would otherwise blow away
    user-assigned session names."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a", name="Important")
    await store.record("opencode.ai", "sess-1", "/proj/a")  # no name
    row = await store.get("opencode.ai", "sess-1")
    assert row is not None and row.name == "Important"


@pytest.mark.asyncio
async def test_touch_bumps_last_used_only(tmp_path):
    """Touching after every prompt is a hot path. It must update only
    ``last_used_at`` — never reset created_at, name, metadata."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record(
        "opencode.ai",
        "sess-1",
        "/proj/a",
        name="Keep me",
        metadata={"model": "x"},
    )
    first = await store.get("opencode.ai", "sess-1")
    assert first is not None

    # Sleep tiny — sqlite REAL timestamps need a measurable delta.
    await asyncio.sleep(0.01)
    await store.touch("opencode.ai", "sess-1")
    after = await store.get("opencode.ai", "sess-1")

    assert after is not None
    assert after.last_used_at > first.last_used_at
    assert after.created_at == first.created_at
    assert after.name == "Keep me"
    assert after.metadata == {"model": "x"}


@pytest.mark.asyncio
async def test_list_for_agent_scoped_to_cwd(tmp_path):
    """A session in project A must not appear in project B's listing —
    that's the whole point of recording cwd."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "a1", "/proj/a")
    await store.record("opencode.ai", "b1", "/proj/b")
    await store.record("opencode.ai", "b2", "/proj/b")

    a = await store.list_for_agent("opencode.ai", cwd="/proj/a")
    b = await store.list_for_agent("opencode.ai", cwd="/proj/b")
    assert [s.session_id for s in a] == ["a1"]
    assert {s.session_id for s in b} == {"b1", "b2"}


@pytest.mark.asyncio
async def test_list_for_agent_orders_by_last_used_desc(tmp_path):
    """Newest session first — that's what "list recent" demands."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "old", "/proj/a")
    await asyncio.sleep(0.01)
    await store.record("opencode.ai", "newer", "/proj/a")
    await asyncio.sleep(0.01)
    await store.record("opencode.ai", "newest", "/proj/a")

    rows = await store.list_for_agent("opencode.ai", cwd="/proj/a")
    assert [s.session_id for s in rows] == ["newest", "newer", "old"]


@pytest.mark.asyncio
async def test_list_for_agent_without_cwd_returns_all_projects(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "a", "/proj/a")
    await store.record("opencode.ai", "b", "/proj/b")
    rows = await store.list_for_agent("opencode.ai")
    assert {s.session_id for s in rows} == {"a", "b"}


@pytest.mark.asyncio
async def test_list_for_agent_does_not_leak_across_agents(tmp_path):
    """``opencode.ai`` and ``claude.com`` are different namespaces. A
    session id collision (vanishingly rare but possible) must not bleed
    into the wrong agent's history."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a")
    await store.record("claude.com", "sess-1", "/proj/a")
    a = await store.list_for_agent("opencode.ai")
    b = await store.list_for_agent("claude.com")
    assert len(a) == 1 and len(b) == 1
    assert a[0].agent_identity == "opencode.ai"
    assert b[0].agent_identity == "claude.com"


@pytest.mark.asyncio
async def test_most_recent_for_agent(tmp_path):
    """Convenience helper for the common "resume the latest" flow."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "first", "/proj/a")
    await asyncio.sleep(0.01)
    await store.record("opencode.ai", "second", "/proj/a")
    latest = await store.most_recent_for_agent("opencode.ai", cwd="/proj/a")
    assert latest is not None and latest.session_id == "second"


@pytest.mark.asyncio
async def test_most_recent_returns_none_when_empty(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    assert await store.most_recent_for_agent("nothing", cwd="/proj/a") is None


@pytest.mark.asyncio
async def test_delete_removes_row(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a")
    assert await store.delete("opencode.ai", "sess-1") is True
    assert await store.get("opencode.ai", "sess-1") is None


@pytest.mark.asyncio
async def test_delete_returns_false_for_unknown(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    assert await store.delete("opencode.ai", "never-set") is False


@pytest.mark.asyncio
async def test_clear_all_wipes_everything(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "a", "/proj/a")
    await store.record("claude.com", "b", "/proj/b")
    await store.clear_all()
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_update_name(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a")
    await store.update_name("opencode.ai", "sess-1", "Renamed")
    row = await store.get("opencode.ai", "sess-1")
    assert row is not None and row.name == "Renamed"


@pytest.mark.asyncio
async def test_corrupted_metadata_does_not_crash_listing(tmp_path):
    """If a user hand-edits the DB and breaks the JSON, listing must
    keep working with metadata={} rather than throwing."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "sess-1", "/proj/a", metadata={"x": 1})

    # Corrupt the JSON column directly.
    import sqlite3

    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.execute(
        "UPDATE sessions SET metadata_json = ? WHERE session_id = ?",
        ("{not json", "sess-1"),
    )
    conn.commit()
    conn.close()

    rows = await store.list_for_agent("opencode.ai")
    assert len(rows) == 1
    assert rows[0].metadata == {}  # graceful fallback


@pytest.mark.asyncio
async def test_db_file_initialized_lazily(tmp_path):
    """No DB file until the first operation — keeps tests fast and
    avoids touching disk on a no-op import."""
    path = tmp_path / "sessions.db"
    store = ACPSessionStore(path=path)
    assert not path.exists()
    await store.record("opencode.ai", "sess-1", "/proj/a")
    assert path.exists()


# ---------------------------------------------------------------------------
# ACPClient integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_current_session_writes_record(tmp_path):
    """When session_store + agent_identity are configured, the client
    records the session after creation."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    client = ACPClient(
        project_root=tmp_path,
        command="(unused)",
        model="claude-sonnet-4",
        session_store=store,
        agent_identity="opencode.ai",
    )
    client._session_id = "sess-abc"
    await client._persist_current_session()

    rows = await store.list_for_agent("opencode.ai", cwd=str(tmp_path))
    assert len(rows) == 1
    assert rows[0].session_id == "sess-abc"
    assert rows[0].metadata.get("model") == "claude-sonnet-4"


@pytest.mark.asyncio
async def test_persist_current_session_noop_without_store(tmp_path):
    """No store wired = no persistence — preserves the pre-A3 behavior
    so existing callers don't need to opt out of anything."""
    client = ACPClient(project_root=tmp_path, command="(unused)")
    client._session_id = "sess-abc"
    # Must not raise.
    await client._persist_current_session()


@pytest.mark.asyncio
async def test_persist_current_session_touch_only(tmp_path):
    """``touch_only=True`` (used after resume) must not overwrite
    metadata set on the original record."""
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    # Pre-seed a record with metadata.
    await store.record(
        "opencode.ai",
        "sess-x",
        str(tmp_path),
        metadata={"model": "older-model"},
    )

    client = ACPClient(
        project_root=tmp_path,
        command="(unused)",
        model="new-model-being-set-mid-session",
        session_store=store,
        agent_identity="opencode.ai",
    )
    client._session_id = "sess-x"
    await client._persist_current_session(touch_only=True)

    row = await store.get("opencode.ai", "sess-x")
    assert row is not None
    # touch_only path didn't rewrite the metadata blob.
    assert row.metadata.get("model") == "older-model"


@pytest.mark.asyncio
async def test_list_persisted_sessions_scopes_to_cwd_by_default(tmp_path):
    store = ACPSessionStore(path=tmp_path / "sessions.db")
    await store.record("opencode.ai", "this-proj", str(tmp_path))
    await store.record("opencode.ai", "elsewhere", "/proj/other")

    client = ACPClient(
        project_root=tmp_path,
        command="(unused)",
        session_store=store,
        agent_identity="opencode.ai",
    )
    rows = await client.list_persisted_sessions()
    assert [s.session_id for s in rows] == ["this-proj"]

    # Opt out of the cwd scope.
    rows_global = await client.list_persisted_sessions(cwd_only=False)
    assert {s.session_id for s in rows_global} == {"this-proj", "elsewhere"}


@pytest.mark.asyncio
async def test_list_persisted_sessions_returns_empty_without_store(tmp_path):
    client = ACPClient(project_root=tmp_path, command="(unused)")
    assert await client.list_persisted_sessions() == []


@pytest.mark.asyncio
async def test_supports_resume_reflects_agent_capabilities(tmp_path):
    """``loadSession`` capability flag must be surfaced through the
    public ``supports_resume()`` method so CLIs can branch on it."""
    client = ACPClient(project_root=tmp_path, command="(unused)")
    assert client.supports_resume() is False
    client._agent_capabilities = {"loadSession": True}
    assert client.supports_resume() is True
    client._agent_capabilities = {"loadSession": False}
    assert client.supports_resume() is False
