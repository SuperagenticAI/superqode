"""Focused result and activity screens for structured product outcomes."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, OptionList, Static
from textual.widgets.option_list import Option

from superqode.app.outcomes import Outcome, OutcomeSeverity


_SEVERITY_COLORS = {
    OutcomeSeverity.SUCCESS: "#22c55e",
    OutcomeSeverity.INFORMATION: "#38bdf8",
    OutcomeSeverity.WARNING: "#f59e0b",
    OutcomeSeverity.ERROR: "#ef4444",
}

#: Read before the words are. Kept to the set already used in the transcript so
#: the modal and the receipt below it agree.
_SEVERITY_ICONS = {
    OutcomeSeverity.SUCCESS: "✅",
    OutcomeSeverity.INFORMATION: "ℹ️",
    OutcomeSeverity.WARNING: "⚠️",
    OutcomeSeverity.ERROR: "❌",
}


@dataclass(frozen=True)
class OutcomeSelection:
    """Action selected from a focused outcome screen."""

    action_id: str
    command: str = ""


def outcome_text(outcome: Outcome) -> Text:
    """Render an outcome without relying on Rich markup in external data."""
    color = _SEVERITY_COLORS[outcome.severity]
    text = Text()
    text.append(f"{_SEVERITY_ICONS[outcome.severity]}  ", style=color)
    text.append(f"{outcome.title}\n\n", style=f"bold {color}")
    text.append(f"{outcome.summary}\n", style="bold #f4f4f5")
    if outcome.source:
        text.append(f"\nFrom {outcome.source}\n", style="#71717a")
    if outcome.details:
        text.append("\n")
        for detail in outcome.details:
            if detail:
                text.append(f"• {detail}\n", style="#d4d4d8")
    return text


class OutcomeScreen(ModalScreen[OutcomeSelection | None]):
    """Focused, acknowledgeable result that never lands below the fold."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("enter", "close", "Continue"),
    ]

    CSS = """
    OutcomeScreen {
        align: center middle;
        background: #000000 65%;
    }
    OutcomeScreen > Vertical {
        width: 78;
        max-width: 94%;
        height: auto;
        max-height: 82%;
        background: #0a0a0a;
        border: round #3f3f46;
        padding: 1 2;
    }
    OutcomeScreen #outcome-content {
        height: auto;
        max-height: 24;
        padding: 1;
    }
    OutcomeScreen #outcome-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    OutcomeScreen Button {
        margin-left: 1;
        min-width: 12;
    }
    """

    def __init__(self, outcome: Outcome) -> None:
        super().__init__()
        self.outcome = outcome

    def compose(self) -> ComposeResult:
        with Vertical():
            with ScrollableContainer(id="outcome-content"):
                yield Static(outcome_text(self.outcome))
            with Horizontal(id="outcome-actions"):
                for action in self.outcome.actions:
                    yield Button(
                        action.label,
                        id=f"outcome-action-{action.id}",
                        variant="primary" if action.primary else "default",
                    )
                yield Button("Back", id="outcome-close")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "outcome-close":
            self.dismiss(None)
            return
        prefix = "outcome-action-"
        if not str(event.button.id).startswith(prefix):
            return
        action_id = str(event.button.id)[len(prefix) :]
        action = next((item for item in self.outcome.actions if item.id == action_id), None)
        if action is not None:
            self.dismiss(OutcomeSelection(action.id, action.command))

    def action_close(self) -> None:
        self.dismiss(None)

    def replace_outcome(self, outcome: Outcome) -> bool:
        """Show a newer result in the open modal instead of stacking another.

        Connecting an agent announces more than once: the connection, then the
        model. Pushing a screen per announcement would make the user dismiss a
        queue of them, so a modal that is already up takes the newer content.

        Returns False when the screen is not mounted, so the caller can push a
        fresh one instead.
        """
        self.outcome = outcome
        try:
            self.query_one("#outcome-content", ScrollableContainer).query_one(Static).update(
                outcome_text(outcome)
            )
        except Exception:  # noqa: BLE001 - fall back to a fresh screen
            return False
        return True


class ActivityScreen(Screen[OutcomeSelection | None]):
    """Session activity browser for results the user may have missed."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back", show=False),
    ]

    CSS = """
    ActivityScreen {
        background: #050505;
    }
    ActivityScreen #activity-title {
        height: 3;
        padding: 1 2;
        color: #a855f7;
        text-style: bold;
        border-bottom: solid #27272a;
    }
    ActivityScreen #activity-body {
        height: 1fr;
    }
    ActivityScreen #activity-list {
        width: 42%;
        height: 100%;
        border-right: solid #27272a;
        background: #080808;
    }
    ActivityScreen #activity-detail {
        width: 1fr;
        height: 100%;
        padding: 2;
    }
    ActivityScreen #activity-actions {
        height: 3;
        align-horizontal: right;
        padding: 0 1;
        border-top: solid #27272a;
    }
    ActivityScreen #activity-actions Button {
        margin-left: 1;
        min-width: 12;
    }
    """

    def __init__(self, outcomes: list[Outcome]) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.selected_outcome = outcomes[0] if outcomes else None

    def compose(self) -> ComposeResult:
        yield Static("Activity · results and state changes", id="activity-title")
        with Horizontal(id="activity-body"):
            yield OptionList(*self._options(), id="activity-list")
            yield Static(self._initial_detail(), id="activity-detail")
        with Horizontal(id="activity-actions"):
            yield Button("Open action", id="activity-open", variant="primary")
            yield Button("Back", id="activity-close")
        yield Footer()

    def on_mount(self) -> None:
        self._update_open_button()

    def _options(self) -> list[Option]:
        if not self.outcomes:
            return [Option("No activity yet", id="empty", disabled=True)]
        options: list[Option] = []
        for outcome in self.outcomes:
            stamp = outcome.created_at.astimezone().strftime("%H:%M")
            label = Text()
            label.append(f"{stamp}  ", style="#71717a")
            label.append(outcome.title, style=f"bold {_SEVERITY_COLORS[outcome.severity]}")
            label.append(f"\n      {outcome.summary}", style="#a1a1aa")
            options.append(Option(label, id=outcome.id))
        return options

    def _initial_detail(self) -> Text:
        if not self.outcomes:
            return Text("Important results will remain available here.", style="#a1a1aa")
        return outcome_text(self.outcomes[0])

    @on(OptionList.OptionHighlighted)
    def on_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        outcome = next((item for item in self.outcomes if item.id == event.option.id), None)
        if outcome is not None:
            self.selected_outcome = outcome
            self.query_one("#activity-detail", Static).update(outcome_text(outcome))
            self._update_open_button()

    def _primary_action(self):
        outcome = self.selected_outcome
        if outcome is None or not outcome.actions:
            return None
        return next((action for action in outcome.actions if action.primary), outcome.actions[0])

    def _update_open_button(self) -> None:
        button = self.query_one("#activity-open", Button)
        action = self._primary_action()
        button.disabled = action is None
        button.label = action.label if action is not None else "No action"

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "activity-close":
            self.dismiss(None)
            return
        if event.button.id == "activity-open":
            action = self._primary_action()
            if action is not None:
                self.dismiss(OutcomeSelection(action.id, action.command))

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["ActivityScreen", "OutcomeScreen", "OutcomeSelection", "outcome_text"]
