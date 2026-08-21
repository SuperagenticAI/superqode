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
    """The link scheme must not become a way to run anything at all.

    The example is derived rather than hardcoded: a literal went stale twice
    when the command it named was later added to the allowlist, and the test
    kept passing for the wrong reason.
    """
    from superqode.app.constants import COMMANDS

    outsider = next(
        command.lstrip(":")
        for command in COMMANDS
        if command.startswith(":")
        and " " not in command
        and command.lstrip(":") not in CLICKABLE_COMMANDS
    )

    app = App()
    app._run_clicked_command(outsider)

    assert app.commands == [], f":{outsider} should not be reachable by a click"
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
    assert ":hub" in bar.render().plain
    bar.connected = True
    assert ":disconnect" in bar.render().plain
    assert ":hub" in bar.render().plain


def test_hint_entries_are_clickable():
    rendered = HintsBar().render()

    links = {span.style for span in rendered.spans if "superqode://cmd/" in str(span.style)}
    assert any("home" in str(style) for style in links)
    for command in (":home", ":hub", ":help"):
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
    assert "[⏏ Disconnect] [⚓ Hub] [⏻ Exit]" in rendered.plain
    assert rendered.plain.index("[⏏") < rendered.plain.index("openai")


def test_the_hub_is_a_permanent_top_level_control():
    rendered = _bar(interaction_mode="build")._render_for_width(120)

    assert "[⚓ Hub]" in rendered.plain
    assert any("cmd/hub" in str(span.style) for span in rendered.spans)
    assert rendered.plain.index("Connect") < rendered.plain.index("Hub")
    assert rendered.plain.index("Hub") < rendered.plain.index("Exit")


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


def test_picker_rows_do_not_emit_osc8_pick_links():
    """OSC-8 pick URLs make the terminal show a ⌘-click tooltip over the list."""
    rendered = _picker("agents")

    assert _click_targets(rendered, "1") == []
    assert _click_targets(rendered, "2") == []
    # v2 splits the old "Other harnesses" row and shortens "ACP agents" to "ACP".
    assert "Open harnesses" in rendered.plain
    assert "Closed harnesses" in rendered.plain


def test_descriptions_carry_no_link_style():
    """Prose must not be a link span: terminals decorate OSC-8 themselves.

    A link across a wrapped paragraph renders as an underlined, recoloured
    block in most terminals, which turned a thirteen-row screen into a wall.
    Clicks on these lines still select the row, resolved by position in
    _click_selects_picker_row rather than by a style under the pointer.
    """
    rendered = _picker("agents")
    targets = _click_targets(rendered, "2")

    assert targets == []
    assert "OpenCode" in rendered.plain  # still shown, just not linked


def test_a_click_on_a_description_still_selects_its_row():
    """The row stays clickable across its full height, link or no link."""
    import re

    from superqode.app.mixins.pickers import PickerNavigationMixin

    rendered = _picker("vendors", width=120)
    lines = rendered.plain.splitlines()

    row_index = next(i for i, line in enumerate(lines) if line.lstrip().startswith("○ ["))
    description_index = row_index + 1
    assert not PickerNavigationMixin._PICKER_ROW.match(lines[description_index])

    # Walking up from the description reaches its own header line.
    for cursor in range(description_index, -1, -1):
        match = PickerNavigationMixin._PICKER_ROW.match(lines[cursor])
        if match:
            break
    assert cursor == row_index
    assert match.group(1) == re.match(r"\s*○ \[\s*(\d+)", lines[row_index]).group(1)


def test_the_footer_does_not_advertise_a_click_link():
    footer = _picker("agents").plain

    assert "or type a number" in footer
    assert "click ↗" not in footer


def test_every_row_carries_a_clickable_arrow():
    """The dot alone read as a bullet, so nothing said "click me".

    The arrow sits at the end of the label. It is a visual mark only — not an
    OSC-8 link — so the terminal does not pop a ⌘-click tooltip over the list.
    """
    import re

    rendered = _picker("vendors", width=120)
    rows = [line for line in rendered.plain.splitlines() if re.match(r"\s*[●○]\s+\[\s*\d+\]", line)]

    assert len(rows) >= 10, "expected a long list to measure"
    # The arrow closes the label on every row, before any trailing marker.
    assert all(re.search(r"↗(\s|$)", line) for line in rows)
    assert _click_targets(rendered, "2") == []


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


# -- the connected hint set -------------------------------------------------- #


def _hints(connected: bool, width: int = 120):
    from unittest.mock import PropertyMock, patch

    from textual.geometry import Size

    bar = HintsBar()
    bar.connected = connected
    with patch.object(type(bar), "size", PropertyMock(return_value=Size(width, 1))):
        return bar.render()


def test_capability_commands_appear_only_once_connected():
    """Evaluating and optimising mean nothing before a session exists."""
    idle = _hints(False).plain
    for command in (":memory", ":eval", ":skills", ":harness"):
        assert command not in idle, f"{command} offered before connecting"

    working = _hints(True).plain
    for command in (":memory", ":eval", ":skills", ":harness"):
        assert command in working, f"{command} missing once connected"


def test_the_connected_bar_still_offers_the_way_out():
    plain = _hints(True).plain

    assert ":disconnect" in plain
    assert ":connect" not in plain.replace(":disconnect", "")


def test_every_connected_hint_is_clickable():
    rendered = _hints(True)
    linked = {
        str(span.style).rsplit("/", 1)[-1]
        for span in rendered.spans
        if "superqode://cmd/" in str(span.style)
    }
    shown = {word.lstrip(":") for word in rendered.plain.split() if word.startswith(":")}

    assert shown <= linked, f"not clickable: {sorted(shown - linked)}"
    assert shown <= CLICKABLE_COMMANDS


@pytest.mark.parametrize("width", [50, 60, 70, 80, 100, 120, 200])
def test_the_bar_never_outgrows_the_terminal(width):
    """A wrapped hints bar costs a row of the transcript."""
    rendered = _hints(True, width=width)

    assert cell_len(rendered.plain) <= width, f"hints bar overflowed {width}"
    # Whatever is dropped, the way out and the way to help survive.
    assert ":disconnect" in rendered.plain
    assert ":help" in rendered.plain


# -- the link convention ----------------------------------------------------- #
#
# Underline means clickable. Colour keeps meaning state, so a link that also
# carries state (ready, destructive) keeps its colour and relies on the
# underline alone; a link with no state takes THEME["link"].


def _underlined(rendered):
    return {
        rendered.plain[span.start : span.end].strip()
        for span in rendered.spans
        if "underline" in str(span.style)
    }


def _clickable(rendered):
    return {
        rendered.plain[span.start : span.end].strip()
        for span in rendered.spans
        if "superqode://" in str(span.style)
    }


def _renderings():
    """One of every surface that draws click targets."""
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, "tests")
    from test_tui_smoke import FakeLog, make_app

    from superqode.app.widgets import ColorfulStatusBar

    idle = HintsBar()
    idle.connected = False
    working = HintsBar()
    working.connected = True

    status = ColorfulStatusBar()
    status.byok_provider = "openai"
    status.byok_model = "gpt-4o"
    status.interaction_mode = "build"
    status.can_go_back = True

    surfaces = {
        "hints idle": idle.render(),
        "hints connected": working.render(),
        "status bar": status._render_for_width(120),
    }
    for menu in ("root", "vendors"):
        app = make_app()
        log = FakeLog()
        log.content_size = SimpleNamespace(width=110)
        app._scroll_to_highlighted_item = lambda *a, **k: None
        app.query_one = lambda *a, **k: log
        app._show_connect_type_picker(log, menu=menu)
        surfaces[f"picker {menu}"] = log.items[-1]
    return surfaces


def test_nothing_is_underlined():
    """Underline was tried and rejected: it read as a rule across the row."""
    for name, rendered in _renderings().items():
        assert not _underlined(rendered), f"{name}: underline is back"


def test_every_surface_offers_something_clickable():
    for name, rendered in _renderings().items():
        if name.startswith("picker "):
            # Picker rows stay clickable by position. They must not emit
            # OSC-8 pick URLs — those pop a ⌘-click tooltip over the list.
            assert "↗" in rendered.plain, f"{name}: no row arrow"
            assert _clickable(rendered) == set()
            continue
        assert _clickable(rendered), f"{name}: nothing clickable at all"


def test_the_link_colour_is_distinct_from_the_action_colours():
    """It may share the brand purple, but never a colour that means an outcome."""
    from superqode.app.constants import THEME

    for state in ("success", "error", "warning", "pink", "gold"):
        assert THEME["link"] != THEME[state], f"link colour collides with {state}"


def test_a_link_carrying_state_keeps_its_state_colour():
    """Disconnect stays destructive-coloured rather than becoming a plain link."""
    from superqode.app.constants import THEME

    bar = HintsBar()
    bar.connected = True
    rendered = bar.render()

    styles = {
        rendered.plain[span.start : span.end].strip(): str(span.style)
        for span in rendered.spans
        if "superqode://" in str(span.style)
    }
    assert THEME["pink"] in styles[":disconnect"]
    assert THEME["link"] in styles[":memory"]
