"""Which command gets suggested, and when.

A command is suggested once its precondition holds, never twice, and never
after the user has run it.
"""

from __future__ import annotations

import pytest

from superqode.app.mixins.dialogs import DialogsMixin
from superqode.app.progress import (
    HINTS,
    MILESTONES,
    command_used,
    load_progress,
    mark_hint_shown,
    next_hint,
    record_command_used,
    record_milestone,
)


def reveal(*milestones: str):
    """Return the hint offered to somebody who has done exactly these things."""
    for name in milestones:
        record_milestone(name)
    return next_hint()


# --- the ladder ---------------------------------------------------------------


def test_every_hint_is_gated_on_declared_milestones():
    """Every hint is gated on declared milestone names."""
    for hint in HINTS:
        assert set(hint.requires) <= set(MILESTONES), hint.id
        assert set(hint.blocked_by) <= set(MILESTONES), hint.id


def test_a_new_user_is_never_nudged():
    """No hints before the first completed task."""
    assert next_hint() is None
    assert reveal("connected") is None


@pytest.mark.parametrize(
    "milestones,expected",
    [
        # Editing and running come first in the ladder, so they win when they
        # apply: those are the commands that make the run safe to look at.
        (("task_completed", "edited_files"), "diff"),
        (("task_completed", "ran_shell"), "trust"),
        (("task_completed",), "memory"),
    ],
)
def test_the_first_relevant_capability_is_the_one_offered(milestones, expected):
    hint = reveal(*milestones)
    assert hint is not None
    assert hint.id == expected


def test_later_rungs_wait_for_the_earlier_ones_to_be_seen():
    """Hints are shown one at a time, in ladder order."""
    for name in ("task_completed", "connected", "compared_harnesses"):
        record_milestone(name)

    seen = []
    for _ in range(len(HINTS)):
        hint = next_hint()
        if hint is None:
            break
        seen.append(hint.id)
        mark_hint_shown(hint.id)

    assert "eval" in seen
    assert seen.index("memory") < seen.index("eval")


def test_editing_then_failing_offers_the_way_back():
    """``:undo`` requires both an edit and a failure."""
    record_milestone("task_completed")
    record_milestone("edited_files")
    mark_hint_shown("diff")

    assert (reveal("hit_an_error") or HINTS[0]).id == "undo"


def test_running_commands_then_failing_offers_the_sandbox():
    for name in ("task_completed", "ran_shell", "edited_files", "hit_an_error"):
        record_milestone(name)
    for hint_id in ("diff", "undo", "trust"):
        mark_hint_shown(hint_id)

    assert (next_hint() or HINTS[0]).id == "sandbox"


# --- never repeat, never state the obvious ------------------------------------


def test_a_hint_is_offered_once_and_never_again():
    record_milestone("task_completed")
    first = next_hint()
    assert first is not None

    mark_hint_shown(first.id)
    second = next_hint()
    assert second is None or second.id != first.id


def test_a_command_the_user_already_ran_is_never_suggested():
    """A command the user has run is not suggested."""
    record_milestone("task_completed")
    record_milestone("edited_files")
    record_command_used("diff")

    assert (next_hint() or HINTS[0]).id != "diff"


def test_command_usage_survives_the_leading_colon_and_arguments():
    record_command_used(":memory remember something")

    assert command_used("memory") is True
    assert command_used(":memory") is True
    assert command_used("skills") is False


def test_running_a_real_tui_command_records_its_root():
    from superqode.app.mixins.slash_commands import SlashCommandMixin

    class Stub(SlashCommandMixin):
        _acp_client = None

        def _record_ex_command(self, *_args):
            pass

        def _show_help(self, _log):
            pass

        def set_timer(self, *_args):
            pass

        def _ensure_input_focus(self):
            pass

    SlashCommandMixin._handle_command(Stub(), ":help", object())

    assert command_used("help") is True


def test_doing_the_thing_makes_its_hint_redundant():
    record_milestone("task_completed")
    record_milestone("used_memory")

    hint = next_hint()
    assert hint is None or hint.id != "memory"


def test_progress_records_commands_separately_from_milestones():
    record_milestone("task_completed")
    record_command_used("diff")

    progress = load_progress()
    assert "task_completed" in progress.milestones
    assert "diff" in progress.commands_used
    assert "diff" not in progress.milestones


# --- reading a run ------------------------------------------------------------


def test_a_run_that_executed_something_is_recognised():
    assert DialogsMixin._run_used_shell({"commands_run": ["pytest -q"]}) is True
    assert DialogsMixin._run_used_shell({"tools": [{"name": "bash"}]}) is True
    assert DialogsMixin._run_used_shell({"tools": [{"name": "read_file"}]}) is False
    assert DialogsMixin._run_used_shell({}) is False


def test_a_run_that_failed_is_recognised():
    assert DialogsMixin._run_hit_an_error({"tools": [{"name": "bash", "error": "boom"}]}) is True
    assert DialogsMixin._run_hit_an_error({"tools": [{"name": "bash", "status": "failed"}]}) is True
    assert DialogsMixin._run_hit_an_error({"commands_run": [{"exit_code": 1}]}) is True
    assert DialogsMixin._run_hit_an_error({"tools": [{"name": "bash", "status": "ok"}]}) is False
    assert DialogsMixin._run_hit_an_error({}) is False


def test_reading_a_run_never_raises_on_unexpected_shapes():
    for summary in ({"tools": ["bash"]}, {"tools": None}, {"commands_run": None}):
        DialogsMixin._run_used_shell(summary)
        DialogsMixin._run_hit_an_error(summary)


# --- help lists what you have not tried ---------------------------------------


class _Text:
    def __init__(self):
        self.parts = []

    def append(self, value, style=""):
        self.parts.append(str(value))

    @property
    def plain(self):
        return "".join(self.parts)


def test_help_offers_commands_the_user_has_not_run():
    text = _Text()
    DialogsMixin._append_unused_command_suggestions(DialogsMixin(), text)

    rendered = text.plain
    assert "You Have Not Tried" in rendered
    assert ":diff" in rendered


def test_help_drops_commands_once_they_have_been_used():
    for command in (cmd for cmd, _why in DialogsMixin._WORTH_KNOWING):
        record_command_used(command)

    text = _Text()
    DialogsMixin._append_unused_command_suggestions(DialogsMixin(), text)

    # Nothing left to suggest, so the section does not appear at all.
    assert text.plain == ""


def test_help_suggests_a_handful_not_a_catalogue():
    text = _Text()
    DialogsMixin._append_unused_command_suggestions(DialogsMixin(), text)

    offered = [line for line in text.plain.split("\n") if line.strip().startswith(":")]
    assert 0 < len(offered) <= 5
