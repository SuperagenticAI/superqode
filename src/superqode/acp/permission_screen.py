"""
Permission Screen for ACP permission requests.

Shows a modal dialog when the agent requests permission to perform an action.

Enhanced Features:
- Support for multi-file permission requests
- j/k navigation between requests
- Multiple diff view modes
- Integration with enhanced permission preview
"""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Label
from textual.reactive import reactive

from rich.text import Text
from rich.panel import Panel

from superqode.acp.types import PermissionOption, ToolCall


# Theme colors
THEME = {
    "purple": "#a855f7",
    "pink": "#ec4899",
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "text": "#e4e4e7",
    "muted": "#71717a",
    "dim": "#52525b",
    "bg": "#000000",
}


class PermissionScreen(ModalScreen[str]):
    """
    Modal screen for handling ACP permission requests.

    Returns the selected option ID.

    Enhanced keyboard shortcuts:
    - a: Allow once
    - A: Allow always
    - r: Reject once
    - R: Reject always
    - j: Next request (when multiple)
    - k: Previous request (when multiple)
    - v: Toggle diff view mode
    - ?: Show help
    """

    BINDINGS = [
        Binding("a", "allow_once", "Allow once", priority=True),
        Binding("A", "allow_always", "Allow always", priority=True),
        Binding("r", "reject_once", "Reject once", priority=True),
        Binding("R", "reject_always", "Reject always", priority=True),
        Binding("j", "next_request", "Next", priority=True, show=False),
        Binding("k", "prev_request", "Previous", priority=True, show=False),
        Binding("v", "toggle_view", "Toggle view", priority=True, show=False),
        Binding("?", "show_help", "Help", priority=True, show=False),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    CSS = """
    PermissionScreen {
        align: center middle;
    }

    #permission-dialog {
        width: 80;
        height: auto;
        max-height: 30;
        background: #0a0a0a;
        border: tall #a855f7;
        padding: 1 2;
    }

    #permission-title {
        text-align: center;
        text-style: bold;
        color: #f59e0b;
        margin-bottom: 1;
    }

    #permission-tool {
        margin-bottom: 1;
    }

    #permission-content {
        height: auto;
        max-height: 15;
        overflow-y: auto;
        margin-bottom: 1;
        padding: 1;
        background: #000000;
        border: round #1a1a1a;
    }

    #permission-buttons {
        height: auto;
        align: center middle;
    }

    .permission-btn {
        margin: 0 1;
    }

    .allow-btn {
        background: #22c55e;
    }

    .reject-btn {
        background: #ef4444;
    }

    #permission-hints {
        text-align: center;
        color: #52525b;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        options: list[PermissionOption],
        tool_call: ToolCall,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.options = options
        self.tool_call = tool_call
        self._option_map: dict[str, str] = {}  # kind -> optionId

        for opt in options:
            kind = opt.get("kind", "")
            option_id = opt.get("optionId", "")
            self._option_map[kind] = option_id

    def compose(self) -> ComposeResult:
        with Container(id="permission-dialog"):
            yield Static("⚠️ Permission Request", id="permission-title")
            yield Static(self._format_tool_info(), id="permission-tool")
            yield Static(self._format_content(), id="permission-content")

            with Horizontal(id="permission-buttons"):
                yield Button("Allow [a]", id="btn-allow", classes="permission-btn allow-btn")
                yield Button("Always [A]", id="btn-always", classes="permission-btn allow-btn")
                yield Button("Reject [r]", id="btn-reject", classes="permission-btn reject-btn")
                yield Button("Never [R]", id="btn-never", classes="permission-btn reject-btn")

            yield Static(
                "[a] Allow once  [A] Allow always  [r] Reject  [R] Reject always  [Esc] Cancel",
                id="permission-hints",
            )

    def _format_tool_info(self) -> Text:
        """Format the tool call information."""
        t = Text()

        title = self.tool_call.get("title", "Unknown operation")
        kind = self.tool_call.get("kind", "other")

        # Icon based on kind
        icons = {
            "read": "📖",
            "edit": "✏️",
            "delete": "🗑️",
            "move": "📦",
            "search": "🔍",
            "execute": "💻",
            "think": "🧠",
            "fetch": "🌐",
            "other": "🔧",
        }
        icon = icons.get(kind, "🔧")

        t.append(f"{icon} ", style=f"bold {THEME['warning']}")
        t.append(f"{title}\n", style=f"bold {THEME['text']}")
        t.append(f"Type: {kind}", style=THEME["muted"])

        return t

    def _format_content(self) -> Text:
        """Format the tool call content (diff, command, etc.)."""
        t = Text()

        content_list = self.tool_call.get("content", [])
        raw_input = self.tool_call.get("rawInput", {})

        for content in content_list:
            content_type = content.get("type", "")

            if content_type == "diff":
                path = content.get("path", "")
                old_text = content.get("oldText", "")
                new_text = content.get("newText", "")

                t.append(f"📄 File: {path}\n", style=f"bold {THEME['purple']}")

                if old_text:
                    t.append("--- Old:\n", style=THEME["error"])
                    # Show first few lines
                    lines = old_text.split("\n")[:5]
                    for line in lines:
                        t.append(f"  {line}\n", style=THEME["dim"])
                    if len(old_text.split("\n")) > 5:
                        t.append("  ...\n", style=THEME["dim"])

                t.append("+++ New:\n", style=THEME["success"])
                lines = new_text.split("\n")[:10]
                for line in lines:
                    t.append(f"  {line}\n", style=THEME["text"])
                if len(new_text.split("\n")) > 10:
                    t.append("  ...\n", style=THEME["dim"])

            elif content_type == "terminal":
                terminal_id = content.get("terminalId", "")
                t.append(f"💻 Terminal: {terminal_id}\n", style=f"bold {THEME['purple']}")

        # Show raw input if no content
        if not content_list and raw_input:
            for key, value in raw_input.items():
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                t.append(f"{key}: ", style=THEME["muted"])
                t.append(f"{value}\n", style=THEME["text"])

        if not t.plain:
            t.append("No details available", style=THEME["dim"])

        return t

    def action_allow_once(self) -> None:
        """Allow this operation once."""
        option_id = self._option_map.get("allow_once", "")
        if option_id:
            self.dismiss(option_id)
        else:
            # Fallback to first allow option
            for opt in self.options:
                if "allow" in opt.get("kind", ""):
                    self.dismiss(opt.get("optionId", ""))
                    return

    def action_allow_always(self) -> None:
        """Allow this operation always."""
        option_id = self._option_map.get("allow_always", "")
        if option_id:
            self.dismiss(option_id)
        else:
            self.action_allow_once()

    def action_reject_once(self) -> None:
        """Reject this operation once."""
        option_id = self._option_map.get("reject_once", "")
        if not option_id:
            option_id = self._option_map.get("reject", "")
        if option_id:
            self.dismiss(option_id)
        else:
            # Fallback to first reject option
            for opt in self.options:
                if "reject" in opt.get("kind", ""):
                    self.dismiss(opt.get("optionId", ""))
                    return

    def action_reject_always(self) -> None:
        """Reject this operation always."""
        option_id = self._option_map.get("reject_always", "")
        if option_id:
            self.dismiss(option_id)
        else:
            self.action_reject_once()

    def action_cancel(self) -> None:
        """Cancel the permission request."""
        self.dismiss("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn-allow":
            self.action_allow_once()
        elif button_id == "btn-always":
            self.action_allow_always()
        elif button_id == "btn-reject":
            self.action_reject_once()
        elif button_id == "btn-never":
            self.action_reject_always()

    def action_next_request(self) -> None:
        """Navigate to next request (for multi-file support)."""
        # This is a placeholder for multi-request navigation
        # Will be used when batch permissions are implemented
        pass

    def action_prev_request(self) -> None:
        """Navigate to previous request (for multi-file support)."""
        # This is a placeholder for multi-request navigation
        # Will be used when batch permissions are implemented
        pass

    def action_toggle_view(self) -> None:
        """Toggle between unified and split diff view."""
        # This is a placeholder for diff view mode toggle
        # Will integrate with enhanced permission preview
        pass

    def action_show_help(self) -> None:
        """Show help for permission screen."""
        # Could show a help overlay with keyboard shortcuts
        pass


class MultiPermissionScreen(ModalScreen[List[str]]):
    """
    Modal screen for handling multiple ACP permission requests.

    Returns a list of (request_id, action) tuples for each request.
    Uses the enhanced permission preview with navigator.
    """

    BINDINGS = [
        Binding("a", "allow_once", "Allow", priority=True),
        Binding("A", "allow_always", "Allow always", priority=True),
        Binding("r", "reject_once", "Reject", priority=True),
        Binding("R", "reject_always", "Reject always", priority=True),
        Binding("j", "next_request", "Next", priority=True),
        Binding("k", "prev_request", "Previous", priority=True),
        Binding("v", "toggle_view", "Toggle view", priority=True),
        Binding("enter", "confirm", "Confirm all", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    CSS = """
    MultiPermissionScreen {
        align: center middle;
    }

    #multi-permission-dialog {
        width: 90%;
        height: 80%;
        max-width: 120;
        background: #0a0a0a;
        border: tall #a855f7;
    }
    """

    def __init__(
        self,
        requests: List[tuple],  # List of (options, tool_call) tuples
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.requests = requests
        self._decisions: dict[int, str] = {}  # index -> action
        self._current_index = 0

    def compose(self) -> ComposeResult:
        with Container(id="multi-permission-dialog"):
            yield Static(
                f" Multiple Permission Requests ({len(self.requests)} pending)",
                id="permission-title",
            )

            # Will integrate with EnhancedPermissionPreviewScreen
            yield Static("Permission requests will be shown here", id="request-content")

            with Horizontal(id="permission-buttons"):
                yield Button("Allow [a]", id="btn-allow", classes="permission-btn allow-btn")
                yield Button("Always [A]", id="btn-always", classes="permission-btn allow-btn")
                yield Button("Reject [r]", id="btn-reject", classes="permission-btn reject-btn")
                yield Button("Never [R]", id="btn-never", classes="permission-btn reject-btn")

            yield Static(
                "[j/k] Navigate  [a/A] Allow  [r/R] Reject  [Enter] Confirm all  [Esc] Cancel",
                id="permission-hints",
            )

    def action_allow_once(self) -> None:
        """Allow current request once."""
        self._decisions[self._current_index] = "allow_once"
        self._advance()

    def action_allow_always(self) -> None:
        """Allow current request always."""
        self._decisions[self._current_index] = "allow_always"
        self._advance()

    def action_reject_once(self) -> None:
        """Reject current request."""
        self._decisions[self._current_index] = "reject_once"
        self._advance()

    def action_reject_always(self) -> None:
        """Reject current request always."""
        self._decisions[self._current_index] = "reject_always"
        self._advance()

    def action_next_request(self) -> None:
        """Go to next request."""
        if self._current_index < len(self.requests) - 1:
            self._current_index += 1
            self._update_display()

    def action_prev_request(self) -> None:
        """Go to previous request."""
        if self._current_index > 0:
            self._current_index -= 1
            self._update_display()

    def action_toggle_view(self) -> None:
        """Toggle diff view mode."""
        pass

    def action_confirm(self) -> None:
        """Confirm all decisions."""
        # Build result list
        results = []
        for i in range(len(self.requests)):
            action = self._decisions.get(i, "reject_once")  # Default to reject
            results.append(action)
        self.dismiss(results)

    def action_cancel(self) -> None:
        """Cancel all requests."""
        self.dismiss([])

    def _advance(self) -> None:
        """Advance to next request or finish."""
        if self._current_index < len(self.requests) - 1:
            self._current_index += 1
            self._update_display()
        elif len(self._decisions) == len(self.requests):
            # All decisions made
            self.action_confirm()

    def _update_display(self) -> None:
        """Update the display for current request."""
        # Update title with current position
        title = self.query_one("#permission-title", Static)
        title.update(f" Request {self._current_index + 1} of {len(self.requests)}")
