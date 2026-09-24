"""SessionManager dual-write and harness / PiPy resume routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.agent.session_manager import SessionManager
from superqode.harness.store import FileHarnessStore
from superqode.harness.templates import pipy_template
from superqode.pure_mode import PureMode
from superqode.session.harness_bridge import (
    SessionResumeError,
    discover_external_sessions,
    ensure_sessions_listed,
    format_session_label,
    missing_provider_credentials,
    relative_age,
    topic_from_preview,
    upsert_harness_session_meta,
)


def test_upsert_harness_session_meta_creates_listable_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    meta = upsert_harness_session_meta(
        "harness-abc123",
        provider="ollama",
        model="qwen2.5-coder",
        harness_id="pipy",
        harness_source="harness-spec",
        harness_display="PiPy",
        preview="refactor auth middleware",
    )
    assert meta.harness_session is True
    assert meta.harness_id == "pipy"
    assert meta.harness_display_name == "PiPy"
    assert meta.title == "refactor auth middleware"
    assert meta.provider == "ollama"
    assert meta.model == "qwen2.5-coder"
    assert meta.working_directory.endswith(str(tmp_path.resolve()))

    listed = SessionManager(".superqode/sessions").list_all_sessions()
    assert [item.session_id for item in listed] == ["harness-abc123"]
    payload = json.loads((tmp_path / ".superqode/sessions/harness-abc123.meta.json").read_text())
    assert payload["harness_session"] is True
    assert payload["harness_display_name"] == "PiPy"
    assert "refactor auth" in payload["title"]


def test_format_session_label_is_human_readable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    meta = upsert_harness_session_meta(
        "sess-label",
        provider="openai",
        model="gpt-4.1",
        harness_id="pipy",
        harness_display="PiPy",
        title="refactor auth",
    )
    label = format_session_label(meta)
    assert label.startswith("PiPy · gpt-4.1 · refactor auth ·")
    assert "ago" in label or "just now" in label


def test_upsert_is_idempotent_and_updates_binding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    upsert_harness_session_meta("sess-1", provider="ollama", model="m1", harness_id="pipy")
    upsert_harness_session_meta(
        "sess-1",
        provider="ollama",
        model="m2",
        harness_id="pipy",
        title="renamed topic",
        message_count=3,
    )
    meta = SessionManager(".superqode/sessions").get_session_info("sess-1")
    assert meta is not None
    assert meta.provider == "ollama"
    assert meta.model == "m2"
    assert meta.title == "renamed topic"
    assert meta.message_count == 3
    assert meta.harness_session is True


def test_discover_registers_file_harness_store_sessions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = FileHarnessStore(tmp_path / ".superqode/sessions")
    store.open_session(
        "harness-deadbeef",
        pipy_template(),
        metadata={"provider": "ollama", "model": "qwen", "title": "stored topic"},
    )

    discovered = discover_external_sessions(cwd=tmp_path, register=True)
    assert any(item.session_id == "harness-deadbeef" for item in discovered)

    listed = ensure_sessions_listed(cwd=tmp_path)
    match = next(item for item in listed if item.session_id == "harness-deadbeef")
    assert match.harness_session is True
    assert match.harness_id == "pipy"
    assert match.provider == "ollama"
    assert "stored topic" in match.title


@pytest.mark.asyncio
async def test_ensure_harness_session_dual_writes_session_manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)

    pure = PureMode()
    pure.select_harness("pipy")
    pure.connect("ollama", "qwen2.5-coder")

    session = await pure._ensure_harness_session()
    assert session.session_id
    assert pure._harness_session_id == session.session_id

    meta = SessionManager(".superqode/sessions").get_session_info(session.session_id)
    assert meta is not None
    assert meta.harness_session is True
    assert meta.harness_id == "pipy"
    assert meta.harness_display_name == "PiPy"
    assert meta.provider == "ollama"
    assert meta.model == "qwen2.5-coder"
    assert meta.working_directory


def test_resume_harness_session_restores_route_and_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)

    upsert_harness_session_meta(
        "harness-resume1",
        provider="ollama",
        model="qwen2.5-coder",
        harness_id="pipy",
        harness_source="harness-spec",
        harness_display="PiPy",
        title="continue transcript",
        working_directory=tmp_path,
    )

    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    messages = pure.resume_session("harness-resume1")

    assert messages == []
    assert pure.get_current_session_id() == "harness-resume1"
    assert pure._harness_session_id == "harness-resume1"
    assert pure.session.connected is True
    assert pure.session.provider == "ollama"
    assert pure.session.model == "qwen2.5-coder"
    assert pure._harness_spec is not None
    assert pure.session.harness_name == "PiPy"


def test_resume_by_human_title(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    upsert_harness_session_meta(
        "named-sess-01",
        provider="ollama",
        model="qwen2.5-coder",
        harness_id="pipy",
        harness_display="PiPy",
        title="refactor auth",
        working_directory=tmp_path,
    )
    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    assert pure.resolve_session_id("refactor auth") == "named-sess-01"
    assert pure.resume_session("refactor auth") == []


def test_resume_missing_credentials_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    upsert_harness_session_meta(
        "need-key-01",
        provider="openai",
        model="gpt-4.1",
        harness_id="pipy",
        harness_display="PiPy",
        title="needs key",
    )
    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    with pytest.raises(SessionResumeError) as exc:
        pure.resume_session("need-key-01")
    assert "OPENAI_API_KEY" in str(exc.value)
    assert "needs key" in str(exc.value) or "PiPy" in str(exc.value)


def test_resume_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    assert pure.resume_session("does-not-exist") is None


def test_missing_provider_credentials_ignores_local_routes():
    assert missing_provider_credentials("ollama") == ""
    assert missing_provider_credentials("") == ""


def test_topic_and_relative_age_helpers():
    assert topic_from_preview("  fix the login  flow  ") == "fix the login flow"
    assert "ago" in relative_age("2000-01-01T00:00:00") or "d ago" in relative_age(
        "2000-01-01T00:00:00"
    )


def test_pipy_resume_target_resolver_by_index_and_path(tmp_path):
    from superqode.app.mixins.pipy_commands import PiPyCommandMixin
    from superqode.pipy.session.repository import SessionRecord
    from superqode.pipy.session.entries import SessionMetadata as PiPyMeta

    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"
    path_a.write_text("{}\n", encoding="utf-8")
    path_b.write_text("{}\n", encoding="utf-8")
    records = [
        SessionRecord(path=path_a, metadata=PiPyMeta(id="aaa", cwd=str(tmp_path), timestamp="t1")),
        SessionRecord(path=path_b, metadata=PiPyMeta(id="bbb", cwd=str(tmp_path), timestamp="t2")),
    ]

    assert PiPyCommandMixin._resolve_pipy_resume_target(records, "1").id == "aaa"
    assert PiPyCommandMixin._resolve_pipy_resume_target(records, "2").id == "bbb"
    assert PiPyCommandMixin._resolve_pipy_resume_target(records, str(path_b)).id == "bbb"
    assert PiPyCommandMixin._resolve_pipy_resume_target(records, "bbb").id == "bbb"
    assert PiPyCommandMixin._resolve_pipy_resume_target(records, "9") is None
