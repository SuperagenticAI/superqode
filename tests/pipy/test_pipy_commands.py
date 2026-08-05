"""The ``:pipy`` command surface.

These hold the typed surface to PiPy's ``SLASH_COMMANDS`` declaration, so a new
command cannot go missing from the TUI, the help text or the completions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.app.constants import COMMANDS
from superqode.app.mixins.pipy_commands import PiPyCommandMixin
from superqode.pipy.ai import FakeStream, text_response
from superqode.pipy.coding_session import SLASH_COMMANDS, CodingSessionOptions, PiPyCodingSession
from superqode.pipy.stream import Model

MODEL = Model(id="fake-1", provider="fake", api="fake-api")


class RecordingLog:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.rendered: list[object] = []

    def add_error(self, message):
        self.errors.append(str(message))

    def add_info(self, message):
        self.infos.append(str(message))

    def add_success(self, message):
        self.successes.append(str(message))

    def write(self, renderable):
        self.rendered.append(renderable)


class App(PiPyCommandMixin):
    """The mixin plus the two attributes it reads from the app."""

    def __init__(self, *, active: bool) -> None:
        self._active = active
        self.workers: list[object] = []

    def _pipy_is_active(self) -> bool:
        return self._active

    def run_worker(self, coro, **_kwargs):
        self.workers.append(coro)
        coro.close()


async def make_session(tmp_path: Path) -> PiPyCodingSession:
    return await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=FakeStream([text_response("ok")]),
            session_root=tmp_path / "sessions",
        )
    )


# -- the surface matches the declaration ------------------------------------- #


def test_every_declared_command_is_offered_for_completion():
    for command in SLASH_COMMANDS:
        assert f":pipy {command.name}" in COMMANDS, f":pipy {command.name} is not in the catalogue"
    assert ":pipy" in COMMANDS
    assert ":pipy help" in COMMANDS
    assert ":pi" in COMMANDS, "the :pi alias must complete too"


def test_help_lists_every_declared_command():
    from rich.console import Console

    app = App(active=True)
    log = RecordingLog()
    app._show_pipy_help(log)

    console = Console(width=100, force_terminal=False)
    with console.capture() as capture:
        console.print(log.rendered[-1])
    rendered = capture.get()

    for command in SLASH_COMMANDS:
        assert f":pipy {command.name}" in rendered
        assert command.summary in rendered


@pytest.mark.parametrize("name", [command.name for command in SLASH_COMMANDS])
async def test_every_declared_command_is_wired(name, tmp_path):
    """No command may reach the "declared but not wired" branch."""
    session = await make_session(tmp_path)
    log = RecordingLog()
    app = App(active=True)

    try:
        await app._pipy_dispatch(session, name, "", log)
    except Exception:
        # Failing without an argument is fine; falling through is not.
        pass

    assert not any("not wired" in message for message in log.errors)


# -- guards ------------------------------------------------------------------ #


def test_commands_are_refused_when_pipy_is_not_active():
    app = App(active=False)
    log = RecordingLog()
    app._pipy_cmd("session", log)

    assert any("not the active harness" in message for message in log.errors)
    assert app.workers == []


def test_unknown_subcommand_is_reported():
    app = App(active=True)
    log = RecordingLog()
    app._pipy_cmd("nonsense", log)

    assert any("Unknown PiPy command" in message for message in log.errors)
    assert app.workers == []


def test_a_command_taking_no_argument_rejects_one():
    app = App(active=True)
    log = RecordingLog()
    app._pipy_cmd("new extra-argument", log)

    assert any("takes no argument" in message for message in log.errors)


def test_bare_pi_shows_help():
    app = App(active=True)
    log = RecordingLog()
    app._pipy_cmd("", log)

    assert log.rendered, "bare :pi should render the catalog"


# -- behaviour ---------------------------------------------------------------- #


async def test_session_reports_id_and_path(tmp_path):
    session = await make_session(tmp_path)
    log = RecordingLog()

    await App(active=True)._pipy_dispatch(session, "session", "", log)

    assert any(str(session.session_path) in message for message in log.infos)
    assert any(message.startswith("id ") for message in log.infos)


async def test_name_renames_the_session(tmp_path):
    session = await make_session(tmp_path)
    log = RecordingLog()

    await App(active=True)._pipy_dispatch(session, "name", "the-refactor", log)

    assert (await session.info()).name == "the-refactor"
    assert any("the-refactor" in message for message in log.successes)


async def test_name_without_an_argument_is_refused(tmp_path):
    session = await make_session(tmp_path)
    log = RecordingLog()

    await App(active=True)._pipy_dispatch(session, "name", "", log)

    assert any("needs a name" in message for message in log.errors)


async def test_export_writes_markdown_beside_the_session(tmp_path):
    """Never into the working directory: that is the user's repository."""
    session = await make_session(tmp_path)
    log = RecordingLog()

    await App(active=True)._pipy_dispatch(session, "export", "", log)

    written = Path(session.session_path).with_suffix(".md")
    assert written.is_file()
    assert list(tmp_path.glob("*.md")) == [], "export leaked into the working directory"
    assert any(str(written) in message for message in log.successes)


async def test_fork_leaves_the_source_untouched(tmp_path):
    session = await make_session(tmp_path)
    log = RecordingLog()
    before = session.session_path

    await App(active=True)._pipy_dispatch(session, "fork", "", log)

    assert before.is_file()
    assert any("untouched" in message for message in log.infos)
