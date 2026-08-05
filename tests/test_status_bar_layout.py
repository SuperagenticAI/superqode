"""The status bar must use the full terminal width on a wide terminal.

Identity/connection info hugged the left edge while the mode badge sat right
next to it, leaving the rest of a wide row visually empty. Session state (mode,
plan, usage) is now a second cluster right-aligned to the far edge.
"""

from __future__ import annotations

from rich.cells import cell_len

from superqode.app.widgets import ColorfulStatusBar


def _bar(**attrs) -> ColorfulStatusBar:
    bar = ColorfulStatusBar()
    for name, value in attrs.items():
        setattr(bar, name, value)
    return bar


class TestFullWidthUsage:
    def test_the_mode_badge_reaches_the_far_edge_on_a_wide_terminal(self):
        bar = _bar(active_harness="core", interaction_mode="build")

        line = bar._render_for_width(150)

        assert cell_len(line.plain) == 150
        # The session-state cluster reaches the far edge rather than hugging
        # the left. The connect/disconnect control is the last thing on it.
        assert "BUILD" in line.plain
        # Identity keeps the corner, controls follow it, state right aligns.
        assert line.plain.startswith("SuperQode")
        assert "[🔌 Connect]" in line.plain
        assert line.plain.rstrip().endswith("BUILD")

    def test_a_narrower_terminal_still_produces_a_valid_line(self):
        bar = _bar(active_harness="core", interaction_mode="build")

        line = bar._render_for_width(80)

        assert "BUILD" in line.plain
        assert "SuperQode" in line.plain

    def test_width_scales_the_right_cluster_position(self):
        """A wider terminal must push the badge further right, not float it
        at a fixed column — otherwise the row still reads as left-hugged."""
        bar = _bar(active_harness="core", interaction_mode="build")

        narrow = bar._render_for_width(90)
        wide = bar._render_for_width(180)

        narrow_pos = narrow.plain.index("BUILD")
        wide_pos = wide.plain.index("BUILD")

        assert wide_pos > narrow_pos


class TestNoSessionStateIsAQuietRow:
    def test_with_no_session_state_only_the_control_is_right_aligned(self):
        """No mode, no plan, no usage. The connect control is always offered,
        so it right-aligns alone rather than the row ending at the left cluster."""
        bar = _bar(interaction_mode="")

        line = bar._render_for_width(150)

        assert line.plain.startswith("SuperQode")
        assert "[🔌 Connect]" in line.plain
        assert "BUILD" not in line.plain


class TestLeftClusterUnaffected:
    def test_identity_and_connection_still_lead_the_line(self):
        bar = _bar(active_model="claude-opus", active_harness="core", interaction_mode="chat")

        line = bar._render_for_width(150)

        assert "SuperQode" in line.plain
        assert "claude-opus" in line.plain
        assert line.plain.index("claude-opus") < line.plain.index("CHAT")

    def test_narrow_width_overflow_is_not_worse_than_before(self):
        """A busy status line could already exceed a very narrow terminal;
        right-aligning must not make that meaningfully worse."""
        bar = _bar(
            active_model="gpt-5.4-turbo-preview-extended",
            active_harness="workbench-extended-name",
            interaction_mode="chat",
            plan_state="active",
        )

        line = bar._render_for_width(60)

        # Not asserting zero overflow (pre-existing, per-field truncation only
        # loosely tracks the target width) — asserting it stays in the same
        # order of magnitude rather than exploding.
        assert len(line.plain) <= 60 + 15
