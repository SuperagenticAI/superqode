"""Commands reachable by clicking, not only by typing.

The hints bar and the status bar have always looked like controls. This routes
a click on one through the same dispatch a typed command uses, so there is one
behaviour to reason about rather than two.
"""

from __future__ import annotations

from rich.text import Text

from superqode.app.constants import THEME
from superqode.app.prompt_stack import PromptSpec

#: Commands a click may run. Anything destructive needs an entry in
#: CONFIRM_WHILE_BUSY as well.
CLICKABLE_COMMANDS: frozenset[str] = frozenset(
    {
        "back",
        "connect",
        "disconnect",
        "eval",
        "exit",
        "explore",
        "harness",
        "help",
        "home",
        "hub",
        "memory",
        "skills",
    }
)

#: Commands that must ask before interrupting a run in progress. Nothing asks
#: when the agent is idle: the prompt exists to protect work in flight, and
#: showing it with no run to lose is just a false claim.
CONFIRM_WHILE_BUSY: frozenset[str] = frozenset({"disconnect", "exit"})


def command_link(command: str) -> str:
    """Rich style fragment making a span click to run ``command``."""
    return f"link superqode://cmd/{command}"


class ClickableCommandMixin:
    """Click-to-run for the persistent chrome."""

    @property
    def _history(self):
        from superqode.app.navigation import NavigationHistory

        existing = getattr(self, "_navigation_history", None)
        if existing is None:
            existing = NavigationHistory()
            self._navigation_history = existing
        return existing

    def _record_screen(self, key: str, label: str, restore) -> None:
        """Remember a screen so back can return to it."""
        self._history.visit(key, label, restore)
        self._sync_navigation_controls()

    def _navigate_back(self) -> bool:
        moved = self._history.back()
        self._sync_navigation_controls()
        return moved

    def _sync_navigation_controls(self) -> None:
        """Show the back control exactly while there is somewhere to go."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            self.query_one("#status-bar", ColorfulStatusBar).can_go_back = self._history.can_go_back
        except Exception:  # noqa: BLE001 - chrome must never break a render
            pass

    def _has_live_connection(self) -> bool:
        """Whether there is anything to disconnect from."""
        pure = getattr(self, "_pure_mode", None)
        if pure is None:
            return False
        session = getattr(pure, "session", None)
        return bool(
            getattr(session, "provider", "")
            or getattr(session, "model", "")
            or getattr(self, "_acp_client", None)
        )

    def _clicked_command_log(self):
        from superqode.app.widgets import ConversationLog

        return self.query_one("#log", ConversationLog)

    def _run_clicked_command(self, command: str) -> None:
        command = command.strip().lstrip(":")
        if command not in CLICKABLE_COMMANDS:
            return
        if command == "back":
            if not self._navigate_back():
                self._clicked_command_log().add_info("Nothing to go back to.")
            return
        if command in CONFIRM_WHILE_BUSY and getattr(self, "is_busy", False):
            self._confirm_clicked_command(command)
            return
        self._dispatch_clicked_command(command)

    def _dispatch_clicked_command(self, command: str) -> None:
        log = self._clicked_command_log()
        self._handle_command(f":{command}", log)

    def _confirm_clicked_command(self, command: str) -> None:
        """Ask before a click throws away work that is still running."""
        if self._prompts.is_active("clicked_command_confirm"):
            return

        options = [
            ("run", f"Yes, run :{command}", "the turn in progress is cancelled"),
            ("keep", "No, keep running", "nothing changes"),
        ]

        def choose(option) -> None:
            self._prompts.pop()
            if option[0] == "run":
                self._dispatch_clicked_command(command)
            else:
                self._clicked_command_log().add_info("Left the run alone.")

        self._prompts.push(
            PromptSpec(
                name="clicked_command_confirm",
                kind="picker",
                options=lambda: list(options),
                on_select=choose,
                on_cancel=lambda: self._prompts.pop(),
                render=lambda: self._render_clicked_command_confirm(command, options),
                data={"command": command, "options": options},
            )
        )
        self._render_clicked_command_confirm(command, options)

    def _render_clicked_command_confirm(self, command: str, options) -> None:
        log = self._clicked_command_log()
        highlighted = self._prompts.index

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("A run is in progress\n", style=f"bold {THEME['text']}")
        t.append(f"  :{command} cancels it.\n\n", style=THEME["muted"])
        for index, (_key, label, description) in enumerate(options):
            selected = index == highlighted
            marker = "  ▶ " if selected else "    "
            style = f"bold {THEME['success']}" if selected else THEME["text"]
            t.append(marker, style=f"bold {THEME['success']}" if selected else "")
            t.append(f"[{index + 1}] ", style=style)
            t.append(label, style=style)
            t.append("\n")
            t.append(f"        {description}\n", style=THEME["muted"])
        log.write(t)


__all__ = [
    "CLICKABLE_COMMANDS",
    "CONFIRM_WHILE_BUSY",
    "ClickableCommandMixin",
    "command_link",
]
