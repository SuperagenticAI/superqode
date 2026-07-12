"""Tool-permission requests, approval bridge, and permission pulse."""

from __future__ import annotations
import os
import threading
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)


class HelperPermissionsMixin:
    """Tool-permission requests, approval bridge, and permission pulse."""

    def _ensure_pure_mode(self):
        """Ensure the PureMode object exists for session operations."""
        if not hasattr(self, "_pure_mode"):
            from superqode.pure_mode import PureMode

            self._pure_mode = PureMode()
        return self._pure_mode

    def _install_pure_permission_bridge(self, pure, log: ConversationLog) -> None:
        """Route self-contained runtime approval callbacks through the TUI prompt."""

        def on_permission_request(tool_name: str, arguments: dict) -> bool:
            if getattr(self, "_active_plan_mode_for_current_message", False):
                try:
                    self._call_ui(
                        log.add_info,
                        f"Plan mode blocked runtime approval for {tool_name}.",
                    )
                except Exception:
                    pass
                return False
            return self._request_runtime_permission(tool_name, arguments, log)

        pure.on_permission_request = on_permission_request

    def _announce_pending_approvals(self, source, log) -> None:
        """Surface pending approvals from an active runtime or HarnessSpec session."""
        try:
            pending = source.get_pending_approvals()
        except Exception:  # noqa: BLE001
            return
        if not pending:
            return
        card = Text()
        card.append("🔐 Tool approval needed\n\n", style=f"bold {THEME['warning']}")
        card.append(f"{len(pending)} pending item(s)\n", style=THEME["text"])
        for entry in pending:
            tool = entry.get("tool_name") or "<unknown>"
            args_preview = str(entry.get("arguments", {}))
            if len(args_preview) > 120:
                args_preview = args_preview[:117] + "..."
            card.append("\n[", style=THEME["muted"])
            card.append(str(entry.get("index", 0)), style=f"bold {THEME['cyan']}")
            card.append("] ", style=THEME["muted"])
            card.append(tool, style=f"bold {THEME['text']}")
            card.append(f"  {args_preview}", style=THEME["muted"])
        card.append("\n\n")
        card.append(":approve [N]", style=f"bold {THEME['success']}")
        card.append("  •  ", style=THEME["dim"])
        card.append(":reject [N]", style=f"bold {THEME['error']}")
        card.append(' ["message"]', style=THEME["muted"])
        log.write(
            Panel(
                card,
                title=f"[bold {THEME['warning']}]Action approval[/]",
                border_style=THEME["warning"],
                box=ROUNDED,
                padding=(1, 2),
            )
        )

    def _is_permission_request(self, line: str) -> bool:
        """Check if a line is a permission request from the agent."""
        permission_keywords = [
            "permission",
            "allow",
            "approve",
            "confirm",
            "run command",
            "execute",
            "write file",
            "delete",
            "y/n",
            "[y/N]",
            "[Y/n]",
            "(yes/no)",
            "allow?",
            "proceed",
            "continue?",
        ]
        line_lower = line.lower()
        return any(kw in line_lower for kw in permission_keywords)

    def _ensure_approved_tools(self) -> set:
        """Ensure _approved_tools is initialized and return it.

        This helper method ensures the _approved_tools set always exists,
        preventing AttributeError when approval mode is set to 'ask'.
        """
        if not hasattr(self, "_approved_tools"):
            self._approved_tools = set()
        return self._approved_tools

    def _tool_needs_permission(self, tool_name: str, tool_input: dict) -> bool:
        """Check if a tool call needs user permission.

        Returns True if permission is needed:
        - External tools (web, fetch, etc.)
        - File operations outside current project directory
        - Bash commands that might affect system

        Returns False (auto-allow) for:
        - Read operations within project
        - Write/edit operations within project directory
        - Search/list operations within project
        - Tools that have already been approved in this session
        """
        # Ensure _approved_tools is initialized
        approved_tools = self._ensure_approved_tools()

        # Check if this tool was already approved in this session
        tool_sig = self._get_tool_signature(tool_name, tool_input)
        if tool_sig in approved_tools:
            return False

            # Also check _pending_tool_id patterns in approved tools
        if approved_tools:
            # Check if any approved tool matches this one (by tool name prefix)
            for approved in approved_tools:
                if approved and approved.startswith(f"{tool_name}:"):
                    # Same tool type was approved before - allow similar calls
                    return False

        tool_lower = tool_name.lower()
        cwd = os.getcwd()

        # External tools always need permission
        external_tools = ("web", "fetch", "http", "curl", "wget", "browser", "url")
        if any(ext in tool_lower for ext in external_tools):
            return True

        # Get file path from tool input
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))

        side_effect_tools = (
            "write",
            "edit",
            "patch",
            "create",
            "mkdir",
            "delete",
            "remove",
            "rm",
            "move",
            "rename",
            "replace",
            "insert",
            "append",
            "multi_edit",
            "apply_patch",
        )

        # Side-effecting filesystem tools should be visible in ASK mode even
        # when they target the project. This is the permission dialog users
        # expect from coding agents before edits land.
        if any(name in tool_lower for name in side_effect_tools):
            return True

        if file_path:
            # Resolve to absolute path
            try:
                abs_path = os.path.abspath(file_path)
                # Check if file is within current working directory
                if abs_path.startswith(cwd):
                    # File is within project - auto-allow
                    return False
                else:
                    # File is outside project - needs permission
                    return True
            except Exception:
                # If we can't resolve path, ask for permission
                return True

        # Bash/shell commands - check if they might affect outside project
        if tool_lower in ("bash", "shell", "terminal", "exec", "run"):
            command = tool_input.get("command", "")
            # Dangerous commands that might affect system
            dangerous_patterns = (
                "sudo",
                "rm -rf /",
                "chmod",
                "chown",
                "mkfs",
                "dd ",
                "curl",
                "wget",
                "> /",
                ">> /",
                "/etc/",
                "/usr/",
                "/var/",
                "/home/",
                "~/",
            )
            if any(pattern in command for pattern in dangerous_patterns):
                return True
            # Even commands within project should ask for permission in ASK mode
            return True

        # Read operations - auto-allow
        if tool_lower in ("read", "cat", "head", "tail", "less", "view"):
            return False

        # Search/list operations - auto-allow
        if tool_lower in ("search", "grep", "find", "list", "ls", "glob", "tree"):
            return False

        # Unknown tools - ask for permission to be safe
        return True

    def _request_runtime_permission(
        self,
        tool_name: str,
        tool_input: dict,
        log: ConversationLog,
        *,
        timeout: float = 60.0,
    ) -> bool:
        """Synchronously bridge a runtime approval callback to the TUI prompt."""
        if self.approval_mode == "deny":
            try:
                self._call_ui(log.add_info, f"Denied {tool_name} by approval mode.")
            except Exception:
                pass
            return False
        if self.approval_mode == "auto":
            try:
                self._call_ui(log.add_info, f"Approved {tool_name} by AUTO mode.")
            except Exception:
                pass
            return True
        if getattr(self, "_runtime_permission_allow_all", False):
            try:
                self._call_ui(log.add_info, f"Approved {tool_name} by session approval.")
            except Exception:
                pass
            return True

        if getattr(self, "_permission_pending", False):
            try:
                self._call_ui(log.add_error, "Another approval prompt is already pending.")
            except Exception:
                pass
            return False

        self._permission_response = None
        self._permission_response_event = threading.Event()
        try:
            self._call_ui(self._show_permission_prompt, tool_name, tool_input, log)
        except Exception as exc:
            self._permission_response_event = None
            try:
                self._call_ui(log.add_error, f"Could not show approval prompt: {exc}")
            except Exception:
                pass
            return False

        event = self._permission_response_event
        resolved = event.wait(timeout)

        if not resolved or getattr(self, "_permission_pending", False):
            self._permission_pending = False
            self._permission_response = "deny"
            self._permission_response_event = None
            try:
                self._call_ui(log.add_info, f"Approval timed out for {tool_name}.")
                self._call_ui(self._reset_input_placeholder)
            except Exception:
                pass
            return False

        response = getattr(self, "_permission_response", None)
        self._permission_response_event = None
        if response == "allow_all":
            self._runtime_permission_allow_all = True
            return True
        return response == "allow"

    def _permission_risk(
        self, tool_name: str, tool_input: dict, reason: str = ""
    ) -> tuple[str, str]:
        """Return a coarse risk label/color for a permission request."""
        tool_lower = tool_name.lower()
        command = str(tool_input.get("command", "") or "").lower()
        path = str(
            tool_input.get("filePath", tool_input.get("path", tool_input.get("file", ""))) or ""
        )
        dangerous = (
            "rm -rf",
            "sudo",
            "chmod 777",
            "chown",
            "mkfs",
            "dd ",
            ">/dev/",
            ":(){",
        )
        if any(pattern in command for pattern in dangerous):
            return "critical", THEME["error"]
        if reason == "outside project" or path.startswith(("/etc/", "/usr/", "/var/", "/bin/")):
            return "high", THEME["error"]
        if reason == "external network":
            return "high", THEME["warning"]
        if tool_lower in ("bash", "shell", "terminal") or "exec" in tool_lower:
            return "medium", THEME["warning"]
        if any(name in tool_lower for name in ("delete", "remove", "rm")):
            return "high", THEME["error"]
        if reason == "file change":
            return "medium", THEME["warning"]
        return "low", THEME["success"]

    def _start_permission_pulse(self):
        """Start pulsing animation on input box to draw attention."""
        self._permission_pulse_frame = 0
        if hasattr(self, "_permission_pulse_timer") and self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
        self._permission_pulse_timer = self.set_interval(0.4, self._update_permission_pulse)

    def _stop_permission_pulse(self):
        """Stop the permission pulse animation."""
        if hasattr(self, "_permission_pulse_timer") and self._permission_pulse_timer:
            self._permission_pulse_timer.stop()
            self._permission_pulse_timer = None
        # Reset input box style
        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", "#1a1a1a")
        except Exception:
            pass

    def _update_permission_pulse(self):
        """Update the pulsing animation on input box."""
        if not self._permission_pending:
            self._stop_permission_pulse()
            return

        self._permission_pulse_frame = getattr(self, "_permission_pulse_frame", 0) + 1

        # Smooth gradient through warm colors
        colors = ["#f59e0b", "#fbbf24", "#f97316", "#fbbf24"]
        color = colors[self._permission_pulse_frame % len(colors)]

        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", color)
        except Exception:
            pass
