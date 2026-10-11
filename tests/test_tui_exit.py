"""Exit/command routing must win over picker selection on Enter.

Regression: from inside a local-provider picker (LM Studio / MLX / Ollama),
typing ``:exit`` and pressing Enter was swallowed by the picker (it confirmed
the highlighted item) so the user could never leave the TUI.
"""

from superqode.app_main import SelectionAwareInput

import asyncio
import errno
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

# Call the method unbound with lightweight stand-ins; it only reads
# ``self.value`` and attributes off ``app``.
_handle = SelectionAwareInput._handle_selection_enter


class _Stub:
    """Stands in for the input widget; ``value`` is the typed text."""

    def __init__(self, value):
        self.value = value


class _App:
    """Stands in for the app; selection flags + the highlighted-select action."""

    def __init__(self, **flags):
        self.selected = False
        for k, v in flags.items():
            setattr(self, k, v)

    def action_select_highlighted_local_model(self):
        self.selected = True


def test_command_prefixes_bypass_picker_selection():
    # In a local-model picker, a typed command/shell line must NOT select the
    # highlighted item — it must fall through to be submitted as a command.
    app = _App(_awaiting_local_model=True)
    for typed in (":exit", ":quit", ":q", ":home", "/help", "!ls", "  :exit  "):
        assert _handle(_Stub(typed), app) is False, typed
    assert app.selected is False


def test_empty_enter_still_selects_highlighted():
    # Empty Enter inside a picker confirms the highlighted item (unchanged).
    app = _App(_awaiting_local_model=True)
    assert _handle(_Stub(""), app) is True
    assert app.selected is True


def test_plain_text_still_selects_highlighted():
    # A non-command line (e.g. a typed model name) keeps the old behaviour.
    app = _App(_awaiting_local_model=True)
    assert _handle(_Stub("qwen3"), app) is True
    assert app.selected is True


def test_command_bypasses_even_with_no_active_picker():
    # No picker active: a command line is not consumed as a selection.
    assert _handle(_Stub(":exit"), _App()) is False


def test_digit_inside_command_is_not_buffered_as_model_selection():
    """The ``4`` in ``:local stop ds4`` must remain command text."""

    class _InputStub:
        value = ":local stop ds"

        def __init__(self, app):
            self.app = app

        def _is_newline_key(self, event):
            return False

    class _KeyEvent:
        key = "4"
        aliases = ["4"]

        def stop(self):
            raise AssertionError("command digit must not be consumed")

        def prevent_default(self):
            raise AssertionError("command digit must remain normal input")

    app = _App(_awaiting_local_model=True)
    app._queue_selection_digit = lambda digit: (_ for _ in ()).throw(
        AssertionError(f"command digit was buffered: {digit}")
    )

    SelectionAwareInput.on_key(_InputStub(app), _KeyEvent())


@pytest.mark.skipif(os.name != "posix", reason="POSIX input driver")
@pytest.mark.parametrize("failure", [None, errno.EIO, errno.EBADF])
def test_terminal_input_loss_requests_app_exit_without_spinning(monkeypatch, failure):
    from superqode.theming import terminal

    monkeypatch.delenv("TEXTUAL_DRIVER", raising=False)
    monkeypatch.setattr(terminal.sys.stdin, "isatty", lambda: False)
    driver_class = terminal.terminal_driver()
    assert driver_class is not None  # Pipes need the EOF-safe driver too.
    messages = []
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    reads = []
    original_read = os.read

    def read(fd, size):
        if fd == read_fd:
            reads.append(fd)
            if failure is not None:
                raise OSError(failure, "Terminal closed")
        return original_read(fd, size)

    monkeypatch.setattr(terminal.os, "read", read)

    class Probe(driver_class):
        def __init__(self):
            self.fileno = read_fd
            self._debug = False
            self.exit_event = threading.Event()

        def send_message(self, message):
            messages.append(message)

    try:
        Probe().run_input_thread()
    finally:
        os.close(read_fd)
    assert len(reads) == 1
    assert len(messages) == 1 and isinstance(messages[0], terminal.TerminalInputClosed)


def test_explicit_web_driver_is_preserved(monkeypatch):
    from superqode.theming import terminal

    monkeypatch.setenv("TEXTUAL_DRIVER", "textual.drivers.web_driver:WebDriver")
    assert terminal.terminal_driver() is None


async def test_app_exit_cleans_up_runtime_and_animation_once(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.theming.terminal import TerminalInputClosed

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
    app = SuperQodeApp()
    calls = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=False),
            cancel=lambda: calls.append("cancel"),
            disconnect=lambda: calls.append("disconnect"),
        )
        app.post_message(TerminalInputClosed())
        await asyncio.sleep(0.1)
        assert app._exit  # The input-loss message must invoke App.exit().
    assert calls == ["cancel", "disconnect"]
    assert not app.animation_manager.is_running
    app._cleanup_on_exit()
    assert calls == ["cancel", "disconnect"]
