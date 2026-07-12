"""The subscription-login consent gate: SuperQode must ask before running the
vendor CLI login, and must never auto-open a browser."""

from __future__ import annotations

import asyncio

from superqode.app_main import SuperQodeApp
from superqode.providers import subscription_login as sl


class _Log:
    def __init__(self):
        self.info, self.err, self.ok, self.fb = [], [], [], []

    def add_info(self, m):
        self.info.append(str(m))

    def add_error(self, m):
        self.err.append(str(m))

    def add_success(self, m):
        self.ok.append(str(m))

    def write_feedback(self, t):
        self.fb.append(t)

    def write(self, t):
        self.fb.append(t)


def _new_app():
    app = object.__new__(SuperQodeApp)
    app.scheduled = []
    # Capture, but never run, the login worker coroutine (no real subprocess).
    app.run_worker = lambda coro, **k: (app.scheduled.append(coro), coro.close())
    app.placeholders = []
    app._set_input_placeholder = lambda text: app.placeholders.append(text)
    app._reset_input_placeholder = lambda: app.placeholders.append(None)
    return app


def _force_installed_signed_out(monkeypatch, tmp_path):
    """Grok CLI on PATH, but no local auth file."""
    monkeypatch.setattr(sl.shutil, "which", lambda name: "/usr/bin/" + name)
    from superqode.providers import grok_cli_auth

    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", tmp_path / "missing.json")


def test_begin_login_asks_first_and_does_not_launch(monkeypatch, tmp_path):
    _force_installed_signed_out(monkeypatch, tmp_path)
    app, log = _new_app(), _Log()

    started = SuperQodeApp._begin_subscription_login(app, "grok", log, reason="no login")

    assert started is True
    # A consent prompt is shown, the intent is stashed, and NOTHING is launched.
    assert app._awaiting_subscription_login is not None
    assert app._awaiting_subscription_login["product"] == "grok"
    assert app.scheduled == []
    assert app.placeholders and app.placeholders[-1] is not None


def test_confirm_launches_worker_and_carries_callback(monkeypatch, tmp_path):
    _force_installed_signed_out(monkeypatch, tmp_path)
    app, log = _new_app(), _Log()
    sentinel = lambda: None  # noqa: E731

    SuperQodeApp._begin_subscription_login(app, "grok", log, on_success=sentinel)
    # User presses Enter to confirm.
    handled = SuperQodeApp._handle_subscription_login_input(app, "", log)

    assert handled is True
    assert app._awaiting_subscription_login is None
    assert len(app.scheduled) == 1
    assert app._subscription_login_busy is True
    assert app._subscription_login_on_success is sentinel


def test_decline_cancels_without_launching(monkeypatch, tmp_path):
    _force_installed_signed_out(monkeypatch, tmp_path)
    app, log = _new_app(), _Log()

    SuperQodeApp._begin_subscription_login(app, "grok", log)
    handled = SuperQodeApp._handle_subscription_login_input(app, "n", log)

    assert handled is True
    assert app._awaiting_subscription_login is None
    assert app.scheduled == []
    assert any("cancelled" in m.lower() for m in log.info)


def test_unrecognized_answer_reprompts(monkeypatch, tmp_path):
    _force_installed_signed_out(monkeypatch, tmp_path)
    app, log = _new_app(), _Log()

    SuperQodeApp._begin_subscription_login(app, "grok", log)
    handled = SuperQodeApp._handle_subscription_login_input(app, "maybe", log)

    assert handled is True
    # Still awaiting; nothing launched.
    assert app._awaiting_subscription_login is not None
    assert app.scheduled == []


def test_worker_never_opens_browser(monkeypatch):
    """The login worker must pass open_browser=False to run_subscription_login."""
    app, log = _new_app(), _Log()
    app._call_ui = lambda func, *a: func(*a)
    app._subscription_login_busy = True
    app._subscription_login_on_success = None
    app._subscription_login_force = False

    captured = {}

    async def _fake_run(product, **kwargs):
        captured.update(kwargs)
        captured["product"] = product
        return sl.LoginResult(ok=False, reason="stopped")

    monkeypatch.setattr(sl, "run_subscription_login", _fake_run)

    asyncio.run(SuperQodeApp._subscription_login_worker(app, "grok", log))

    assert captured.get("open_browser") is False
    assert captured.get("product") == "grok"
