"""
SuperQode App Widgets - All UI widget classes.
"""

from __future__ import annotations

import json
import math
from time import monotonic
from typing import Any

from textual.widgets import Static, RichLog
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel
from rich.console import Group
from rich.box import ROUNDED, HEAVY

from superqode.rendering.markdown import render_agent_markdown
from superqode.tools.display import format_tool_call_compact

from .constants import (
    ASCII_LOGO,
    TAGLINE_PART1,
    TAGLINE_PART2,
    GRADIENT,
    RAINBOW,
    THEME,
    ICONS,
    AGENT_COLORS,
    AGENT_ICONS,
)


def summarize_tool_output(tool_name: str, status: str, output: str, mode: str = "normal") -> str:
    """Summarize tool output for clear, collapsed-by-default TUI logs."""
    if not output:
        return ""
    output = str(output).strip()
    if not output:
        return ""

    if mode == "verbose":
        return output

    lines = [line for line in output.splitlines() if line.strip()]
    if mode == "minimal" and status != "error":
        return ""

    tool_lower = tool_name.lower()
    if status == "error":
        return _clip_single_line(lines[0] if lines else output, 240)
    if "repo_search" in tool_lower:
        return _summarize_repo_search(lines)
    if any(name in tool_lower for name in ("grep", "search", "find")):
        if output.lower().startswith("no "):
            return output
        return f"{len(lines)} match{'es' if len(lines) != 1 else ''}"
    if "glob" in tool_lower or "list" in tool_lower:
        if output.lower().startswith("no "):
            return output
        return f"{len(lines)} item{'s' if len(lines) != 1 else ''}"
    if "read" in tool_lower:
        return f"read {len(lines)} line{'s' if len(lines) != 1 else ''}"
    if any(name in tool_lower for name in ("write", "edit", "patch", "insert", "multi_edit")):
        return _clip_single_line(lines[0] if lines else "updated", 160)
    if "bash" in tool_lower or "shell" in tool_lower:
        if not lines:
            return "completed"
        return f"{len(lines)} output line{'s' if len(lines) != 1 else ''}: {_clip_single_line(lines[-1], 120)}"
    return _clip_single_line(lines[0] if lines else output, 160)


def _summarize_repo_search(lines: list[str]) -> str:
    sections = {"Files": 0, "Content": 0, "Symbols": 0}
    current = ""
    for line in lines:
        label = line.rstrip(":")
        if label in sections:
            current = label
            continue
        if current:
            sections[current] += 1
    parts = [f"{name.lower()} {count}" for name, count in sections.items() if count]
    return ", ".join(parts) if parts else "no matches"


def _clip_single_line(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _diff_stats_from_text(diff_text: str) -> tuple[int, int]:
    additions = sum(
        1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    deletions = sum(
        1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    return additions, deletions


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = max(0.0, seconds)
    if seconds < 0.05:
        return "<0.1s"
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _tail_nonempty_lines(text: str, limit: int = 8) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-limit:]


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
    context_window: reactive[int] = reactive(0)
    # Active runtime + model (e.g. self-contained runtimes like codex-sdk). Shown
    # in full (no shortening) so the user can see exactly what's selected.
    active_runtime: reactive[str] = reactive("")
    active_model: reactive[str] = reactive("")
    interaction_mode: reactive[str] = reactive("build")
    plan_state: reactive[str] = reactive("")

    @staticmethod
    def _format_token_count(tokens: int) -> str:
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M".replace(".0M", "M")
        if tokens >= 1000:
            return f"{tokens / 1000:.1f}K".replace(".0K", "K")
        return str(tokens)

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
        result.append("Harness Engineering frameworks for Coding Agents", style="")

        # BYOK status (if connected)
        if self.byok_provider:
            result.append("  │  ", style="#3f3f46")
            result.append(f"{self.byok_provider}", style="bold #10b981")
            if self.byok_model:
                result.append(f"/{self.byok_model}", style="#a1a1aa")

            # Show usage
            if self.byok_tokens > 0:
                result.append("  ", style="")
                result.append(self._format_token_count(self.byok_tokens), style="#06b6d4")
                result.append(" tok", style="#52525b")

            # Live context window meter: how full the model's context is.
            if self.context_window > 0 and self.byok_tokens > 0:
                pct = min(100, round(100 * self.byok_tokens / self.context_window))
                if pct < 60:
                    gauge_color = "#22c55e"
                elif pct < 85:
                    gauge_color = "#fbbf24"
                else:
                    gauge_color = "#ef4444"
                filled = min(8, round(pct / 100 * 8))
                result.append("  ", style="")
                result.append("▰" * filled, style=gauge_color)
                result.append("▱" * (8 - filled), style="#3f3f46")
                result.append(f" {pct}%", style=gauge_color)
                result.append(
                    f" of {self._format_token_count(self.context_window)}", style="#52525b"
                )

            # Show cost
            if self.byok_cost > 0:
                result.append("  ", style="")
                if self.byok_cost >= 0.01:
                    result.append(f"${self.byok_cost:.2f}", style="#fbbf24")
                else:
                    result.append(f"${self.byok_cost:.3f}", style="#fbbf24")

        # Active runtime + model (full, not shortened), e.g. "codex-sdk · gpt-5.5"
        if self.active_runtime or self.active_model:
            result.append("  │  ", style="#3f3f46")
            result.append("🔧 ", style="#06b6d4")
            if self.active_runtime:
                result.append(self.active_runtime, style="bold #06b6d4")
            if self.active_model:
                sep = " · " if self.active_runtime else ""
                result.append(f"{sep}{self.active_model}", style="#a1a1aa")

        mode = (self.interaction_mode or "").strip().lower()
        if mode:
            mode_label = {"chat": "CHAT", "plan": "PLAN", "build": "BUILD"}.get(
                mode, mode.upper()
            )
            mode_color = {
                "chat": "#06b6d4",
                "plan": "#fbbf24",
                "build": "#22c55e",
            }.get(mode, "#a855f7")
            result.append("  │  ", style="#3f3f46")
            result.append(mode_label, style=f"bold {mode_color} reverse")

        if self.plan_state:
            state = self.plan_state.strip()
            color = {
                "ON": "#fbbf24",
                "pending": "#f59e0b",
                "active": "#06b6d4",
                "approved": "#22c55e",
            }.get(state, "#a855f7")
            result.append("  │  ", style="#3f3f46")
            result.append("PLAN", style=f"bold {color}")
            result.append(f" {state}", style=color)

        return result

    def update_byok_status(
        self,
        provider: str = "",
        model: str = "",
        tokens: int = 0,
        cost: float = 0.0,
        context_window: int = 0,
    ):
        """Update BYOK status display."""
        self.byok_provider = provider
        self.byok_model = model
        self.byok_tokens = tokens
        self.byok_cost = cost
        self.context_window = context_window


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

        part2 = TAGLINE_PART2
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
    # When set (normal thinking mode), shows this steady status instead of the
    # cycling whimsical phrases - e.g. "Working… (step 2)".
    status = reactive("")
    SPINNER_FRAMES = ["◌", "◔", "◑", "◕"]

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
        self.auto_refresh = 1 / 2

    def render(self) -> Text:
        if not self.is_active:
            return Text("")

        t = monotonic()
        result = Text()

        spinner_idx = int(t * 2) % len(self.SPINNER_FRAMES)
        color = "#a855f7"

        spinner = self.SPINNER_FRAMES[spinner_idx]

        # Always cycle the whimsical phrases so there's lively, ever-changing
        # text whenever the agent is working - in every mode, not just chat.
        phrase_idx = int(t / 4) % len(self.THINKING_PHRASES)
        phrase = self.THINKING_PHRASES[phrase_idx]

        result.append(f"  {spinner} ", style=f"bold {color}")
        result.append(phrase, style=f"bold {color}")

        # When the agent loop has a concrete live status (e.g. "📄 Read foo.py…"
        # or "Working… (step 2)") show it as a secondary detail beside the
        # cycling phrase. Generic "thinking" statuses are skipped since the
        # phrase already conveys that.
        status = (self.status or "").strip()
        if status and "thinking" not in status.lower():
            result.append("  ·  ", style="#52525b")
            result.append(status, style="#a1a1aa")

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
                "qa": (ICONS["qa"], THEME["orange"], "🧪"),
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
            t.append("🏠 ", style=f"bold {THEME['purple']}")
            t.append("SUPERQODE", style=f"bold {THEME['purple']}")

        return t


class HintsBar(Static):
    """Context hints with gradient colors and emojis."""

    approval_mode = reactive("auto")

    def render(self) -> Text:
        t = Text()

        # t.append("\n", style="")

        hints = [
            ("🔌 :connect", THEME["pink"]),
            ("⚙️ :mode", THEME["gold"]),
            ("🧩 :harness", THEME["purple"]),
            ("🧠 :memory", THEME["cyan"]),
            ("🏠 :home", THEME["cyan"]),
            ("❓ :help", THEME["purple"]),
            ("👋 :exit", THEME["orange"]),
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
    - Drag with the mouse to select — selection is copied to the clipboard
      automatically (no command needed).
    - :copy command to copy the last response/error/transcript.
    - Shift+drag for the terminal's native selection (fallback for terminals
      where clipboard access is blocked).
    - :select to open a plain selectable view.
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

    SEARCH_HIGHLIGHT_STYLE = "bold #111827 on #facc15"

    def set_search_highlight(self, query: str) -> None:
        self._search_highlight_query = (query or "").strip()
        try:
            self.refresh()
        except Exception:
            pass

    @staticmethod
    def _style_strip_span(strip, start: int, end: int, style):
        from rich.segment import Segment
        from textual.strip import Strip

        if end <= start:
            return strip
        start = max(0, min(start, strip.cell_length))
        end = max(start, min(end, strip.cell_length))
        if end <= start:
            return strip
        selected = strip.crop(start, end)
        selected = Strip(
            [
                Segment(
                    segment.text,
                    (segment.style or style) + style,
                    segment.control,
                )
                for segment in selected
            ],
            selected.cell_length,
        )
        return Strip.join(
            [
                strip.crop(0, start),
                selected,
                strip.crop(end, strip.cell_length),
            ]
        )

    @classmethod
    def _highlight_query_in_strip(cls, strip, query: str):
        from rich.style import Style

        query = (query or "").strip()
        if not query:
            return strip
        line = strip.text
        lowered_line = line.lower()
        lowered_query = query.lower()
        if not lowered_query:
            return strip

        spans: list[tuple[int, int]] = []
        start = 0
        while True:
            index = lowered_line.find(lowered_query, start)
            if index < 0:
                break
            spans.append((index, index + len(query)))
            start = index + max(1, len(query))
        if not spans:
            return strip

        highlight_style = Style.parse(cls.SEARCH_HIGHLIGHT_STYLE)
        for start, end in reversed(spans):
            strip = cls._style_strip_span(strip, start, end, highlight_style)
        return strip

    def render_line(self, y):
        """Render a line, tagging each segment with its content ``offset``.

        Mouse text-selection in Textual only *starts* if the segment under the
        cursor carries a ``style.meta["offset"]`` (content cell, row) — that's
        how the compositor maps a screen cell back to a position in the widget's
        content. ``RichLog`` blits cached strips without that meta, so
        ``get_widget_and_offset_at`` returns ``None`` and no selection is ever
        created (the conversation looked completely unselectable, regardless of
        which connector produced the output). We re-tag each rendered segment
        here. The row we emit (``scroll_y + y``) is the index into ``self.lines``,
        which is exactly what :meth:`get_selection` extracts from — so selection
        start/extract stay consistent.
        """
        strip = super().render_line(y)
        try:
            from rich.segment import Segment
            from rich.style import Style
            from textual.strip import Strip

            row = self.scroll_offset[1] + y
            col = 0
            segments = []
            for seg in strip:
                base = seg.style or Style()
                segments.append(
                    Segment(
                        seg.text,
                        base + Style.from_meta({"offset": (col, row)}),
                        seg.control,
                    )
                )
                col += seg.cell_length
            strip = Strip(segments, strip.cell_length)

            strip = self._highlight_query_in_strip(
                strip,
                getattr(self, "_search_highlight_query", ""),
            )

            selection = self.text_selection
            span = selection.get_span(row) if selection is not None else None
            if span is not None:
                start, end = span
                end = strip.cell_length if end == -1 else end
                if end < start:
                    start, end = end, start
                start = max(0, min(start, strip.cell_length))
                end = max(start, min(end, strip.cell_length))
                if end > start:
                    selection_style = Style.parse("bold white on #2563eb")
                    strip = self._style_strip_span(strip, start, end, selection_style)
            return strip
        except Exception:
            # Never let selection tagging break rendering.
            return strip

    def get_selection(self, selection):
        """Extract the text under a mouse selection.

        ``RichLog`` renders to a ``RichVisual`` (not plain ``Text``/``Content``),
        so the base ``Widget.get_selection`` returns ``None`` — meaning mouse
        drag-select produces no copyable text. We override it to extract from the
        widget's own rendered line strips (the exact visual grid the selection
        offsets index into), so dragging the mouse over the conversation yields
        real text that the app then copies to the clipboard. Paired with
        :meth:`render_line`, which makes the selection start in the first place.
        """
        lines = getattr(self, "lines", None)
        if not lines:
            return None
        try:
            selected_lines: list[str] = []
            for row, strip in enumerate(lines):
                span = selection.get_span(row)
                if span is None:
                    continue

                start, end = span
                end = strip.cell_length if end == -1 else end
                if end < start:
                    start, end = end, start

                selected_lines.append(strip.crop(start, end).text)
        except Exception:
            return None

        if not selected_lines:
            return None
        return "\n".join(selected_lines), "\n"

    def __init__(self, *args, **kwargs):
        # Remove any width-related kwargs that might limit display
        kwargs.pop("max_width", None)
        kwargs.pop("width", None)
        super().__init__(*args, **kwargs)
        # Track messages for copy functionality
        self._messages: list[tuple[str, str, str]] = []  # (role, text, agent_name)
        self._last_response: str = ""
        self._last_error: str = ""  # Track last error for easy copy
        self._search_highlight_query: str = ""
        # Track thinking and tool calls for agent sessions
        self._thinking_lines: list[str] = []
        self._tool_calls: list[dict] = []
        # Session-wide record of completed tool runs (never reset per turn) so
        # :timeline / :tools reflect the whole conversation, not just this turn.
        self._session_tool_calls: list[dict] = []
        self._streaming_response: str = ""
        self._streaming_notice_shown: bool = False
        self._answer_header_shown: bool = False
        self._active_response_agent: str = "Assistant"
        self._rendered_response_text: str = ""
        # Characters of `_streaming_response` already rendered as finished
        # markdown during progressive streaming (block-wise live rendering).
        self._streamed_offset: int = 0
        self._last_thinking_key: str = ""
        self._last_thinking_at: float = 0.0
        self._active_tool_start_times: list[dict[str, Any]] = []
        # Initial verbosity respects ``SUPERQODE_LOG_VERBOSITY`` so a
        # user who runs ``SUPERQODE_LOG_VERBOSITY=verbose superqode`` or
        # passes ``--verbose`` sees full tool output from the first
        # tool call, not just after they run ``:log verbose`` mid-
        # session. Unknown values silently fall back to ``normal``.
        import os as _os

        _initial_mode = (_os.environ.get("SUPERQODE_LOG_VERBOSITY") or "").strip().lower()
        if _initial_mode in ("min", "minimum"):
            _initial_mode = "minimal"
        elif _initial_mode in ("full", "debug"):
            _initial_mode = "verbose"
        elif _initial_mode in ("default",):
            _initial_mode = "normal"
        if _initial_mode not in ("minimal", "normal", "verbose"):
            _initial_mode = "normal"
        self.tool_output_mode: str = _initial_mode
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
        question = Text()
        question.append(str(text).strip() or "(empty)", style=THEME["text"])
        panel = Panel(
            question,
            title=f"[bold {THEME['cyan']}]YOU[/]",
            border_style=THEME["cyan"],
            box=ROUNDED,
            padding=(0, 1),
            width=None,
        )
        self.write(Text("\n"))
        self.write(panel)

    def add_agent(self, text: str, agent: str = "Agent"):
        color = AGENT_COLORS.get(agent.lower(), THEME["purple"])
        icon = AGENT_ICONS.get(agent.lower(), "🤖")
        panel = Panel(
            render_agent_markdown(text),
            title=f"[bold {color}]{icon} {agent} Agent[/]",
            border_style=color,
            box=ROUNDED,
            padding=(0, 1),
            width=None,  # Use full available width
        )
        self._record_final_response(text, agent=agent, role="agent")
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

    def format_session_timeline(self) -> str:
        """Return a replay-style timeline of messages and tool runs."""
        tool_runs = getattr(self, "_session_tool_calls", [])
        lines = [
            "SuperQode Session Timeline",
            "=" * 26,
            "",
            f"Messages: {len(self._messages)}   Tool runs: {len(tool_runs)}",
            "",
        ]
        if not self._messages and not tool_runs:
            lines.append("No session activity recorded yet.")
            return "\n".join(lines)

        if self._messages:
            lines.extend(["Conversation", "------------"])
            for index, (role, text, agent) in enumerate(self._messages, 1):
                label = role.title()
                if role == "agent" and agent:
                    label = f"{agent}"
                preview = " ".join(str(text).split())
                if len(preview) > 220:
                    preview = preview[:217].rstrip() + "..."
                lines.append(f"{index:>2}. {label}: {preview}")
            lines.append("")

        if tool_runs:
            lines.extend(["Tool Runs", "---------"])
            for index, call in enumerate(tool_runs, 1):
                status = str(call.get("status") or "unknown")
                name = self._format_tool_name(str(call.get("name") or "tool")).title()
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                detail = self._format_tool_detail(
                    str(call.get("name") or "tool"), args, max_length=88
                )
                duration = _format_duration(call.get("duration"))
                diff = " diff" if call.get("diff_text") else ""
                duration_suffix = f" {duration}" if duration else ""
                lines.append(
                    f"{index:>2}. {status:<7} {name:<14} {detail}{duration_suffix}{diff}".rstrip()
                )
            lines.extend(["", "Use :tools recent or :tools <number> for full tool drilldown."])

        return "\n".join(lines).strip()

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
        self._streaming_notice_shown = False
        self._streamed_offset = 0
        self._answer_header_shown = False
        self._active_response_agent = agent_name or "Assistant"
        self._rendered_response_text = ""
        self._streaming_thinking = ""
        self._thinking_lines = []
        self._tool_calls = []
        self._last_thinking_key = ""
        self._last_thinking_at = 0.0
        self._active_tool_start_times = []
        self._update_active_tool_status()
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
        agent_color = AGENT_COLORS.get(agent_name.lower(), THEME["purple"])
        agent_icon = AGENT_ICONS.get(agent_name.lower(), "🤖")
        header.append("\n  ", style="")
        header.append(f"{agent_icon} ", style=f"bold {agent_color}")
        header.append(agent_name, style=f"bold {THEME['text']}")
        header.append(" running", style=THEME["muted"])
        header.append("  •  ", style=THEME["dim"])
        header.append(model_name or "auto", style=f"bold {THEME['cyan']}")
        header.append("  •  ", style=THEME["dim"])
        header.append(f"{mode_icon} ", style=mode_color)
        header.append(mode_label, style=f"bold {mode_color}")
        header.append("  •  ", style=THEME["dim"])
        header.append(f"{app_icon} ", style=app_color)
        header.append(app_label, style=f"bold {app_color}")
        header.append("\n")

        self.write(header)

    def _write_answer_header(self, agent: str = "Assistant") -> None:
        """Render a stable answer divider before assistant content."""
        if self._answer_header_shown:
            return
        self._answer_header_shown = True
        header = Text()
        header.append("\n  ")
        header.append("AGENT", style=f"bold {THEME['success']} reverse")
        if agent:
            header.append("  ", style="")
            header.append(str(agent), style=f"bold {THEME['muted']}")
        header.append("\n", style="")
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
        text = " ".join(str(text).split())
        if not text:
            return
        if self._is_protocol_noise(text):
            return

        now = monotonic()
        key = text.lower()
        if key == self._last_thinking_key and now - self._last_thinking_at < 2.0:
            return
        self._last_thinking_key = key
        self._last_thinking_at = now

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
                icon, color = category_styles["general"]

        # Display thinking line
        line = Text()
        line.append(f"  {icon} ", style=f"bold {color}")
        line.append(text, style=f"italic {THEME['muted']}")
        line.append("\n")
        self.write(line)

    def _is_protocol_noise(self, text: str) -> bool:
        """Suppress raw protocol chatter from compact thinking logs."""
        stripped = text.strip()
        lowered = stripped.lower()
        protocol_markers = (
            '"jsonrpc"',
            '"method"',
            '"params"',
            "session/update",
            "session/did",
            "terminal/output",
            "raw event",
        )
        if any(marker in lowered for marker in protocol_markers):
            return True
        if len(stripped) > 200 and stripped[:1] in ("{", "["):
            return True
        return False

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
        self._write_answer_header(getattr(self, "_active_response_agent", "Assistant"))

        # The animated TUI indicator already shows live generation state.
        # RichLog is append-only, so a textual "generating response" line would
        # remain in the transcript after the final answer. Keep the transcript
        # clean and only render actual response content here.
        self._streaming_notice_shown = True

        # Progressive markdown: flush completed blocks as they stabilize so the
        # user sees formatted output live instead of waiting for the full
        # response. RichLog is append-only, so we only render text up to the
        # last safe paragraph boundary and keep the in-progress tail buffered.
        pending = self._streaming_response[self._streamed_offset :]
        flush_len = self._stable_markdown_split(pending)
        if flush_len:
            flushed = pending[:flush_len]
            block = flushed.strip("\n")
            self._streamed_offset += flush_len
            if block:
                self._rendered_response_text += flushed
                self.write(render_agent_markdown(block))

    def reset_response_stream(self, agent: str = "Assistant") -> None:
        """Reset per-response streaming buffers before a new streamed answer."""
        self._streaming_response = ""
        self._streaming_notice_shown = False
        self._streamed_offset = 0
        self._answer_header_shown = False
        self._active_response_agent = agent or "Assistant"
        self._rendered_response_text = ""

    @staticmethod
    def _stable_markdown_split(buffer: str) -> int:
        """Length of the leading portion of *buffer* safe to render as markdown.

        Splits only at blank-line paragraph boundaries that fall outside an open
        code fence, so a partially written paragraph or an unterminated code
        block is never rendered mid-stream (which would flash broken markdown).
        Returns 0 when nothing is safe to flush yet.
        """
        if "\n\n" not in buffer:
            return 0
        safe = 0
        search_from = 0
        while True:
            idx = buffer.find("\n\n", search_from)
            if idx == -1:
                break
            boundary = idx + 2
            # Only flush when every code fence opened so far has been closed.
            if buffer.count("```", 0, boundary) % 2 == 0:
                safe = boundary
            search_from = boundary
        return safe

    def flush_response_buffer(self):
        """Compatibility no-op.

        Progressive markdown is flushed block-by-block in ``add_response_chunk``;
        any remaining tail is rendered by ``write_final_response`` at session end.
        """
        return None

    def _record_final_response(self, text: str, agent: str, role: str = "agent") -> None:
        """Store final response text for copy/transcript without duplicates."""
        if not text:
            return
        self._last_response = text
        if not self._messages or self._messages[-1][1] != text:
            self._messages.append((role, text, agent))

    def write_final_response(
        self,
        text: str,
        *,
        agent: str = "Assistant",
        success: bool = True,
        leading_newline: bool = False,
        trailing_newline: bool = True,
    ) -> None:
        """Record and render a final assistant response through one path."""
        if not text:
            return
        role = "agent" if success else "error"
        self._record_final_response(text, agent=agent, role=role)
        if leading_newline:
            self.write(Text("\n"))
        if success:
            # If blocks were already rendered live during streaming, only render
            # the remaining tail to avoid duplicating earlier paragraphs.
            remaining = text
            rendered = getattr(self, "_rendered_response_text", "")
            if rendered:
                if text.startswith(rendered):
                    remaining = text[len(rendered) :]
                elif text.strip() == rendered.strip():
                    remaining = ""
            remaining = remaining.strip("\n")
            if remaining:
                self._write_answer_header(agent)
                self.write(render_agent_markdown(remaining))
                self._rendered_response_text = text
        else:
            self.write(Text(f"  ✕ {text}\n", style=THEME["error"], overflow="fold"))
        if trailing_newline:
            self.write(Text("\n"))

    def add_tool_call(
        self,
        tool_name: str,
        status: str = "running",
        file_path: str = "",
        command: str = "",
        output: str = "",
        arguments: dict[str, Any] | None = None,
        diff_text: str = "",
        duration: float | None = None,
        additions: int | None = None,
        deletions: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """
        Add a tool call display.

        Args:
            tool_name: Name of the tool being called
            status: Status ("pending", "running", "success", "error")
            file_path: File path if applicable
            command: Command if it's a shell tool
            output: Tool output/result
            arguments: Original tool arguments for compact display
            diff_text: Unified diff to render after successful file edits
            duration: Elapsed execution time in seconds
            additions: Added line count for file-changing tools
            deletions: Deleted line count for file-changing tools
        """
        display_args = dict(arguments or {})
        metadata = dict(metadata or {})

        # Keep the pinned plan/todo panel in sync whenever a todo tool runs.
        if "todo" in tool_name.lower():
            self._sync_todo_panel(tool_name, display_args, output)
        if file_path and not any(
            key in display_args for key in ("path", "file_path", "filePath", "target_file")
        ):
            display_args["path"] = file_path
        if command and "command" not in display_args:
            display_args["command"] = command

        self._tool_calls.append(
            {
                "name": tool_name,
                "status": status,
                "path": file_path,
                "command": command,
                "arguments": display_args,
                "output": output,
                "diff_text": diff_text,
                "duration": duration,
                "additions": additions,
                "deletions": deletions,
                "metadata": metadata,
            }
        )

        if not hasattr(self, "_active_tool_start_times"):
            self._active_tool_start_times = []

        if status == "running":
            active_calls = getattr(self, "_active_tool_start_times", [])
            if not any(
                self._active_tool_matches(active, tool_name, file_path, command)
                for active in active_calls
            ):
                active_calls.append(
                    {
                        "name": tool_name,
                        "path": file_path,
                        "command": command,
                        "arguments": display_args,
                        "started_at": monotonic(),
                    }
                )
        elif duration is None:
            active_calls = getattr(self, "_active_tool_start_times", [])
            for index in range(len(active_calls) - 1, -1, -1):
                active = active_calls[index]
                if not self._active_tool_matches(active, tool_name, file_path, command):
                    continue
                duration = monotonic() - active.get("started_at", monotonic())
                del active_calls[index]
                break
        elif status in ("success", "error"):
            active_calls = getattr(self, "_active_tool_start_times", [])
            for index in range(len(active_calls) - 1, -1, -1):
                if self._active_tool_matches(active_calls[index], tool_name, file_path, command):
                    del active_calls[index]
                    break

        self._update_active_tool_status()

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
        mode = getattr(self, "tool_output_mode", "normal")

        # RichLog is append-only, so showing both a "running" row and a
        # completion row creates noisy duplicates. Keep live running rows for
        # verbose/debug mode; normal/minimal transcripts show the completed
        # result row only.
        if status in ("pending", "running") and mode != "verbose":
            return

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
            "python": "λ",
        }
        tool_icon = "•"
        for key, icon in tool_icons.items():
            if key in tool_name.lower():
                tool_icon = icon
                break

        # Build a compact, scannable display. Normal mode shows only action rows;
        # verbose mode includes summarized successful output.
        line = Text()
        line.append(f"  {status_icon} ", style=f"bold {status_color}")
        line.append(f"{tool_icon} ", style=THEME["dim"])
        line.append(self._format_tool_name(tool_name).title(), style=f"bold {THEME['text']}")
        detail = self._format_tool_detail(
            tool_name,
            display_args,
            max_length=120 if mode == "verbose" else 76,
        )
        if detail:
            line.append("  ", style=THEME["dim"])
            detail_style = THEME["muted"]
            # Make file targets clickable (OSC-8) so supporting terminals can
            # open them in the user's editor/viewer.
            link = self._file_link_for(file_path or display_args)
            if link:
                detail_style = f"{THEME['muted']} link {link}"
            line.append(detail, style=detail_style)

        meta_parts: list[tuple[str, str]] = []
        duration_label = _format_duration(duration)
        if duration_label and status in ("success", "error"):
            meta_parts.append((duration_label, THEME["dim"]))
        if diff_text and additions is None and deletions is None:
            additions, deletions = _diff_stats_from_text(diff_text)
        if additions or deletions:
            if additions:
                meta_parts.append((f"+{additions}", THEME["success"]))
            if deletions:
                meta_parts.append((f"-{deletions}", THEME["error"]))
        if meta_parts:
            line.append("  ")
            for index, (label, style) in enumerate(meta_parts):
                if index:
                    line.append(" ", style=THEME["dim"])
                line.append(label, style=f"bold {style}" if label.startswith(("+", "-")) else style)

        if output and status == "success":
            summary = summarize_tool_output(
                tool_name,
                status,
                output,
                mode,
            )
            if summary:
                style = THEME["error"] if status == "error" else THEME["muted"]
                line.append(f"\n    → {summary}", style=style)

        line.append("\n")
        self.write(line)

        if status == "error":
            self.write(
                self._render_tool_failure_card(
                    tool_name,
                    display_args,
                    output,
                    duration=duration,
                    metadata=metadata,
                )
            )

        if diff_text and status == "success" and mode != "minimal":
            from superqode.widgets.response_changes import render_diff_text

            max_lines = 120 if mode == "verbose" else 48
            self.write(render_diff_text(diff_text, max_lines=max_lines))

        # Record completed runs session-wide (after duration is resolved) so the
        # timeline/tool index survive the per-turn reset of ``_tool_calls``.
        if status in ("success", "error"):
            if not hasattr(self, "_session_tool_calls"):
                self._session_tool_calls = []
            self._session_tool_calls.append(
                {
                    "name": tool_name,
                    "status": status,
                    "path": file_path,
                    "command": command,
                    "arguments": display_args,
                    "output": output,
                    "diff_text": diff_text,
                    "duration": duration,
                    "additions": additions,
                    "deletions": deletions,
                    "metadata": metadata,
                }
            )

    @staticmethod
    def _file_link_for(source: Any) -> str:
        """Return a file:// URL for a tool's target path, if it resolves."""
        candidate = ""
        if isinstance(source, str):
            candidate = source
        elif isinstance(source, dict):
            for key in ("path", "file_path", "filePath", "target_file", "file"):
                value = source.get(key)
                if value:
                    candidate = str(value)
                    break
        if not candidate:
            return ""
        try:
            from pathlib import Path as _Path

            path = _Path(candidate).expanduser()
            if not path.is_absolute():
                path = _Path.cwd() / path
            if path.exists():
                return path.resolve().as_uri()
        except Exception:
            return ""
        return ""

    def _sync_todo_panel(self, tool_name: str, arguments: dict[str, Any], output: str) -> None:
        """Forward todo data to the app's live plan panel, if present."""
        setter = getattr(self.app, "_set_todos", None)
        if not callable(setter):
            return
        todos = None
        if isinstance(arguments, dict) and isinstance(arguments.get("todos"), list):
            todos = arguments["todos"]
        elif output:
            try:
                import json

                parsed = json.loads(str(output))
                if isinstance(parsed, list):
                    todos = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get("todos"), list):
                    todos = parsed["todos"]
            except Exception:
                todos = None
        if todos is not None:
            try:
                setter(todos)
            except Exception:
                pass

    def recent_tool_runs(self, limit: int = 12) -> list[dict[str, Any]]:
        """Return recent tool call records, newest last."""
        if limit <= 0:
            return []
        return list(getattr(self, "_session_tool_calls", [])[-limit:])

    def format_tool_runs_index(self, limit: int = 12) -> str:
        """Return a compact numbered index of recent tool runs."""
        calls = self.recent_tool_runs(limit)
        if not calls:
            return "No tool runs recorded yet."
        lines = [f"Recent tool runs ({len(calls)})", ""]
        start = len(getattr(self, "_session_tool_calls", [])) - len(calls) + 1
        for offset, call in enumerate(calls):
            number = start + offset
            status = str(call.get("status") or "unknown")
            name = self._format_tool_name(str(call.get("name") or "tool")).title()
            detail = self._format_tool_detail(
                str(call.get("name") or "tool"),
                call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
                max_length=72,
            )
            duration = _format_duration(call.get("duration"))
            suffix = f"  {duration}" if duration else ""
            lines.append(f"{number:>2}. {status:<7} {name:<14} {detail}{suffix}".rstrip())
        lines.extend(["", "Use :tools <number> to inspect one run."])
        return "\n".join(lines)

    def format_tool_run_detail(self, index: int) -> str:
        """Return a drilldown document for a recorded tool run."""
        session_calls = getattr(self, "_session_tool_calls", [])
        if index < 1 or index > len(session_calls):
            return f"No tool run #{index}. Use :tools recent."
        call = session_calls[index - 1]
        name = str(call.get("name") or "tool")
        status = str(call.get("status") or "unknown")
        args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        metadata = call.get("metadata") if isinstance(call.get("metadata"), dict) else {}
        output = str(call.get("output") or "").strip()
        diff_text = str(call.get("diff_text") or "").strip()
        duration = _format_duration(call.get("duration"))
        command = str(metadata.get("command") or call.get("command") or args.get("command") or "")
        cwd = str(metadata.get("cwd") or args.get("cwd") or "")
        exit_code = metadata.get("exit_code")
        timed_out = bool(metadata.get("timed_out"))
        timeout = metadata.get("timeout")

        lines = [
            "SuperQode Tool Run",
            "=" * 19,
            "",
            f"Run:      #{index}",
            f"Tool:     {name}",
            f"Status:   {status}",
        ]
        if duration:
            lines.append(f"Duration: {duration}")
        if command:
            lines.append(f"Command:  {command}")
        if cwd:
            lines.append(f"Cwd:      {cwd}")
        if exit_code is not None:
            lines.append(f"Exit:     {exit_code}")
        if timed_out:
            timeout_label = f" after {timeout}s" if timeout else ""
            lines.append(f"Timeout:  yes{timeout_label}")

        if args:
            lines.extend(["", "Arguments", "---------"])
            lines.append(json.dumps(args, indent=2, sort_keys=True, default=str))
        if metadata:
            lines.extend(["", "Metadata", "--------"])
            lines.append(json.dumps(metadata, indent=2, sort_keys=True, default=str))
        if output:
            lines.extend(["", "Output", "------"])
            lines.append(output)
        if diff_text:
            lines.extend(["", "Diff", "----"])
            lines.append(diff_text)
        if not output and not diff_text:
            lines.extend(["", "No output or diff was recorded for this run."])
        lines.extend(["", "Actions: copy this view, rerun/copy command from your shell."])
        return "\n".join(lines).strip()

    def _active_tool_matches(
        self,
        active: dict[str, Any],
        tool_name: str,
        file_path: str = "",
        command: str = "",
    ) -> bool:
        if active.get("name") != tool_name:
            return False
        if file_path and active.get("path") and active.get("path") != file_path:
            return False
        if command and active.get("command") and active.get("command") != command:
            return False
        return True

    def _active_tools_renderable(self) -> Text:
        active_calls = getattr(self, "_active_tool_start_times", [])
        line = Text()
        if not active_calls:
            return line
        line.append("  ◐ ", style=f"bold {THEME['purple']}")
        line.append("running ", style=THEME["muted"])
        visible = active_calls[-3:]
        for index, active in enumerate(visible):
            if index:
                line.append("  •  ", style=THEME["dim"])
            name = str(active.get("name") or "tool")
            args = active.get("arguments") if isinstance(active.get("arguments"), dict) else {}
            detail = self._format_tool_detail(name, args, max_length=42)
            label = self._format_tool_name(name).title()
            line.append(label, style=f"bold {THEME['text']}")
            if detail:
                line.append(f" {detail}", style=THEME["muted"])
            duration = monotonic() - float(active.get("started_at") or monotonic())
            if duration >= 1:
                line.append(f" {_format_duration(duration)}", style=THEME["dim"])
        hidden = len(active_calls) - len(visible)
        if hidden > 0:
            line.append(f"  +{hidden} more", style=THEME["dim"])
        return line

    def _update_active_tool_status(self) -> None:
        try:
            panel = self.app.query_one("#active-tools", Static)
        except Exception:
            return
        active_calls = getattr(self, "_active_tool_start_times", [])
        if not active_calls:
            panel.update("")
            panel.remove_class("visible")
            return
        panel.update(self._active_tools_renderable())
        panel.add_class("visible")

    def _render_tool_failure_card(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        output: str,
        *,
        duration: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Panel:
        """Render a focused failure card for failed tools/commands."""
        metadata = metadata or {}
        body = Text()
        body.append("Command failed\n\n", style=f"bold {THEME['error']}")

        command = (
            metadata.get("command")
            or arguments.get("command")
            or arguments.get("cmd")
            or arguments.get("path")
            or arguments.get("file_path")
            or ""
        )
        cwd = metadata.get("cwd") or arguments.get("cwd") or arguments.get("working_dir") or ""
        exit_code = metadata.get("exit_code")
        timeout = metadata.get("timeout")
        timed_out = bool(metadata.get("timed_out")) or "timed out" in str(output).lower()

        facts: list[str] = []
        duration_label = _format_duration(duration)
        if duration_label:
            facts.append(duration_label)
        if timed_out:
            facts.append(
                f"timeout {timeout:g}s" if isinstance(timeout, (int, float)) else "timeout"
            )
        elif exit_code not in (None, ""):
            facts.append(f"exit {exit_code}")
        if facts:
            body.append("Status: ", style=THEME["muted"])
            body.append("  •  ".join(facts), style=THEME["text"])
            body.append("\n")
        if command:
            body.append("Run: ", style=THEME["muted"])
            body.append(_clip_single_line(str(command), 180), style=THEME["text"])
            body.append("\n")
        if cwd:
            body.append("Cwd: ", style=THEME["muted"])
            body.append(_clip_single_line(str(cwd), 180), style=THEME["muted"])
            body.append("\n")

        tail = _tail_nonempty_lines(output, limit=8)
        if tail:
            body.append("\nLast output:\n", style=THEME["muted"])
            for line in tail:
                body.append("  ")
                body.append(_clip_single_line(line, 220), style=THEME["error"])
                body.append("\n")
        else:
            body.append("\nNo output captured.\n", style=THEME["muted"])

        body.append("\n")
        body.append(":work verbose", style=f"bold {THEME['cyan']}")
        body.append(" for full tool output", style=THEME["muted"])
        return Panel(
            body,
            title=f"[bold {THEME['error']}]Tool failed: {self._format_tool_name(tool_name).title()}[/]",
            border_style=THEME["error"],
            box=ROUNDED,
            padding=(1, 2),
        )

    def _format_tool_name(self, tool_name: str) -> str:
        """Make common tool names read like concise actions."""
        name = tool_name.replace("_", " ").replace("-", " ").strip()
        aliases = {
            "read": "read",
            "read file": "read",
            "read_file": "read",
            "write": "write",
            "write file": "write",
            "write_file": "write",
            "edit": "edit",
            "edit file": "edit",
            "edit_file": "edit",
            "multi edit": "edit",
            "multi_edit": "edit",
            "patch": "patch",
            "bash": "run",
            "shell": "run",
            "terminal": "run",
            "grep": "search",
            "repo search": "search",
            "repo_search": "search",
            "glob": "find",
            "list directory": "list",
            "list_directory": "list",
            "todo write": "todo",
            "todo_write": "todo",
        }
        return aliases.get(name.lower(), name)

    def _format_tool_detail(
        self, tool_name: str, arguments: dict[str, Any], max_length: int
    ) -> str:
        """Return the important target for a tool row without noisy JSON."""
        lower = tool_name.lower()
        keys_by_kind = (
            (
                ("read", "write", "edit", "patch", "create"),
                ("path", "file_path", "filePath", "target_file"),
            ),
            (("bash", "shell", "terminal", "exec"), ("command", "cmd")),
            (("grep", "search", "repo_search"), ("pattern", "query", "search")),
            (("glob", "list", "ls"), ("path", "directory", "pattern")),
            (("todo",), ("todos",)),
        )
        for names, keys in keys_by_kind:
            if not any(name in lower for name in names):
                continue
            for key in keys:
                value = arguments.get(key)
                if value:
                    if key == "todos" and isinstance(value, list):
                        return f"{len(value)} item{'s' if len(value) != 1 else ''}"
                    return _clip_single_line(str(value), max_length)
        compact = format_tool_call_compact(tool_name, arguments, max_length=max_length)
        prefix = f"{tool_name}("
        if compact.startswith(prefix) and compact.endswith(")"):
            compact = compact[len(prefix) : -1]
        return _clip_single_line(compact, max_length)

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

        # Store and render the final response once. Streaming chunks are kept
        # out of the log so markdown tables/code render cleanly here.
        final_response = response_text or self._streaming_response
        if final_response:
            self._streaming_response = final_response
            self.write_final_response(
                final_response,
                agent="Assistant",
                success=success,
                leading_newline=not self._streaming_notice_shown,
                trailing_newline=True,
            )

        summary_content = Text()
        if success:
            summary_content.append("Done", style=f"bold {THEME['success']}")
        else:
            summary_content.append("Failed", style=f"bold {THEME['error']}")

        tool_counts = {}
        for tool in getattr(self, "_tool_calls", []):
            name = tool.get("name", "Unknown")
            tool_counts[name] = tool_counts.get(name, 0) + 1

        files_mod = getattr(self, "_files_modified", set())
        total_tokens = prompt_tokens + completion_tokens

        stats_line = []
        if duration > 0:
            stats_line.append(f"{duration:.1f}s")
        if tool_counts:
            stats_line.append(f"{sum(tool_counts.values())} tools")
        if files_mod:
            stats_line.append(f"{len(files_mod)} changed")
        if total_tokens > 0:
            stats_line.append(f"{total_tokens:,} toks")
        if cost > 0:
            stats_line.append(f"${cost:.4f}")

        if stats_line:
            summary_content.append("  •  ", style=THEME["dim"])
            summary_content.append("  •  ".join(stats_line), style=THEME["dim"])

        if files_mod and getattr(self, "tool_output_mode", "normal") == "verbose":
            summary_content.append("\n")
            for f in sorted(files_mod):
                summary_content.append(f"  {f}\n", style=THEME["warning"])

        summary_content.append("\n")
        self.write(summary_content)

        footer = Text()
        footer.append("  ", style=THEME["dim"])
        footer.append(":work verbose", style=THEME["cyan"])
        footer.append(" details", style=THEME["dim"])
        if files_mod:
            footer.append("  •  ", style=THEME["dim"])
            footer.append(":diff", style=THEME["cyan"])
            footer.append(" changes", style=THEME["dim"])
        footer.append("  •  ", style=THEME["dim"])
        footer.append(":select response", style=THEME["cyan"])
        footer.append(" copy\n", style=THEME["dim"])
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
