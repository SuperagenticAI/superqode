"""
Unified Log Formatter for SuperQode.

Converts LogEntry objects into Rich renderables with consistent styling
across all provider modes.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from rich.console import RenderableType, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.box import ROUNDED

from superqode.logging.unified_log import LogConfig, LogEntry, LogVerbosity

import superqode.code_theme  # noqa: F401  (registers the "superqode" Pygments style)


class _ThemeColors:
    """Fallback defaults for the live theme accessor."""

    _DEFAULTS = {
        "purple": "#a855f7",
        "magenta": "#d946ef",
        "pink": "#ec4899",
        "cyan": "#06b6d4",
        "green": "#22c55e",
        "orange": "#f97316",
        "gold": "#fbbf24",
        "blue": "#3b82f6",
        "success": "#22c55e",
        "error": "#ef4444",
        "warning": "#f59e0b",
        "info": "#06b6d4",
        "text": "#e4e4e7",
        "muted": "#a1a1aa",
        "dim": "#71717a",
        "bg": "#0a0a0a",
        "bg_surface": "#111111",
    }

    @classmethod
    def resolve(cls, name: str) -> str:
        try:
            from superqode.app.constants import THEME as _LIVE

            if name in _LIVE:
                return _LIVE[name]
        except Exception:
            pass
        return cls._DEFAULTS.get(name, "#e4e4e7")


class _ThemeAccessor:
    """Allows Theme.purple style access backed by the live theme."""

    def __getattr__(self, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        return _ThemeColors.resolve(name)


Theme = _ThemeAccessor()  # type: ignore[no-redef]


# Thought category icons
THOUGHT_ICONS = {
    "planning": "📋",
    "analyzing": "🔬",
    "deciding": "🤔",
    "searching": "🔍",
    "reading": "📖",
    "writing": "✏️",
    "debugging": "🐛",
    "executing": "⚡",
    "verifying": "✅",
    "testing": "🧪",
    "refactoring": "🔧",
    "general": "💭",
}

# Tool icons
TOOL_ICONS = {
    "read": "↳",
    "write": "↲",
    "edit": "⟳",
    "shell": "▸",
    "bash": "▸",
    "search": "⌕",
    "glob": "⋮",
    "grep": "⌕",
    "todo": "📋",
}

# Status indicators
STATUS_ICONS = {
    "pending": ("○", "muted"),
    "running": ("◐", "purple"),
    "success": ("✦", "success"),
    "error": ("✕", "error"),
}

# Language detection for syntax highlighting
LANGUAGE_PATTERNS = {
    r"\.py$": "python",
    r"\.js$": "javascript",
    r"\.ts$": "typescript",
    r"\.jsx$": "jsx",
    r"\.tsx$": "tsx",
    r"\.rs$": "rust",
    r"\.go$": "go",
    r"\.java$": "java",
    r"\.rb$": "ruby",
    r"\.sh$": "bash",
    r"\.bash$": "bash",
    r"\.zsh$": "zsh",
    r"\.json$": "json",
    r"\.yaml$": "yaml",
    r"\.yml$": "yaml",
    r"\.toml$": "toml",
    r"\.md$": "markdown",
    r"\.html$": "html",
    r"\.css$": "css",
    r"\.sql$": "sql",
}


def detect_language(file_path: str = "", content: str = "") -> str:
    """Detect programming language from file path or content."""
    # Try file path first
    if file_path:
        for pattern, lang in LANGUAGE_PATTERNS.items():
            if re.search(pattern, file_path, re.IGNORECASE):
                return lang

    # Try content heuristics
    if content:
        content_lower = content.lower()
        if content.startswith("#!/bin/bash") or content.startswith("#!/bin/sh"):
            return "bash"
        if "def " in content and ":" in content:
            return "python"
        if "function " in content or "const " in content or "let " in content:
            return "javascript"
        if "fn " in content and "->" in content:
            return "rust"
        if "func " in content and "{" in content:
            return "go"

    return "text"


def classify_thought(text: str) -> str:
    """Classify thinking text into a category."""
    text_lower = text.lower()

    if any(w in text_lower for w in ["test", "pytest", "expect", "assert"]):
        return "testing"
    if any(w in text_lower for w in ["verify", "confirm", "check", "validate"]):
        return "verifying"
    if any(w in text_lower for w in ["run", "execute", "command", "shell"]):
        return "executing"
    if any(w in text_lower for w in ["debug", "error", "fix", "bug"]):
        return "debugging"
    if any(w in text_lower for w in ["plan", "step", "approach", "let me", "i'll"]):
        return "planning"
    if any(w in text_lower for w in ["analyze", "understand", "examine", "look at"]):
        return "analyzing"
    if any(w in text_lower for w in ["search", "find", "look for", "grep"]):
        return "searching"
    if any(w in text_lower for w in ["read", "file", "content"]):
        return "reading"
    if any(w in text_lower for w in ["write", "create", "add"]):
        return "writing"
    if any(w in text_lower for w in ["refactor", "restructure", "clean"]):
        return "refactoring"

    return "general"


def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


class UnifiedLogFormatter:
    """
    Formats LogEntry objects into Rich renderables.

    Provides consistent formatting across all provider modes with
    support for different verbosity levels.
    """

    def __init__(self, config: Optional[LogConfig] = None):
        self.config = config or LogConfig.normal()

    def _code_theme(self) -> str:
        """Resolve the syntax palette at render time so :theme is immediate."""
        if self.config.code_theme:
            return self.config.code_theme
        from superqode.rendering.markdown import active_code_theme

        return active_code_theme()

    def format(self, entry: LogEntry) -> Optional[RenderableType]:
        """Format a log entry into a Rich renderable."""
        handlers = {
            "thinking": self._format_thinking,
            "tool_call": self._format_tool_call,
            "tool_result": self._format_tool_result,
            "tool_update": self._format_tool_update,
            "response_delta": self._format_response_delta,
            "response_final": self._format_response_final,
            "code_block": self._format_code_block,
            "info": self._format_info,
            "warning": self._format_warning,
            "error": self._format_error,
            "system": self._format_system,
            "user": self._format_user,
            "assistant": self._format_assistant,
        }

        handler = handlers.get(entry.kind)
        if handler:
            return handler(entry)
        return None

    def _format_thinking(self, entry: LogEntry) -> RenderableType:
        """Format thinking/reasoning entry with engaging display."""
        text = entry.text.strip()
        if not text:
            return Text("")

        # Get category and icon
        category = entry.data.get("category", classify_thought(text))
        icon = THOUGHT_ICONS.get(category, "💭")

        # Clean up common prefixes that make thoughts less readable
        cleaned_text = text
        skip_prefixes = [
            "I need to ",
            "I should ",
            "I will ",
            "I'll ",
            "I'm going to ",
            "Let me ",
            "Now I ",
            "Next I ",
            "First, I ",
            "Then I ",
        ]
        for prefix in skip_prefixes:
            if cleaned_text.lower().startswith(prefix.lower()):
                # Keep first letter capitalized after removing prefix
                cleaned_text = cleaned_text[len(prefix) :]
                if cleaned_text:
                    cleaned_text = cleaned_text[0].upper() + cleaned_text[1:]
                break

        # Truncate if needed
        if self.config.verbosity == LogVerbosity.MINIMAL:
            cleaned_text = truncate(cleaned_text, 50)
        elif self.config.verbosity == LogVerbosity.NORMAL:
            cleaned_text = truncate(cleaned_text, self.config.max_thinking_chars)

        # Category-based styling follows the active theme.
        category_styles = {
            "planning": (Theme.purple, "Planning: "),
            "analyzing": (Theme.cyan, "Analyzing: "),
            "debugging": (Theme.warning, "Debugging: "),
            "testing": (Theme.success, "Testing: "),
            "verifying": (Theme.success, "Verifying: "),
            "searching": (Theme.purple, ""),
            "reading": (Theme.purple, ""),
            "writing": (Theme.magenta, ""),
            "executing": (Theme.orange, ""),
        }

        style_info = category_styles.get(category)

        line = Text()
        line.append(f"  {icon} ", style=f"bold {Theme.pink}")

        if style_info and style_info[1]:
            # Add category prefix for certain types
            line.append(style_info[1], style=f"bold {style_info[0]}")
            line.append(cleaned_text, style=f"italic {Theme.muted}")
        else:
            line.append(cleaned_text, style=f"italic {Theme.muted}")

        return line

    def _format_tool_call(self, entry: LogEntry) -> RenderableType:
        """Format tool call entry with action-oriented display."""
        name = entry.tool_name
        args = entry.tool_args
        file_path = entry.file_path
        command = entry.command

        # Map tool names to action verbs
        action_verbs = {
            "read": ("📖 Reading", Theme.cyan),
            "write": ("✏️ Writing", Theme.magenta),
            "edit": ("🔧 Editing", Theme.orange),
            "bash": ("⚡ Running", Theme.purple),
            "shell": ("⚡ Running", Theme.purple),
            "search": ("🔍 Searching", Theme.purple),
            "grep": ("🔍 Searching", Theme.purple),
            "glob": ("📂 Finding", Theme.blue),
            "todo": ("📋 Updating", Theme.cyan),
            "task": ("📝 Managing", Theme.purple),
        }

        # Find matching action
        action_text = None
        action_style = Theme.purple
        name_lower = name.lower()
        for key, (verb, style) in action_verbs.items():
            if key in name_lower:
                action_text = verb
                action_style = style
                break

        fell_back_to_name = False
        if not action_text:
            # Fallback: the name itself (ACP titles are often the command).
            # Truncate so a command-as-title doesn't flood the log.
            action_text = f"◐ {truncate(name, 60)}"
            fell_back_to_name = True

        line = Text()
        line.append(f"  {action_text}", style=f"bold {action_style}")

        # Add context based on verbosity
        if self.config.verbosity == LogVerbosity.MINIMAL:
            pass  # Just action
        elif file_path:
            # Shorten path for display
            display_path = file_path
            if len(display_path) > 50:
                display_path = "..." + display_path[-47:]
            line.append(f" {display_path}", style=Theme.muted)
        elif command:
            # Skip when the fallback header already shows this command
            if fell_back_to_name and (name == command or name.startswith(command[:30])):
                pass
            else:
                cmd_display = truncate(
                    command, 50 if self.config.verbosity == LogVerbosity.NORMAL else 100
                )
                line.append(f"  $ {cmd_display}", style=Theme.muted)
        elif self.config.show_tool_args and args:
            # Show most relevant arg
            relevant_arg = None
            for key in ("path", "file_path", "pattern", "query", "command", "content"):
                if key in args:
                    val = str(args[key])
                    if len(val) > 40:
                        val = val[:37] + "..."
                    relevant_arg = val
                    break
            if relevant_arg:
                line.append(f" {relevant_arg}", style=Theme.muted)
            elif self.config.verbosity == LogVerbosity.VERBOSE:
                args_str = str(args)[:80]
                line.append(f"  {args_str}", style=Theme.dim)

        return line

    def _format_tool_result(self, entry: LogEntry) -> RenderableType:
        """Format tool result entry."""
        name = entry.tool_name
        success = entry.is_success
        result = entry.tool_result_text

        # Get tool icon
        tool_icon = "•"
        for key, icon in TOOL_ICONS.items():
            if key in name.lower():
                tool_icon = icon
                break

        status = "success" if success else "error"
        status_icon, status_color_name = STATUS_ICONS.get(status, ("●", "muted"))
        status_color = getattr(Theme, status_color_name)

        # ACP titles are often the full command — truncate so the header
        # stays one line instead of duplicating the call line + output.
        display_name = name if len(name) <= 60 else truncate(name, 60)

        # Strip a command echo prefix: shell/ACP results sometimes repeat the
        # command as the first line, which duplicates the call line above.
        command = entry.command
        if command and len(command) > 10 and result.startswith(command):
            result = result[len(command) :].lstrip("\n ")
        elif len(name) > 20 and result.startswith(name):
            result = result[len(name) :].lstrip("\n ")

        line = Text()
        line.append(f"  {status_icon} ", style=f"bold {status_color}")
        line.append(f"{tool_icon} ", style=Theme.dim)
        line.append(display_name, style=Theme.text)

        # One-line diff summary for file mutations (cheap stats only, no diff text)
        diff = entry.diff_stats
        if diff and self.config.verbosity != LogVerbosity.MINIMAL:
            add, dele = diff
            line.append("  ± ", style=Theme.dim)
            if add:
                line.append(f"+{add}", style=f"bold {Theme.success}")
            if add and dele:
                line.append(" ", style="")
            if dele:
                line.append(f"−{dele}", style=f"bold {Theme.error}")

        # Add result based on verbosity
        if self.config.verbosity == LogVerbosity.MINIMAL:
            line.append(" done" if success else " failed", style=Theme.muted)
        elif self.config.show_tool_result and result:
            # Try to format as structured JSON first
            formatted_json = self._format_json_result(name, result)
            if formatted_json:
                return Group(line, formatted_json)

            # Regular result display
            max_chars = self.config.max_tool_output_chars
            result_display = truncate(result, max_chars)

            # Check if result looks like code
            if self._looks_like_code(result_display):
                lang = detect_language(entry.file_path, result_display)
                if self.config.syntax_highlight:
                    code_result = Syntax(
                        result_display,
                        lang,
                        theme=self._code_theme(),
                        word_wrap=True,
                        line_numbers=False,
                    )
                    return Group(line, Text("    → ", style=Theme.muted), code_result)

            if result_display:
                line.append(f"\n    → {result_display}", style=Theme.muted)

        return line

    def _format_tool_update(self, entry: LogEntry) -> RenderableType:
        """Format tool update entry."""
        # Similar to tool_call but for progress updates
        return self._format_tool_call(entry)

    def _format_response_delta(self, entry: LogEntry) -> RenderableType:
        """Format streaming response chunk."""
        text = entry.text
        if not text:
            return Text("")

        # For streaming, just show plain text (final will render markdown)
        return Text(text, style=Theme.text)

    def _format_response_final(self, entry: LogEntry) -> RenderableType:
        """Format final complete response."""
        text = entry.text
        if not text:
            return Text("")

        # Render as markdown with syntax highlighting for code blocks
        if "```" in text:
            return Markdown(
                text,
                code_theme=self._code_theme(),
                inline_code_lexer="python",
            )

        return Text(text, style=Theme.text)

    def _format_code_block(self, entry: LogEntry) -> RenderableType:
        """Format a code block with syntax highlighting."""
        code = entry.text
        language = entry.data.get("language", "")

        if not language:
            language = detect_language(content=code)

        if self.config.syntax_highlight:
            return Syntax(
                code,
                language,
                theme=self._code_theme(),
                word_wrap=True,
                line_numbers=True,
            )

        return Text(code, style=Theme.text)

    def _format_info(self, entry: LogEntry) -> RenderableType:
        """Format info message."""
        return Text(f"  ℹ️ {entry.text}", style=Theme.pink)

    def _format_warning(self, entry: LogEntry) -> RenderableType:
        """Format warning message."""
        return Text(f"  ⚠️ {entry.text}", style=Theme.warning)

    def _format_error(self, entry: LogEntry) -> RenderableType:
        """Format error message."""
        return Text(f"  ❌ {entry.text}", style=Theme.error)

    def _format_system(self, entry: LogEntry) -> RenderableType:
        """Format system message."""
        return Text(f"  ✨ {entry.text}", style=f"italic {Theme.muted}")

    def _format_user(self, entry: LogEntry) -> RenderableType:
        """Format user message."""
        return Panel(
            Text(entry.text, style=Theme.text, overflow="fold"),
            title=f"[bold {Theme.cyan}]👩‍💻👨‍💻 >[/]",
            border_style=Theme.dim,
            box=ROUNDED,
            padding=(0, 1),
        )

    def _format_assistant(self, entry: LogEntry) -> RenderableType:
        """Format assistant message."""
        text = entry.text
        agent = entry.agent or "Assistant"

        content = (
            Markdown(text, code_theme=self._code_theme())
            if "```" in text
            else Text(text, style=Theme.text, overflow="fold")
        )

        return Panel(
            content,
            title=f"[bold {Theme.purple}]🤖 {agent}[/]",
            border_style=Theme.purple,
            box=ROUNDED,
            padding=(0, 1),
        )

    def _format_json_result(self, tool_name: str, result: str) -> Optional[RenderableType]:
        """
        Intelligently format JSON tool results into engaging displays.

        Handles various JSON structures:
        - TODO lists
        - File lists (search results)
        - Task definitions
        - Error reports
        - Generic objects/arrays
        """
        import json

        # Skip if not JSON
        result_stripped = result.strip()
        if not result_stripped or (
            not result_stripped.startswith("{") and not result_stripped.startswith("[")
        ):
            return None

        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            return None

        # Route to specific formatters based on tool name or data structure
        tool_lower = tool_name.lower()

        # TODO/Task list
        if "todo" in tool_lower or self._looks_like_todo_list(data):
            return self._format_todo_list(data)

        # File search results
        if any(x in tool_lower for x in ("glob", "search", "find", "grep")):
            return self._format_file_results(data)

        # Read/Write file result
        if any(x in tool_lower for x in ("read", "write", "edit")):
            return self._format_file_operation(data)

        # Task list (Claude Code style)
        if "task" in tool_lower and isinstance(data, list):
            return self._format_task_list(data)

        # Error/diagnostic result
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            return self._format_error_result(data)

        # Plan entries
        if isinstance(data, list) and data and isinstance(data[0], dict) and "step" in data[0]:
            return self._format_plan_entries(data)

        # Generic list of items with identifiable structure
        if isinstance(data, list) and data:
            return self._format_generic_list(data)

        # Generic dict
        if isinstance(data, dict):
            return self._format_generic_dict(data)

        return None

    def _looks_like_todo_list(self, data) -> bool:
        """Check if data looks like a TODO list."""
        if not isinstance(data, list):
            return False
        if not data:
            return False
        first = data[0]
        if not isinstance(first, dict):
            return False
        return any(k in first for k in ("status", "title", "priority", "completed"))

    def _format_todo_list(self, data) -> Optional[RenderableType]:
        """Format TODO list with visual status indicators."""
        if not isinstance(data, list):
            if isinstance(data, dict) and "todos" in data:
                data = data["todos"]
            else:
                return None

        if not data:
            return Text("    📋 No tasks", style=Theme.muted)

        lines = []
        for item in data:
            if not isinstance(item, dict):
                continue

            status = item.get("status", "pending")
            title = item.get("title", item.get("name", item.get("description", str(item))))
            priority = item.get("priority", "normal")

            # Status icons with colors
            status_icons = {
                "completed": ("✅", Theme.success),
                "done": ("✅", Theme.success),
                "in_progress": ("🔄", Theme.purple),
                "active": ("🔄", Theme.purple),
                "pending": ("○", Theme.muted),
                "blocked": ("🚫", Theme.error),
                "failed": ("✕", Theme.error),
            }
            icon, icon_style = status_icons.get(status, ("○", Theme.muted))

            # Priority styling
            title_style = Theme.text
            if priority in ("high", "important"):
                title_style = Theme.warning
            elif priority in ("critical", "urgent"):
                title_style = Theme.error
            elif status in ("completed", "done"):
                title_style = Theme.muted

            line = Text()
            line.append(f"    {icon} ", style=icon_style)
            line.append(str(title)[:80], style=title_style)
            lines.append(line)

        # Summary line
        completed = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("completed", "done")
        )
        in_progress = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("in_progress", "active")
        )
        pending = sum(
            1 for t in data if isinstance(t, dict) and t.get("status") in ("pending", None)
        )

        parts = []
        if completed:
            parts.append(f"✅ {completed}")
        if in_progress:
            parts.append(f"🔄 {in_progress}")
        if pending:
            parts.append(f"○ {pending}")

        summary = Text()
        summary.append("    📋 ", style=Theme.cyan)
        summary.append(f"Tasks: {' · '.join(parts) if parts else 'none'}", style=Theme.text)

        return Group(summary, *lines[:10])  # Limit to 10 items

    def _format_file_results(self, data) -> Optional[RenderableType]:
        """Format file search/glob results."""
        files = []

        if isinstance(data, list):
            files = [str(f) for f in data if f]
        elif isinstance(data, dict):
            files = data.get("files", data.get("matches", data.get("results", [])))
            if not isinstance(files, list):
                return None

        if not files:
            return Text("    🔍 No matches found", style=Theme.muted)

        lines = []
        for i, f in enumerate(files[:8]):  # Show max 8 files
            line = Text()
            line.append("    ", style=Theme.dim)
            # File icon based on extension
            ext = str(f).split(".")[-1].lower() if "." in str(f) else ""
            icon = "📄"
            if ext in ("py", "pyw"):
                icon = "🐍"
            elif ext in ("js", "ts", "jsx", "tsx"):
                icon = "📜"
            elif ext in ("rs",):
                icon = "🦀"
            elif ext in ("go",):
                icon = "🐹"
            elif ext in ("md", "txt", "rst"):
                icon = "📝"
            elif ext in ("json", "yaml", "yml", "toml"):
                icon = "⚙️"

            line.append(f"{icon} ", style=Theme.dim)
            # Truncate long paths
            path_str = str(f)
            if len(path_str) > 60:
                path_str = "..." + path_str[-57:]
            line.append(path_str, style=Theme.cyan)
            lines.append(line)

        if len(files) > 8:
            more = Text()
            more.append(f"    ... and {len(files) - 8} more", style=Theme.muted)
            lines.append(more)

        header = Text()
        header.append("    🔍 ", style=Theme.cyan)
        header.append(f"Found {len(files)} file{'s' if len(files) != 1 else ''}", style=Theme.text)

        return Group(header, *lines)

    def _format_file_operation(self, data) -> Optional[RenderableType]:
        """Format read/write/edit file results."""
        if not isinstance(data, dict):
            return None

        path = data.get("path", data.get("file", ""))
        success = data.get("success", data.get("ok", True))
        content = data.get("content", data.get("data", ""))
        lines_affected = data.get("lines", data.get("lines_changed", 0))

        result = Text()
        result.append("    ", style=Theme.dim)

        if success:
            result.append("✓ ", style=Theme.success)
            if path:
                result.append(f"{path}", style=Theme.cyan)
            if lines_affected:
                result.append(f" ({lines_affected} lines)", style=Theme.muted)
        else:
            result.append("✕ ", style=Theme.error)
            error = data.get("error", "Operation failed")
            result.append(str(error)[:60], style=Theme.error)

        return result

    def _format_task_list(self, data) -> Optional[RenderableType]:
        """Format Claude Code style task lists."""
        if not isinstance(data, list):
            return None

        lines = []
        for task in data[:5]:  # Limit display
            if not isinstance(task, dict):
                continue

            status = task.get("status", "pending")
            subject = task.get("subject", task.get("title", ""))
            task_id = task.get("id", "")

            icons = {
                "completed": ("✅", Theme.success),
                "in_progress": ("⏳", Theme.purple),
                "pending": ("○", Theme.muted),
            }
            icon, style = icons.get(status, ("○", Theme.muted))

            line = Text()
            line.append(f"    {icon} ", style=style)
            if task_id:
                line.append(f"[{task_id}] ", style=Theme.dim)
            line.append(
                str(subject)[:60], style=Theme.text if status != "completed" else Theme.muted
            )
            lines.append(line)

        header = Text()
        header.append("    📝 ", style=Theme.purple)
        header.append(f"{len(data)} task{'s' if len(data) != 1 else ''}", style=Theme.text)

        return Group(header, *lines)

    def _format_error_result(self, data) -> Optional[RenderableType]:
        """Format error/diagnostic results."""
        errors = data.get("errors", [data.get("error")]) if isinstance(data, dict) else []
        if not errors:
            return None

        lines = []
        for err in errors[:5]:
            line = Text()
            line.append("    ✕ ", style=Theme.error)
            if isinstance(err, dict):
                msg = err.get("message", err.get("error", str(err)))
                loc = err.get("location", err.get("file", ""))
                line.append(str(msg)[:60], style=Theme.error)
                if loc:
                    line.append(f" @ {loc}", style=Theme.muted)
            else:
                line.append(str(err)[:70], style=Theme.error)
            lines.append(line)

        header = Text()
        header.append("    ⚠️ ", style=Theme.error)
        header.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}", style=Theme.error)

        return Group(header, *lines)

    def _format_plan_entries(self, data) -> Optional[RenderableType]:
        """Format plan/step entries."""
        if not isinstance(data, list):
            return None

        lines = []
        for i, step in enumerate(data[:6], 1):
            if not isinstance(step, dict):
                continue

            desc = step.get("description", step.get("step", step.get("action", "")))
            status = step.get("status", "pending")

            icons = {
                "completed": "✓",
                "done": "✓",
                "in_progress": "→",
                "active": "→",
                "pending": str(i),
            }
            icon = icons.get(status, str(i))
            style = Theme.success if status in ("completed", "done") else Theme.text

            line = Text()
            line.append(
                f"    {icon}. ",
                style=Theme.purple if status not in ("completed", "done") else Theme.success,
            )
            line.append(str(desc)[:65], style=style)
            lines.append(line)

        header = Text()
        header.append("    📋 ", style=Theme.purple)
        header.append("Plan:", style=Theme.text)

        return Group(header, *lines)

    def _format_generic_list(self, data) -> Optional[RenderableType]:
        """Format a generic list of items."""
        if not data:
            return None

        lines = []
        for item in data[:6]:
            line = Text()
            line.append("    • ", style=Theme.dim)

            if isinstance(item, dict):
                # Try to find a display field
                display = None
                for key in ("name", "title", "path", "message", "value", "text", "description"):
                    if key in item:
                        display = item[key]
                        break
                if display is None:
                    display = str(item)
                line.append(str(display)[:70], style=Theme.text)
            else:
                line.append(str(item)[:70], style=Theme.text)

            lines.append(line)

        if len(data) > 6:
            more = Text()
            more.append(f"    ... and {len(data) - 6} more items", style=Theme.muted)
            lines.append(more)

        return Group(*lines) if lines else None

    def _format_generic_dict(self, data) -> Optional[RenderableType]:
        """Format a generic dictionary result."""
        if not data:
            return None

        # Check for common success/result patterns
        if "success" in data or "ok" in data or "result" in data:
            success = data.get("success", data.get("ok", True))
            result_val = data.get("result", data.get("message", data.get("output", "")))

            line = Text()
            line.append("    ", style=Theme.dim)
            if success:
                line.append("✓ ", style=Theme.success)
                if result_val:
                    line.append(str(result_val)[:60], style=Theme.text)
                else:
                    line.append("Success", style=Theme.success)
            else:
                line.append("✕ ", style=Theme.error)
                error = data.get("error", data.get("message", "Failed"))
                line.append(str(error)[:60], style=Theme.error)
            return line

        # Show key-value pairs for small dicts
        if len(data) <= 4:
            lines = []
            for key, val in list(data.items())[:4]:
                line = Text()
                line.append("    ", style=Theme.dim)
                line.append(f"{key}: ", style=Theme.purple)
                val_str = str(val)
                if len(val_str) > 50:
                    val_str = val_str[:47] + "..."
                line.append(val_str, style=Theme.text)
                lines.append(line)
            return Group(*lines) if lines else None

        # For larger dicts, just show a summary
        line = Text()
        line.append("    ", style=Theme.dim)
        line.append("{ ", style=Theme.muted)
        keys = list(data.keys())[:4]
        line.append(", ".join(keys), style=Theme.text)
        if len(data) > 4:
            line.append(f", ... +{len(data) - 4}", style=Theme.muted)
        line.append(" }", style=Theme.muted)
        return line

    def _format_todo_result(self, result: str) -> Optional[RenderableType]:
        """Format todo list result nicely. (Legacy - redirects to new formatter)"""
        try:
            import json

            data = json.loads(result)
            return self._format_todo_list(data)
        except (json.JSONDecodeError, TypeError):
            return None

    def _looks_like_code(self, text: str) -> bool:
        """Check if text looks like code."""
        indicators = [
            "def ",
            "class ",
            "function ",
            "const ",
            "let ",
            "var ",
            "import ",
            "from ",
            "fn ",
            "func ",
            "pub ",
            "async ",
            "await ",
            "return ",
            "{",
            "}",
            "=>",
            "->",
        ]
        return any(ind in text for ind in indicators) and len(text) > 20
