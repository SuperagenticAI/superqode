"""Regression tests for consequential TUI transition feedback."""

from __future__ import annotations

import pytest

from superqode.app.mixins.feedback import FeedbackMixin
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp


@pytest.fixture(autouse=True)
def isolate_feedback_startup(monkeypatch, tmp_path):
    from superqode.app import theme_bridge as bridge

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *args, **kwargs: None)


class _Log:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add_success(self, text: str) -> None:
        self.items.append(("success", text))

    def add_info(self, text: str) -> None:
        self.items.append(("information", text))

    def add_warning(self, text: str) -> None:
        self.items.append(("warning", text))

    def add_error(self, text: str) -> None:
        self.items.append(("error", text))

    def add_meta(self, text: str, icon: str = "·") -> None:
        self.items.append(("meta", f"{icon} {text}"))


class _FeedbackApp(FeedbackMixin):
    def __init__(self, log: _Log) -> None:
        self.log = log
        self.notifications: list[tuple[str, dict]] = []
        self.focus_count = 0

    def notify(self, message: str, **kwargs) -> None:
        self.notifications.append((message, kwargs))

    def query_one(self, *_args, **_kwargs):
        return self.log

    def _ensure_input_focus(self) -> None:
        self.focus_count += 1


def test_transition_feedback_has_toast_receipt_guidance_and_deduplication() -> None:
    log = _Log()
    app = _FeedbackApp(log)

    first = app._announce_transition(
        title="Connection failed",
        primary="OpenCode ACP",
        detail="No response received",
        severity="error",
        guidance="Run :log verbose for startup details.",
        dedupe_key="opencode-failure",
    )
    duplicate = app._announce_transition(
        title="Connection failed",
        primary="OpenCode ACP",
        detail="No response received",
        severity="error",
        guidance="Run :log verbose for startup details.",
        dedupe_key="opencode-failure",
    )

    assert first is True
    assert duplicate is False
    assert app.notifications == [
        (
            "OpenCode ACP\nNo response received\nRun :log verbose for startup details.",
            {
                "title": "Connection failed",
                "severity": "error",
                "timeout": 5.0,
                "markup": False,
            },
        )
    ]
    assert log.items == [
        ("error", "Connection failed: OpenCode ACP · No response received"),
        ("meta", "→ Run :log verbose for startup details."),
    ]
    assert app.focus_count == 1


@pytest.mark.asyncio
async def test_model_transition_is_visible_without_scrolling(monkeypatch) -> None:
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    # A saved-connection resume and the catalogue freshness line both write to
    # the transcript on mount. On a slower machine they arrive after the
    # announcement and replace the receipt this test reads back.
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        if hasattr(SuperQodeApp, name):
            monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None, raising=False)
    app = SuperQodeApp()
    async with app.run_test(size=(58, 24), notifications=True) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._announce_transition(
            title="Model ready",
            primary="Laguna S 2.1 Free",
            detail="OpenCode via ACP · opencode/laguna-s-2.1-free",
            severity="success",
            log=log,
        )
        for _ in range(6):
            await pilot.pause()

        # Routine success feedback is non-blocking; the transcript retains
        # the receipt after the toast disappears.
        from superqode.widgets.outcome_screen import OutcomeScreen

        assert not isinstance(app.screen, OutcomeScreen)
        # The transcript still keeps the receipt, so it survives dismissal.
        assert "Model ready" in "\n".join(line.text for line in log.lines)
        assert "Laguna S 2.1 Free" in "\n".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_model_ready_reports_without_asking_for_a_keypress():
    """Model selection repeats on every connect and every switch.

    A modal there stops being an acknowledgement and becomes a step to clear,
    so this one result reports through the self-clearing toast instead. The
    transcript receipt is what keeps it recoverable after the toast fades.
    """
    app = SuperQodeApp()
    async with app.run_test(size=(58, 24), notifications=True) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._announce_model_ready(
            model_name="Big Pickle",
            model_id="opencode/big-pickle",
            source="OpenCode",
            log=log,
            free=True,
        )
        for _ in range(6):
            await pilot.pause()

        from superqode.widgets.outcome_screen import OutcomeScreen

        assert not isinstance(app.screen, OutcomeScreen)
        assert "Model ready" in "\n".join(line.text for line in log.lines)
        assert "Big Pickle" in "\n".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_success_notification_is_a_centered_colored_card():
    """Connection feedback should look intentional, not like corner chrome."""
    from textual.widgets._toast import Toast

    app = SuperQodeApp()
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        app.notify(
            "OpenAI · gpt-5.6\nReady for your next prompt",
            title="Model ready",
            severity="information",
            timeout=5,
            markup=False,
        )
        await pilot.pause()

        toast = app.query_one(Toast)
        title_style = toast.get_component_rich_style("toast--title")

        assert 30 <= toast.region.width < 58
        assert abs(toast.region.x - (80 - toast.region.width) // 2) <= 1
        from superqode.app.constants import THEME

        assert toast.styles.background.hex.lower() == THEME["bg"]
        assert title_style.color is not None
        assert title_style.color.name == THEME["pink"]
        assert toast.styles.border_left[1].hex.lower() == THEME["purple"]
        assert toast.styles.border_right[1].hex.lower() == THEME["orange"]


def test_information_transition_can_request_a_short_popup() -> None:
    log = _Log()
    app = _FeedbackApp(log)

    announced = app._announce_transition(
        title="Action complete",
        primary="Evaluation report exported",
        severity="information",
        log=log,
        popup=True,
    )

    assert announced is True
    assert app.notifications == [
        (
            "Evaluation report exported",
            {
                "title": "Action complete",
                "severity": "information",
                "timeout": 1.5,
                "markup": False,
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("theme", ["superqode", "light", "ayu-light", "nord"])
async def test_theme_change_uses_connection_card_and_preserves_draft(theme):
    from textual.document._document import Selection
    from textual.widgets._toast import Toast
    from superqode.app.constants import THEME
    from superqode.app.inputs import SelectionAwareInput
    from superqode.app.theme_bridge import theme_display_name
    from superqode.theming import contrast
    from superqode.widgets.outcome_screen import OutcomeScreen

    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my developer draft"
        prompt.selection = Selection((0, 1), (0, 5))
        log = app.query_one("#log", ConversationLog)
        app._handle_theme(theme, log)
        await pilot.pause()

        toast = app.query_one(Toast)
        assert toast._notification.title == "Theme changed"
        assert theme_display_name(theme) in toast._notification.message
        assert "Saved for your next session" in toast._notification.message
        assert abs(toast.region.x - (80 - toast.region.width) // 2) <= 1
        assert toast.region.y <= app.query_one("#input-box").region.bottom
        title_color = toast.get_component_rich_style("toast--title").color
        assert contrast(title_color.name, toast.styles.background.hex) >= 4.5
        assert contrast(toast.styles.color.hex, toast.styles.background.hex) >= 4.5
        assert not isinstance(app.screen, OutcomeScreen)
        assert prompt.value == "Keep my developer draft"
        assert prompt.selection == Selection((0, 1), (0, 5))
        assert app.focused is prompt
        assert "Theme changed" in "\n".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_theme_save_error_is_visible_without_claiming_it_was_saved(monkeypatch):
    from textual.widgets._toast import Toast

    monkeypatch.setattr(
        "superqode.app.mixins.helpers.save_theme",
        lambda _name: "Theme applied but could not be saved: disk full",
    )
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await pilot.pause()
        app._handle_theme("light", app.query_one("#log", ConversationLog))
        await pilot.pause()
        toast = app.query_one(Toast)
        assert toast._notification.severity == "warning"
        assert "disk full" in toast._notification.message
        assert "Saved for your next session" not in toast._notification.message


@pytest.mark.asyncio
@pytest.mark.parametrize("theme", ["superqode", "light"])
@pytest.mark.parametrize("severity", ["warning", "error"])
async def test_attention_cards_are_readable_on_dark_and_light_themes(theme, severity):
    from textual.widgets._toast import Toast
    from superqode.theming import contrast

    app = SuperQodeApp(theme_selection=theme)
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        app.notify(
            "Details and recovery guidance", title="Needs attention", severity=severity, timeout=5
        )
        await pilot.pause()
        toast = app.query_one(Toast)
        title = toast.get_component_rich_style("toast--title").color.name
        assert contrast(title, toast.styles.background.hex) >= 4.5
        assert contrast(toast.styles.color.hex, toast.styles.background.hex) >= 4.5
