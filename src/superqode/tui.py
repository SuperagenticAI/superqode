"""
SuperQode TUI - Clean, Professional Developer Experience
Using Rich + prompt_toolkit for a polished CLI interface.

Features:
- Beautiful welcome screen with ASCII art
- Clean, focused prompt box with clear input area
- Smooth thinking animations
- Syntax-highlighted responses
- Professional exit/disconnect messages
"""

from __future__ import annotations

import os
import re
import sys
import time
import random
import shutil
import textwrap
import threading
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.status import Status
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.align import Align
from rich.box import ROUNDED, DOUBLE, SIMPLE, HEAVY, MINIMAL, Box
from rich.rule import Rule
from rich.columns import Columns
from rich.style import Style
from rich.padding import Padding

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory, FileHistory
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.formatted_text import HTML


# ============================================================================
# TEAM CONFIGURATION READER
# ============================================================================


@dataclass
class TeamRole:
    """Represents a configured team role."""

    mode: str
    role: str
    description: str
    model: str
    provider: str
    coding_agent: str
    enabled: bool
    job_description: str = ""
    execution_mode: str = "acp"  # "acp", "byok", or "local"
    agent: str = ""  # Agent ID for ACP mode

    @property
    def command(self) -> str:
        return f":{self.mode} {self.role}"

    @property
    def display_name(self) -> str:
        return f"{self.mode.upper()}.{self.role}"

    @property
    def exec_mode_display(self) -> str:
        """Get display string for execution mode."""
        if self.execution_mode == "acp":
            return f"ACP•{self.agent or self.coding_agent}"
        else:
            return f"BYOK•{self.provider}"


@dataclass
class TeamConfig:
    """Team configuration loaded from YAML."""

    team_name: str
    description: str
    roles: List[TeamRole]

    @property
    def enabled_roles(self) -> List[TeamRole]:
        return [r for r in self.roles if r.enabled]

    @property
    def enabled_count(self) -> int:
        return len(self.enabled_roles)

    def get_roles_by_mode(self, mode: str) -> List[TeamRole]:
        return [r for r in self.roles if r.mode == mode]

    def get_enabled_roles_by_mode(self, mode: str) -> List[TeamRole]:
        return [r for r in self.enabled_roles if r.mode == mode]


def load_team_config() -> TeamConfig:
    """Load team configuration from superqode.yaml."""
    try:
        from superqode.config import load_config

        config = load_config()

        team_name = "Development Team"
        description = "AI-powered software development team"

        if hasattr(config, "superqode") and config.superqode:
            team_name = getattr(config.superqode, "team_name", team_name)
            description = getattr(config.superqode, "description", description)

        roles = []

        if hasattr(config, "team") and config.team and hasattr(config.team, "modes"):
            for mode_name, mode_config in config.team.modes.items():
                if hasattr(mode_config, "roles") and mode_config.roles:
                    for role_name, role_config in mode_config.roles.items():
                        enabled = getattr(role_config, "enabled", True)

                        # Get execution mode (explicit or inferred)
                        exec_mode = getattr(role_config, "mode", "")
                        agent_id = getattr(role_config, "agent", "")
                        coding_agent = getattr(role_config, "coding_agent", "opencode")

                        # Infer execution mode if not explicit
                        if not exec_mode:
                            if agent_id or (
                                coding_agent
                                and coding_agent not in ("superqode", "superqode", "byok")
                            ):
                                exec_mode = "acp"
                            else:
                                exec_mode = "byok"

                        # Get model from agent_config if ACP mode
                        model = getattr(role_config, "model", "")
                        provider = getattr(role_config, "provider", "")

                        agent_config = getattr(role_config, "agent_config", None)
                        if agent_config:
                            if not model:
                                model = getattr(agent_config, "model", "glm-4.7")
                            if not provider:
                                provider = getattr(agent_config, "provider", "")

                        roles.append(
                            TeamRole(
                                mode=mode_name,
                                role=role_name,
                                description=getattr(role_config, "description", ""),
                                model=model or "glm-4.7",
                                provider=provider or "opencode",
                                coding_agent=coding_agent,
                                enabled=enabled,
                                job_description=getattr(role_config, "job_description", ""),
                                execution_mode=exec_mode,
                                agent=agent_id or coding_agent,
                            )
                        )

        return TeamConfig(team_name=team_name, description=description, roles=roles)

    except Exception:
        return TeamConfig(
            team_name="Development Team",
            description="AI-powered software development team",
            roles=[
                TeamRole(
                    "dev",
                    "fullstack",
                    "Full-stack development",
                    "glm-4.7",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
                TeamRole(
                    "qe",
                    "fullstack",
                    "Full-stack QE",
                    "grok-code",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
                TeamRole(
                    "devops",
                    "fullstack",
                    "Full-stack DevOps",
                    "glm-4.7",
                    "opencode",
                    "opencode",
                    True,
                    "",
                    "acp",
                    "opencode",
                ),
            ],
        )


# ============================================================================
# ASCII ART LOGO
# ============================================================================

SUPERQODE_ASCII = """
[bold #a855f7] ____  _   _ ____  _____ ____   ___    ___  ____  _____[/]
[bold #c084fc]/ ___|| | | |  _ \\| ____|  _ \\ / _ \\  / _ \\|  _ \\| ____|[/]
[bold #ec4899]\\___ \\| | | | |_) |  _| | |_) | | | || | | | | | |  _|  [/]
[bold #f97316] ___) | |_| |  __/| |___|  _ <| |_| || |_| | |_| | |___ [/]
[bold #fb923c]|____/ \\___/|_|   |_____|_| \\_\\\\__\\_\\ \\___/|____/|_____|[/]
"""

# Compact logo for smaller terminals
SUPERQODE_ASCII_COMPACT = """[bold bright_cyan]SUPERQODE[/]"""


# ============================================================================
# EMOJI & CONSTANTS
# ============================================================================

EMOJI = {
    "brain": "🧠",
    "rocket": "🚀",
    "sparkles": "✨",
    "lightning": "⚡",
    "star": "⭐",
    "fire": "🔥",
    "gem": "💎",
    "robot": "🤖",
    "laptop": "💻",
    "test_tube": "🧪",
    "wrench": "🔧",
    "house": "🏠",
    "link": "🔗",
    "folder": "📁",
    "check": "✅",
    "cross": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "gear": "⚙️",
    "search": "🔍",
    "thought": "💭",
    "writing": "🖋️",
    "tools": "🛠️",
    "package": "📦",
    "wave": "👋",
    "point_right": "👉",
    "bulb": "💡",
    "zap": "⚡",
    "target": "🎯",
    "trophy": "🏆",
    "magic": "🪄",
    "crystal": "🔮",
    "hourglass": "⏳",
    "clock": "🕐",
    "green_circle": "🟢",
    "yellow_circle": "🟡",
    "blue_circle": "🔵",
    "white_circle": "⚪",
    "plug": "🔌",
    "key": "🔑",
    "book": "📖",
    "globe": "🌐",
    "heart": "❤️",
    "thumbs_up": "👍",
    "eyes": "👀",
    "speech": "💬",
    "terminal": "▶",
    "prompt": "❯",
    "arrow": "→",
    "dot": "●",
}

# Thinking messages with emojis
THINKING_MESSAGES = [
    ("Analyzing your request", "brain"),
    ("Understanding context", "search"),
    ("Thinking deeply", "thought"),
    ("Processing information", "gear"),
    ("Reading codebase", "book"),
    ("Exploring files", "folder"),
    ("Formulating response", "writing"),
    ("Crafting solution", "tools"),
    ("Connecting the dots", "link"),
    ("Almost there", "rocket"),
]


# ============================================================================
# OUTPUT FILTERING
# ============================================================================


class OutputFilter:
    """Filter agent output to show only the response."""

    TOOL_OPERATIONS = [
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Grep",
        "Glob",
        "Search",
        "List",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "LSP",
        "NotebookEdit",
    ]

    def __init__(self):
        self.ansi_pattern = re.compile(r"\x1b\[[0-9;]*m|\[\d+(?:;\d+)*m")

    def filter(self, text: str) -> str:
        """Filter out file operations from agent output."""
        if not text:
            return text

        lines = text.split("\n")
        filtered = []

        for line in lines:
            clean = self.ansi_pattern.sub("", line).strip()

            # Skip tool operation lines
            should_skip = False
            if clean.startswith("|"):
                after_pipe = clean[1:].strip()
                for op in self.TOOL_OPERATIONS:
                    if after_pipe.startswith(op) and (
                        len(after_pipe) == len(op) or after_pipe[len(op)] in " \t"
                    ):
                        should_skip = True
                        break

            if not should_skip:
                filtered.append(line)

        result = "\n".join(filtered)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()


output_filter = OutputFilter()


# ============================================================================
# THINKING ANIMATION - Clean, Professional Spinner
# ============================================================================


class ThinkingSpinner:
    """
    Clean thinking animation using Rich Status.
    Shows a professional spinner with elapsed time.
    """

    def __init__(self, console: Console, message: str = "Thinking..."):
        self.console = console
        self.initial_message = message
        self._status: Optional[Status] = None
        self._start_time = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._msg_index = 0
        self._last_msg_change = 0.0

    def _get_status_text(self) -> str:
        """Generate the status text with emoji and time."""
        elapsed = time.time() - self._start_time

        # Change message every 3 seconds
        if time.time() - self._last_msg_change > 3.0:
            self._msg_index = (self._msg_index + 1) % len(THINKING_MESSAGES)
            self._last_msg_change = time.time()

        msg_text, emoji_key = THINKING_MESSAGES[self._msg_index]
        emoji = EMOJI.get(emoji_key, EMOJI["brain"])

        return f"  {emoji} [bold cyan]{msg_text}[/bold cyan] [dim]({elapsed:.1f}s)[/dim]"

    def _update_loop(self):
        """Background thread to update status text."""
        while self._running and self._status:
            try:
                self._status.update(self._get_status_text())
                time.sleep(0.1)
            except Exception:
                break

    def __enter__(self):
        """Start the animation."""
        self._start_time = time.time()
        self._last_msg_change = time.time()
        self._msg_index = random.randint(0, len(THINKING_MESSAGES) - 1)
        self._running = True

        # Create Rich Status with spinner
        self._status = self.console.status(
            self._get_status_text(),
            spinner="dots",
            spinner_style="bright_cyan",
        )
        self._status.__enter__()

        # Start update thread
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

        return self

    def __exit__(self, *args):
        """Stop the animation and show completion."""
        self._running = False

        if self._thread:
            self._thread.join(timeout=0.5)

        if self._status:
            self._status.__exit__(*args)

        elapsed = time.time() - self._start_time
        self.console.print(
            f"  [bold green]✓[/bold green] [green]Complete[/green] [dim]({elapsed:.1f}s)[/dim]"
        )


# ============================================================================
# RESPONSE PANEL - Clean Code Display
# ============================================================================


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting from text for clean display."""
    # Strip bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Strip italic: *text* or _text_
    text = re.sub(r"(?<![*\w])\*([^*]+?)\*(?![*\w])", r"\1", text)
    text = re.sub(r"(?<![_\w])_([^_]+?)_(?![_\w])", r"\1", text)

    # Strip strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # Strip inline code: `code`
    text = re.sub(r"`([^`]+?)`", r"\1", text)

    # Strip links: [text](url) -> text
    text = re.sub(r"\[([^\]]+?)\]\([^)]+?\)", r"\1", text)

    # Strip images: ![alt](url) -> alt
    text = re.sub(r"!\[([^\]]*?)\]\([^)]+?\)", r"\1", text)

    # Strip blockquotes: > text -> text
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Strip headers: # text -> text (keep the text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    return text


class ResponsePanel:
    """Display agent responses with syntax highlighting."""

    def __init__(self, console: Console):
        self.console = console
        self.filter = output_filter

    def display(self, content: str, title: str = "Response", agent_name: str = ""):
        """Display a response with code highlighting."""
        filtered = self.filter.filter(content)

        if not filtered.strip():
            return

        rendered = self._render_content(filtered)

        # Create header with agent name
        if agent_name:
            header = f"[bold bright_cyan]{EMOJI['robot']} {agent_name}[/bold bright_cyan]"
        else:
            header = f"[bold bright_cyan]{title}[/bold bright_cyan]"

        panel = Panel(
            rendered,
            title=header,
            title_align="left",
            border_style="bright_blue",
            box=ROUNDED,
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)

    def _render_content(self, content: str) -> Group:
        """Render content with syntax-highlighted code blocks - no raw markdown."""
        # Get terminal width for wrapping
        term_width = shutil.get_terminal_size().columns
        wrap_width = min(term_width - 10, 100)  # Conservative width

        # Pattern to match code blocks with optional language
        code_pattern = r"```(\w*)\n?(.*?)```"
        parts = []
        last_end = 0

        for match in re.finditer(code_pattern, content, re.DOTALL):
            # Add text before code block
            if match.start() > last_end:
                text = content[last_end : match.start()]
                if text.strip():
                    # Strip markdown and wrap text properly
                    clean_text = _strip_markdown(text.strip())
                    wrapped = textwrap.fill(clean_text, width=wrap_width)
                    parts.append(Text(wrapped))

            lang = match.group(1) or "text"
            code = match.group(2)

            # Language mapping
            lang_map = {
                "py": "python",
                "js": "javascript",
                "ts": "typescript",
                "sh": "bash",
                "yml": "yaml",
            }
            lang = lang_map.get(lang.lower(), lang) if lang else "text"

            # Create syntax highlighted code
            if code.strip():
                syntax = Syntax(
                    code.strip(),
                    lang,
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                    background_color="#000000",
                )
                parts.append(Text())  # Spacing
                parts.append(syntax)
                parts.append(Text())  # Spacing

            last_end = match.end()

        # Add remaining text after last code block
        if last_end < len(content):
            remaining = content[last_end:]
            if remaining.strip():
                # Strip markdown and wrap
                clean_text = _strip_markdown(remaining.strip())
                wrapped = textwrap.fill(clean_text, width=wrap_width)
                parts.append(Text(wrapped))

        return Group(*parts) if parts else Group(Text(_strip_markdown(content)))


# ============================================================================
# WELCOME SCREEN - Professional Landing Page
# ============================================================================


def print_welcome(console: Console, team_config: Optional[TeamConfig] = None):
    """Print a beautiful, professional welcome screen."""
    console.clear()

    if team_config is None:
        team_config = load_team_config()

    # Get terminal width for responsive layout
    term_width = shutil.get_terminal_size().columns

    # ASCII Logo (use compact for narrow terminals)
    console.print()
    if term_width >= 80:
        console.print(SUPERQODE_ASCII)
    else:
        console.print(SUPERQODE_ASCII_COMPACT)

    # Tagline
    console.print(
        Align.center(
            f"[bold white]{team_config.team_name}[/bold white] [dim]•[/dim] [dim]{team_config.description}[/dim]"
        )
    )
    console.print()

    # Separator
    console.print(Rule(style="bright_magenta"))
    console.print()

    # Quick start section in a clean grid
    enabled = team_config.enabled_roles

    if enabled:
        # Create a nice table for available agents
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 2),
            expand=False,
        )
        table.add_column("Icon", style="bold", width=3)
        table.add_column("Command", style="bold yellow", width=18)
        table.add_column("Mode", style="bold", width=14)
        table.add_column("Description", style="white")
        table.add_column("Model", style="dim cyan", width=15)

        mode_icons = {"dev": "💻", "qe": "🧪", "devops": "⚙️"}

        for role in enabled[:5]:
            icon = mode_icons.get(role.mode, "🔧")

            # Execution mode badge
            if role.execution_mode == "acp":
                exec_badge = f"[blue]ACP[/blue]•{role.agent[:8]}"
            else:
                exec_badge = f"[green]BYOK[/green]•{role.provider[:6]}"

            table.add_row(
                icon,
                role.command,
                exec_badge,
                role.description[:30] + "..." if len(role.description) > 30 else role.description,
                role.model[:12],
            )

        console.print(Align.center(table))

        if len(enabled) > 5:
            console.print(
                Align.center(
                    f"[dim]... and {len(enabled) - 5} more roles (use :roles to see all)[/dim]"
                )
            )

    console.print()
    console.print(Rule(style="dim cyan"))
    console.print()

    # Quick commands hint
    hints = Text()
    hints.append("  Quick Start: ", style="bold white")
    hints.append("🏠 :home", style="bold yellow")
    hints.append("  •  ", style="dim")
    hints.append("🚀 :i", style="bold yellow")
    hints.append("  •  ", style="dim")
    hints.append("📚 :s", style="bold yellow")
    hints.append("  •  ", style="dim")
    hints.append("🔌 :c", style="bold yellow")
    hints.append("  •  ", style="dim")
    hints.append("👋 :q", style="bold yellow")
    hints.append(" exit", style="dim")

    console.print()
    console.print(Align.center(hints))
    console.print()


def print_roles(console: Console, team_config: Optional[TeamConfig] = None):
    """Print all available roles in a clean format."""
    if team_config is None:
        team_config = load_team_config()

    console.print()

    # Header
    header = Text()
    header.append(f"{EMOJI['robot']} ", style="bold")
    header.append(team_config.team_name, style="bold white")
    header.append(" - Available Roles", style="dim")
    console.print(Align.center(header))
    console.print()

    # Legend
    console.print(
        Align.center(
            "[dim]Execution Modes:[/dim] [blue]ACP[/blue] = Coding Agent  [green]BYOK[/green] = Direct LLM API"
        )
    )
    console.print()

    mode_info = {
        "dev": (EMOJI["laptop"], "Development", "bright_green"),
        "qa": (EMOJI["test_tube"], "Quality Assurance", "bright_yellow"),
        "devops": (EMOJI["gear"], "DevOps", "bright_blue"),
    }

    for mode in ["dev", "qe", "devops"]:
        roles = team_config.get_roles_by_mode(mode)
        if not roles:
            continue

        icon, title, color = mode_info.get(mode, (EMOJI["wrench"], mode.upper(), "white"))

        # Mode header
        console.print(f"  [bold {color}]{icon} {title}[/bold {color}]")

        # Roles table
        for role in roles:
            status = (
                f"[green]{EMOJI['green_circle']}[/green]"
                if role.enabled
                else f"[dim]{EMOJI['white_circle']}[/dim]"
            )
            desc = role.description[:35] + "..." if len(role.description) > 35 else role.description

            # Execution mode badge
            if role.execution_mode == "acp":
                exec_badge = f"[blue]ACP[/blue]•{role.agent[:8]:<8}"
            else:
                exec_badge = f"[green]BYOK[/green]•{role.provider[:6]:<6}"

            console.print(
                f"    {status} [yellow]{role.command:<18}[/yellow] "
                f"{exec_badge} "
                f"[dim cyan]{role.model:<12}[/dim cyan] "
                f"[dim]{desc}[/dim]"
            )
        console.print()

    # Footer
    total = len(team_config.roles)
    enabled = team_config.enabled_count
    console.print(
        f"  [dim]{EMOJI['bulb']} {enabled}/{total} roles enabled. Edit superqode.yaml to configure.[/dim]"
    )
    console.print()

    # Commands hint
    console.print(
        f"  [dim]Commands:[/dim] [yellow]:agents connect[/yellow] (ACP)  [yellow]:providers use[/yellow] (BYOK)"
    )
    console.print()


# ============================================================================
# DISCONNECT & EXIT MESSAGES
# ============================================================================


def print_disconnect_message(console: Console, agent_name: str = "Agent"):
    """Print a clean disconnect message."""
    console.print()

    content = Text()
    content.append(f"{EMOJI['wave']} ", style="bold")
    content.append("Disconnected from ", style="white")
    content.append(agent_name, style="bold cyan")

    panel = Panel(
        content,
        border_style="cyan",
        box=ROUNDED,
        padding=(0, 2),
    )
    console.print(panel)
    console.print()


def print_exit_message(console: Console):
    """Print a clean exit message."""
    console.print()

    content = Text()
    content.append(f"{EMOJI['wave']} ", style="bold")
    content.append("Thanks for using ", style="white")
    content.append("SuperQode", style="bold bright_cyan")
    content.append("!", style="white")

    panel = Panel(
        content,
        border_style="bright_cyan",
        box=ROUNDED,
        padding=(0, 2),
    )
    console.print(panel)
    console.print()


# ============================================================================
# COMMAND COMPLETER
# ============================================================================


class SuperQodeCompleter(Completer):
    """Command completer with dynamic role loading."""

    def __init__(self):
        self.base_commands = [
            (":roles", "List all available roles"),
            (":agents", "List available ACP agents"),
            (":agents store", "Browse agent store"),
            (":agents connect", "Connect to an ACP agent (full coding capabilities)"),
            (":providers", "List available BYOK providers"),
            (":providers list", "List all BYOK providers"),
            (":providers use", "Use a BYOK provider (direct LLM API)"),
            (":disconnect", "Disconnect from agent/provider"),
            (":home", "Return to home screen"),
            (":files", "Show project files"),
            (":find", "Fuzzy search files"),
            (":recent", "Show recent files"),
            (":bookmark", "Manage bookmarks"),
            (":handoff", "Hand off to another role"),
            (":context", "Show work context"),
            (":approve", "Approve work"),
            (":help", "Show help"),
            (":h", "Alias for :help"),
            (":init", "Initialize SuperQode configuration"),
            (":i", "Alias for :init"),
            (":sidebar", "Show/hide sidebar"),
            (":s", "Alias for :sidebar"),
            (":connect", "Connect to an agent or provider"),
            (":c", "Alias for :connect"),
            (":clear", "Clear screen"),
            (":exit", "Exit SuperQode"),
            (":quit", "Exit SuperQode"),
            (":q", "Alias for :exit"),
        ]
        self._role_commands: Optional[List[tuple]] = None

    @property
    def commands(self) -> List[tuple]:
        if self._role_commands is None:
            self._load_role_commands()
        return self._role_commands + self.base_commands

    def _load_role_commands(self):
        self._role_commands = []
        try:
            team_config = load_team_config()
            for role in team_config.roles:
                # Show execution mode in description
                mode_badge = "ACP" if role.execution_mode == "acp" else "BYOK"
                desc = f"[{mode_badge}] {role.description} ({role.model})"
                if not role.enabled:
                    desc += " [disabled]"
                self._role_commands.append((role.command, desc))
        except Exception:
            self._role_commands = [
                (":qe fullstack", "[ACP] Full-stack QE"),
                (":qe api_tester", "[ACP] API Tester"),
            ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        if not text.startswith(":"):
            return

        for cmd, desc in self.commands:
            if cmd.lower().startswith(text):
                yield Completion(cmd, start_position=-len(text), display=cmd, display_meta=desc)


# Alias for backward compatibility
SuperQodeCompleter = SuperQodeCompleter


# ============================================================================
# ENHANCED PROMPT - Centered, Fully Visible Input Box
# ============================================================================


class EnhancedPrompt:
    """
    Clean, professional prompt centered on screen.

    Features:
    - Centered prompt box that's always fully visible
    - Mode indicator (HOME, DEV, QA, etc.)
    - Agent connection status
    - Tab completion for commands
    - History navigation
    - Footer hints always visible
    """

    # prompt_toolkit style
    STYLE = PTStyle.from_dict(
        {
            "prompt": "bold ansicyan",
            "mode": "bold ansigreen",
            "arrow": "bold ansiwhite",
            "input": "ansiwhite",
            "completion-menu": "bg:ansiblack ansigreen",
            "completion-menu.completion": "bg:ansiblack ansiwhite",
            "completion-menu.completion.current": "bg:ansicyan ansiblack bold",
            "completion-menu.meta": "bg:ansiblack ansigray",
            "completion-menu.meta.current": "bg:ansicyan ansiblack",
        }
    )

    def __init__(self, history_file: Optional[Path] = None):
        # Setup history
        if history_file:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            self.history = FileHistory(str(history_file))
        else:
            self.history = InMemoryHistory()

        # Key bindings
        self.bindings = KeyBindings()

        @self.bindings.add(Keys.ControlC)
        def _(event):
            event.app.exit(exception=KeyboardInterrupt())

        @self.bindings.add(Keys.ControlD)
        def _(event):
            event.app.exit(exception=EOFError())

        # Create session
        self.session = PromptSession(
            history=self.history,
            completer=SuperQodeCompleter(),
            style=self.STYLE,
            key_bindings=self.bindings,
            complete_while_typing=True,
            enable_history_search=True,
        )

        # State
        self.mode = "HOME"
        self.connected = False
        self.agent_name = ""
        self.execution_mode = ""  # "acp" or "byok"
        self.console = Console()

    def _get_mode_info(self) -> tuple:
        """Get mode icon, text, and color."""
        if self.connected and self.agent_name:
            # Show execution mode when connected
            if self.execution_mode == "acp":
                return EMOJI["link"], f"ACP • {self.agent_name.upper()}", "bright_blue"
            elif self.execution_mode == "byok":
                return EMOJI["zap"], f"BYOK • {self.agent_name.upper()}", "bright_green"
            else:
                return EMOJI["link"], self.agent_name.upper(), "bright_magenta"

        mode_map = {
            "HOME": (EMOJI["house"], "HOME", "bright_cyan"),
            "DEV": (EMOJI["laptop"], "DEV", "bright_green"),
            "QA": (EMOJI["test_tube"], "QA", "bright_yellow"),
            "DEVOPS": (EMOJI["gear"], "DEVOPS", "bright_blue"),
        }

        base = self.mode.split(".")[0].upper() if "." in self.mode else self.mode.upper()
        return mode_map.get(base, (EMOJI["wrench"], self.mode.upper(), "white"))

    def _get_box_width(self) -> int:
        """Get the prompt box width based on terminal size."""
        term_width = shutil.get_terminal_size().columns
        return min(term_width - 4, 70)

    def prompt(self, clear_screen: bool = False) -> str:
        """Show clean prompt with mode badge and get input.

        Args:
            clear_screen: If True, clears screen before showing prompt.
        """
        if clear_screen:
            self.console.clear()

        icon, mode_text, color = self._get_mode_info()

        # REMOVED EXTRA PRINT HERE to move badge fully up

        # Mode badge with extra text for HOME
        if mode_text == "HOME":
            display_text = f"{icon} {mode_text}    [dim]ready to code[/dim]"
        else:
            display_text = f"{icon} {mode_text}"

        self.console.print(f"[bold {color} reverse] {display_text} [/]")

        # Get input with simple prompt
        try:
            # Add a small prefix to the prompt to give it some horizontal breathing room
            result = self.session.prompt("❯ ")
        except (KeyboardInterrupt, EOFError):
            self.console.print()
            raise

        # Footer hints after input - reduced space to match badge-prompt gap
        self.console.print()

        hints = (
            f"  [bright_cyan]🏠 :home[/]  [dim]•[/]  "
            f"[bright_yellow]❓ :h[/] [dim][:help][/]  [dim]•[/]  "
            f"[bright_magenta]🚀 :i[/] [dim][:init][/]  [dim]•[/]  "
            f"[bright_blue]📚 :s[/] [dim][:sidebar][/]  [dim]•[/]  "
            f"[bright_green]🔌 :c[/] [dim][:connect][/]  [dim]•[/]  "
            f"[bright_red]👋 :q[/] [dim][:quit][/]"
        )
        self.console.print(hints)

        return result

    def set_mode(self, mode: str):
        """Set the current mode."""
        self.mode = mode

    def set_connected(self, agent_name: str, connected: bool = True, execution_mode: str = "acp"):
        """Set connection state.

        Args:
            agent_name: Name of the agent or provider
            connected: Whether connected or not
            execution_mode: "acp" for coding agent, "byok" for direct LLM
        """
        self.agent_name = agent_name
        self.connected = connected
        self.execution_mode = execution_mode


# ============================================================================
# MAIN TUI CLASS - Unified Interface
# ============================================================================


class SuperQodeUI:
    """Main TUI controller combining all components."""

    def __init__(self):
        self.console = Console()
        self.prompt = EnhancedPrompt(history_file=Path.home() / ".superqode" / "history")
        self.response_panel = ResponsePanel(self.console)
        self.output_filter = output_filter
        self._team_config: Optional[TeamConfig] = None

    @property
    def team_config(self) -> TeamConfig:
        if self._team_config is None:
            self._team_config = load_team_config()
        return self._team_config

    def reload_config(self):
        """Reload team configuration."""
        self._team_config = load_team_config()

    def print_welcome(self):
        """Print the welcome screen."""
        print_welcome(self.console, self.team_config)

    def print_roles(self):
        """Print all available roles."""
        print_roles(self.console, self.team_config)

    def get_input(self, clear_screen: bool = False) -> str:
        """Get user input with the enhanced prompt.

        Args:
            clear_screen: If True, clears screen before showing prompt.
        """
        return self.prompt.prompt(clear_screen=clear_screen)

    def wait_for_keypress(self):
        """Wait for user to press Enter before continuing."""
        self.console.print()
        self.console.print("[dim]  Press Enter to continue...[/dim]", end="")
        input()

    def set_mode(self, mode: str):
        """Set the current mode."""
        self.prompt.set_mode(mode)

    def set_agent(self, name: str, connected: bool = False, execution_mode: str = "acp"):
        """Set agent connection state.

        Args:
            name: Name of the agent or provider
            connected: Whether connected or not
            execution_mode: "acp" for coding agent, "byok" for direct LLM
        """
        self.prompt.set_connected(name, connected, execution_mode)

    def show_thinking(self, message: str = "Thinking..."):
        """Show thinking animation (context manager)."""
        return ThinkingSpinner(self.console, message)

    def display_response(self, content: str, agent_name: str = "Agent"):
        """Display an agent response."""
        self.response_panel.display(content, agent_name=agent_name)

    def filter_output(self, text: str) -> str:
        """Filter agent output."""
        return self.output_filter.filter(text)

    def print(self, *args, **kwargs):
        """Print to console."""
        self.console.print(*args, **kwargs)

    def clear(self):
        """Clear the console."""
        self.console.clear()

    def rule(self, title: str = "", style: str = "dim"):
        """Print a horizontal rule."""
        self.console.print(Rule(title=title, style=style))

    def print_disconnect(self, agent_name: str = "Agent"):
        """Print disconnect message."""
        print_disconnect_message(self.console, agent_name)

    def print_exit(self):
        """Print exit message."""
        print_exit_message(self.console)

    def print_error(self, message: str):
        """Print an error message."""
        self.console.print(f"  [bold red]✗[/bold red] [red]{message}[/red]")

    def print_success(self, message: str):
        """Print a success message."""
        self.console.print(f"  [bold green]✓[/bold green] [green]{message}[/green]")

    def print_info(self, message: str):
        """Print an info message."""
        self.console.print(f"  [bold blue]ℹ[/bold blue] [blue]{message}[/blue]")

    def print_warning(self, message: str):
        """Print a warning message."""
        self.console.print(f"  [bold yellow]⚠[/bold yellow] [yellow]{message}[/yellow]")


# Alias for backward compatibility
SuperQodeTUI = SuperQodeUI
