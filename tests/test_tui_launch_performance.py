"""Launch-path behaviour: the work before the first frame, and what fills it.

The TUI paints at roughly 0.7s, and everything heavy is deliberately deferred
behind that. These tests pin the parts that are easy to regress: the file walk
that runs alongside the first frames, the splash that covers the wait, and the
indicator that says a catalogue is refreshing.
"""

from __future__ import annotations

import io
import os
import sys

import pytest


def _quiet_startup(monkeypatch) -> None:
    """Stop the launch timers from writing over a test's own state.

    On mount the app schedules a models.dev refresh, an ACP registry refresh, a
    catalogue freshness line and a saved-connection resume. Each of them writes
    to the transcript or moves the catalogue chip, and on a slower machine they
    land in the middle of a test that is asserting on exactly those surfaces.
    Tests that are about announcement behaviour rather than about launch turn
    them off.
    """
    from superqode.app_main import SuperQodeApp

    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        if hasattr(SuperQodeApp, name):
            monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None, raising=False)


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _tree(root):
    """Build a project shaped like the ones that made the old walk expensive."""
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x")
    (root / "README.md").write_text("x")
    for ignored in ("node_modules", "__pycache__", ".venv", "venv"):
        directory = root / ignored
        directory.mkdir()
        (directory / "junk.py").write_text("x")
        nested = directory / "deep" / "deeper"
        nested.mkdir(parents=True)
        (nested / "more.py").write_text("x")
    hidden = root / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("x")
    return root


def test_the_file_walk_never_descends_into_ignored_directories(tmp_path, monkeypatch):
    """Pruning must happen during the walk, not after it.

    ``rglob("*")`` visited every ignored tree and discarded the results at the
    end: on the SuperQode repo that was 26,984 paths to keep 1,478.
    """
    from pathlib import Path

    root = _tree(tmp_path)
    visited: list[str] = []
    real_iterdir = Path.iterdir

    def counted(self):
        visited.append(self.name)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", counted)

    from superqode.sidebar import FileSearch

    panel = FileSearch.__new__(FileSearch)
    panel.root_path = root
    panel._all_files = []
    panel._files_loaded = False
    # The decorated worker is a Textual thread worker; call the function itself.
    FileSearch._load_files.__wrapped__(panel)

    names = {path.name for path in panel._all_files}
    assert names == {"app.py", "README.md"}
    for ignored in ("node_modules", "__pycache__", ".venv", "venv", ".git", "deep", "deeper"):
        assert ignored not in visited, f"walked into {ignored}"


def test_the_file_walk_still_honours_its_result_cap(tmp_path):
    from superqode.sidebar import FileSearch

    root = tmp_path
    (root / "many").mkdir()
    for index in range(5100):
        (root / "many" / f"f{index}.txt").write_text("")

    panel = FileSearch.__new__(FileSearch)
    panel.root_path = root
    panel._all_files = []
    panel._files_loaded = False
    FileSearch._load_files.__wrapped__(panel)

    assert panel._files_loaded is True
    assert len(panel._all_files) <= 5001


@pytest.mark.parametrize(
    "env, expect_output",
    [
        ({}, True),
        ({"NO_COLOR": "1"}, True),
        ({"SUPERQODE_NO_SPLASH": "1"}, False),
        ({"TERM": "dumb"}, True),
    ],
)
def test_the_launch_splash_respects_the_environment(env, expect_output, monkeypatch):
    """It fills the pre-paint gap, and gets out of the way when asked."""
    from superqode.app import _print_launch_splash

    for key in ("NO_COLOR", "SUPERQODE_NO_SPLASH", "TERM"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    stream = _FakeTTY()
    monkeypatch.setattr(sys, "stdout", stream)
    _print_launch_splash()
    written = stream.getvalue()

    assert bool(written) is expect_output
    if expect_output:
        assert "SuperQode" in written.replace("\033", "").replace("[0m", "") or "S" in written
    if env.get("NO_COLOR") or env.get("TERM") == "dumb":
        assert "\033[" not in written, "colour escaped a plain terminal"


def test_the_launch_splash_stays_silent_when_piped(monkeypatch):
    """Redirected output is someone else's data, not a place for decoration."""
    from superqode.app import _print_launch_splash

    monkeypatch.delenv("SUPERQODE_NO_SPLASH", raising=False)
    stream = io.StringIO()  # isatty() is False
    monkeypatch.setattr(sys, "stdout", stream)
    _print_launch_splash()
    assert stream.getvalue() == ""


def test_the_launch_splash_never_breaks_a_launch(monkeypatch):
    """A terminal that refuses to be written to must not stop the TUI."""
    from superqode.app import _print_launch_splash

    class Hostile(_FakeTTY):
        def write(self, _text):
            raise OSError("broken pipe")

    monkeypatch.delenv("SUPERQODE_NO_SPLASH", raising=False)
    monkeypatch.setattr(sys, "stdout", Hostile())
    _print_launch_splash()  # must not raise


async def test_the_catalog_chip_clears_only_after_the_last_refresh(monkeypatch):
    """Two refreshes run at launch; whichever finishes first must not clear it."""
    from superqode.app_main import SuperQodeApp
    from superqode.app.widgets import ColorfulStatusBar

    # The launch refreshes drive this same counter, so they are silenced to
    # leave the two below as the only ones in flight.
    _quiet_startup(monkeypatch)
    app = SuperQodeApp()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one("#status-bar", ColorfulStatusBar)

        app._begin_catalog_refresh("models")
        app._begin_catalog_refresh("agents")
        await pilot.pause()
        assert bar.catalog_state != ""

        app._end_catalog_refresh()
        await pilot.pause()
        assert bar.catalog_state != "", "the first refresh cleared the other's indicator"

        app._end_catalog_refresh()
        await pilot.pause()
        assert bar.catalog_state == ""


async def test_the_catalog_chip_reaches_the_status_row(monkeypatch):
    """A chip nobody can see is not an indicator."""
    _quiet_startup(monkeypatch)
    from superqode.app_main import SuperQodeApp
    from superqode.app.widgets import ColorfulStatusBar

    app = SuperQodeApp()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        bar.catalog_state = "agents"
        await pilot.pause()
        assert "agents" in bar._render_for_width(120).plain


def test_the_splash_costs_nothing_to_import():
    """It exists to cover a delay, so it must not import anything to draw."""
    import subprocess

    code = (
        "import sys; from superqode.app import _print_launch_splash;"
        "before=set(sys.modules);"
        "import io\n"
        "class T(io.StringIO):\n"
        "    def isatty(self): return True\n"
        "sys.stdout=T(); _print_launch_splash();"
        "sys.stdout=sys.__stdout__;"
        "print(sorted(set(sys.modules)-before-{'io'}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "SUPERQODE_NO_SPLASH": ""},
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("[]"), f"splash imported modules: {out.stdout}"


def test_animated_launch_splash_spins_and_clears_cleanly(monkeypatch):
    """Animated splash renders spinning frames and clears before Textual takes over."""
    import time

    from superqode.launch_splash import LaunchSplash

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("SUPERQODE_NO_SPLASH", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    stream = _FakeTTY()
    splash = LaunchSplash(stream=stream, interval=0.01)
    splash.start()
    time.sleep(0.05)
    splash.stop()

    written = stream.getvalue()
    assert "\033[?25l" in written  # hid cursor during animation
    assert written.endswith("\r\033[2K\033[?25h")  # cleared line and restored cursor
    assert "◇" in written and "◈" in written  # rendered multiple spinner frames


def test_animated_launch_splash_plain_mode_avoids_ansi(monkeypatch):
    from superqode.launch_splash import LaunchSplash

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("SUPERQODE_NO_SPLASH", raising=False)

    stream = _FakeTTY()
    splash = LaunchSplash(stream=stream, interval=0.01)
    splash.start()
    splash.stop()

    written = stream.getvalue()
    assert "SuperQode" in written
    assert "\033[" not in written


def test_undo_manager_load_deduplicates_path_validation(tmp_path, monkeypatch):
    """Repeated repository index entries across checkpoints validate once per unique path."""
    import subprocess
    from superqode.app.task_changes import TaskChanges
    from superqode.undo_manager import UndoManager

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text(f"v{i}\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)

    manager = UndoManager(tmp_path)
    assert manager.initialize()
    for step in range(4):
        task = TaskChanges(tmp_path).capture()
        manager.register_task(task, f"step-{step}")
        (tmp_path / "f0.txt").write_text(f"changed-{step}\n")
        task.finish([])
        manager.seal_task(task)

    calls = 0
    original_path = TaskChanges._path

    def counted_path(self, name):
        nonlocal calls
        calls += 1
        return original_path(self, name)

    monkeypatch.setattr(TaskChanges, "_path", counted_path)
    reloaded = UndoManager(tmp_path)
    assert reloaded.initialize()
    assert reloaded.can_undo()
    # 5 tracked files across 4 checkpoints should validate 5 times, not 20.
    assert calls == 5


def test_run_textual_app_wires_colormode_and_launch_splash(monkeypatch):
    """Regression test: run_textual_app must import colormode (_cube/color_mode) cleanly."""
    import superqode.app as app_pkg
    import superqode.app.colormode as colormode
    import superqode.app_main as app_main

    assert app_pkg._cube is colormode._cube
    assert app_pkg.color_mode is colormode.color_mode
    assert app_pkg.sgr_foreground is colormode.sgr_foreground

    events = []

    class _FakeApp:
        def __init__(self, **startup):
            events.append(("init", startup))

        def run(self):
            events.append(("run", None))

    monkeypatch.setattr(app_main, "SuperQodeApp", _FakeApp)
    monkeypatch.setattr(
        "superqode.app.herdr.close", lambda app: events.append(("close", type(app).__name__))
    )
    monkeypatch.setenv("SUPERQODE_NO_SPLASH", "1")

    app_pkg.run_textual_app(demo=True)

    assert events == [("init", {"demo": True}), ("run", None), ("close", "_FakeApp")]
