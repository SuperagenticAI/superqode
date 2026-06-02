"""Interactive transcript + rewind overlay.

A full-screen modal that shows the conversation transcript and lets the user
pick an earlier user message to rewind to. Selecting a target dismisses the
screen with that message's 1-based user-occurrence index; the app then truncates
the agent's stored history to that point and reloads the message for editing.

A double-Esc (or Ctrl+R) "backtrack" flow that keeps SuperQode's purple/quantum
identity and reuses Textual primitives so it stays robust (scrolling, focus, and
keyboard navigation all come from OptionList).
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


@dataclass
class RewindTarget:
    """A user message that can be rewound to."""

    occurrence: int  # 1-based index among user messages
    preview: str


def _preview(text: str, width: int = 88) -> str:
    """Collapse whitespace and clip a message to a single readable line."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) > width:
        collapsed = collapsed[: width - 1].rstrip() + "…"
    return collapsed


class RewindOverlay(ModalScreen[int | None]):
    """Modal that lists rewind targets and returns the chosen occurrence."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Rewind", show=False),
    ]

    CSS = """
    RewindOverlay {
        align: center middle;
    }

    RewindOverlay > Vertical {
        width: 86%;
        height: 86%;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1 2;
    }

    RewindOverlay .title {
        text-align: center;
        color: #a855f7;
        text-style: bold;
        height: 1;
    }

    RewindOverlay .subtitle {
        text-align: center;
        color: #71717a;
        height: 2;
    }

    RewindOverlay #rewind-transcript {
        height: 1fr;
        background: #000000;
        border: solid #1a1a1a;
        padding: 0 1;
        margin-bottom: 1;
    }

    RewindOverlay #rewind-targets {
        height: auto;
        max-height: 40%;
        background: #050505;
        border: solid #27272a;
    }

    RewindOverlay #rewind-targets:focus {
        border: solid #7c3aed;
    }

    RewindOverlay .hints {
        text-align: center;
        color: #71717a;
        height: 1;
    }
    """

    def __init__(
        self,
        transcript: list[tuple[str, str, str]],
        targets: list[RewindTarget],
    ) -> None:
        super().__init__()
        self._transcript = transcript
        self._targets = targets

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("↩  Rewind conversation", classes="title")
            yield Static(
                "Pick an earlier message — context after it is cleared so the agent forgets it.",
                classes="subtitle",
            )
            with VerticalScroll(id="rewind-transcript"):
                yield Static(self._render_transcript())
            yield OptionList(*self._build_options(), id="rewind-targets")
            yield Static(
                "↑↓ choose   •   Enter rewind   •   Esc cancel",
                classes="hints",
            )

    def on_mount(self) -> None:
        targets = self.query_one("#rewind-targets", OptionList)
        if self._targets:
            targets.focus()
            targets.highlighted = len(self._targets) - 1  # default to most recent

    # ----- rendering helpers -------------------------------------------------

    _ROLE_STYLES = {
        "user": ("#22d3ee", "you"),
        "agent": ("#a855f7", "agent"),
        "assistant": ("#a855f7", "agent"),
        "error": ("#f43f5e", "error"),
        "system": ("#71717a", "system"),
    }

    def _render_transcript(self) -> Text:
        text = Text()
        if not self._transcript:
            text.append("  (empty transcript)\n", style="#71717a")
            return text
        user_seen = 0
        for role, body, agent in self._transcript:
            color, label = self._ROLE_STYLES.get(role, ("#a1a1aa", role or "msg"))
            tag = label
            if role == "user":
                user_seen += 1
                tag = f"you #{user_seen}"
            elif role in ("agent", "assistant") and agent:
                tag = agent
            text.append(f"  {tag}\n", style=f"bold {color}")
            text.append(f"  {_preview(body, 200)}\n\n", style="#d4d4d8")
        return text

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for target in self._targets:
            label = Text()
            label.append(f" [{target.occurrence}] ", style="bold #22d3ee")
            label.append(target.preview, style="#e4e4e7")
            options.append(Option(label, id=str(target.occurrence)))
        if not options:
            options.append(Option(Text("  No messages to rewind to", style="#71717a")))
        return options

    # ----- actions -----------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        targets = self.query_one("#rewind-targets", OptionList)
        if targets.highlighted is None:
            self.dismiss(None)
            return
        option = targets.get_option_at_index(targets.highlighted)
        self._dismiss_with(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._dismiss_with(event.option)

    def _dismiss_with(self, option: Option) -> None:
        if option is None or option.id is None:
            self.dismiss(None)
            return
        try:
            self.dismiss(int(option.id))
        except (TypeError, ValueError):
            self.dismiss(None)
