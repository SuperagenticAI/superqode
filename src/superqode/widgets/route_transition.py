"""Review execution-boundary changes before mutating the active connection."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class RouteTransitionScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Keep current route", priority=True)]
    CSS = """
    RouteTransitionScreen { align: center middle; }
    #route-transition { width: 76; max-width: 96%; height: auto; max-height: 90%; background: $surface; border: round $warning; padding: 1 2; }
    #route-transition Static { height: auto; margin-bottom: 1; }
    #route-transition Horizontal { height: 3; }
    #route-transition Button { width: auto; min-width: 12; margin-right: 1; }
    """

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="route-transition"):
            yield Static("Review route change", markup=False)
            yield Static("\n\n".join(self.plan.details), markup=False)
            with Horizontal():
                yield Button("Keep current", id="route-keep")
                yield Button("Switch route", id="route-accept", variant="warning")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "route-accept")

    def action_cancel(self):
        self.dismiss(False)
