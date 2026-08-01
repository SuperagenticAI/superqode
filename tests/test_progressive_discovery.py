"""Tests for the discovery surfaces: milestones, ``:tour``, and harness import.

These cover the machinery that decides what a user is shown next. The point of
each is that the product reports what actually happened on this machine rather
than replaying a scripted introduction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.app.mixins.build_harness import (
    HARNESS_OUTPUT_DIR,
    BuildHarnessMixin,
    discover_importable,
)
from superqode.app.mixins.tour import TOUR_STEPS, TourMixin, tour_state
from superqode.app.progress import (
    HINTS,
    MILESTONES,
    load_progress,
    mark_hint_shown,
    next_hint,
    progress_path,
    record_milestone,
)


class FakeLog:
    """Minimal stand-in for ConversationLog: records what was written."""

    def __init__(self):
        self.items = []

    def write(self, value):
        self.items.append(value.plain if hasattr(value, "plain") else str(value))

    #: Renderers set this while writing, so it has to be assignable.
    auto_scroll = True

    def clear(self):
        pass

    def scroll_home(self, *args, **kwargs):
        pass

    def add_error(self, message):
        self.items.append(f"ERROR {message}")

    def add_info(self, message):
        self.items.append(f"INFO {message}")


# --- milestones and hints -----------------------------------------------------


def test_progress_is_written_where_the_override_points():
    """The override is what keeps automation out of a developer's own state."""
    record_milestone("connected")

    assert progress_path().exists()
    assert "connected" in load_progress().milestones
    # The autouse fixture points this at a tmp directory, so a real home path
    # here would mean the isolation is not working.
    assert Path.home() not in progress_path().parents


def test_a_hint_is_shown_once_and_never_again():
    """Repeating a suggestion the user already dismissed is nagging, not help."""
    record_milestone("task_completed")
    first = next_hint()

    assert first is not None and first.id == "memory"

    mark_hint_shown(first.id)
    second = next_hint()
    assert second is None or second.id != "memory"


def test_a_hint_stays_hidden_until_its_milestone_lands():
    """Suggesting :eval to somebody who has not connected teaches nothing."""
    assert next_hint() is None

    record_milestone("connected")
    assert next_hint() is None  # "connected" alone unlocks no hint


def test_a_milestone_makes_its_hint_redundant():
    """Somebody who already used memory should not be told memory exists."""
    record_milestone("task_completed")
    record_milestone("used_memory")

    hint = next_hint()
    assert hint is None or hint.id != "memory"


def test_every_hint_depends_on_declared_milestones():
    """A hint gated on a typo would never fire, and nothing would report it."""
    for hint in HINTS:
        assert set(hint.requires) <= set(MILESTONES), hint.id
        assert set(hint.blocked_by) <= set(MILESTONES), hint.id


# --- the tour -----------------------------------------------------------------


def test_every_tour_step_is_gated_on_a_real_milestone():
    assert [step.milestone for step in TOUR_STEPS if step.milestone not in MILESTONES] == []


def test_tour_marks_rungs_as_the_user_actually_climbs_them():
    done, current = tour_state(set())
    assert done == [False] * len(TOUR_STEPS)
    assert current == 0

    done, current = tour_state({"connected"})
    assert done[0] is True
    assert current == 1

    done, current = tour_state({step.milestone for step in TOUR_STEPS})
    assert all(done)
    assert current == len(TOUR_STEPS)


class _TourStub(TourMixin):
    def __init__(self):
        self.milestones = set()
        self.commands = []

    def _record_milestone(self, name):
        self.milestones.add(name)

    def _handle_command(self, command, log):
        self.commands.append(command)


def test_tour_renders_the_ladder_and_records_the_visit():
    stub, log = _TourStub(), FakeLog()
    stub._tour_cmd("", log)

    rendered = log.items[-1]
    for step in TOUR_STEPS:
        assert step.title in rendered
    assert "toured" in stub.milestones


def test_tour_next_runs_the_current_step():
    stub, log = _TourStub(), FakeLog()
    stub._tour_cmd("next", log)

    assert stub.commands == [":connect"]


def test_tour_next_on_a_typing_step_explains_instead_of_running():
    """Step two has no command, so "next" must not silently do nothing."""
    record_milestone("connected")
    stub, log = _TourStub(), FakeLog()
    stub._tour_cmd("next", log)

    assert stub.commands == []
    assert "type your request" in log.items[-1]


@pytest.mark.parametrize("argument,expected", [("6", "Own the harness"), ("eval", "Measure it")])
def test_tour_can_open_one_rung_without_running_it(argument, expected):
    stub, log = _TourStub(), FakeLog()
    stub._tour_cmd(argument, log)

    assert expected in log.items[-1]
    assert stub.commands == []


# --- building a harness from what the repository already has -------------------


class _BuildStub(BuildHarnessMixin):
    def __init__(self):
        self.milestones = []

    def _record_milestone(self, name):
        self.milestones.append(name)


def test_discover_importable_finds_existing_agent_config(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Run the tests.\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("Never push.\n", encoding="utf-8")
    (tmp_path / "empty.md").write_text("", encoding="utf-8")

    found = discover_importable(tmp_path)

    assert [label for _path, label, _kind in found] == [
        "AGENTS.md",
        "Claude Code project instructions",
    ]


def test_import_turns_repository_instructions_into_an_owned_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Always run pytest first.\n", encoding="utf-8")

    stub, log = _BuildStub(), FakeLog()
    stub._harness_import_picker(log)
    assert stub._awaiting_harness_import is True

    stub._import_harness_selection(0, log)

    written = list((tmp_path / HARNESS_OUTPUT_DIR).glob("*.yaml"))
    assert len(written) == 1

    from superqode.harness.loader import load_harness_spec

    spec = load_harness_spec(written[0])
    # The instructions have to survive the import, or the harness is not the
    # one the repository was already describing.
    assert "Always run pytest first." in spec.agents[0].system_prompt
    assert spec.metadata["built_with"] == "connect import"
    assert stub.milestones == ["built_harness"]


def test_import_screen_points_somewhere_when_there_is_nothing_to_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stub, log = _BuildStub(), FakeLog()

    stub._harness_import_picker(log)

    assert ":connect build-preset" in log.items[-1]
    assert getattr(stub, "_awaiting_harness_import", False) is False


def test_preset_clone_lands_in_the_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stub, log = _BuildStub(), FakeLog()

    stub._show_harness_preset_picker(log)
    stub._clone_harness_preset(0, log)

    template_id = stub._harness_preset_list[0][0]
    assert (tmp_path / HARNESS_OUTPUT_DIR / f"{template_id}.yaml").exists()
    assert stub.milestones == ["built_harness"]


def test_blank_scaffold_never_overwrites_an_existing_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stub, log = _BuildStub(), FakeLog()

    stub._scaffold_blank_harness(log)
    original = (tmp_path / "harness.yaml").read_text(encoding="utf-8")

    stub._scaffold_blank_harness(log)

    assert "already exists" in log.items[-1]
    assert (tmp_path / "harness.yaml").read_text(encoding="utf-8") == original


# --- picking from the build screens ------------------------------------------


class _PickerStub(_BuildStub):
    """Enough of the app to drive number selection into the build pickers."""

    def __init__(self):
        super().__init__()
        self._log = FakeLog()
        self._prompts = None

    def query_one(self, *args, **kwargs):
        return self._log


def _number_selector(stub):
    from superqode.app.mixins.pickers import PickerNavigationMixin

    return lambda num: PickerNavigationMixin._select_by_number_universal(stub, num)


def test_typing_a_number_picks_a_preset(tmp_path, monkeypatch):
    """Arrow keys reached these screens; typing a number did nothing at all."""
    monkeypatch.chdir(tmp_path)
    stub = _PickerStub()
    stub._show_harness_preset_picker(stub._log)

    assert _number_selector(stub)(9) is True
    assert stub.milestones == ["built_harness"]
    written = list((tmp_path / HARNESS_OUTPUT_DIR).glob("*.yaml"))
    assert written


def test_typing_a_number_picks_an_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Run the tests.\n", encoding="utf-8")
    stub = _PickerStub()
    stub._harness_import_picker(stub._log)

    assert _number_selector(stub)(1) is True
    assert stub.milestones == ["built_harness"]


def test_an_out_of_range_number_is_refused_rather_than_guessed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stub = _PickerStub()
    stub._show_harness_preset_picker(stub._log)

    assert _number_selector(stub)(99) is False
    assert stub.milestones == []


def test_a_preset_with_no_tools_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stub, log = _BuildStub(), FakeLog()
    stub._show_harness_preset_picker(log)
    index = next(i for i, (name, _d) in enumerate(stub._harness_preset_list) if name == "no-tool")
    stub._clone_harness_preset(index, log)

    assert "not change it" in log.items[-1]


# --- every screen answers the same four inputs --------------------------------


def test_the_screens_i_added_answer_every_selection_path():
    """Arrows, a typed number, number+Enter and Esc.

    Two of these screens shipped answering only arrows, which is why picking a
    preset by number did nothing. This is the contract, checked at the wiring
    rather than per screen.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "superqode"

    def flags(path):
        return set(re.findall(r"_awaiting_[a-z_]+", path.read_text(encoding="utf-8")))

    app_main = src / "app_main.py"
    keys = flags(app_main)
    numbers = flags(src / "app" / "mixins" / "pickers.py")
    enter = flags(src / "app" / "mixins" / "events.py")
    escape = set(
        re.findall(
            r"_awaiting_[a-z_]+",
            app_main.read_text(encoding="utf-8").split("def action_smart_cancel")[1],
        )
    )

    for flag in ("_awaiting_explore", "_awaiting_harness_import", "_awaiting_harness_preset"):
        assert flag in keys, f"{flag}: no arrow-key handling"
        assert flag in numbers, f"{flag}: typing a number does nothing"
        assert flag in enter, f"{flag}: number then Enter does nothing"
        assert flag in escape, f"{flag}: Esc leaves the user on a dead screen"


def test_escape_from_a_build_screen_returns_to_the_build_menu(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from superqode.app_main import SuperQodeApp

    class EscStub:
        _awaiting_harness_preset = True
        _prompts = None

        def __init__(self):
            self.menus = []
            self._log = FakeLog()

        def query_one(self, *args, **kwargs):
            return self._log

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu)

    stub = EscStub()
    SuperQodeApp.action_smart_cancel(stub)

    assert stub._awaiting_harness_preset is False
    assert stub.menus == ["build"]


def test_explore_opens_a_category_by_number(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from superqode.app.mixins.explore import ExploreMixin

    class ExploreStub(ExploreMixin):
        def __init__(self):
            self.milestones = []

        def _record_milestone(self, name):
            self.milestones.append(name)

    stub, log = ExploreStub(), FakeLog()
    stub._explore_cmd("", log)
    assert stub._explore_capabilities

    stub._select_explore_row(2, log)

    opened = stub._explore_capabilities[2].id
    assert opened in stub._explore_expanded
    assert stub._explore_index == 2
