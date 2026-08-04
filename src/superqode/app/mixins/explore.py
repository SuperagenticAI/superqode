"""``:explore`` — capability categories with their live state on this machine.

Every row is a probe: what the category is, whether it is active here, and the
command that acts on it.
"""

from __future__ import annotations

from rich.text import Text

from superqode.app.constants import THEME
from superqode.app.widgets import ConversationLog

#: State glyphs; active rows read as filled.
_STATE_MARKS = {
    "on": ("●", "success"),
    "ready": ("●", "success"),
    "available": ("○", "muted"),
    "install": ("○", "dim"),
}


class ExploreMixin:
    """Capability browser and its keyboard navigation."""

    def _explore_cmd(self, args: str, log: ConversationLog) -> None:
        """Open the browser, or jump straight to one category by name."""
        query = (args or "").strip().lower()
        self._record_milestone("explored")
        self._explore_capabilities = self._load_capability_inventory()

        if query:
            matches = [
                index
                for index, capability in enumerate(self._explore_capabilities)
                if query in capability.id or query in capability.title.lower()
            ]
            if matches:
                self._explore_index = matches[0]
                self._explore_expanded = {self._explore_capabilities[matches[0]].id}
                self._awaiting_explore = True
                self._render_explore(log)
                return
            log.add_info(f"No capability matches {query!r}. Showing everything instead.")

        self._explore_index = 0
        self._explore_expanded = set()
        self._awaiting_explore = True
        self._render_explore(log)

    def _load_capability_inventory(self):
        from superqode.app.capabilities import capability_inventory

        return capability_inventory()

    def _render_explore(self, log: ConversationLog, *, clear_log: bool = True) -> None:
        from superqode.app.capabilities import DETAIL_LIMIT, inventory_totals

        capabilities = getattr(self, "_explore_capabilities", [])
        highlighted = getattr(self, "_explore_index", 0)
        expanded = getattr(self, "_explore_expanded", set())
        active, total = inventory_totals(capabilities)

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("What SuperQode can do here\n", style=f"bold {THEME['text']}")
        t.append(f"  {active} of {total} active in this repository.\n\n", style=THEME["muted"])

        label_width = max((len(c.title) for c in capabilities), default=10) + 2
        for index, capability in enumerate(capabilities):
            is_open = capability.id in expanded
            arrow = "▾" if is_open else "▸"
            if index == highlighted:
                t.append(f"  {arrow} ", style=f"bold {THEME['success']}")
                t.append(f"{capability.title:<{label_width}}", style=f"bold {THEME['success']}")
            else:
                t.append(f"  {arrow} ", style=THEME["dim"])
                t.append(f"{capability.title:<{label_width}}", style=f"bold {THEME['text']}")
            t.append(f"{capability.headline:<26}", style=THEME["muted"])
            if capability.command:
                t.append(capability.command, style=THEME["cyan"])
            t.append("\n", style="")

            if index == highlighted and capability.summary:
                t.append(f"      {capability.summary}\n", style=THEME["dim"])

            if is_open:
                for item in capability.items[:DETAIL_LIMIT]:
                    mark, color = _STATE_MARKS.get(item.state, ("○", "muted"))
                    t.append(f"      {mark} ", style=THEME[color])
                    t.append(f"{item.name:<24}", style=THEME["text"])
                    t.append(f"{item.state:<11}", style=THEME[color])
                    if item.detail:
                        t.append(item.detail, style=THEME["muted"])
                    t.append("\n", style="")
                remaining = len(capability.items) - DETAIL_LIMIT
                if remaining > 0:
                    t.append(f"      … {remaining} more, see ", style=THEME["dim"])
                    t.append(f"{capability.command}\n", style=THEME["cyan"])
                t.append("\n", style="")

        t.append("\n  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" expand  ", style=THEME["dim"])
        t.append("→", style=THEME["cyan"])
        t.append(" run its command  ", style=THEME["dim"])
        t.append("Esc", style=THEME["purple"])
        t.append(" close  •  ", style=THEME["dim"])
        t.append(":explore memory", style=THEME["cyan"])
        t.append(" jumps to one\n", style=THEME["dim"])

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            log.auto_scroll = True
        else:
            log.auto_scroll = False
            log.clear()
            log.write(t)
            log.auto_scroll = True

    # --- navigation -----------------------------------------------------------

    def action_navigate_explore_up(self) -> None:
        if not getattr(self, "_awaiting_explore", False):
            return
        current = getattr(self, "_explore_index", 0)
        if current > 0:
            self._explore_index = current - 1
            self._render_explore(self.query_one("#log", ConversationLog), clear_log=False)

    def action_navigate_explore_down(self) -> None:
        if not getattr(self, "_awaiting_explore", False):
            return
        current = getattr(self, "_explore_index", 0)
        if current < len(getattr(self, "_explore_capabilities", [])) - 1:
            self._explore_index = current + 1
            self._render_explore(self.query_one("#log", ConversationLog), clear_log=False)

    def _select_explore_row(self, index: int, log: ConversationLog) -> None:
        """Open one category by number, the same as highlighting and pressing Enter."""
        capabilities = getattr(self, "_explore_capabilities", [])
        if not (0 <= index < len(capabilities)):
            return
        self._explore_index = index
        self._explore_expanded = {capabilities[index].id}
        self._render_explore(log, clear_log=False)

    def action_toggle_explore_row(self) -> None:
        """Expand or collapse the highlighted category."""
        if not getattr(self, "_awaiting_explore", False):
            return
        capabilities = getattr(self, "_explore_capabilities", [])
        index = getattr(self, "_explore_index", 0)
        if not (0 <= index < len(capabilities)):
            return
        expanded = set(getattr(self, "_explore_expanded", set()))
        capability_id = capabilities[index].id
        if capability_id in expanded:
            self._explore_expanded = set()
        else:
            self._explore_expanded = {capability_id}
        self._render_explore(self.query_one("#log", ConversationLog), clear_log=False)

    def action_run_explore_command(self) -> None:
        """Run the highlighted category's command, closing the browser."""
        if not getattr(self, "_awaiting_explore", False):
            return
        capabilities = getattr(self, "_explore_capabilities", [])
        index = getattr(self, "_explore_index", 0)
        if not (0 <= index < len(capabilities)):
            return
        command = capabilities[index].command
        if not command:
            return
        self._awaiting_explore = False
        log = self.query_one("#log", ConversationLog)
        log.clear()
        self._handle_command(command, log)


__all__ = ["ExploreMixin"]
