"""Changing theme must visibly change the screen, without eating the transcript.

Retained strips carry semantic roles and resolve them when painted. Theme changes
refresh CSS and widgets without clearing or replaying conversation activity.
"""

from __future__ import annotations

from superqode.app.mixins.helpers import HelpersMixin
from superqode.app.mixins.feedback import FeedbackMixin


class _Log:
    def __init__(self):
        self.info: list[str] = []
        self.success: list[str] = []

    def add_info(self, value):
        self.info.append(str(value))

    def add_success(self, value):
        self.success.append(str(value))


def _app(*, welcome_active: bool, applied: bool = True):
    from superqode.app.mixins.slash_commands import SlashCommandMixin

    class Stub(HelpersMixin, SlashCommandMixin, FeedbackMixin):
        def __init__(self):
            self._welcome_active = welcome_active
            self._current_theme = "dracula"
            self.rerendered = 0
            self.refreshed = 0
            self.saved: list[str] = []
            self.notifications = []

        def notify(self, message, **kwargs):
            self.notifications.append((message, kwargs))

        def _rerender_welcome(self):
            self.rerendered += 1

        @property
        def screen(self):
            outer = self

            class _Screen:
                def refresh(self, **_kwargs):
                    outer.refreshed += 1

            return _Screen()

    return Stub()


class TestRepaintOnThemeChange:
    def test_home_screen_refreshes_without_clearing_retained_content(self, monkeypatch):
        monkeypatch.setattr("superqode.app.mixins.helpers._apply_theme_palette", lambda _n: True)
        monkeypatch.setattr("superqode.app.mixins.helpers.save_theme", lambda _n, **kw: None)
        app = _app(welcome_active=True)

        assert app._apply_and_persist_theme("superqode") is True
        assert app.rerendered == 0
        assert app.refreshed == 1

    def test_a_transcript_is_never_destroyed_by_a_cosmetic_command(self, monkeypatch):
        """Rebuilding clears the log, so it must not run over a conversation."""
        monkeypatch.setattr("superqode.app.mixins.helpers._apply_theme_palette", lambda _n: True)
        monkeypatch.setattr("superqode.app.mixins.helpers.save_theme", lambda _n, **kw: None)
        app = _app(welcome_active=False)

        assert app._apply_and_persist_theme("nord") is True
        assert app.rerendered == 0
        assert app.refreshed == 1

    def test_an_unknown_theme_changes_and_repaints_nothing(self, monkeypatch):
        monkeypatch.setattr("superqode.app.mixins.helpers._apply_theme_palette", lambda _n: False)
        saved: list[str] = []
        monkeypatch.setattr(
            "superqode.app.mixins.helpers.save_theme", lambda n, **kw: saved.append(n)
        )
        app = _app(welcome_active=True)

        assert app._apply_and_persist_theme("nope") is False
        assert app.rerendered == 0
        assert saved == [], "an invalid theme must not be persisted"

    def test_theme_switch_never_invokes_destructive_welcome_replay(self, monkeypatch):
        """The welcome replay path must not run during a theme switch."""
        monkeypatch.setattr("superqode.app.mixins.helpers._apply_theme_palette", lambda _n: True)
        monkeypatch.setattr("superqode.app.mixins.helpers.save_theme", lambda _n, **kw: None)
        app = _app(welcome_active=True)

        def explode():
            raise RuntimeError("render failed")

        app._rerender_welcome = explode

        assert app._apply_and_persist_theme("superqode") is True
        assert app.refreshed == 1


class TestUserIsToldWhatHappened:
    def test_a_repainted_change_needs_no_caveat(self):
        app = _app(welcome_active=True)
        app._theme_repainted_welcome = True
        log = _Log()

        app._report_theme_change("superqode", log)

        assert log.success == ["Theme changed: SuperQode · Saved for your next session"]
        assert log.info == []
        assert app.notifications == [
            (
                "SuperQode\nSaved for your next session",
                {
                    "title": "Theme changed",
                    "severity": "information",
                    "timeout": 3,
                    "markup": False,
                },
            )
        ]

    def test_a_changed_theme_does_not_claim_retained_output_is_stale(self):
        """Retained output now resolves its colours at paint time."""
        app = _app(welcome_active=False)
        app._theme_repainted_welcome = False
        log = _Log()

        app._report_theme_change("nord", log)

        assert log.success == ["Theme changed: Nord · Saved for your next session"]
        assert log.info == []
