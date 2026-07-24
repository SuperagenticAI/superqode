"""Regression tests for consequential TUI transition feedback."""

from __future__ import annotations

import pytest

from superqode.app.mixins.feedback import FeedbackMixin
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp


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
async def test_model_transition_uses_transcript_without_popup(monkeypatch) -> None:
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
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
        await pilot.pause(0.1)

        assert len(app._notifications) == 0
        assert "Model ready" in "\n".join(line.text for line in log.lines)


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
