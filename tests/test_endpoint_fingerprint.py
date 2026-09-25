"""Local session endpoint fingerprint resume guard."""

from __future__ import annotations

import pytest

from superqode.agent.session_manager import SessionManager, SessionMetadata
from superqode.session.endpoint_fingerprint import (
    check_resume_endpoint,
    fingerprint_endpoint,
    is_local_endpoint_provider,
)
from superqode.session.harness_bridge import SessionResumeError


def test_local_providers_are_fingerprint_gated():
    assert is_local_endpoint_provider("ollama")
    assert is_local_endpoint_provider("vllm")
    assert is_local_endpoint_provider("openai-compatible")
    assert not is_local_endpoint_provider("anthropic")


def test_fingerprint_stable_for_same_binding():
    a = fingerprint_endpoint("http://localhost:11434/v1", "")
    b = fingerprint_endpoint("http://localhost:11434/v1/", "")
    assert a and a == b


def test_resume_allows_legacy_sessions_without_fingerprint():
    meta = SessionMetadata(
        session_id="s1",
        created_at="t",
        updated_at="t",
        provider="ollama",
        model="qwen3:8b",
    )
    check_resume_endpoint(meta, provider="ollama")


def test_resume_refuses_changed_endpoint(monkeypatch):
    meta = SessionMetadata(
        session_id="s1",
        created_at="t",
        updated_at="t",
        provider="ollama",
        model="qwen3:8b",
        endpoint_base_url="http://localhost:11434/v1",
        endpoint_auth_slot="",
        endpoint_fingerprint=fingerprint_endpoint("http://localhost:11434/v1", ""),
    )

    def fake_binding(_provider: str):
        return ("http://127.0.0.1:9999/v1", "")

    monkeypatch.setattr(
        "superqode.session.endpoint_fingerprint.current_endpoint_binding",
        fake_binding,
    )
    with pytest.raises(SessionResumeError, match="endpoint or auth slot changed"):
        check_resume_endpoint(meta, provider="ollama")


def test_session_manager_binds_local_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "superqode.session.endpoint_fingerprint.current_endpoint_binding",
        lambda _p: ("http://localhost:11434/v1", ""),
    )
    manager = SessionManager(storage_dir=str(tmp_path))
    sid = manager.start_session(provider="ollama", model="qwen3:8b")
    info = manager.get_session_info(sid)
    assert info is not None
    assert info.endpoint_base_url == "http://localhost:11434/v1"
    assert info.endpoint_fingerprint == fingerprint_endpoint("http://localhost:11434/v1", "")
