"""Unit tests for superqode.providers.subscription_login."""

from __future__ import annotations

import asyncio

import pytest

from superqode.providers import subscription_login as sl


def test_get_login_spec_known_and_unknown():
    assert sl.get_login_spec("codex").id == "codex"
    assert sl.get_login_spec("GROK").id == "grok"
    assert sl.get_login_spec("copilot").login_args == ("login",)
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


def test_copilot_login_accepts_clean_exit_without_auth_file(monkeypatch, tmp_path):
    class _Stdout:
        async def read(self, _size):
            return b""

    class _Process:
        returncode = 0
        stdout = _Stdout()

    process = _Process()

    async def _create(*args, **kwargs):
        return process

    monkeypatch.setattr(sl.shutil, "which", lambda _name: "/usr/bin/copilot")
    monkeypatch.setattr(sl.asyncio, "create_subprocess_exec", _create)
    result = asyncio.run(
        sl.run_subscription_login(
            "copilot",
            auth_path=tmp_path / "missing.json",
            force=True,
            open_browser=False,
        )
    )

    assert result.ok is True
    assert result.returncode == 0


def test_muse_readiness_ignores_the_signed_out_skeleton_file(monkeypatch, tmp_path):
    """Muse keeps a parseable auth.json while signed out, so size proves nothing.

    The default probe accepts any non-empty file, which would report every Muse
    user as already authenticated and never offer sign-in.
    """
    monkeypatch.setattr(sl.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MUSE_AUTH_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    store = tmp_path / ".config" / "muse"
    store.mkdir(parents=True)
    skeleton = '{"schema_version": 1, "providers": {}}'
    (store / "auth.json").write_text(skeleton, encoding="utf-8")

    assert len(skeleton) > 0  # non-empty: the default probe would say "ready"
    assert sl.has_local_login(sl.MUSE_LOGIN) is False
    assert sl.login_ready(sl.MUSE_LOGIN) is False


def test_muse_signed_out_state_is_believed_rather_than_worked_around(monkeypatch, tmp_path):
    """Muse revokes its own credential, so an empty provider map is the truth.

    An account without a payment method signs in and is then signed back out by
    Muse ("logged out: removed the stored Meta credential"). Caching a past
    sign-in would report a session that Muse has already thrown away.
    """
    monkeypatch.setattr(sl.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MUSE_AUTH_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    store = tmp_path / ".config" / "muse"
    store.mkdir(parents=True)
    auth = store / "auth.json"

    auth.write_text('{"schema_version": 1, "providers": {"meta": {}}}', encoding="utf-8")
    assert sl.login_ready(sl.MUSE_LOGIN) is True

    # Muse revokes the session on the next run when billing is missing.
    auth.write_text('{"schema_version": 1, "providers": {}}', encoding="utf-8")
    assert sl.login_ready(sl.MUSE_LOGIN) is False

    # Nothing may remember the earlier success and override Muse.
    assert not hasattr(sl, "record_muse_login")


def test_muse_carries_the_billing_requirement_for_the_user(monkeypatch):
    """A sign-in that leaves no credential must explain why, not just fail."""
    assert "payment method" in sl.MUSE_BILLING_HINT
    assert "dev.meta.ai" in sl.MUSE_BILLING_HINT


def test_interactive_logins_are_refused_by_the_piped_flow():
    """A TUI login piped for its stdout can never finish, so never claim it did.

    `muse login` draws a menu and waits on keys. Running it through the
    device-code flow gave it no TTY, opened no browser, and then read its exit
    code as a completed sign-in.
    """
    assert sl.MUSE_LOGIN.interactive_tty is True

    result = asyncio.run(sl.run_subscription_login("muse", force=True, open_browser=False))

    assert result.ok is False
    assert "interactive terminal" in result.reason


def test_device_code_logins_are_still_allowed_through_the_piped_flow():
    """The guard must not touch Codex, Grok, or Copilot."""
    for product in ("codex", "grok", "copilot"):
        assert sl.get_login_spec(product).interactive_tty is False
