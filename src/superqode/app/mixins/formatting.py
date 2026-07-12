"""Output formatting, rendering, and display helpers."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from textual.widgets import Static
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.plan import (
    TaskStatus,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
)

# --- helpers extracted from app_main (A1) ---


class FormattingMixin:
    """_format_/_render_/_display_/_write_ output helpers."""

    def _render_queued_input(self) -> None:
        """Render the pending type-ahead queue under the prompt."""
        queue = getattr(self, "_typeahead_queue", [])
        try:
            panel = self.query_one("#queued-input", Static)
        except Exception:
            return
        if not queue:
            panel.update("")
            panel.remove_class("visible")
            return
        t = Text()
        t.append(f"  ⏳ queued ({len(queue)})  ", style=f"bold {THEME['warning']}")
        t.append("sends when the agent is free  •  ", style=THEME["dim"])
        t.append(":queue clear", style=f"bold {THEME['cyan']}")
        t.append("\n", style="")
        for index, msg in enumerate(queue[:5], 1):
            preview = " ".join(str(msg).split())
            if len(preview) > 80:
                preview = preview[:77].rstrip() + "..."
            t.append(f"    {index}. ", style=THEME["dim"])
            t.append(preview, style=THEME["muted"])
            t.append("\n", style="")
        if len(queue) > 5:
            t.append(f"    +{len(queue) - 5} more\n", style=THEME["dim"])
        panel.update(t)
        panel.add_class("visible")

    def _render_compare_results(self, results, log: ConversationLog) -> None:
        """Render parallel-compare results as labelled stacked sections."""
        from superqode.rendering.markdown import render_agent_markdown

        for result in results:
            header = Text()
            mark = "✓" if result.ok else "✕"
            color = THEME["success"] if result.ok else THEME["error"]
            header.append(f"\n  {mark} ", style=f"bold {color}")
            header.append(f"{result.spec.label}", style=f"bold {THEME['cyan']}")
            header.append(f"  ({result.elapsed:.1f}s)\n", style=THEME["dim"])
            log.write(header)
            if result.ok and result.text:
                log.write(render_agent_markdown(result.text))
            elif result.ok:
                log.write(Text("  (empty response)\n", style=THEME["muted"]))
            else:
                log.write(Text(f"  {result.error}\n", style=THEME["error"], overflow="fold"))

    def _render_attachments(self) -> Text:
        t = Text()
        t.append("\n  📎 ", style=f"bold {THEME['cyan']}")
        t.append("Prompt Attachments\n\n", style=f"bold {THEME['text']}")
        refs = getattr(self, "_attached_refs", [])
        if not refs:
            t.append("  No staged references.\n", style=THEME["muted"])
            t.append("  Add one with ", style=THEME["muted"])
            t.append(":attach <file|url>\n", style=THEME["cyan"])
            return t
        for index, ref in enumerate(refs, 1):
            t.append(f"  [{index}] ", style=THEME["dim"])
            ref_style = (
                THEME["purple"]
                if ref.startswith("mcp://")
                else THEME["cyan"]
                if ref.startswith("@")
                else THEME["text"]
            )
            t.append(ref, style=ref_style)
            t.append("\n")
        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":attach remove <n>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":attach clear\n", style=THEME["cyan"])
        return t

    def _write_share_artifact(
        self,
        session_id: str,
        path_arg: str = "",
        *,
        include_tree: bool = False,
    ) -> Path:
        from superqode.session.share_artifacts import create_share_artifact

        return create_share_artifact(
            session_id,
            output=path_arg or None,
            storage_dir=".superqode/sessions",
            include_tree=include_tree,
        )

    def _render_harness_wizard_step(self, log) -> None:
        state = getattr(self, "_harness_wizard_state", None)
        if not state:
            return
        step = state["step"]
        answers = state["answers"]
        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Wizard\n", style=f"bold {THEME['text']}")
        t.append("  Type ", style=THEME["muted"])
        t.append("back", style=THEME["cyan"])
        t.append(" or ", style=THEME["muted"])
        t.append("cancel", style=THEME["cyan"])
        t.append(" anytime. Press Enter for defaults.\n\n", style=THEME["muted"])

        if step == "name":
            t.append("  Step 1/9  Harness name\n", style=f"bold {THEME['cyan']}")
            t.append(f"  Default: {answers['name']}\n", style=THEME["muted"])
            t.append("  Example: my-coder\n", style=THEME["text"])
        elif step == "starter":
            t.append("  Step 2/9  Choose starting point\n", style=f"bold {THEME['cyan']}")
            for index, (key, label) in enumerate(self._wizard_starters(), 1):
                marker = " (default)" if key == answers["starter"] else ""
                t.append(f"  {index}. {key:<18} {label}{marker}\n", style=THEME["text"])
        elif step == "provider":
            t.append("  Step 3/9  Provider\n", style=f"bold {THEME['cyan']}")
            t.append("  Leave blank to keep the template default.\n", style=THEME["muted"])
            t.append(
                "  Examples: ollama, lmstudio, mlx, ds4, openai, anthropic\n", style=THEME["text"]
            )
        elif step == "model":
            t.append("  Step 4/9  Model\n", style=f"bold {THEME['cyan']}")
            t.append("  Leave blank to keep the template model.\n", style=THEME["muted"])
            t.append("  Example: qwen3-coder\n", style=THEME["text"])
        elif step == "tools":
            t.append("  Step 5/9  Tools\n", style=f"bold {THEME['cyan']}")
            options = (
                ("full", "file read/edit, search, shell, todos"),
                ("read-only", "read/search/review only"),
                ("no-shell", "file edits allowed, shell blocked"),
                ("no-tools", "model-only reasoning/review"),
            )
            for index, (key, label) in enumerate(options, 1):
                default = " (default)" if key == "full" else ""
                t.append(f"  {index}. {key:<10} {label}{default}\n", style=THEME["text"])
        elif step == "permissions":
            t.append("  Step 6/9  Permissions\n", style=f"bold {THEME['cyan']}")
            options = (
                ("balanced", "auto safe reads/searches; ask before writes and shell"),
                ("careful", "ask before most actions"),
                ("yolo", "auto-approve actions allowed by the harness"),
                ("balanced-network", "balanced approvals plus network access"),
            )
            for index, (key, label) in enumerate(options, 1):
                default = " (default)" if key == "balanced" else ""
                t.append(f"  {index}. {key:<18} {label}{default}\n", style=THEME["text"])
        elif step == "tool_format":
            t.append("  Step 7/9  Tool-call format\n", style=f"bold {THEME['cyan']}")
            for index, (key, label) in enumerate(
                (
                    ("auto", "use template/runtime default"),
                    ("native", "model-native tool calling"),
                    ("prompt", "prompt-described tools for weaker local models"),
                ),
                1,
            ):
                default = " (default)" if key == "auto" else ""
                t.append(f"  {index}. {key:<8} {label}{default}\n", style=THEME["text"])
        elif step == "workflow":
            t.append("  Step 8/9  Workflow\n", style=f"bold {THEME['cyan']}")
            options = (
                ("single", "one agent handles the task"),
                ("plan-implement-review", "planner, implementer, reviewer chain"),
                ("fix-and-verify", "fix then verify with checks"),
                ("parallel-review", "multiple reviewers in parallel"),
                ("security-review", "security-focused review chain"),
            )
            for index, (key, label) in enumerate(options, 1):
                default = " (default)" if key == "single" else ""
                t.append(f"  {index}. {key:<22} {label}{default}\n", style=THEME["text"])
        elif step == "output":
            t.append("  Step 9/10  Output file\n", style=f"bold {THEME['cyan']}")
            t.append(f"  Default: {state['output']}\n", style=THEME["muted"])
            t.append("  Example: harness.yaml\n", style=THEME["text"])
        elif step == "load":
            t.append("  Step 10/10  Load this harness now?\n", style=f"bold {THEME['cyan']}")
            t.append("  Default: yes\n", style=THEME["muted"])
            t.append("  Answer: yes or no\n", style=THEME["text"])

        self._show_command_output(log, t)

    def _write_chat_stats(self, log: ConversationLog, ttft, tps, tokens: int, total: float) -> None:
        """One muted metrics line under a chat reply."""
        line = Text()
        line.append("  ⚡ ", style=f"bold {THEME['gold']}")
        parts = []
        if ttft is not None:
            parts.append(f"TTFT {ttft:.2f}s")
        if tps is not None:
            parts.append(f"{tps:.1f} tok/s")
        parts.append(f"{tokens} tok")
        parts.append(f"{total:.1f}s total")
        line.append("  ·  ".join(parts), style=THEME["muted"])
        line.append("\n", style="")
        log.write(line)

    def _format_todo_list(self, todos: list) -> list:
        """Format a TODO list with emojis and nice display."""
        if not todos:
            return ["📋 No tasks"]

        formatted_lines = []

        # Status emoji mapping
        status_emojis = {"completed": "✅", "in_progress": "🔄", "pending": "⏳", "cancelled": "❌"}

        # Priority indicators (subtle)
        priority_indicators = {"high": "🔴", "medium": "🟡", "low": "🟢"}

        for i, todo in enumerate(todos, 1):
            status = todo.get("status", "pending")
            content = todo.get("content", "")
            priority = todo.get("priority", "medium")

            # Get emojis
            status_emoji = status_emojis.get(status, "○")
            priority_emoji = priority_indicators.get(priority, "")

            # Format the line
            line = f"{status_emoji} {i}. {content}"
            if priority_emoji:
                line += f" {priority_emoji}"

            formatted_lines.append(line)

        return formatted_lines

    def _format_tool_message(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use message with permission indicator based on approval mode."""
        # Check if this is a destructive operation
        is_destructive = tool_name.lower() in (
            "write",
            "edit",
            "bash",
            "shell",
            "terminal",
            "delete",
            "rm",
        )

        # Get tool icon
        tool_icons = {
            "read": "📖",
            "write": "✏️",
            "edit": "✏️",
            "bash": "💻",
            "shell": "💻",
            "terminal": "💻",
            "search": "🔍",
            "grep": "🔍",
            "find": "🔍",
            "list": "📁",
            "ls": "📁",
            "glob": "📁",
            "git": "📦",
            "fetch": "🌐",
            "web": "🌐",
        }
        icon = "🔧"
        for key, emoji in tool_icons.items():
            if key in tool_name.lower():
                icon = emoji
                break

        # Format tool message
        if tool_name == "read" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Reading: {file_path}"
        elif tool_name == "write" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Writing: {file_path}"
        elif tool_name == "edit" and "filePath" in tool_input:
            file_path = tool_input["filePath"]
            if len(file_path) > 50:
                file_path = "..." + file_path[-47:]
            msg = f"{icon} Editing: {file_path}"
        elif tool_name in ("bash", "shell", "terminal"):
            cmd = tool_input.get("command", "")
            if len(cmd) > 50:
                cmd = cmd[:47] + "..."
            msg = f"{icon} Running: {cmd}"
        elif tool_name in ("search", "grep"):
            pattern = tool_input.get("pattern", tool_input.get("query", ""))
            if len(pattern) > 30:
                pattern = pattern[:27] + "..."
            msg = f"{icon} Searching: {pattern}"
        elif tool_name in ("list", "ls", "glob"):
            path = tool_input.get("path", tool_input.get("directory", "."))
            msg = f"{icon} Listing: {path}"
        else:
            # Generic tool message
            msg = f"{icon} {tool_name}"
            if tool_input:
                first_key = list(tool_input.keys())[0] if tool_input else None
                if first_key:
                    val = str(tool_input[first_key])[:30]
                    msg = f"{icon} {tool_name}: {val}"

        # Add permission indicator for destructive operations
        if is_destructive:
            mode = getattr(self, "approval_mode", "ask")
            if mode == "auto":
                msg = f"🟢 {msg}"
            elif mode == "ask":
                msg = f"🟡 {msg}"
            elif mode == "deny":
                msg = f"🔴 {msg}"

        return msg

    def _format_tool_output(self, tool_name: str, output: Any, log: ConversationLog) -> bool:
        """Format and display tool output with proper JSON parsing.

        Returns True if output was formatted and displayed, False otherwise.
        """
        import json

        if not output:
            return False

        output_str = str(output)

        # Try to parse as JSON
        try:
            # Check if it looks like JSON
            stripped = output_str.strip()
            if not stripped.startswith("{") and not stripped.startswith("["):
                return False

            data = json.loads(output_str)

            tool_lower = tool_name.lower()

            # Handle TODO/Task lists
            if "todo" in tool_lower or self._is_todo_list(data):
                self._display_todo_list(data, log)
                return True

            # Handle file search results (glob, grep, search)
            if any(x in tool_lower for x in ("glob", "search", "grep", "find")):
                self._display_file_results(data, tool_name, log)
                return True

            # Handle task lists (Claude Code style)
            if "task" in tool_lower and isinstance(data, list):
                self._display_task_list(data, log)
                return True

            # Handle errors
            if isinstance(data, dict) and ("error" in data or "errors" in data):
                self._display_error_result(data, log)
                return True

            # Handle plan entries
            if isinstance(data, list) and data and isinstance(data[0], dict) and "step" in data[0]:
                self._display_plan(data, log)
                return True

            # Generic success/result dicts and ordinary JSON list/dict payloads now
            # fall through to add_tool_call, which renders a single compact line with
            # a one-line summary - much less noisy than the per-field panel.
            # (Errors, todos, plans, and file search results above still take the
            # custom paths since their structure is genuinely useful to see.)

        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        return False

    def _display_todo_list(self, data: Any, log: ConversationLog) -> None:
        """Display a TODO list with nice formatting."""
        from rich.text import Text

        if isinstance(data, dict) and "todos" in data:
            data = data["todos"]

        if not isinstance(data, list):
            return

        if not data:
            self._call_ui(log.write, Text("  📋 No tasks", style="#71717a"))
            return

        # Count statuses
        completed = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("completed", "done")
        )
        in_progress = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("in_progress", "active")
        )
        pending = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("pending", None)
        )

        # Header with summary
        parts = []
        if completed:
            parts.append(f"✅ {completed}")
        if in_progress:
            parts.append(f"🔄 {in_progress}")
        if pending:
            parts.append(f"○ {pending}")

        header = Text()
        header.append("  📋 ", style="#06b6d4")
        header.append(f"Tasks: {' · '.join(parts) if parts else 'none'}\n", style="#e4e4e7")
        self._call_ui(log.write, header)

        # Task items (limit to 8)
        for item in data[:8]:
            if not isinstance(item, dict):
                continue

            status = item.get("status", "pending")
            title = item.get("title", item.get("name", item.get("description", str(item))))
            priority = item.get("priority", "normal")

            # Status icons
            status_icons = {
                "completed": ("✅", "#22c55e"),
                "done": ("✅", "#22c55e"),
                "in_progress": ("🔄", "#a855f7"),
                "active": ("🔄", "#a855f7"),
                "pending": ("○", "#71717a"),
                "blocked": ("🚫", "#ef4444"),
            }
            icon, color = status_icons.get(status, ("○", "#71717a"))

            # Priority styling
            title_style = "#e4e4e7"
            if priority in ("high", "important"):
                title_style = "#f59e0b"
            elif priority in ("critical", "urgent"):
                title_style = "#ef4444"
            elif status in ("completed", "done"):
                title_style = "#71717a"

            line = Text()
            line.append(f"    {icon} ", style=color)
            line.append(f"{str(title)}\n", style=title_style)
            self._call_ui(log.write, line)

        if len(data) > 8:
            more = Text()
            more.append(f"    ... and {len(data) - 8} more\n", style="#71717a")
            self._call_ui(log.write, more)

    def _display_file_results(self, data: Any, tool_name: str, log: ConversationLog) -> None:
        """Display file search results."""
        from rich.text import Text

        files = []
        if isinstance(data, list):
            files = [str(f) for f in data if f]
        elif isinstance(data, dict):
            files = data.get("files", data.get("matches", data.get("results", [])))
            if not isinstance(files, list):
                return

        if not files:
            self._call_ui(log.write, Text("  🔍 No matches found\n", style="#71717a"))
            return

        # Header
        header = Text()
        header.append("  🔍 ", style="#06b6d4")
        header.append(f"Found {len(files)} file{'s' if len(files) != 1 else ''}\n", style="#e4e4e7")
        self._call_ui(log.write, header)

        # File list (limit to 6)
        for f in files[:6]:
            ext = str(f).split(".")[-1].lower() if "." in str(f) else ""
            icons = {
                "py": "🐍",
                "js": "📜",
                "ts": "📜",
                "rs": "🦀",
                "go": "🐹",
                "md": "📝",
                "json": "⚙️",
                "yaml": "⚙️",
            }
            icon = icons.get(ext, "📄")

            path_str = str(f)
            if len(path_str) > 55:
                path_str = "..." + path_str[-52:]

            line = Text()
            line.append(f"    {icon} ", style="#52525b")
            line.append(f"{path_str}\n", style="#06b6d4")
            self._call_ui(log.write, line)

        if len(files) > 6:
            more = Text()
            more.append(f"    ... and {len(files) - 6} more\n", style="#71717a")
            self._call_ui(log.write, more)

    def _display_task_list(self, data: list, log: ConversationLog) -> None:
        """Display Claude Code style task list."""
        from rich.text import Text

        header = Text()
        header.append("  📝 ", style="#a855f7")
        header.append(f"{len(data)} task{'s' if len(data) != 1 else ''}\n", style="#e4e4e7")
        self._call_ui(log.write, header)

        for task in data[:5]:
            if not isinstance(task, dict):
                continue

            status = task.get("status", "pending")
            subject = task.get("subject", task.get("title", ""))
            task_id = task.get("id", "")

            icons = {
                "completed": ("✅", "#22c55e"),
                "in_progress": ("⏳", "#a855f7"),
                "pending": ("○", "#71717a"),
            }
            icon, color = icons.get(status, ("○", "#71717a"))

            line = Text()
            line.append(f"    {icon} ", style=color)
            if task_id:
                line.append(f"[{task_id}] ", style="#52525b")
            line.append(
                f"{str(subject)}\n", style="#e4e4e7" if status != "completed" else "#71717a"
            )
            self._call_ui(log.write, line)

    def _display_error_result(self, data: dict, log: ConversationLog) -> None:
        """Display error result."""
        from rich.text import Text

        errors = data.get("errors", [data.get("error")]) if isinstance(data, dict) else []

        header = Text()
        header.append("  ⚠️ ", style="#ef4444")
        header.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}\n", style="#ef4444")
        self._call_ui(log.write, header)

        for err in errors[:3]:
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            line = Text()
            line.append("    ✕ ", style="#ef4444")
            line.append(f"{str(msg)}\n", style="#ef4444")
            self._call_ui(log.write, line)

    def _display_plan(self, data: list, log: ConversationLog) -> None:
        """Display plan steps."""
        from rich.text import Text

        header = Text()
        header.append("  📋 ", style="#a855f7")
        header.append("Plan:\n", style="#e4e4e7")
        self._call_ui(log.write, header)

        for i, step in enumerate(data[:5], 1):
            if not isinstance(step, dict):
                continue

            desc = step.get("description", step.get("step", step.get("action", "")))
            status = step.get("status", "pending")

            icon = "✓" if status in ("completed", "done") else str(i)
            color = "#22c55e" if status in ("completed", "done") else "#a855f7"

            line = Text()
            line.append(f"    {icon}. ", style=color)
            line.append(f"{str(desc)}\n", style="#e4e4e7")
            self._call_ui(log.write, line)

    def _display_success_result(self, data: dict, tool_name: str, log: ConversationLog) -> None:
        """Display success/result dict."""
        from rich.text import Text

        success = data.get("success", data.get("ok", True))
        result_val = data.get("result", data.get("message", data.get("output", "")))

        line = Text()
        if success:
            line.append("  ✓ ", style="#22c55e")
            if result_val:
                line.append(f"{str(result_val)}\n", style="#e4e4e7")
            else:
                line.append("Success\n", style="#22c55e")
        else:
            line.append("  ✕ ", style="#ef4444")
            error = data.get("error", data.get("message", "Failed"))
            line.append(f"{str(error)}\n", style="#ef4444")
        self._call_ui(log.write, line)

    def _display_generic_list(self, data: list, tool_name: str, log: ConversationLog) -> None:
        """Display a generic list."""
        from rich.text import Text

        header = Text()
        header.append(f"  ✦ {tool_name}: ", style="#a855f7")
        header.append(f"{len(data)} items\n", style="#e4e4e7")
        self._call_ui(log.write, header)

        for item in data[:5]:
            line = Text()
            line.append("    • ", style="#52525b")

            if isinstance(item, dict):
                display = None
                for key in ("name", "title", "path", "message", "value", "text"):
                    if key in item:
                        display = item[key]
                        break
                if display is None:
                    display = str(item)
                line.append(f"{str(display)}\n", style="#e4e4e7")
            else:
                line.append(f"{str(item)}\n", style="#e4e4e7")
            self._call_ui(log.write, line)

        if len(data) > 5:
            more = Text()
            more.append(f"    ... and {len(data) - 5} more\n", style="#71717a")
            self._call_ui(log.write, more)

    def _display_generic_dict(self, data: dict, tool_name: str, log: ConversationLog) -> None:
        """Display a generic dict."""
        from rich.text import Text

        for key, val in list(data.items())[:4]:
            line = Text()
            line.append(f"  {key}: ", style="#a855f7")
            val_str = str(val)
            if len(val_str) > 50:
                val_str = val_str[:47] + "..."
            line.append(f"{val_str}\n", style="#e4e4e7")
            self._call_ui(log.write, line)

        if len(data) > 4:
            more = Text()
            more.append(f"  ... +{len(data) - 4} more fields\n", style="#71717a")
            self._call_ui(log.write, more)

    def _format_tool_message_rich(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use message as a single compact line.

        Style: `<icon> <target>` - icon conveys the action, target shows what
        is being acted on. Paths are made relative to cwd. No "Reading:" /
        "Modifying:" labels because the icon already says so.
        """
        tool_lower = tool_name.lower()

        tool_icons = {
            "read": "↳",
            "write": "↲",
            "edit": "⟳",
            "patch": "⟳",
            "bash": "▸",
            "shell": "▸",
            "terminal": "▸",
            "exec": "▸",
            "run": "▸",
            "search": "⌕",
            "grep": "⌕",
            "find": "⌕",
            "glob": "⋮",
            "list": "⋮",
            "ls": "⋮",
            "tree": "⋮",
            "git": "◎",
            "fetch": "◎",
            "web": "◎",
            "http": "◎",
            "create": "↲",
            "mkdir": "⋮",
            "delete": "✕",
            "rm": "✕",
        }
        icon = "•"
        for key, ic in tool_icons.items():
            if key in tool_lower:
                icon = ic
                break

        def _relpath(p: str) -> str:
            if not p:
                return p
            try:
                if os.path.isabs(p):
                    rel = os.path.relpath(p, os.getcwd())
                    if not rel.startswith(".."):
                        return rel
            except Exception:
                pass
            return p

        def _first_arg(*keys: str) -> str:
            for key in keys:
                value = tool_input.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        # Cover snake_case and camelCase: harness tools, ACP agents, and the
        # codex-sdk runtime all spell these keys differently.
        file_path = _relpath(
            _first_arg(
                "filePath", "file_path", "path", "file", "abs_path", "filename", "target_file"
            )
        )

        # Substring matching ("read_file", "Read file", "edit" all count as reads/
        # edits); exact-name matching left every external agent in the generic branch.
        def _matches(*fragments: str) -> bool:
            return any(fragment in tool_lower for fragment in fragments)

        if _matches("read", "write", "edit", "patch", "create") and file_path:
            return f"{icon} {file_path}"
        if _matches("bash", "shell", "terminal", "exec", "command", "run"):
            cmd = _first_arg("command", "cmd", "script")
            if cmd:
                return f"{icon} {cmd}"
        if _matches("search", "grep", "find"):
            query = _first_arg("pattern", "query", "search", "regex")
            if query:
                return f"{icon} {query}"
        if _matches("list", "ls", "glob", "tree"):
            path = _relpath(_first_arg("path", "directory", "dir_path"))
            if path:
                return f"{icon} {path}"
        if tool_lower == "todo_write":
            todos = tool_input.get("todos", [])
            return f"{icon} todo list ({len(todos)} items)"
        if _matches("fetch", "web", "http"):
            url = _first_arg("url", "uri")
            if url:
                return f"{icon} {url}"
        if file_path:
            return f"{icon} {tool_name} {file_path}"

        # Generic: show a short hint of the first argument value, not full JSON.
        if tool_input:
            first_key = next(iter(tool_input), None)
            if first_key:
                val_str = str(tool_input[first_key])
                if len(val_str) > 80:
                    val_str = val_str[:77] + "…"
                return f"{icon} {tool_name} {val_str}"
        return f"{icon} {tool_name}"

    def _write_collapsed_changes_line(
        self, log: ConversationLog, files_modified: list, file_diffs: dict
    ) -> None:
        """One muted line for file changes, hidden details, expandable on demand.

        The full file panel and inline diffs are intentionally not printed; the
        user opens them with ``:diff`` (working tree) or ``:work verbose``
        (inline in the transcript).
        """
        count = len(files_modified)
        total_add = sum(d.get("additions", 0) for d in file_diffs.values())
        total_del = sum(d.get("deletions", 0) for d in file_diffs.values())
        line = Text()
        line.append("  ▸ ", style=f"bold {SQ_COLORS.info}")
        label = f"{count} file{'s' if count != 1 else ''} changed"
        if total_add or total_del:
            label += f" (+{total_add}/-{total_del})"
        line.append(label, style=SQ_COLORS.text_secondary)
        line.append("  ·  ", style=SQ_COLORS.text_muted)
        line.append(":diff", style=f"bold {SQ_COLORS.info}")
        line.append(" to view  ·  ", style=SQ_COLORS.text_muted)
        line.append(":work verbose", style=f"bold {SQ_COLORS.info}")
        line.append(" for inline diffs\n", style=SQ_COLORS.text_muted)
        log.write(line)

    def _format_free_inference_offers(self, offers, offer_status) -> Text:
        """Render curated fallback/free setup offers."""
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['green']}")
        t.append("Free / Local Inference\n\n", style=f"bold {THEME['text']}")
        t.append(
            "  Curated setup hints. Use :providers free --live for current model routes.\n\n",
            style=THEME["muted"],
        )
        if not offers:
            t.append("  No matching free inference options found.\n", style=THEME["warning"])
            return t
        for offer in offers[:14]:
            status = offer_status(offer)
            status_style = THEME["success"] if status == "ready" else THEME["warning"]
            t.append(f"  {offer.provider:<14}", style=f"bold {THEME['cyan']}")
            t.append(f"{offer.offer_kind:<16}", style=THEME["green"])
            t.append(f"{offer.access_mode:<9}", style=THEME["muted"])
            t.append(f"{status}\n", style=status_style)
            t.append(f"    {offer.summary}\n", style=THEME["text"])
            if offer.superqode_command:
                t.append("    use: ", style=THEME["muted"])
                t.append(f"{offer.superqode_command}\n", style=THEME["cyan"])
            t.append("\n")
        t.append("  Live scan: ", style=THEME["muted"])
        t.append(":providers free --live openrouter", style=THEME["cyan"])
        t.append(" or ", style=THEME["muted"])
        t.append(":providers free --live models-dev\n", style=THEME["cyan"])
        return t

    def _format_live_free_inference(self, candidates, errors, sources) -> Text:
        """Render live zero-price model routes."""
        t = Text()
        source_label = ", ".join(sources or ["openrouter", "models-dev", "litellm"])
        t.append("\n  ◈ ", style=f"bold {THEME['green']}")
        t.append("Live Free Model Routes\n\n", style=f"bold {THEME['text']}")
        t.append(f"  Sources: {source_label}\n", style=THEME["muted"])
        t.append(
            "  These are zero-price model routes from live catalogs; rate limits can change.\n\n",
            style=THEME["muted"],
        )
        if not candidates:
            t.append("  No live free model routes found.\n", style=THEME["warning"])
        for item in candidates[:20]:
            ctx = f"{item.context_window:,}" if item.context_window else "-"
            tools = "tools" if item.supports_tools else "no-tools"
            t.append(f"  {item.source:<11}", style=THEME["cyan"])
            t.append(f"{item.provider:<18}", style=f"bold {THEME['text']}")
            t.append(f"{item.model}\n", style=THEME["green"])
            t.append(f"    ctx={ctx}  {tools}  source={item.source_url}\n", style=THEME["muted"])
        if len(candidates) > 20:
            t.append(
                f"\n  ... and {len(candidates) - 20} more. Use CLI --json for all rows.\n",
                style=THEME["dim"],
            )
        if errors:
            t.append("\n  Source errors:\n", style=THEME["warning"])
            for error in errors:
                t.append(f"    {error['source']}: {error['error']}\n", style=THEME["warning"])
        t.append("\n  CLI JSON: ", style=THEME["muted"])
        t.append("superqode providers scan-free --live --json\n", style=THEME["cyan"])
        return t

    def _format_acp_doctor_results(self, results: list[dict], live: bool = False) -> Text:
        """Render ACP diagnostics for TUI."""
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("ACP Agent Doctor\n\n", style=f"bold {THEME['text']}")

        if not results:
            t.append("  No ACP agents found.\n", style=THEME["muted"])
            return t

        for result in results[:20]:
            installed = bool(result.get("installed"))
            status_style = THEME["success"] if installed else THEME["warning"]
            status = "installed" if installed else "missing"
            t.append(f"  {result.get('short_name', '-'):<16}", style=f"bold {THEME['cyan']}")
            t.append(f"{status:<10}", style=status_style)
            t.append(f"{result.get('name', '-')}\n", style=THEME["text"])

            if result.get("command"):
                t.append("    command: ", style=THEME["muted"])
                t.append(f"{result['command']}\n", style=THEME["dim"])
            if result.get("missing_env_vars"):
                t.append("    env:     ", style=THEME["muted"])
                t.append(
                    f"set one of {', '.join(result['missing_env_vars'])}\n",
                    style=THEME["warning"],
                )
            if not installed and result.get("install_command"):
                t.append("    install: ", style=THEME["muted"])
                t.append(f"{result['install_command']}\n", style=THEME["cyan"])

            live_result = result.get("live")
            if live_result:
                started = bool(live_result.get("started"))
                t.append("    protocol:", style=THEME["muted"])
                t.append(
                    " started" if started else " not started",
                    style=THEME["success"] if started else THEME["warning"],
                )
                if live_result.get("session"):
                    t.append("  session", style=THEME["success"])
                if live_result.get("models"):
                    t.append(f"  models={len(live_result['models'])}", style=THEME["cyan"])
                if live_result.get("modes"):
                    t.append(f"  modes={len(live_result['modes'])}", style=THEME["cyan"])
                t.append("\n")
                if live_result.get("error"):
                    t.append("    error:   ", style=THEME["muted"])
                    t.append(f"{live_result['error']}\n", style=THEME["error"])
            t.append("\n")

        if not live:
            t.append("  Action: ", style=THEME["muted"])
            t.append(":acp doctor <agent> live", style=THEME["cyan"])
            t.append(" to run protocol startup check\n", style=THEME["muted"])

        return t

    def _format_diff_review(self, sections: list[tuple[str, str]]) -> str:
        """Build a review document with a file index and full patches."""
        sections = [(label, text.strip()) for label, text in sections if text and text.strip()]
        if not sections:
            return ""

        all_stats: list[dict[str, Any]] = []
        for label, text in sections:
            for stat in self._diff_file_stats(text):
                stat["section"] = label
                all_stats.append(stat)

        total_adds = sum(int(item.get("additions") or 0) for item in all_stats)
        total_dels = sum(int(item.get("deletions") or 0) for item in all_stats)
        lines: list[str] = [
            "SuperQode Diff Review",
            "=" * 22,
            "",
            f"Files: {len(all_stats)}   +{total_adds} -{total_dels}",
            "",
            "Keys: copy all, search in your terminal/editor, use :diff after more edits.",
            "",
        ]

        if all_stats:
            lines.extend(["Files", "-----"])
            for index, item in enumerate(all_stats, 1):
                path = item.get("path") or "(unknown)"
                section = item.get("section") or "Diff"
                adds = int(item.get("additions") or 0)
                dels = int(item.get("deletions") or 0)
                lines.append(f"{index:>2}. [{section}] {path}  +{adds} -{dels}")
            lines.append("")

        lines.extend(["Patches", "-------"])
        for label, text in sections:
            lines.extend(["", f"## {label}", ""])
            lines.append(text)
        return "\n".join(lines).strip()

    def _format_diff_file_index(self, sections: list[tuple[str, str]]) -> str:
        """Return only the file index for quick review in the log."""
        stats = self._diff_review_entries(sections)
        if not stats:
            return "No changed files."
        total_adds = sum(int(item.get("additions") or 0) for item in stats)
        total_dels = sum(int(item.get("deletions") or 0) for item in stats)
        lines = [f"Changed files ({len(stats)})  +{total_adds} -{total_dels}"]
        for index, item in enumerate(stats, 1):
            lines.append(
                f"  {index:>2}. [{item.get('section')}] {item.get('path')}  "
                f"+{int(item.get('additions') or 0)} -{int(item.get('deletions') or 0)}"
            )
        lines.append("Use :diff <path> to open one file.")
        return "\n".join(lines)

    def _format_diff_entry_review(
        self,
        entry: dict[str, Any],
        *,
        index: int,
        total: int,
    ) -> str:
        """Build a focused one-file diff review document."""
        path = entry.get("path") or "(unknown)"
        section = entry.get("section") or "Diff"
        adds = int(entry.get("additions") or 0)
        dels = int(entry.get("deletions") or 0)
        patch = str(entry.get("patch") or "").strip()
        return "\n".join(
            [
                "SuperQode Diff Review",
                "=" * 22,
                "",
                f"File {index + 1}/{total}: [{section}] {path}   +{adds} -{dels}",
                "",
                "Keys: n next, p previous, a all files, y approve pending, r reject pending, Ctrl+C copy, Esc close.",
                "",
                "Patch",
                "-----",
                patch,
            ]
        ).strip()

    def _render_plan_review(self, log: ConversationLog) -> None:
        pending = getattr(self, "_pending_plan_request", "").strip()
        if not pending and not self._plan_manager.tasks:
            mode = "ON" if getattr(self, "_plan_mode_enabled", False) else "OFF"
            log.add_info(f"Plan mode: {mode}")
            log.add_info(
                "Usage: :plan <task>, :plan approve, :plan edit, :plan reject, :plan on, :plan off"
            )
            log.add_info("No internal task plan is active yet.")
            return

        # Render the plan
        t = Text()
        t.append(f"\n  📋 ", style=f"bold {THEME['purple']}")
        t.append("Plan Review\n", style=f"bold {THEME['purple']}")
        if pending:
            state = getattr(self, "_pending_plan_status", "") or "pending"
            state_style = {
                "pending": THEME["warning"],
                "approved": THEME["success"],
                "rejected": THEME["error"],
            }.get(state, THEME["muted"])
            t.append("  Request: ", style=THEME["muted"])
            t.append(pending[:220], style=THEME["text"])
            if len(pending) > 220:
                t.append("...", style=THEME["dim"])
            t.append("\n  State:   ", style=THEME["muted"])
            t.append(state, style=f"bold {state_style}")
            t.append("\n\n")
        else:
            t.append(f"  {self._plan_manager.current_plan_name}\n\n", style=THEME["muted"])

        completed, total, percentage = self._plan_manager.get_progress()
        if total:
            t.append(
                f"  Progress: {completed}/{total} ({percentage:.0f}%)\n\n", style=THEME["muted"]
            )
        else:
            t.append("  No structured TODOs were emitted yet.\n\n", style=THEME["muted"])

        status_icons = {
            TaskStatus.PENDING: ("⏳", THEME["muted"]),
            TaskStatus.IN_PROGRESS: ("🔄", THEME["cyan"]),
            TaskStatus.COMPLETED: ("✅", THEME["success"]),
            TaskStatus.FAILED: ("❌", THEME["error"]),
        }

        for i, task in enumerate(self._plan_manager.tasks, 1):
            icon, color = status_icons.get(task.status, ("○", THEME["muted"]))
            t.append(f"  {icon} ", style=color)
            t.append(f"{i}. ", style=THEME["muted"])

            if task.status == TaskStatus.COMPLETED:
                t.append(task.content, style=f"strike {color}")
            else:
                t.append(
                    task.content,
                    style=color if task.status == TaskStatus.IN_PROGRESS else THEME["text"],
                )
            t.append("\n", style="")

        t.append("\n  Actions: ", style=THEME["muted"])
        t.append(":plan approve", style=THEME["cyan"])
        t.append("  ", style=THEME["dim"])
        t.append(":plan edit", style=THEME["cyan"])
        t.append("  ", style=THEME["dim"])
        t.append(":plan reject", style=THEME["cyan"])
        t.append("\n", style="")
        log.write(t)
