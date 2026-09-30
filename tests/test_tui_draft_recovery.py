"""Restart, disk-failure and cursor checks for unsent workspace drafts."""

import base64
import json
from pathlib import Path

import pytest

from superqode.app.draft_recovery import DraftStore, MAX_DRAFT_BYTES
from superqode.app.inputs import SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp
from superqode.image_input import load_image


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


def draft(text="unsent\nexact layout", cursor=7, refs=None, images=None):
    return {
        "text": text,
        "cursor": cursor,
        "refs": refs or [],
        "images": images or {},
        "prefill": "",
    }


def test_store_is_private_bounded_and_workspace_scoped(tmp_path):
    store = DraftStore(tmp_path / "one")
    store.save(draft(), 1)
    assert store.load()["text"] == "unsent\nexact layout"
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert DraftStore(tmp_path / "two").load() == {}
    store.save(draft("new"), 3)
    store.save(draft("stale"), 2)
    assert store.load()["text"] == "new"
    store.save(draft("x" * MAX_DRAFT_BYTES), 4)
    assert not store.path.exists()
    store.path.write_text('{"version": 1, "text": "broken"}')
    assert store.load() == {}
    store.path.write_bytes(b"x" * (MAX_DRAFT_BYTES + 1))
    assert store.load() == {}


async def test_restart_restores_exact_text_cursor_and_lazy_image_refs(tmp_path):
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII="
        )
    )
    store = DraftStore(tmp_path)
    app = SuperQodeApp()
    app._draft_store = store
    text = "@source.py explain\n  diagram precisely"
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = text
        prompt.cursor_position = len("@source.py explain\n  diagram")
        app._attached_refs = ["@source.py", "@diagram.png", "mcp://fixture/source"]
        app._staged_images = {"@diagram.png": load_image(image_path)}
        app._attachment_prefill = "@source.py "
        app._refresh_attachment_bar()
        await pilot.pause(0.65)
        assert store.load()["text"] == text
        assert "base64" not in store.path.read_text()
    restarted = SuperQodeApp()
    restarted._draft_store = DraftStore(tmp_path)
    async with restarted.run_test() as pilot:
        await pilot.pause()
        prompt = restarted.query_one("#prompt-input", SelectionAwareInput)
        assert prompt.value == text
        assert prompt.cursor_position == len("@source.py explain\n  diagram")
        assert prompt.has_focus
        assert restarted._attached_refs == app._attached_refs
        assert restarted._attachment_prefill == "@source.py "
        assert restarted._staged_images["@diagram.png"].data == ""
        images = restarted._prepare_image_input(restarted.query_one("#log", ConversationLog))
        assert images[0].data == load_image(image_path).data
        await pilot.press("left")
        await pilot.pause(0.65)
        assert restarted._draft_store.load()["cursor"] == prompt.cursor_position


async def test_clear_and_submit_remove_recovery_record(tmp_path):
    app = SuperQodeApp()
    app._draft_store = DraftStore(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "pending"
        app._flush_draft_recovery()
        assert app._draft_store.path.exists()
        await pilot.press("ctrl+u")
        await pilot.pause(0.65)
        assert not app._draft_store.path.exists()
        prompt.value = ":help"
        app._flush_draft_recovery()
        await pilot.press("enter")
        await pilot.pause(0.65)
        assert not app._draft_store.path.exists()


async def test_debounce_flush_and_decision_input_never_replace_draft(tmp_path, monkeypatch):
    app = SuperQodeApp()
    app._draft_store = DraftStore(tmp_path)
    writes = []
    save = app._draft_store.save
    monkeypatch.setattr(
        app._draft_store,
        "save",
        lambda state, revision: (writes.append(state), save(state, revision)),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        writes.clear()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        for text in ("a", "ab", "abc"):
            prompt.value = text
            await pilot.pause(0.04)
        assert not writes
        await pilot.pause(0.65)
        assert len(writes) == 1
        app._decision_draft = ("actual\n  draft", (1, 3))
        prompt.value = "yes"
        app._flush_draft_recovery()
        assert app._draft_store.load()["text"] == "actual\n  draft"
        assert app._draft_store.load()["cursor"] == 10
        monkeypatch.setattr(
            app._draft_store, "save", lambda *args: (_ for _ in ()).throw(OSError("read-only"))
        )
        await app._save_draft_in_background()
        app._flush_draft_recovery()
        assert prompt.value == "yes"


def test_invalid_cursor_refs_and_image_payloads_are_ignored(tmp_path):
    store = DraftStore(tmp_path)
    store.path.parent.mkdir()
    for state in (
        {"version": 2, **draft()},
        {"version": 1, **draft(), "refs": [None]},
        {"version": 1, **draft(), "images": {"@unknown.png": "unknown"}},
        {"version": 1, **draft(), "cursor": "wrong"},
    ):
        store.path.write_text(json.dumps(state))
        assert store.load() == {}
