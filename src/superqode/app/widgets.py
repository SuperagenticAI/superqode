"""
SuperQode App Widgets - All UI widget classes.
"""

from __future__ import annotations

import math
import random
from time import monotonic
from typing import Any

from textual.widgets import Static, RichLog
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Group
from rich.box import ROUNDED, HEAVY

from .constants import (
    ASCII_LOGO,
    TAGLINE_PART1,
    GRADIENT,
    RAINBOW,
    THEME,
    ICONS,
    AGENT_COLORS,
    AGENT_ICONS,
)


class GradientLogo(Static):
    """ASCII logo with purple→pink→orange gradient - BIG display."""

    def render(self) -> Text:
        # Split and filter empty lines, but preserve leading whitespace
        lines = [line for line in ASCII_LOGO.split("\n") if line.strip()]
        result = Text()

        for i, line in enumerate(lines):
            color = GRADIENT[i % len(GRADIENT)]
            result.append(line, style=f"bold {color}")
            if i < len(lines) - 1:
                result.append("\n")

        return result


class ColorfulStatusBar(Static):
    """Colorful SuperQode status bar - always visible at top with BYOK status."""

    # BYOK status properties
    byok_provider: reactive[str] = reactive("")
    byok_model: reactive[str] = reactive("")
    byok_tokens: reactive[int] = reactive(0)
    byok_cost: reactive[float] = reactive(0.0)

    def render(self) -> Text:
        result = Text()

        # Logo part - with gradient colors
        super_colors = ["#a855f7", "#b366f9", "#c177fb", "#cf88fd", "#dd99ff"]
        for i, char in enumerate("Super"):
            color = super_colors[i % len(super_colors)]
            result.append(char, style=f"bold {color}")
        qode_colors = ["#ec4899", "#f472b6", "#f97316", "#fb923c"]
        for i, char in enumerate("Qode"):
            color = qode_colors[i % len(qode_colors)]
            result.append(char, style=f"bold {color}")
        result.append(" ✨", style="bold #fbbf24")
        result.append(" ", style="")
        # "Multi-Agentic" in normal text color (no gradient)
        result.append("Multi-Agentic", style="")
        result.append(" Orchestration of ", style=THEME["muted"])
        # "Coding Agents" in normal text color (no gradient)
        result.append("Coding Agents", style="")

        # BYOK status (if connected)
        if self.byok_provider:
            result.append("  │  ", style="#3f3f46")
            result.append(f"{self.byok_provider}", style="bold #10b981")
            if self.byok_model:
                # Show shortened model name
                model_short = (
                    self.byok_model.split("-")[0]
                    if "-" in self.byok_model
                    else self.byok_model[:12]
                )
                result.append(f"/{model_short}", style="#a1a1aa")

            # Show usage
            if self.byok_tokens > 0:
                result.append("  ", style="")
                if self.byok_tokens >= 1000:
                    result.append(f"{self.byok_tokens // 1000}K", style="#06b6d4")
                else:
                    result.append(f"{self.byok_tokens}", style="#06b6d4")
                result.append(" tok", style="#52525b")

            # Show cost
            if self.byok_cost > 0:
                result.append("  ", style="")
                if self.byok_cost >= 0.01:
                    result.append(f"${self.byok_cost:.2f}", style="#fbbf24")
                else:
                    result.append(f"${self.byok_cost:.3f}", style="#fbbf24")

        return result

    def update_byok_status(
        self, provider: str = "", model: str = "", tokens: int = 0, cost: float = 0.0
    ):
        """Update BYOK status display."""
        self.byok_provider = provider
        self.byok_model = model
        self.byok_tokens = tokens
        self.byok_cost = cost


class GradientTagline(Static):
    """Tagline with gradient colors for visual impact."""

    PART1_GRADIENT = ["#06b6d4", "#0ea5e9", "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7"]
    PART2_GRADIENT = ["#fbbf24", "#f59e0b", "#f97316", "#ef4444", "#ec4899"]

    def render(self) -> Text:
        result = Text()
        result.append("🚀 ", style="bold #06b6d4")

        part1 = TAGLINE_PART1
        for i, char in enumerate(part1):
            color_idx = int(i / len(part1) * len(self.PART1_GRADIENT))
            color_idx = min(color_idx, len(self.PART1_GRADIENT) - 1)
            color = self.PART1_GRADIENT[color_idx]
            result.append(char, style=f"bold {color}")

        result.append("  •  ", style="bold #71717a")

        part2 = "Automate Your SDLC"
        for i, char in enumerate(part2):
            color_idx = int(i / len(part2) * len(self.PART2_GRADIENT))
            color_idx = min(color_idx, len(self.PART2_GRADIENT) - 1)
            color = self.PART2_GRADIENT[color_idx]
            result.append(char, style=f"bold {color}")

        result.append(" ✨", style="bold #fbbf24")

        return result


class PulseWaveBar(Static):
    """Animated pulse wave bar - unique SuperQode style."""

    frame = reactive(0)
    WAVE_CHARS = "▁▂▃▄▅▆▇█▇▆▅▄▃▂▁"
    PULSE_COLORS = [
        "#7c3aed",
        "#8b5cf6",
        "#a855f7",
        "#c026d3",
        "#d946ef",
        "#ec4899",
        "#f472b6",
        "#fbbf24",
    ]

    def on_mount(self):
        self.auto_refresh = 1 / 20

    def render(self) -> Text:
        width = self.size.width or 80
        t = monotonic()
        result = Text()
        wave_len = len(self.WAVE_CHARS)

        for i in range(width):
            wave_primary = math.sin(t * 2 + i * 0.15) * 0.5
            wave_secondary = math.sin(t * 4 + i * 0.25 + math.pi / 3) * 0.3
            wave_tertiary = math.sin(t * 1.5 + i * 0.08 + math.pi / 2) * 0.2
            combined = (wave_primary + wave_secondary + wave_tertiary + 1.2) / 2.4
            combined = max(0, min(1, combined))
            char_idx = int(combined * (wave_len - 1))
            char = self.WAVE_CHARS[char_idx]
            color_pos = (i / width + t * 0.15) % 1.0
            color_idx = int(color_pos * len(self.PULSE_COLORS)) % len(self.PULSE_COLORS)
            color = self.PULSE_COLORS[color_idx]

            if char in "▅▆▇█":
                result.append(char, style=f"bold {color}")
            elif char in "▃▄":
                result.append(char, style=color)
            else:
                result.append(char, style=f"dim {color}")

        return result


# Alias for backward compatibility
RainbowProgressBar = PulseWaveBar


class ScanningLine(Static):
    """Scanning line that sweeps left-to-right like a radar."""

    is_active = reactive(False)
    needs_approval = reactive(False)

    SCAN_COLORS = ["#a855f7", "#c026d3", "#ec4899", "#f472b6"]
    APPROVAL_COLORS = ["#f59e0b", "#fbbf24", "#f97316", "#ef4444"]

    def on_mount(self):
        self.auto_refresh = 1 / 30

    def render(self) -> Text:
        if not self.is_active:
            return Text("")

        width = self.size.width or 80
        t = monotonic()
        result = Text()

        speed = 0.6 if self.needs_approval else 0.4
        scan_pos = (t * speed) % 1.0
        scan_x = int(scan_pos * width)
        trail_len = 12

        for i in range(width):
            dist = scan_x - i
            if dist < 0:
                dist += width

            if dist == 0:
                result.append("█", style="bold #ffffff")
            elif dist > 0 and dist <= trail_len:
                fade = 1.0 - (dist / trail_len)
                if self.needs_approval:
                    if fade > 0.7:
                        result.append("▓", style="bold #fbbf24")
                    elif fade > 0.4:
                        result.append("▒", style="#f59e0b")
                    elif fade > 0.2:
                        result.append("░", style="#f97316")
                    else:
                        result.append("░", style="#7c2d12")
                else:
                    if fade > 0.7:
                        result.append("▓", style="bold #ec4899")
                    elif fade > 0.4:
                        result.append("▒", style="#c026d3")
                    elif fade > 0.2:
                        result.append("░", style="#a855f7")
                    else:
                        result.append("░", style="#4a1a6b")
            else:
                if self.needs_approval:
                    bg_color = "#2a1a00" if int(t * 4) % 2 == 0 else "#1a1a1a"
                    result.append("─", style=bg_color)
                else:
                    result.append("─", style="#1a1a1a")

        return result


class TopScanningLine(Static):
    """Top scanning line - flowing wave animation."""

    is_active = reactive(False)
    needs_approval = reactive(False)
    WAVE_COLORS = ["#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#c026d3", "#ec4899"]

    def on_mount(self):
        self.auto_refresh = 1 / 25

    def render(self) -> Text:
        if not self.is_active:
            return Text("")

        width = self.size.width or 80
        t = monotonic()
        result = Text()

        for i in range(width):
            wave1 = math.sin(t * 2 + i * 0.2) * 0.4
            wave2 = math.sin(t * 3.5 + i * 0.15 + 1.5) * 0.3
            combined = (wave1 + wave2 + 1) / 2
            combined = max(0, min(1, combined))

            if combined > 0.8:
                char = "█"
            elif combined > 0.6:
                char = "▓"
            elif combined > 0.4:
                char = "▒"
            elif combined > 0.2:
                char = "░"
            else:
                char = "─"

            color_pos = (i / width + t * 0.1) % 1.0
            color_idx = int(color_pos * len(self.WAVE_COLORS)) % len(self.WAVE_COLORS)
            color = self.WAVE_COLORS[color_idx]

            if char in "█▓":
                result.append(char, style=f"bold {color}")
            elif char == "▒":
                result.append(char, style=color)
            else:
                result.append(char, style=f"dim {color}")

        return result


class BottomScanningLine(Static):
    """Bottom scanning line - radar sweep animation."""

    is_active = reactive(False)
    needs_approval = reactive(False)

    def on_mount(self):
        self.auto_refresh = 1 / 30

    def render(self) -> Text:
        if not self.is_active:
            return Text("")

        width = self.size.width or 80
        t = monotonic()
        result = Text()

        sweep_pos = (t * 0.5) % 1.0
        sweep_x = int(sweep_pos * width)

        for i in range(width):
            dist = abs(i - sweep_x)

            if dist == 0:
                result.append("█", style="bold #ffffff")
            elif dist <= 3:
                fade = 1.0 - (dist / 3.0)
                if fade > 0.7:
                    result.append("▓", style="bold #ec4899")
                elif fade > 0.4:
                    result.append("▒", style="#c026d3")
                elif fade > 0.2:
                    result.append("░", style="#a855f7")
                else:
                    result.append("░", style="#4a1a6b")
            elif dist <= 8:
                fade = 1.0 - ((dist - 3) / 5.0)
                if fade > 0.7:
                    result.append("▓", style="bold #ec4899")
                elif fade > 0.4:
                    result.append("▒", style="#c026d3")
                elif fade > 0.2:
                    result.append("░", style="#a855f7")
                else:
                    result.append("░", style="#4a1a6b")
            else:
                result.append("─", style="#1a1a1a")

        return result


# Aliases for compatibility
ProgressChase = ScanningLine
SparkleTrail = ScanningLine
ThinkingWave = ScanningLine


class StreamingThinkingIndicator(Static):
    """Animated thinking indicator for streaming."""

    is_active = reactive(False)
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    THINKING_PHRASES = [
        "🧠 Thinking deeply",
        "💭 Processing your request",
        "⚡ Analyzing the problem",
        "🔍 Understanding context",
        "✨ Generating response",
        "🎯 Computing solution",
        "🚀 Working on it",
        "💡 Light bulb moment",
        "🎪 Juggling possibilities",
        "🎨 Painting a masterpiece",
        "🧩 Solving the puzzle",
        "👨‍🍳 Cooking up magic",
        "🚀 Launching into orbit",
        "🪄 Casting a spell",
        "💻 Compiling thoughts",
        "🔧 Tightening the bolts",
        "🐝 Busy bee mode",
        "🏗️ Under construction",
        "🧙‍♂️ Wizarding up a solution",
        "🦄 Summoning unicorn power",
        "🐉 Awakening the code dragon",
        "🌟 Aligning the stars",
        "🔭 Scanning the codeverse",
        "⚛️ Splitting atoms of logic",
        "🌌 Exploring the galaxy",
        "🛸 Beaming down answers",
        "🔮 Consulting the crystal ball",
        "🎬 Directing the scene",
        "🎸 Jamming on your code",
        "🎲 Rolling for initiative",
        "🍳 Frying some fresh code",
        "☕ Brewing the perfect response",
        "🍕 Serving hot code",
        "🦊 Being clever like a fox",
        "🐙 Multitasking like an octopus",
        "🦅 Eagle-eye analyzing",
        "🔥 Firing up the engines",
        "💎 Polishing the gem",
        "🎭 Getting into character",
        "🎡 Spinning up ideas",
        "🎯 Locking onto target",
        "⚙️ Processing information",
        "🧪 Experimenting with solutions",
        "🔬 Running analysis",
        "📊 Crunching numbers",
        "🎨 Creating art",
        "🎪 Performing magic",
        "🎭 Acting out the solution",
    ]

    def on_mount(self):
        self.auto_refresh = 1 / 15

    def render(self) -> Text:
        if not self.is_active:
            return Text("")

        t = monotonic()
        result = Text()

        spinner_idx = int(t * 10) % len(self.SPINNER_FRAMES)
        phrase_idx = int(t / 1.5) % len(self.THINKING_PHRASES)

        colors = [
            "#a855f7",
            "#c026d3",
            "#d946ef",
            "#ec4899",
            "#f97316",
            "#fbbf24",
            "#22c55e",
            "#06b6d4",
        ]
        color = colors[int(t * 4) % len(colors)]

        spinner = self.SPINNER_FRAMES[spinner_idx]
        phrase = self.THINKING_PHRASES[phrase_idx]

        dot_count = int(t * 3) % 4
        dots = "." * dot_count

        sparkles = ["✨", "⭐", "💫", "🌟"]
        sparkle = sparkles[int(t * 2) % len(sparkles)]

        result.append(f"  {spinner} ", style=f"bold {color}")
        result.append(phrase, style=f"bold {color}")
        result.append(dots, style=color)
        result.append(f" {sparkle}", style=color)
        result.append("   ", style="")

        return result


class ModeBadge(Static):
    """Shows current mode with rich styling and connection info."""

    mode = reactive("home")
    role = reactive("")
    agent = reactive("")
    model = reactive("")
    provider = reactive("")
    execution_mode = reactive("")
    approval_mode = reactive("auto")

    def render(self) -> Text:
        t = Text()

        if self.execution_mode == "pure":
            t.append(" 🧪 ", style=f"bold {THEME['pink']}")
            t.append("PURE", style=f"bold {THEME['pink']} reverse")
            t.append(" • ", style=THEME["muted"])

            if self.provider:
                t.append(f"{self.provider.upper()}", style=f"bold {THEME['cyan']}")

            if self.model:
                t.append("  ", style="")
                t.append(f"📊 {self.model}", style=THEME["muted"])

            return t

        if self.agent:
            color = AGENT_COLORS.get(self.agent, THEME["purple"])
            icon = AGENT_ICONS.get(self.agent, "🤖")

            if self.execution_mode == "acp":
                t.append(" 🔗 ", style=f"bold {THEME['cyan']}")
                t.append("ACP", style=f"bold {THEME['cyan']} reverse")
                t.append(" • ", style=THEME["muted"])
            elif self.execution_mode == "byok":
                t.append(" ⚡ ", style=f"bold {THEME['success']}")
                t.append("BYOK", style=f"bold {THEME['success']} reverse")
                t.append(" • ", style=THEME["muted"])

            t.append(f"{icon} ", style=f"bold {color}")
            t.append(self.agent.upper(), style=f"bold {color}")

            if self.model:
                t.append("  ", style="")
                t.append(f"📊 {self.model}", style=THEME["muted"])
            if self.provider:
                t.append("  ", style="")
                t.append(f"☁️ {self.provider}", style=THEME["dim"])

            mode_icons = {"auto": "🟢", "ask": "🟡", "deny": "🔴"}
            mode_colors = {
                "auto": THEME["success"],
                "ask": THEME["warning"],
                "deny": THEME["error"],
            }
            approval_icon = mode_icons.get(self.approval_mode, "🟡")
            approval_color = mode_colors.get(self.approval_mode, THEME["warning"])
            t.append("  ", style="")
            t.append(f"{approval_icon}", style=approval_color)

        elif self.role:
            mode_styles = {
                "dev": (ICONS["dev"], THEME["success"], "💻"),
                "qa": (ICONS["qa"], THEME["orange"], "🧪"),
                "devops": (ICONS["devops"], THEME["cyan"], "⚙️"),
            }
            icon, color, emoji = mode_styles.get(self.mode, (ICONS["home"], THEME["purple"], "🏠"))

            if self.execution_mode == "acp":
                t.append(" 🔗 ", style=f"bold {THEME['cyan']}")
                t.append("ACP", style=f"bold {THEME['cyan']} reverse")
                t.append(" • ", style=THEME["muted"])
            elif self.execution_mode == "byok":
                t.append(" ⚡ ", style=f"bold {THEME['success']}")
                t.append("BYOK", style=f"bold {THEME['success']} reverse")
                t.append(" • ", style=THEME["muted"])

            t.append(f"{emoji} ", style=f"bold {color}")
            t.append(f"{self.mode.upper()}", style=f"bold {color}")
            t.append(" › ", style=THEME["muted"])
            t.append(self.role, style=f"bold {color}")

            if self.model:
                t.append("  ", style="")
                t.append(f"📊 {self.model}", style=THEME["dim"])

            mode_icons = {"auto": "🟢", "ask": "🟡", "deny": "🔴"}
            mode_colors = {
                "auto": THEME["success"],
                "ask": THEME["warning"],
                "deny": THEME["error"],
            }
            approval_icon = mode_icons.get(self.approval_mode, "🟡")
            approval_color = mode_colors.get(self.approval_mode, THEME["warning"])
            t.append("  ", style="")
            t.append(f"{approval_icon}", style=approval_color)
        else:
            t.append(f" 🏠 ", style=f"bold {THEME['purple']}")
            t.append("HOME", style=f"bold {THEME['purple']} reverse")
            t.append("    ", style="")
            t.append("ready to code", style=f"dim {THEME['muted']}")

        return t


class HintsBar(Static):
    """Context hints with gradient colors and emojis."""

    approval_mode = reactive("auto")

    def render(self) -> Text:
        t = Text()

        # t.append("\n", style="")

        hints = [
            ("🏠 :home", THEME["cyan"]),
            ("❓ :h [:help]", THEME["purple"]),
            ("🚀 :i [:init]", THEME["success"]),
            ("📚 :s [:sidebar]", THEME["cyan"]),
            ("🔌 :c [:connect]", THEME["pink"]),
            ("👋 :q [:quit]", THEME["orange"]),
        ]
        for i, (hint, color) in enumerate(hints):
            if i > 0:
                t.append("  •  ", style=THEME["dim"])
            t.append(hint, style=color)

        return t


class SelectableTextArea(Static):
    """A text area that allows mouse selection and copying.

    Used as a popup overlay when user wants to select/copy text.
    """

    DEFAULT_CSS = """
    SelectableTextArea {
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1 2;
        width: 80%;
        height: 80%;
        layer: overlay;
    }

    SelectableTextArea .title {
        text-align: center;
        color: #a855f7;
        text-style: bold;
        margin-bottom: 1;
    }

    SelectableTextArea .hint {
        text-align: center;
        color: #71717a;
        margin-top: 1;
    }
    """

    def __init__(self, content: str, title: str = "Response", **kwargs):
        super().__init__(**kwargs)
        self._content = content
        self._title = title

    def render(self) -> Text:
        t = Text()
        t.append(f"📋 {self._title}\n", style=f"bold {THEME['purple']}")
        t.append("─" * 40 + "\n\n", style=THEME["border"])
        t.append(self._content, style=THEME["text"])
        t.append("\n\n" + "─" * 40 + "\n", style=THEME["border"])
        t.append(
            "Hold Shift + drag to select • Ctrl+C to copy • Escape to close", style=THEME["muted"]
        )
        return t


class ConversationLog(RichLog):
    """Chat log with styled messages and rich formatting.

    Text Selection:
    - Hold Shift while dragging to select text (terminal native selection)
    - Ctrl+Shift+C to copy last response
    - :copy command to copy to clipboard
    - :select to open selectable view
    """

    DEFAULT_CSS = """
    ConversationLog {
        scrollbar-gutter: stable;
        background: #000000;
        width: 100%;
        padding: 0;
        margin: 0;
    }
    """

    def __init__(self, *args, **kwargs):
        # Remove any width-related kwargs that might limit display
        kwargs.pop("max_width", None)
        kwargs.pop("width", None)
        super().__init__(*args, **kwargs)
        # Track messages for copy functionality
        self._messages: list[tuple[str, str, str]] = []  # (role, text, agent_name)
        self._last_response: str = ""
        self._last_error: str = ""  # Track last error for easy copy
        # Track thinking and tool calls for agent sessions
        self._thinking_lines: list[str] = []
        self._tool_calls: list[dict] = []
        self._streaming_response: str = ""
        # Force console width to None (unlimited) immediately after init
        self._force_unlimited_width = True

    def on_mount(self) -> None:
        """Configure console width when widget is mounted."""
        super().on_mount()
        # Override Rich's internal console width to use full available width
        # RichLog uses an internal Console that might have a default width limit
        # Try multiple possible attribute names for the internal console
        self._update_console_width()
        # Also try to set it after a small delay to ensure it's applied
        self.set_timer(0.1, self._update_console_width)

    def _update_console_width(self) -> None:
        """Update the internal Rich console width - FORCE UNLIMITED (NO CHARACTER LIMITS)."""
        # Get actual terminal width - use a very large value to prevent truncation
        import shutil

        try:
            terminal_width = shutil.get_terminal_size().columns
            # Use terminal width * 2 to ensure no truncation, minimum 200
            target_width = max(terminal_width * 2, 200) if terminal_width > 0 else 500
        except Exception:
            target_width = 500  # Large fallback

        # Set console width on all possible console attributes
        console_attrs = [
            "_console",
            "console",
            "_rich_console",
            "rich_console",
            "_log_console",
            "log_console",
        ]

        for attr in console_attrs:
            try:
                if hasattr(self, attr):
                    console = getattr(self, attr)
                    if console and hasattr(console, "width"):
                        console.width = target_width
                        if hasattr(console, "legacy_width"):
                            console.legacy_width = target_width
                        if hasattr(console, "max_width"):
                            console.max_width = target_width
                        # Also set soft_wrap to True for natural wrapping
                        if hasattr(console, "soft_wrap"):
                            console.soft_wrap = True
            except Exception:
                continue

        # Also try to access console through various internal attributes
        internal_attrs = ["_renderable", "_log", "_buffer", "_output"]
        for attr in internal_attrs:
            try:
                if hasattr(self, attr):
                    obj = getattr(self, attr)
                    if hasattr(obj, "_console"):
                        obj._console.width = target_width
                    if hasattr(obj, "console"):
                        obj.console.width = target_width
            except Exception:
                continue

        # Try to access through __dict__ to find any console-like objects
        try:
            for key, value in self.__dict__.items():
                if "console" in key.lower() and hasattr(value, "width"):
                    value.width = target_width
        except Exception:
            pass

    def on_resize(self, event) -> None:
        """Update console width when widget is resized."""
        super().on_resize(event)
        # Update console width when widget size changes
        self._update_console_width()

    def add_user(self, text: str):
        self._messages.append(("user", text, ""))
        # Use None for width to allow full width usage
        panel = Panel(
            Text(text, style=THEME["text"], overflow="fold"),
            title=f"[bold {THEME['cyan']}]👩‍💻👨‍💻 >[/]",
            border_style=THEME["border"],
            box=ROUNDED,
            padding=(0, 1),
            width=None,  # Use full available width
        )
        self.write(panel)

    def add_agent(self, text: str, agent: str = "Agent"):
        self._messages.append(("agent", text, agent))
        self._last_response = text  # Track for easy copy
        color = AGENT_COLORS.get(agent.lower(), THEME["purple"])
        icon = AGENT_ICONS.get(agent.lower(), "🤖")
        # Use overflow="fold" to wrap instead of truncate
        content = (
            Markdown(text) if "```" in text else Text(text, style=THEME["text"], overflow="fold")
        )
        panel = Panel(
            content,
            title=f"[bold {color}]{icon} {agent} Agent[/]",
            border_style=color,
            box=ROUNDED,
            padding=(0, 1),
            width=None,  # Use full available width
        )
        self.write(panel)

    def add_assistant(self, text: str, agent: str = "Assistant"):
        """Alias for add_agent - used by TUI for assistant responses."""
        self.add_agent(text, agent)

    def write(self, *args, **kwargs):
        """Override write to ensure console width is always correct - NO LIMITS."""
        # Ensure console width is updated before writing
        self._update_console_width()

        # Process args to ensure Text objects have proper overflow handling
        processed_args = []
        for arg in args:
            if isinstance(arg, Text):
                # Ensure Text uses fold overflow for natural wrapping
                if not hasattr(arg, "overflow") or arg.overflow != "fold":
                    arg.overflow = "fold"
            processed_args.append(arg)

        return super().write(*processed_args, **kwargs)

    def add_system(self, text: str):
        self._messages.append(("system", text, ""))
        self.write(Text(f"  ✨ {text}", style=f"italic {THEME['muted']}"))

    def add_error(self, text: str):
        self._messages.append(("error", text, ""))
        self._last_error = text  # Track for easy copy

        # Try to display with rich markup support
        try:
            self.write(Text(f"  ❌ {text}", markup=True))
        except Exception:
            # Fallback to plain text
            self.write(Text(f"  ❌ {text}", style=THEME["error"]))

    def add_success(self, text: str):
        self._messages.append(("success", text, ""))
        self.write(Text(f"  ✅ {text}", style=THEME["success"]))

    def add_info(self, text: str):
        self._messages.append(("info", text, ""))
        self.write(Text(f"  ℹ️ {text}", style=THEME["cyan"]))

    def add_shell(self, cmd: str, output: str, ok: bool = True):
        """Add shell command output to the log."""
        self._messages.append(("shell", f"{cmd}\n{output}", ""))
        status_icon = "⚡" if ok else "💥"
        status_style = THEME["success"] if ok else THEME["error"]

        # Format command and output with distinct styling
        content = Text.assemble(
            (f"  {status_icon} ", status_style),
            (f"Terminal", f"bold {THEME['cyan']}"),
            (": ", THEME["muted"]),
            (f"{cmd}\n", f"bold {THEME['text']}"),
            (output, THEME["text"] if ok else THEME["error"]),
        )
        self.write(content)

    def get_last_response(self) -> str:
        """Get the last agent response text for copying."""
        return self._last_response

    def get_last_error(self) -> str:
        """Get the last error text for copying."""
        return self._last_error

    def get_last_message(self, role: str = None) -> str:
        """Get the last message, optionally filtered by role."""
        if not self._messages:
            return ""
        if role:
            for msg_role, text, _ in reversed(self._messages):
                if msg_role == role:
                    return text
            return ""
        return self._messages[-1][1]

    def get_all_text(self) -> str:
        """Get all messages as plain text for export."""
        lines = []
        for role, text, agent in self._messages:
            if role == "user":
                lines.append(f"You: {text}")
            elif role == "agent":
                lines.append(f"{agent or 'Agent'}: {text}")
            elif role == "system":
                lines.append(f"System: {text}")
            elif role == "error":
                lines.append(f"Error: {text}")
            elif role == "success":
                lines.append(f"Success: {text}")
            elif role == "info":
                lines.append(f"Info: {text}")
        return "\n\n".join(lines)

    def copy_to_clipboard(self, text: str = None) -> bool:
        """Copy text to clipboard. Returns True if successful."""
        try:
            import pyperclip

            content = text if text is not None else self._last_response
            if content:
                pyperclip.copy(content)
                return True
        except ImportError:
            # pyperclip not available, try platform-specific
            try:
                import subprocess
                import sys

                content = text if text is not None else self._last_response
                if not content:
                    return False
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=content.encode(), check=True)
                    return True
                elif sys.platform.startswith("linux"):
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"], input=content.encode(), check=True
                    )
                    return True
                elif sys.platform == "win32":
                    subprocess.run(["clip"], input=content.encode(), check=True)
                    return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    def add_tool_approval_needed(self, tool_name: str, description: str = ""):
        """Display a prominent inline notification that tool approval is needed."""
        self.write(
            Panel(
                Text.assemble(
                    ("⚠️ ACTION REQUIRED\n\n", f"bold {THEME['warning']}"),
                    ("Tool: ", THEME["muted"]),
                    (f"{tool_name}\n", f"bold {THEME['cyan']}"),
                    (f"{description}\n\n" if description else "\n", THEME["text"]),
                    ("↑ ", f"bold {THEME['warning']}"),
                    ("Type in prompt box above: ", THEME["text"]),
                    ("y", f"bold {THEME['success']}"),
                    (" to approve, ", THEME["muted"]),
                    ("n", f"bold {THEME['error']}"),
                    (" to reject", THEME["muted"]),
                ),
                title=f"[bold {THEME['warning']}]🔔 Tool Approval Needed[/]",
                border_style=THEME["warning"],
                box=HEAVY,
                padding=(1, 2),
            )
        )

    # =========================================================================
    # ENHANCED STREAMING OUTPUT METHODS
    # These methods provide better display for agent thinking and responses
    # Compatible with BYOK, ACP, and Local modes
    # =========================================================================

    def start_agent_session(
        self,
        agent_name: str,
        model_name: str = "",
        mode: str = "acp",
        approval_mode: str = "ask",
    ):
        """
        Start a new agent output session with header.

        Args:
            agent_name: Name of the agent (e.g., "OpenCode", "Claude")
            model_name: Model being used (e.g., "gpt-4o", "claude-sonnet")
            mode: Connection mode ("acp", "byok", "local")
            approval_mode: Approval mode ("auto", "ask", "deny")
        """
        # Reset streaming state
        self._streaming_response = ""
        self._streaming_thinking = ""
        self._thinking_lines = []
        self._tool_calls = []
        self._session_start_time = None

        try:
            from time import monotonic

            self._session_start_time = monotonic()
        except Exception:
            pass

        # Mode badges
        mode_badges = {
            "acp": ("🔌", "ACP", THEME["success"]),
            "byok": ("🔑", "BYOK", THEME["cyan"]),
            "local": ("💻", "Local", THEME["warning"]),
        }
        mode_icon, mode_label, mode_color = mode_badges.get(
            mode.lower(), ("●", mode.upper(), THEME["muted"])
        )

        # Approval mode
        approval_badges = {
            "auto": ("🟢", "AUTO", THEME["success"]),
            "ask": ("🟡", "ASK", THEME["warning"]),
            "deny": ("🔴", "DENY", THEME["error"]),
        }
        app_icon, app_label, app_color = approval_badges.get(
            approval_mode, ("🟡", "ASK", THEME["warning"])
        )

        # Build header
        header = Text()
        header.append("\n")

        # Gradient line
        gradient = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a855f7", "#c084fc"]
        line = "─" * 60
        for i, char in enumerate(line):
            header.append(char, style=gradient[i % len(gradient)])
        header.append("\n")

        # Agent name
        agent_color = AGENT_COLORS.get(agent_name.lower(), THEME["purple"])
        agent_icon = AGENT_ICONS.get(agent_name.lower(), "🤖")
        header.append(f"  {agent_icon} ", style=f"bold {agent_color}")
        header.append(agent_name.upper(), style=f"bold {THEME['text']}")
        header.append(" is working\n", style=THEME["muted"])

        # Model and mode info
        header.append("  Model: ", style=THEME["dim"])
        header.append(model_name or "auto", style=f"bold {THEME['cyan']}")
        header.append(f"  │  {mode_icon} ", style=mode_color)
        header.append(mode_label, style=f"bold {mode_color}")
        header.append(f"  │  {app_icon} ", style=app_color)
        header.append(app_label, style=f"bold {app_color}")
        header.append("\n")

        self.write(header)

    def add_thinking(self, text: str, category: str = "general"):
        """
        Add a thinking/reasoning line (always visible).

        This method ALWAYS shows thinking regardless of show_thinking_logs setting
        because it's explicitly called for important agent reasoning.

        Args:
            text: The thinking text to display
            category: Category for icon selection (planning, analyzing, etc.)
        """
        if not text or not text.strip():
            return

        # Ensure auto-scroll is ON
        self.auto_scroll = True

        # Store for later copy
        self._thinking_lines.append(text)

        # Category icons and colors
        category_styles = {
            "planning": ("📋", "#f472b6"),
            "analyzing": ("🔬", "#c084fc"),
            "deciding": ("🤔", "#fbbf24"),
            "searching": ("🔍", "#60a5fa"),
            "reading": ("📖", "#34d399"),
            "writing": ("✏️", "#818cf8"),
            "debugging": ("🐛", "#ef4444"),
            "executing": ("⚡", "#fb923c"),
            "verifying": ("✅", "#22c55e"),
            "testing": ("🧪", "#a78bfa"),
            "refactoring": ("🔧", "#9ca3af"),
            "discovery": ("🔭", "#06b6d4"),
            "thinking": ("🧠", "#e879f9"),
            "notifying": ("🔔", "#facc15"),
            "general": ("💭", "#94a3b8"),
        }

        icon, color = category_styles.get(category.lower(), category_styles["general"])

        # Auto-detect category from text if not specified (or is general)
        if category == "general":
            text_lower = text.lower()
            if any(w in text_lower for w in ["test", "pytest", "expect", "assertion"]):
                icon, color = category_styles["testing"]
            elif any(w in text_lower for w in ["run", "execute", "command", "bash", "shell"]):
                icon, color = category_styles["executing"]
            elif any(w in text_lower for w in ["verify", "confirm", "check", "validation"]):
                icon, color = category_styles["verifying"]
            elif any(w in text_lower for w in ["debug", "error", "fix", "bug", "traceback"]):
                icon, color = category_styles["debugging"]
            elif any(w in text_lower for w in ["plan", "step", "approach", "todo"]):
                icon, color = category_styles["planning"]
            elif any(w in text_lower for w in ["search", "find", "look", "grep", "glob"]):
                icon, color = category_styles["searching"]
            elif any(w in text_lower for w in ["read", "file", "content", "cat"]):
                icon, color = category_styles["reading"]
            elif any(w in text_lower for w in ["write", "create", "add", "edit", "save"]):
                icon, color = category_styles["writing"]
            elif any(w in text_lower for w in ["discover", "list", "explore", "scan"]):
                icon, color = category_styles["discovery"]
            elif any(w in text_lower for w in ["think", "reason", "ponder", "analyze"]):
                icon, color = category_styles["thinking"]
            elif any(w in text_lower for w in ["info", "note", "alert", "notice"]):
                icon, color = category_styles["notifying"]
            else:
                # Randomize generic icon to avoid repetition
                generic_icons = ["💭", "💡", "⚙️", "🧩", "🔮", "✨", "📡"]
                import random

                icon = random.choice(generic_icons)
                # Keep neutral color for generic thoughts

        # Display thinking line
        line = Text()
        line.append(f"  {icon} ", style=f"bold {color}")
        line.append(text, style=f"italic {THEME['muted']}")
        line.append("\n")
        self.write(line)

    def add_response_chunk(self, text: str):
        """
        Add a chunk of response text (for streaming).

        Accumulates chunks and displays them intelligently to avoid word-per-line display.
        Highlights code blocks in real-time.

        Args:
            text: The response chunk to add
        """
        if not text:
            return

        self._streaming_response += text
        self.auto_scroll = True

        # Check for code block state
        if not hasattr(self, "_in_code_block"):
            self._in_code_block = False

        # Toggle code block state
        if "```" in text:
            # Count occurrences to toggle state correctly
            count = text.count("```")
            if count % 2 != 0:
                self._in_code_block = not self._in_code_block

        # Buffer chunks and only write on natural boundaries to avoid word-per-line
        if not hasattr(self, "_chunk_buffer"):
            self._chunk_buffer = ""
        self._chunk_buffer += text

        # Write when we have:
        # 1. A complete sentence (ends with . ! ? : ; followed by space or newline)
        # 2. A newline character in the text
        # 3. Accumulated enough text (50+ chars with a space near the end)
        buffer = self._chunk_buffer
        should_write = (
            (
                buffer.rstrip().endswith((".", "!", "?", ":", ";"))
                and (text.endswith(" ") or text.endswith("\n") or len(buffer) > 30)
            )
            or "\n" in text
            or (len(buffer) > 50 and " " in buffer[-15:])
        )

        if should_write:
            chunk_text = Text()
            style = f"bold {THEME['cyan']}" if self._in_code_block else THEME["text"]
            chunk_text.append(buffer, style=style)
            self.write(chunk_text)
            self._chunk_buffer = ""

    def flush_response_buffer(self):
        """Flush any remaining buffered response chunks."""
        if hasattr(self, "_chunk_buffer") and self._chunk_buffer:
            chunk_text = Text()
            style = (
                f"bold {THEME['cyan']}" if getattr(self, "_in_code_block", False) else THEME["text"]
            )
            chunk_text.append(self._chunk_buffer, style=style)
            self.write(chunk_text)
            self._chunk_buffer = ""

    def add_tool_call(
        self,
        tool_name: str,
        status: str = "running",
        file_path: str = "",
        command: str = "",
        output: str = "",
    ):
        """
        Add a tool call display.

        Args:
            tool_name: Name of the tool being called
            status: Status ("pending", "running", "success", "error")
            file_path: File path if applicable
            command: Command if it's a shell tool
            output: Tool output/result
        """
        self._tool_calls.append(
            {
                "name": tool_name,
                "status": status,
                "path": file_path,
                "command": command,
            }
        )

        # Track file modifications
        if status in ("running", "success") and file_path:
            # Initialize _files_modified if not exists
            if not hasattr(self, "_files_modified"):
                self._files_modified = set()

            # Add to set if it's a write/edit operation
            tool_lower = tool_name.lower()
            if any(op in tool_lower for op in ("write", "edit", "create", "append", "patch")):
                self._files_modified.add(file_path)

        # Status icons and colors
        status_map = {
            "pending": ("○", THEME["muted"]),
            "running": ("◐", THEME["purple"]),
            "success": ("✦", THEME["success"]),
            "error": ("✕", THEME["error"]),
        }
        status_icon, status_color = status_map.get(status, ("●", THEME["muted"]))

        # Tool type icons
        tool_icons = {
            "read": "↳",
            "write": "↲",
            "edit": "⟳",
            "shell": "▸",
            "bash": "▸",
            "search": "⌕",
            "glob": "⋮",
            "grep": "⌕",
        }
        tool_icon = "•"
        for key, icon in tool_icons.items():
            if key in tool_name.lower():
                tool_icon = icon
                break

        # Build display
        line = Text()
        line.append(f"  {status_icon} ", style=f"bold {status_color}")
        line.append(f"{tool_icon} ", style=THEME["dim"])
        line.append(tool_name, style=THEME["text"])

        if file_path:
            # Show full file path - let widget handle wrapping
            line.append(f"  {file_path}", style=THEME["dim"])
        elif command:
            # Show more of the command - 100 chars instead of 40
            cmd_short = command[:100] + "..." if len(command) > 100 else command
            line.append(f"  $ {cmd_short}", style=THEME["dim"])

        if output and status in ("success", "error"):
            # Show full output - no truncation, let the widget handle wrapping
            line.append(f"\n    → {output}", style=THEME["muted"])

        line.append("\n")
        self.write(line)

    def end_agent_session(
        self,
        success: bool = True,
        response_text: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        thinking_tokens: int = 0,
        cost: float = 0.0,
    ):
        """
        End the agent output session with a rich Mission Report summary.

        Args:
            success: Whether the session completed successfully
            response_text: Final response text (if not already streamed)
            prompt_tokens: Number of prompt tokens used
            completion_tokens: Number of completion tokens used
            thinking_tokens: Number of thinking tokens used
            cost: Cost in dollars
        """
        # Flush any remaining buffered response chunks
        self.flush_response_buffer()

        # Calculate duration
        duration = 0.0
        if hasattr(self, "_session_start_time") and self._session_start_time:
            try:
                from time import monotonic

                duration = monotonic() - self._session_start_time
            except Exception:
                pass

        # Store final response for copy
        if response_text:
            self._last_response = response_text
            self._streaming_response = response_text
        elif self._streaming_response:
            self._last_response = self._streaming_response

        # Build rich summary panel
        summary_content = Text()

        # 1. Header
        if success:
            summary_content.append("✅ Mission Accomplished", style=f"bold {THEME['success']}")
        else:
            summary_content.append("❌ Mission Failed", style=f"bold {THEME['error']}")
        summary_content.append("\n\n")

        # 2. Tool Usage Stats
        tool_counts = {}
        for tool in getattr(self, "_tool_calls", []):
            name = tool.get("name", "Unknown")
            tool_counts[name] = tool_counts.get(name, 0) + 1

        if tool_counts:
            summary_content.append("🛠️  Tool Usage:\n", style="bold")
            for name, count in tool_counts.items():
                summary_content.append(f"  • {name}: ", style=THEME["text"])
                summary_content.append(f"{count}\n", style=f"bold {THEME['cyan']}")
            summary_content.append("\n")

        # 3. Modified Files
        files_mod = getattr(self, "_files_modified", set())
        if files_mod:
            summary_content.append("📁 Files Impacted:\n", style="bold")
            for f in sorted(files_mod):
                summary_content.append(f"  • {f}\n", style=THEME["warning"])
            summary_content.append("\n")

        # 4. Performance Stats Grid
        summary_content.append("📊 Stats:\n", style="bold")
        total_tokens = prompt_tokens + completion_tokens

        stats_line = []
        if duration > 0:
            stats_line.append(f"⏱  {duration:.1f}s")
        if total_tokens > 0:
            stats_line.append(f"🔤 {total_tokens:,} toks")
        if cost > 0:
            stats_line.append(f"💰 ${cost:.4f}")

        summary_content.append("  " + "  •  ".join(stats_line), style=THEME["dim"])
        summary_content.append("\n")

        # Create panel
        panel = Panel(
            summary_content,
            title="[bold]Session Report[/bold]",
            border_style=THEME["success"] if success else THEME["error"],
            box=ROUNDED,
            padding=(1, 2),
        )

        self.write(panel)

        # Copy hint
        footer = Text()
        footer.append("\n")
        footer.append(
            "  [Shift+Drag to select text] • [Ctrl+Shift+C to copy full response]",
            style=THEME["dim"],
        )
        footer.append("\n")

        self.write(footer)

    def get_thinking_text(self) -> str:
        """Get all thinking text for copying."""
        return "\n".join(getattr(self, "_thinking_lines", []))

    def get_streaming_response(self) -> str:
        """Get the accumulated streaming response."""
        return getattr(self, "_streaming_response", "")


class ApprovalWidget(Static):
    """Widget for accepting/rejecting agent file changes."""

    DEFAULT_CSS = """
    ApprovalWidget {
        height: auto;
        padding: 1;
        margin: 1 0;
        background: #1a1a1a;
        border: round #3a3a3a;
    }
    """

    def __init__(self, title: str, description: str = "", file_path: str = ""):
        super().__init__()
        self.title = title
        self.description = description
        self.file_path = file_path
        self.approved = None

    def render(self) -> Text:
        t = Text()
        t.append(f"\n  ⚠️ ", style=f"bold {THEME['warning']}")
        t.append("Approval Required\n", style=f"bold {THEME['warning']}")
        t.append(f"  {self.title}\n", style=THEME["text"])
        if self.file_path:
            t.append(f"  📄 {self.file_path}\n", style=THEME["muted"])
        if self.description:
            t.append(f"  {self.description}\n", style=THEME["dim"])
        t.append("\n  ", style="")
        t.append("[A]", style=f"bold {THEME['success']}")
        t.append(" Accept  ", style=THEME["success"])
        t.append("[R]", style=f"bold {THEME['error']}")
        t.append(" Reject  ", style=THEME["error"])
        t.append("[E]", style=f"bold {THEME['cyan']}")
        t.append(" Edit  ", style=THEME["cyan"])
        t.append("[V]", style=f"bold {THEME['purple']}")
        t.append(" View Diff\n", style=THEME["purple"])
        return t


class DiffDisplay(Static):
    """Display code diff with syntax highlighting."""

    def __init__(self, file_path: str, old_content: str, new_content: str):
        super().__init__()
        self.file_path = file_path
        self.old_content = old_content
        self.new_content = new_content

    def render(self) -> Text:
        t = Text()

        t.append(f"\n  📄 ", style=f"bold {THEME['cyan']}")
        t.append(f"{self.file_path}\n", style=f"bold {THEME['cyan']}")
        t.append(f"  ─" * 30 + "\n", style=THEME["border"])

        old_lines = self.old_content.split("\n") if self.old_content else []
        new_lines = self.new_content.split("\n") if self.new_content else []

        additions = 0
        deletions = 0

        for line in old_lines:
            if line not in new_lines:
                t.append(f"  - {line}\n", style=f"on #3d1f1f {THEME['error']}")
                deletions += 1

        for line in new_lines:
            if line not in old_lines:
                t.append(f"  + {line}\n", style=f"on #1f3d1f {THEME['success']}")
                additions += 1

        t.append(f"\n  📊 ", style=THEME["cyan"])
        t.append(f"+{additions}", style=f"bold {THEME['success']}")
        t.append(" / ", style=THEME["muted"])
        t.append(f"-{deletions}", style=f"bold {THEME['error']}")
        t.append(" lines changed\n", style=THEME["muted"])

        return t


class PlanDisplay(Static):
    """Display agent's plan with task status."""

    def __init__(self, tasks: list[dict[str, Any]]):
        super().__init__()
        self.tasks = tasks

    def render(self) -> Text:
        t = Text()
        t.append(f"\n  📋 ", style=f"bold {THEME['purple']}")
        t.append("Agent Plan\n", style=f"bold {THEME['purple']}")
        t.append(f"  ─" * 25 + "\n", style=THEME["border"])

        status_icons = {
            "pending": ("⏳", THEME["muted"]),
            "in_progress": ("🔄", THEME["cyan"]),
            "completed": ("✅", THEME["success"]),
            "failed": ("❌", THEME["error"]),
        }

        for i, task in enumerate(self.tasks, 1):
            status = task.get("status", "pending")
            icon, color = status_icons.get(status, ("○", THEME["muted"]))
            priority = task.get("priority", "medium")

            priority_badges = {
                "high": ("🔴", THEME["error"]),
                "medium": ("🟡", THEME["warning"]),
                "low": ("🟢", THEME["success"]),
            }
            p_icon, p_color = priority_badges.get(priority, ("○", THEME["muted"]))

            t.append(f"  {icon} ", style=color)
            t.append(f"{i}. ", style=THEME["muted"])
            t.append(
                task.get("content", "Task"), style=color if status == "completed" else THEME["text"]
            )
            t.append(f" {p_icon}\n", style=p_color)

        return t


class ToolCallDisplay(Static):
    """Display tool calls made by the agent."""

    def __init__(self, tool_name: str, status: str = "pending", title: str = "", content: str = ""):
        super().__init__()
        self.tool_name = tool_name
        self.status = status
        self.title = title or tool_name
        self.content = content

    def render(self) -> Text:
        t = Text()

        status_styles = {
            "pending": ("⏳", THEME["muted"]),
            "in_progress": ("🔄", THEME["cyan"]),
            "completed": ("✅", THEME["success"]),
            "failed": ("❌", THEME["error"]),
        }
        icon, color = status_styles.get(self.status, ("🔧", THEME["purple"]))

        t.append(f"  {icon} ", style=color)
        t.append("🔧 ", style=THEME["orange"])
        t.append(self.title, style=f"bold {color}")

        if self.status == "completed":
            t.append(" ✔", style=THEME["success"])
        elif self.status == "failed":
            t.append(" ✗", style=THEME["error"])

        t.append("\n", style="")

        if self.content:
            content = self.content[:200] + "..." if len(self.content) > 200 else self.content
            t.append(f"     {content}\n", style=THEME["dim"])

        return t


class FlashMessage(Static):
    """Quick flash notification message."""

    def __init__(self, message: str, style: str = "default"):
        super().__init__()
        self.message = message
        self.flash_style = style

    def render(self) -> Text:
        t = Text()

        style_config = {
            "default": ("ℹ️", THEME["cyan"], "#0a2a3a"),
            "success": ("✅", THEME["success"], "#0a3a1a"),
            "warning": ("⚠️", THEME["warning"], "#3a2a0a"),
            "error": ("❌", THEME["error"], "#3a0a0a"),
        }

        icon, color, _ = style_config.get(self.flash_style, style_config["default"])

        t.append(f"  {icon} ", style=f"bold {color}")
        t.append(self.message, style=f"{color}")

        return t


class DangerWarning(Static):
    """Warning for dangerous operations."""

    def __init__(self, level: str = "warning", message: str = ""):
        super().__init__()
        self.level = level
        self.message = message

    def render(self) -> Text:
        t = Text()

        if self.level == "destructive":
            t.append(f"\n  🚨 ", style=f"bold {THEME['error']}")
            t.append("DESTRUCTIVE OPERATION", style=f"bold {THEME['error']}")
            t.append("\n  May alter files outside project directory!\n", style=THEME["error"])
        else:
            t.append(f"\n  ⚠️ ", style=f"bold {THEME['warning']}")
            t.append("Potentially Dangerous", style=f"bold {THEME['warning']}")
            t.append("\n  Please review carefully before approving.\n", style=THEME["warning"])

        if self.message:
            t.append(f"  {self.message}\n", style=THEME["muted"])

        return t
