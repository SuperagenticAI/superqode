"""Unit tests for superqode.providers.subscription_login."""

from __future__ import annotations

import asyncio

import pytest

from superqode.providers import subscription_login as sl


def test_get_login_spec_known_and_unknown():
    assert sl.get_login_spec("codex").id == "codex"
    assert sl.get_login_spec("GROK").id == "grok"
    with pytest.raises(KeyError):
        sl.get_login_spec("nope")


def test_grok_auth_path_follows_grok_cli_auth(monkeypatch, tmp_path):
    """Grok's auth path must track grok_cli_auth.GROK_AUTH_FILE, not a frozen ~."""
    from superqode.providers import grok_cli_auth

    missing = tmp_path / "missing.json"
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", missing)
    assert sl.GROK_LOGIN.current_auth_path() == missing
    assert sl.has_local_login(sl.GROK_LOGIN) is False

    present = tmp_path / "auth.json"
    present.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", present)
    assert sl.GROK_LOGIN.current_auth_path() == present
    assert sl.has_local_login(sl.GROK_LOGIN) is True


def test_codex_auth_path_follows_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert sl.CODEX_LOGIN.current_auth_path() == tmp_path / ".codex" / "auth.json"
    assert sl.has_local_login(sl.CODEX_LOGIN) is False

    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("{}", encoding="utf-8")
    assert sl.has_local_login(sl.CODEX_LOGIN) is True


def test_login_ready_via_env_key(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.codex/auth.json
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    assert sl.login_ready(sl.CODEX_LOGIN) is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert sl.login_ready(sl.CODEX_LOGIN) is True


def test_extract_device_codes_and_urls():
    text = (
        "Visit https://x.ai/device and enter code 2KP1-NIB5S\n"
        "or open https://accounts.x.ai/authorize?state=ABCD-EFGH"
    )
    assert "https://x.ai/device" in sl.extract_urls(text)
    codes = sl.extract_device_codes(text)
    assert "2KP1-NIB5S" in codes
    # The query-string token that follows '=' is URL noise, not a device code.
    assert "ABCD-EFGH" not in codes


def test_run_subscription_login_already_signed_in(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    result = asyncio.run(sl.run_subscription_login("codex", auth_path=auth))
    assert result.ok is True
    assert result.auth_path == auth


def test_run_subscription_login_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sl.shutil, "which", lambda _name: None)
    missing = tmp_path / "missing.json"
    result = asyncio.run(sl.run_subscription_login("codex", auth_path=missing))
    assert result.ok is False
    assert "not installed" in result.reason
