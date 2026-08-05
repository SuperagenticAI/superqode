"""Click-to-run for the persistent chrome, and the guard on a live run."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from superqode.app.mixins.clickable_commands import (
    CLICKABLE_COMMANDS,
    CONFIRM_WHILE_BUSY,
    ClickableCommandMixin,
    command_link,
)
from superqode.app.prompt_stack import PromptStack
from superqode.app.widgets import HintsBar


class FakeLog:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.written: list[object] = []

    def add_info(self, message):
        self.infos.append(str(message))

    def write(self, renderable):
        self.written.append(renderable)


class App(ClickableCommandMixin):
    def __init__(self, *, busy: bool = False) -> None:
        self.is_busy = busy
        self.commands: list[str] = []
        self.log = FakeLog()
        self._prompts = PromptStack()

    def _clicked_command_log(self):
        return self.log

    def _handle_command(self, command, log):
        self.commands.append(command)


def test_link_targets_carry_the_command():
    assert command_link("disconnect") == "link superqode://cmd/disconnect"


def test_an_idle_click_runs_the_command():
    app = App()
    app._run_clicked_command("disconnect")

    assert app.commands == [":disconnect"]
    assert app._prompts.active is None


def test_a_leading_colon_is_accepted():
    app = App()
    app._run_clicked_command(":connect")

    assert app.commands == [":connect"]


def test_an_unknown_command_is_ignored():
    """The link scheme must not become a way to run anything at all."""
    app = App()
    app._run_clicked_command("eval")

    assert app.commands == []
    assert app._prompts.active is None, "an unknown command must not open a prompt"


@pytest.mark.parametrize("command", sorted(CONFIRM_WHILE_BUSY))
def test_a_click_during_a_run_asks_first(command):
    app = App(busy=True)
    app._run_clicked_command(command)

    assert app.commands == [], "the command ran without asking"
    assert app._prompts.is_active("clicked_command_confirm")
    assert app.log.written, "the confirmation was not shown"


def test_confirming_runs_the_command():
    app = App(busy=True)
    app._run_clicked_command("disconnect")

    spec = app._prompts.active
    spec.on_select(("run", "Yes", ""))

    assert app.commands == [":disconnect"]
    assert app._prompts.active is None


def test_declining_leaves_the_run_alone():
    app = App(busy=True)
    app._run_clicked_command("disconnect")

    spec = app._prompts.active
    spec.on_select(("keep", "No", ""))

    assert app.commands == []
    assert app._prompts.active is None
    assert any("Left the run alone" in message for message in app.log.infos)


def test_a_command_not_marked_for_confirmation_runs_while_busy():
    app = App(busy=True)
    app._run_clicked_command("help")

    assert app.commands == [":help"]


# -- the hints bar ----------------------------------------------------------- #


def test_the_hints_bar_carries_the_connection_slot():
    """Within reach of the prompt, where a new user is already looking."""
    bar = HintsBar()

    bar.connected = False
    assert ":connect" in bar.render().plain
    bar.connected = True
    assert ":disconnect" in bar.render().plain


def test_hint_entries_are_clickable():
    rendered = HintsBar().render()

    links = {span.style for span in rendered.spans if "superqode://cmd/" in str(span.style)}
    assert any("home" in str(style) for style in links)
    for command in (":home", ":help"):
        assert command in rendered.plain


def test_only_allowlisted_hints_are_clickable():
    bar = HintsBar()
    rendered = bar.render()

    linked = {
        str(span.style).rsplit("/", 1)[-1]
        for span in rendered.spans
        if "superqode://cmd/" in str(span.style)
    }
    assert linked <= CLICKABLE_COMMANDS


# -- the status bar button --------------------------------------------------- #


def _bar(**kwargs):
    from superqode.app.widgets import ColorfulStatusBar

    bar = ColorfulStatusBar()
    for key, value in kwargs.items():
        setattr(bar, key, value)
    return bar


def test_the_button_offers_connect_when_nothing_is_connected():
    rendered = _bar(interaction_mode="build")._render_for_width(120)

    assert "Connect" in rendered.plain
    assert "Disconnect" not in rendered.plain
    assert any("cmd/connect" in str(span.style) for span in rendered.spans)


def test_the_button_offers_disconnect_once_connected():
    rendered = _bar(
        byok_provider="openai", byok_model="gpt-4o", interaction_mode="build"
    )._render_for_width(120)

    assert "Disconnect" in rendered.plain
    assert any("cmd/disconnect" in str(span.style) for span in rendered.spans)


def test_the_controls_sit_beside_the_identity():
    rendered = _bar(
        byok_provider="openai", byok_model="gpt-4o", interaction_mode="build"
    )._render_for_width(120)

    # Identity keeps the corner; the controls sit beside it, still on the left.
    assert rendered.plain.startswith("SuperQode")
    assert "[⏏ Disconnect] [⏻ Exit]" in rendered.plain
    assert rendered.plain.index("[⏏") < rendered.plain.index("openai")


@pytest.mark.parametrize("width", [60, 72, 90, 100, 110, 115, 120, 140, 200])
def test_the_button_never_widens_the_row_past_the_terminal(width):
    """A crowded bar drops the label, then the button, rather than wrapping."""
    crowded = _bar(
        byok_provider="anthropic",
        byok_model="claude-opus-4-20250514",
        active_harness="workbench",
        interaction_mode="build",
        context_used=98000,
        context_window=200000,
        byok_cost=1.23,
    )
    plain = crowded._render_for_width(width).plain
    # The bar has a pre-existing overflow with long model names at narrow
    # widths. What this guards is that the button never adds to it: wherever
    # the row fit without a button, it still fits with one.
    without_button = plain.split(" [")[0].rstrip(" │")
    if cell_len(without_button) <= width:
        assert cell_len(plain) <= width, f"controls pushed the row past {width}"


def test_exit_does_not_ask_when_nothing_is_running():
    """The prompt claims a run is in progress, so it must not appear idle."""
    app = App(busy=False)
    app._run_clicked_command("exit")

    assert app.commands == [":exit"]
    assert app._prompts.active is None


def test_exit_asks_while_a_run_is_in_flight():
    app = App(busy=True)
    app._run_clicked_command("exit")

    assert app.commands == []
    assert app._prompts.is_active("clicked_command_confirm")

    app._prompts.active.on_select(("run", "Yes", ""))
    assert app.commands == [":exit"]


def test_exit_is_clickable_and_guarded_only_while_busy():
    assert "exit" in CLICKABLE_COMMANDS
    assert "exit" in CONFIRM_WHILE_BUSY


@pytest.mark.parametrize("command", sorted(CLICKABLE_COMMANDS))
def test_no_command_ever_asks_when_idle(command):
    """Nothing may show the in-progress prompt with no run to lose."""
    app = App(busy=False)
    app._run_clicked_command(command)

    assert app._prompts.active is None, f":{command} asked while idle"
    if command == "back":
        # Navigation, handled by the history rather than the command dispatch.
        assert app.commands == []
    else:
        assert app.commands == [f":{command}"]


def test_the_exit_button_is_offered_and_clickable():
    rendered = _bar(
        byok_provider="openai", byok_model="gpt-4o", interaction_mode="build"
    )._render_for_width(120)

    assert "Exit" in rendered.plain
    assert any("cmd/exit" in str(span.style) for span in rendered.spans)


def test_no_control_is_filled_with_a_reverse_block():
    """Reverse video reads as an alert; these are labels and controls."""
    rendered = _bar(
        byok_provider="openai",
        byok_model="gpt-4o",
        interaction_mode="build",
        vim_state="normal",
    )._render_for_width(120)

    assert not any("reverse" in str(span.style) for span in rendered.spans)


def test_a_row_too_tight_for_the_session_control_drops_exit_too():
    """Exit must never be the lone survivor of a crowded row."""
    crowded = _bar(
        byok_provider="anthropic",
        byok_model="claude-opus-4-20250514",
        active_harness="workbench",
        interaction_mode="build",
        context_used=98000,
        context_window=200000,
        byok_cost=1.23,
    )
    for width in range(60, 200):
        plain = crowded._render_for_width(width).plain
        if "Exit" in plain or "[⏻]" in plain:
            assert "⏏" in plain or "🔌" in plain, f"exit survived alone at width {width}"


# -- picker rows ------------------------------------------------------------- #


def _picker(menu: str, width: int = 110):
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, "tests")
    from test_tui_smoke import FakeLog, make_app

    app = make_app()
    log = FakeLog()
    log.content_size = SimpleNamespace(width=width)
    app._scroll_to_highlighted_item = lambda *a, **k: None
    app.query_one = lambda *a, **k: log
    app._show_connect_type_picker(log, menu=menu)
    return log.items[-1]


def _click_targets(rendered, number: str):
    return [
        rendered.plain[span.start : span.end].strip()
        for span in rendered.spans
        if str(span.style).endswith(f"pick/{number}")
    ]


def test_a_whole_picker_row_is_clickable_not_only_its_number():
    """A mouse user aims at the name, not the bracketed digit."""
    rendered = _picker("agents")
    targets = _click_targets(rendered, "2")

    assert any("[2]" in target for target in targets)
    assert any("ACP agents" == target for target in targets)
    assert any("OpenCode" in target for target in targets)


def test_the_footer_says_rows_can_be_clicked():
    assert "click or type a number" in _picker("agents").plain


def test_a_long_list_gives_every_row_the_same_height():
    """Twelve wrapped paragraphs is a wall. Only the active row expands."""
    rendered = _picker("vendors", width=120)
    lines = rendered.plain.splitlines()

    # "○" is an unhighlighted row. The highlighted one is allowed to be taller:
    # it is the only row spending lines on badges and hints.
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith("○ [")]
    heights = [b - a for a, b in zip(starts, starts[1:])]

    assert len(starts) >= 10, "expected a long list to measure"
    assert set(heights) == {2}, f"unhighlighted rows vary in height: {sorted(set(heights))}"


def test_the_highlighted_row_still_shows_its_full_description():
    rendered = _picker("vendors", width=120)

    assert "Drive OpenAI Codex with your ChatGPT/Codex login" in rendered.plain
    assert "…" in rendered.plain, "long descriptions on other rows should be shortened"


# -- the back control -------------------------------------------------------- #


def test_the_back_button_appears_only_with_somewhere_to_go():
    bar = _bar(interaction_mode="build")

    assert "Back" not in bar._render_for_width(120).plain

    bar.can_go_back = True
    rendered = bar._render_for_width(120)
    assert "← Back" in rendered.plain
    assert any("cmd/back" in str(span.style) for span in rendered.spans)


def test_clicking_back_walks_the_history():
    app = App()
    seen: list[str] = []
    for key in ("root", "agents"):
        app._record_screen(key, key, lambda k=key: seen.append(k))

    app._run_clicked_command("back")

    assert seen == ["root"]
    assert app.commands == [], "back is navigation, not a slash command"


def test_back_with_no_history_says_so_rather_than_failing():
    app = App()
    app._run_clicked_command("back")

    assert any("Nothing to go back to" in message for message in app.log.infos)


def test_connect_screens_are_recorded_as_they_are_drawn():
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, "tests")
    from test_tui_smoke import FakeLog, make_app

    app = make_app()
    log = FakeLog()
    log.content_size = SimpleNamespace(width=100)
    app._scroll_to_highlighted_item = lambda *a, **k: None
    app.query_one = lambda *a, **k: log

    for menu in (None, "agents", "vendors"):
        app._show_connect_type_picker(log, menu=menu)

    assert [screen.label for screen in app._history._stack] == [
        "Connect",
        "Existing harnesses",
        "Subscriptions",
    ]
    assert app._navigate_back() is True
    assert app._history.previous_label == "Connect"
