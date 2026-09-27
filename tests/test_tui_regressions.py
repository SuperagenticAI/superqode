"""Focused regressions for asynchronous harness work and live TUI themes."""

from __future__ import annotations

import asyncio
import threading

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from superqode.app import theme_bridge
from superqode.app.constants import THEME
from superqode.app.mixins.helper_wizard import HelperWizardMixin
from superqode.logging.formatter import UnifiedLogFormatter
from superqode.logging.unified_log import LogConfig, acp_diff_stats
from superqode.widgets.slash_complete import SlashComplete, SlashCompleteItem


class _Log:
    def __init__(self) -> None:
        self.info: list[str] = []
        self.errors: list[str] = []

    def add_info(self, message: str) -> None:
        self.info.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)


@pytest.mark.asyncio
async def test_cancelled_harness_worker_cannot_load_stale_result(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class Wizard(HelperWizardMixin):
        def __init__(self) -> None:
            self._awaiting_harness_wizard = True
            self._harness_wizard_state = {
                "answers": {},
                "output": str(tmp_path / "harness.yaml"),
                "load": True,
                "force": False,
            }
            self.worker = None
            self.shown: list[tuple] = []

        def run_worker(self, coroutine):
            self.worker = asyncio.create_task(coroutine)

        def _run_harness_wizard_finish(self, *_args):
            started.set()
            release.wait(timeout=2)
            return (object(), tmp_path / "harness.yaml", object(), True)

        def _show_harness_wizard_result(self, *args) -> None:
            self.shown.append(args)

    wizard = Wizard()
    wizard._finish_harness_wizard_flow(_Log())
    assert await asyncio.to_thread(started.wait, 1)

    assert wizard._cancel_harness_wizard() is True
    release.set()
    await wizard.worker

    assert wizard.shown == []


class _SlashApp(App):
    def compose(self) -> ComposeResult:
        yield SlashComplete()


@pytest.mark.asyncio
async def test_filtered_slash_rows_mount_with_active_theme_colors():
    theme_bridge.apply_theme("nord")
    try:
        async with _SlashApp().run_test() as pilot:
            overlay = pilot.app.query_one(SlashComplete)
            overlay.show("/")
            await pilot.pause()

            overlay.search_query = "h"
            await pilot.pause()
            unselected = next(
                item for item in overlay.query(SlashCompleteItem) if not item.selected
            )
            command = unselected.query_one(".command", Static)

            assert command.styles.color.hex.lower() == THEME["pink"].lower()
    finally:
        theme_bridge.apply_theme("superqode")


def test_unified_log_code_theme_tracks_active_tui_theme():
    theme_bridge.apply_theme("nord")
    try:
        assert UnifiedLogFormatter()._code_theme() == "nord"
        assert UnifiedLogFormatter(LogConfig(code_theme="monokai"))._code_theme() == "monokai"
    finally:
        theme_bridge.apply_theme("superqode")


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("", "++counter;\n", (1, 0)),
        ("-- SQL comment\n", "", (0, 1)),
        ("", "--- markdown rule\n", (1, 0)),
    ],
)
def test_acp_diff_stats_preserves_source_lines_that_resemble_headers(old, new, expected):
    update = {"content": [{"type": "diff", "oldText": old, "newText": new}]}

    assert acp_diff_stats(update) == expected
