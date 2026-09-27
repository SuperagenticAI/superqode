"""Session browser helpers and mounted screen behaviour."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from superqode.agent.session_manager import SessionManager, SessionMetadata
from superqode.app.project_ui_state import (
    get_last_session_id,
    get_sidebar_width,
    set_last_session_id,
    set_sidebar_width,
)
from superqode.session.harness_bridge import (
    SessionAvailability,
    filter_sessions,
    paginate_sessions,
    probe_session_availability,
    session_list_preview,
)
from superqode.widgets.session_browser import SessionBrowserResult, SessionBrowserScreen


def _meta(
    session_id: str,
    *,
    title: str = "",
    harness_id: str = "workbench",
    model: str = "gpt-4.1",
    provider: str = "openai",
    minutes_ago: int = 5,
    harness_session: bool = False,
    backend_session_path: str = "",
) -> SessionMetadata:
    stamp = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
    return SessionMetadata(
        session_id=session_id,
        created_at=stamp,
        updated_at=stamp,
        provider=provider,
        model=model,
        title=title or f"Topic {session_id}",
        harness_id=harness_id,
        harness_display_name=harness_id[:1].upper() + harness_id[1:],
        harness_session=harness_session,
        backend_session_path=backend_session_path,
        working_directory=str(Path.cwd()),
        message_count=3,
    )


def test_filter_sessions_substring_and_fuzzy():
    rows = [
        _meta("aaa11111", title="refactor auth", harness_id="pipy", model="qwen3"),
        _meta("bbb22222", title="docs polish", harness_id="core", model="gpt-4.1"),
        _meta("ccc33333", title="eval harness", harness_id="tau", model="claude"),
    ]
    assert [item.session_id for item in filter_sessions(rows, "auth")] == ["aaa11111"]
    assert [item.session_id for item in filter_sessions(rows, "pipy")] == ["aaa11111"]
    assert [item.session_id for item in filter_sessions(rows, "gpt")] == ["bbb22222"]
    assert [item.session_id for item in filter_sessions(rows, "ccc333")] == ["ccc33333"]
    assert filter_sessions(rows, "") == rows


def test_paginate_sessions_stable_pages():
    rows = [_meta(f"id{i:04d}") for i in range(95)]
    page0, index, total = paginate_sessions(rows, page=0, page_size=40)
    assert index == 0 and total == 3 and len(page0) == 40
    page2, index, total = paginate_sessions(rows, page=2, page_size=40)
    assert index == 2 and total == 3 and len(page2) == 15
    overflow, index, total = paginate_sessions(rows, page=99, page_size=40)
    assert index == 2 and overflow == page2


def test_probe_availability_ok_missing_harness_and_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = SessionManager(storage_dir=str(tmp_path / ".superqode" / "sessions"))
    ok = store.store.create_session(
        "ok-session", provider="ollama", model="qwen", harness_id="core"
    )
    bad_creds = store.store.create_session(
        "creds-session", provider="openai", model="gpt-4.1", harness_id="core"
    )
    missing = store.store.create_session(
        "harness-session",
        provider="ollama",
        model="qwen",
        harness_id="definitely-missing-harness-xyz",
    )
    registered = {ok.session_id, bad_creds.session_id, missing.session_id}

    assert probe_session_availability(ok, cwd=tmp_path, registered_ids=registered).status == "ok"
    creds = probe_session_availability(bad_creds, cwd=tmp_path, registered_ids=registered)
    assert creds.status == "bad_credentials"
    assert "OPENAI" in creds.detail.upper() or "key" in creds.recovery.lower()
    harness = probe_session_availability(missing, cwd=tmp_path, registered_ids=registered)
    assert harness.status == "missing_harness"

    external = _meta("external-only", harness_session=True, provider="ollama", model="qwen")
    assert (
        probe_session_availability(external, cwd=tmp_path, registered_ids=registered).status
        == "external_only"
    )


def test_project_ui_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    set_last_session_id("abc12345")
    set_sidebar_width(48)
    assert get_last_session_id() == "abc12345"
    assert get_sidebar_width() == 48
    assert (tmp_path / ".superqode" / "ui-state.json").is_file()


def test_session_list_preview_prefers_title():
    assert "Ship auth" in session_list_preview(_meta("x", title="Ship auth"))


class _BrowserApp(App):
    def __init__(self, sessions: list[SessionMetadata], **kwargs) -> None:
        super().__init__()
        self.sessions = sessions
        self.kwargs = kwargs
        self.result: SessionBrowserResult | None = None

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.push_screen(
            SessionBrowserScreen(self.sessions, **self.kwargs),
            callback=self._done,
        )

    def _done(self, result: SessionBrowserResult | None) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_session_browser_search_paginate_and_resume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sessions = [_meta(f"sess{i:04d}", title=f"Topic {i}", minutes_ago=i) for i in range(90)]
    sessions[3] = _meta("sess0003", title="unique auth fix", harness_id="pipy", model="qwen3")
    app = _BrowserApp(
        sessions,
        cwd=tmp_path,
        last_session_id="sess0000",
        page_size=40,
        registered_ids={item.session_id for item in sessions},
    )
    async with app.run_test(size=(110, 36)) as pilot:
        screen = app.screen
        assert isinstance(screen, SessionBrowserScreen)
        assert len(screen.page_rows) == 40
        assert screen.total_pages == 3

        await pilot.pause()
        await pilot.press("/")
        for char in "unique auth":
            await pilot.press(char)
        await pilot.pause()
        assert [item.session_id for item in screen.filtered] == ["sess0003"]
        assert len(screen.page_rows) == 1

        await pilot.press("enter")
        await pilot.pause()
        assert app.result == SessionBrowserResult(action="resume", session_id="sess0003")


@pytest.mark.asyncio
async def test_session_browser_continue_last(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sessions = [_meta("last1111", title="Most recent"), _meta("old2222", title="Older")]
    app = _BrowserApp(
        sessions,
        cwd=tmp_path,
        last_session_id="last1111",
        registered_ids={item.session_id for item in sessions},
    )
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        assert await pilot.click("#sb-continue")
        await pilot.pause()
        assert app.result == SessionBrowserResult(action="continue_last", session_id="last1111")


@pytest.mark.asyncio
async def test_session_browser_rename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = SessionManager(storage_dir=str(tmp_path / ".superqode" / "sessions"))
    meta = store.store.create_session("rename-me", provider="ollama", model="qwen", title="Old")
    app = _BrowserApp(
        [meta],
        cwd=tmp_path,
        storage_dir=str(tmp_path / ".superqode" / "sessions"),
        registered_ids={meta.session_id},
    )
    async with app.run_test(size=(100, 34)) as pilot:
        screen = app.screen
        assert isinstance(screen, SessionBrowserScreen)
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        rename = screen.query_one("#sb-rename", Input)
        rename.value = "Fresh title"
        await pilot.press("enter")
        await pilot.pause()
        reloaded = store.get_session_info("rename-me")
        assert reloaded is not None
        assert reloaded.title == "Fresh title"
        assert screen.query_one("#sb-list", OptionList).option_count >= 1
