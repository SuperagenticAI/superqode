"""Decorative bursts must stop redrawing between runs and preserve live status."""

import pytest
from textual import events

from superqode.app.widgets import BottomScanningLine, StreamingThinkingIndicator, TopScanningLine
from superqode.app_main import SuperQodeApp


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


async def test_real_burst_stops_redrawing_but_keeps_live_status():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._start_thinking()
        app._set_thinking_status("Reading files")
        await pilot.pause()
        waves = [
            app.query_one("#thinking-wave", TopScanningLine),
            app.query_one("#thinking-wave-bottom", BottomScanningLine),
        ]
        assert all(wave.is_active and wave.auto_refresh is not None for wave in waves)
        await pilot.pause(3.1)
        assert app.is_busy
        assert all(not wave.is_active and wave.auto_refresh is None for wave in waves)
        assert all(wave.has_class("visible") and "─" in wave.render().plain for wave in waves)
        indicator = app.query_one("#streaming-thinking", StreamingThinkingIndicator)
        assert indicator.is_active and indicator.auto_refresh is not None
        assert "Reading files" in indicator.render().plain
        app._show_wave_burst()
        await pilot.pause()
        assert all(wave.is_active for wave in waves)
        app._stop_thinking()
        await pilot.pause()
        assert all(not wave.is_active and not wave.has_class("visible") for wave in waves)
        assert app._wave_repeat_timer is None and app._wave_end_timer is None


class Timer:
    def __init__(self, seconds, callback):
        self.seconds, self.callback, self.stopped = seconds, callback, False

    def stop(self):
        self.stopped = True


async def test_schedule_is_shared_and_old_callbacks_cannot_affect_new_run(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        once, repeating = [], []

        def timer(seconds, callback, **kwargs):
            item = Timer(seconds, callback)
            once.append(item)
            return item

        def interval(seconds, callback, **kwargs):
            item = Timer(seconds, callback)
            repeating.append(item)
            return item

        monkeypatch.setattr(app, "set_timer", timer)
        monkeypatch.setattr(app, "set_interval", interval)
        app._start_thinking()
        old_end, old_repeat = once[-1], repeating[-1]
        assert old_end.seconds == 3 and old_repeat.seconds == 5
        app._start_stream_animation(app.query_one("#log"))
        assert len(repeating) == 1
        old_end.callback()
        assert not app.query_one("#thinking-wave", TopScanningLine).is_active
        old_repeat.callback()
        recurring_end = once[-1]
        assert recurring_end.seconds == 1
        assert app.query_one("#thinking-wave", TopScanningLine).is_active
        app._stop_stream_animation()
        assert recurring_end.stopped and old_repeat.stopped
        app._start_thinking()
        wave = app.query_one("#thinking-wave", TopScanningLine)
        assert wave.is_active
        old_end.callback()
        old_repeat.callback()
        assert wave.is_active and len(repeating) == 2
        app._stop_thinking()


async def test_blur_pauses_and_focus_resumes_only_an_active_run():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._start_thinking()
        app.on_app_blur(events.AppBlur())
        app.on_app_blur(events.AppBlur())
        await pilot.pause()
        wave = app.query_one("#thinking-wave", TopScanningLine)
        indicator = app.query_one("#streaming-thinking", StreamingThinkingIndicator)
        assert app.is_busy and not wave.is_active and indicator.auto_refresh is None
        assert app._wave_repeat_timer is None
        app.on_app_focus(events.AppFocus())
        await pilot.pause()
        assert wave.is_active and indicator.auto_refresh is not None
        app.on_app_blur(events.AppBlur())
        app._stop_thinking()
        app.on_app_focus(events.AppFocus())
        await pilot.pause()
        assert not wave.is_active and app._wave_repeat_timer is None


async def test_run_started_while_unfocused_waits_for_focus():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app.on_app_blur(events.AppBlur())
        app._start_thinking()
        await pilot.pause()
        wave = app.query_one("#thinking-wave", TopScanningLine)
        assert app.is_busy and not wave.is_active
        app.on_app_focus(events.AppFocus())
        await pilot.pause()
        assert wave.is_active
        app._stop_thinking()


async def test_launch_refreshes_catalogs_once_without_litellm_or_hourly_jobs(monkeypatch):
    calls = []
    for name in ("_start_models_dev_refresh", "_start_acp_registry_refresh", "_prewarm_litellm"):
        monkeypatch.setattr(SuperQodeApp, name, lambda self, name=name: calls.append(name))
    intervals = []
    original = SuperQodeApp.set_interval

    def record(self, seconds, callback=None, **kwargs):
        intervals.append(seconds)
        return original(self, seconds, callback, **kwargs)

    monkeypatch.setattr(SuperQodeApp, "set_interval", record)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.1)
        assert calls.count("_start_models_dev_refresh") == 1
        assert calls.count("_start_acp_registry_refresh") == 1
        assert "_prewarm_litellm" not in calls
        assert 3600 not in intervals


async def test_working_prompt_has_moving_three_dots_without_idle_redraws(monkeypatch):
    from superqode.app.inputs import SelectionAwareInput
    from superqode.app.widgets import HintsBar

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        hints = app.query_one("#hints", HintsBar)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert hints.auto_refresh is None
        assert getattr(prompt, "_working_timer", None) is None
        app._start_thinking()
        await pilot.pause()
        prompt._working_started_at = 0.0
        rendered = []
        for elapsed in (0.0, 0.5, 1.0):
            monkeypatch.setattr("superqode.app.inputs.monotonic", lambda elapsed=elapsed: elapsed)
            prompt._update_working_placeholder()
            rendered.append(prompt.placeholder)
        assert "Agent working ●··" in rendered[0]
        assert "Agent working ·●·" in rendered[1]
        assert "Agent working ··●" in rendered[2]
        assert "Agent working" not in hints.render().plain
        assert prompt.value == ""
        assert prompt._working_timer is not None
        app.on_app_blur(events.AppBlur())
        assert prompt._working_timer is None
        app.on_app_focus(events.AppFocus())
        assert prompt._working_timer is not None
        prompt.value = "My next prompt"
        await pilot.pause()
        assert prompt._working_timer is None
        assert not prompt.disabled
        app._stop_thinking()
        await pilot.pause()
        assert prompt.value == "My next prompt"
        assert prompt.placeholder == SelectionAwareInput.DEFAULT_PLACEHOLDER
        assert prompt._working_timer is None
        assert hints.auto_refresh is None


async def test_working_prompt_yields_to_decisions_and_restores_drafts():
    from superqode.app.inputs import SelectionAwareInput

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep this draft"
        app._set_composer_working_state(True)
        await pilot.pause()
        app._set_composer_working_state(True, interactive=True)
        app._set_input_placeholder("Approve tool? y / n / a")
        await pilot.pause()
        assert prompt.value == ""
        assert prompt.placeholder == "Approve tool? y / n / a"
        assert prompt._working_timer is None
        app._reset_input_placeholder()
        await pilot.pause()
        assert prompt.value == "Keep this draft"
        assert prompt.placeholder == SelectionAwareInput.DEFAULT_PLACEHOLDER


async def test_working_prompt_resumes_after_draft_cleared_and_stops_with_stream():
    from superqode.app.inputs import SelectionAwareInput

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._start_stream_animation(app.query_one("#log"))
        await pilot.pause()
        prompt.value = "draft"
        await pilot.pause()
        assert prompt._working_timer is None
        prompt.value = ""
        await pilot.pause()
        assert prompt.placeholder.startswith("Agent working ")
        assert prompt._working_timer is not None
        app._stop_stream_animation()
        await pilot.pause()
        assert prompt.placeholder == SelectionAwareInput.DEFAULT_PLACEHOLDER
        assert prompt._working_timer is None


async def test_working_prompt_renders_bright_theme_colors_and_varied_dots(monkeypatch):
    from rich.color import Color
    from superqode.app.constants import THEME
    from superqode.app.inputs import SelectionAwareInput

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._start_thinking()
        await pilot.pause()
        choices = []

        def choose(colors, count):
            choices.append(tuple(colors))
            return colors[:count] if len(choices) % 2 else colors[-count:]

        monkeypatch.setattr("superqode.app.inputs.sample", choose)
        for palette in (
            {
                "purple": "#bb88ff",
                "pink": "#ff88bb",
                "gold": "#ffcc66",
                "cyan": "#66ccff",
                "success": "#66ff99",
            },
            {
                "purple": "#aa77ee",
                "pink": "#ee77aa",
                "gold": "#eebb55",
                "cyan": "#55bbee",
                "success": "#55ee88",
            },
        ):
            for key, color in palette.items():
                monkeypatch.setitem(THEME, key, color)
            prompt._update_working_placeholder()
            segments = list(prompt.render_line(0))
            label = next(segment for segment in segments if "Agent working" in segment.text)
            assert label.style.bold
            assert label.style.color == Color.parse(palette["purple"])
            dots = [segment for segment in segments if segment.text in {"●", "·"}]
            assert len(dots) == 3
            assert len({dot.style.color for dot in dots}) == 3
            assert all(dot.style.bold for dot in dots)
            assert all(
                dot.style.color in {Color.parse(color) for color in palette.values()}
                for dot in dots
            )
        assert choices[0] != choices[1]
        app._stop_thinking()
