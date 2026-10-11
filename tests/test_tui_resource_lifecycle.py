"""Keep task display memory bounded without discarding conversation evidence."""

from pathlib import Path

import pytest
from rich.text import Text

from superqode.app_main import SuperQodeApp
from superqode.app.widgets import ConversationLog


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("superqode.app.theme_bridge._CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


async def test_long_running_transcript_bounds_rendering_and_retains_raw_messages():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        assert log.max_lines == 3000
        log.reset_conversation()
        bodies = [f"Recorded task {index}\n" + "tool output line\n" * 100 for index in range(40)]
        for body in bodies:
            log.add_info(body)
        await pilot.pause()
        assert len(log.lines) <= 3000
        assert log._start_line > 0
        assert [text for role, text, _ in log._messages if role == "info"] == bodies
        transcript = log.get_all_text()
        assert "Recorded task 0" in transcript and "Recorded task 39" in transcript
        assert "Recorded task 0" not in "\n".join(line.text for line in log.lines)


async def test_render_trimming_keeps_response_anchors_and_unread_count_correct():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        log.reset_conversation()
        log.max_lines = 100
        log.write(Text("existing output\n" * 90))
        log._response_start_y, log._response_end_y = 80, 90
        log._set_viewport_mode("user_locked")
        before = log._start_line
        log.write(Text("\n".join(["new output"] * 60)))
        removed = log._start_line - before
        assert removed > 0 and len(log.lines) <= 100
        assert log._response_start_y == max(0, 80 - removed)
        assert log._response_end_y == max(0, 90 - removed)
        assert log.unread_output_lines == 60
        assert log.viewport_mode == "user_locked"


async def test_ds4_warmup_is_optin(monkeypatch):
    monkeypatch.delenv("SUPERQODE_DS4_WARMUP", raising=False)

    class Client:
        async def warmup(self, model):
            raise AssertionError("Connecting must not preload a model by default")

    app = SuperQodeApp()
    async with app.run_test():
        await app._warmup_ds4(Client(), "fixture", app.query_one("#log", ConversationLog))
        assert not app.is_busy


async def test_history_paging_stays_bounded_and_preserves_all_recorded_turns():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        log.max_lines = 100
        turns = [
            {"role": "user", "content": f"Turn {index}\n" + "context\n" * 8} for index in range(120)
        ]
        log.replay_history(turns)
        log.add_user("New live task after resuming")
        full = list(log._messages)
        assert "Load earlier" in "\n".join(line.text for line in log.lines)
        log.load_earlier_history()
        assert log._history_start == 40 and log._history_end == 80
        assert len(log.lines) <= 100
        log.load_earlier_history()
        assert log._history_start == 0 and log._history_end == 40
        assert len(log.lines) <= 100
        log.load_later_history()
        assert log._history_start == 40 and log._history_end == 80
        assert len(log.lines) <= 100 and log._messages == full
        assert "Load later" in "\n".join(line.text for line in log.lines)
        log.load_later_history()
        log.load_later_history()
        assert log._history_end == 121
        assert "New live task after resuming" in "\n".join(line.text for line in log.lines)
        assert log._messages == full and len(log.lines) <= 100
