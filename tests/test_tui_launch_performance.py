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
