"""
SuperQode Design System - Unique Visual Identity.

Design Philosophy:
- QUANTUM-INSPIRED: Playing on the "Q" in SuperQode
- CRYSTALLINE: Sharp, precise, technical aesthetics
- PURPLE/MAGENTA: Signature gradient palette
- MINIMALIST: Clean, no unnecessary decorations
- PURPOSEFUL ANIMATION: Subtle, meaningful motion

Visual Motifs:
- Hexagonal patterns (quantum/molecular)
- Gradient lines (energy flow)
- Minimal borders (clean separation)
- Monospace precision (code-first)

Color System:
- Primary: Purple gradient (#7c3aed → #a855f7)
- Secondary: Magenta accent (#ec4899)
- Success: Emerald (#10b981)
- Warning: Amber (#f59e0b)
- Error: Rose (#f43f5e)
- Background: True black (#000000)
- Surface: Subtle gray (#0a0a0a)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


# ============================================================================
# COLOR PALETTE
# ============================================================================


@dataclass
class ColorPalette:
    """SuperQode signature color palette."""

    # Background layers
    bg_void: str = "#000000"  # True black - deepest
    bg_surface: str = "#050505"  # Almost black surface
    bg_elevated: str = "#0a0a0a"  # Elevated components
    bg_hover: str = "#0f0f0f"  # Hover state
    bg_active: str = "#141414"  # Active/pressed state

    # Border colors
    border_subtle: str = "#1a1a1a"  # Subtle separation
    border_default: str = "#27272a"  # Default borders
    border_strong: str = "#3f3f46"  # Strong emphasis
    border_focus: str = "#7c3aed"  # Focus state (purple)

    # Primary - Purple gradient
    primary_dark: str = "#6d28d9"  # Deep violet
    primary: str = "#7c3aed"  # Main purple
    primary_light: str = "#8b5cf6"  # Light purple
    primary_bright: str = "#a855f7"  # Bright purple
    primary_glow: str = "#c084fc"  # Glowing purple

    # Secondary - Magenta accent
    secondary_dark: str = "#be185d"  # Deep magenta
    secondary: str = "#ec4899"  # Main magenta/pink
    secondary_light: str = "#f472b6"  # Light pink

    # Semantic colors
    success: str = "#10b981"  # Emerald
    success_light: str = "#34d399"  # Light emerald
    warning: str = "#f59e0b"  # Amber
    warning_light: str = "#fbbf24"  # Light amber
    error: str = "#f43f5e"  # Rose red
    error_light: str = "#fb7185"  # Light rose
    info: str = "#06b6d4"  # Cyan
    info_light: str = "#22d3ee"  # Light cyan

    # Text colors
    text_primary: str = "#fafafa"  # Brightest text
    text_secondary: str = "#e4e4e7"  # Normal text
    text_muted: str = "#a1a1aa"  # Muted text
    text_dim: str = "#71717a"  # Dimmed text
    text_ghost: str = "#52525b"  # Ghost text

    # Special colors
    code_bg: str = "#0c0c0c"  # Code block background
    diff_add: str = "#22c55e"  # Diff additions
    diff_remove: str = "#ef4444"  # Diff deletions
    diff_change: str = "#f59e0b"  # Diff changes


COLORS = ColorPalette()


# ============================================================================
# GRADIENT DEFINITIONS
# ============================================================================

# Signature purple gradient (left to right)
GRADIENT_PURPLE = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a855f7", "#c084fc"]

# Magenta accent gradient
GRADIENT_MAGENTA = ["#be185d", "#db2777", "#ec4899", "#f472b6"]

# Full spectrum (for special effects)
GRADIENT_SPECTRUM = [
    "#7c3aed",  # Purple
    "#8b5cf6",  # Light purple
    "#a855f7",  # Bright purple
    "#c084fc",  # Glow purple
    "#ec4899",  # Magenta
    "#f472b6",  # Pink
]

# Quantum energy (for animations)
GRADIENT_QUANTUM = ["#7c3aed", "#06b6d4", "#22c55e", "#f59e0b", "#ec4899"]


# ============================================================================
# ICONS - SUPERQODE STYLE
# ============================================================================

SUPERQODE_ICONS = {
    # Status indicators (quantum-inspired)
    "idle": "◇",  # Empty diamond - idle state
    "active": "◆",  # Filled diamond - active
    "thinking": "◈",  # Diamond with dot - processing
    "streaming": "◇◆",  # Alternating - streaming
    "success": "✦",  # Four-pointed star - success
    "error": "✕",  # X mark - error
    "warning": "⚡",  # Lightning - warning
    # Connection states
    "connected": "●",  # Filled circle - connected
    "disconnected": "○",  # Empty circle - disconnected
    "connecting": "◐",  # Half circle - connecting
    # Tool kinds (minimal, distinct)
    "file_read": "↳",  # Arrow in - reading
    "file_write": "↲",  # Arrow out - writing
    "file_edit": "⟳",  # Rotate - editing
    "shell": "▸",  # Play - shell command
    "search": "⌕",  # Magnifier - search
    "glob": "⋮",  # Vertical dots - glob
    "browser": "◎",  # Target - browser
    "mcp": "⬡",  # Hexagon - MCP (quantum)
    "lsp": "λ",  # Lambda - LSP/language
    "other": "•",  # Bullet - other
    # UI elements
    "expand": "▾",  # Triangle down - expand
    "collapse": "▸",  # Triangle right - collapse
    "menu": "☰",  # Hamburger - menu
    "close": "×",  # X - close
    "pin": "⊙",  # Circle dot - pin
    "unpin": "○",  # Circle - unpin
    # Navigation
    "back": "←",
    "forward": "→",
    "up": "↑",
    "down": "↓",
    # Special
    "quantum": "⬡",  # Hexagon - quantum/SuperQode
    "agent": "◈",  # Diamond dot - agent
    "model": "⬢",  # Filled hexagon - model
    "provider": "⬡",  # Hexagon outline - provider
}


# ============================================================================
# BORDERS & FRAMES (Crystalline/Hexagonal)
# ============================================================================

# Clean minimal borders
BORDER_CHARS = {
    "h": "─",  # Horizontal
    "v": "│",  # Vertical
    "tl": "┌",  # Top left
    "tr": "┐",  # Top right
    "bl": "└",  # Bottom left
    "br": "┘",  # Bottom right
    "t": "┬",  # T down
    "b": "┴",  # T up
    "l": "├",  # T right
    "r": "┤",  # T left
    "x": "┼",  # Cross
}

# Heavy borders for emphasis
BORDER_HEAVY = {
    "h": "━",
    "v": "┃",
    "tl": "┏",
    "tr": "┓",
    "bl": "┗",
    "br": "┛",
}

# Double borders for panels
BORDER_DOUBLE = {
    "h": "═",
    "v": "║",
    "tl": "╔",
    "tr": "╗",
    "bl": "╚",
    "br": "╝",
}


def create_box(width: int, title: str = "", style: str = "default") -> Tuple[str, str, str]:
    """Create top, middle divider, and bottom box lines."""
    chars = (
        BORDER_CHARS if style == "default" else BORDER_HEAVY if style == "heavy" else BORDER_DOUBLE
    )

    if title:
        title_part = f" {title} "
        remaining = width - len(title_part) - 2
        left_pad = remaining // 2
        right_pad = remaining - left_pad
        top = (
            f"{chars['tl']}{chars['h'] * left_pad}{title_part}{chars['h'] * right_pad}{chars['tr']}"
        )
    else:
        top = f"{chars['tl']}{chars['h'] * (width - 2)}{chars['tr']}"

    mid = f"{chars['l']}{chars['h'] * (width - 2)}{chars['r']}"
    bottom = f"{chars['bl']}{chars['h'] * (width - 2)}{chars['br']}"

    return top, mid, bottom


# ============================================================================
# CSS STYLING
# ============================================================================

SUPERQODE_CSS = """
/* ============================================================================
   SUPERQODE DESIGN SYSTEM CSS
   Quantum-inspired, crystalline aesthetics
   ============================================================================ */

/* Base screen */
Screen {
    background: #000000;
}

/* ============================================================================
   LAYOUT: Main Grid
   ============================================================================ */

#sq-main {
    height: 100%;
    layout: horizontal;
}

/* Sidebar - Minimal, precise */
#sq-sidebar {
    width: 36;
    background: #050505;
    border-right: solid #1a1a1a;
}

#sq-sidebar.collapsed {
    width: 0;
    display: none;
}

#sq-sidebar-header {
    height: 2;
    background: #0a0a0a;
    padding: 0 1;
    border-bottom: solid #1a1a1a;
}

/* Content area */
#sq-content {
    width: 1fr;
    height: 100%;
    layout: vertical;
}

/* ============================================================================
   STATUS BAR: Top - Clean, informative
   ============================================================================ */

#sq-status-bar {
    height: 1;
    background: #0a0a0a;
    border-bottom: solid #1a1a1a;
    padding: 0 1;
}

.sq-status-item {
    margin-right: 2;
}

.sq-status-connected {
    color: #10b981;
}

.sq-status-disconnected {
    color: #71717a;
}

/* ============================================================================
   TOOL PANEL: Collapsible, minimal
   ============================================================================ */

#sq-tool-panel {
    height: auto;
    max-height: 25%;
    background: #050505;
    border-bottom: solid #1a1a1a;
    padding: 0 1;
}

#sq-tool-panel.collapsed {
    max-height: 1;
    overflow: hidden;
}

#sq-tool-panel .tool-header {
    height: 1;
    color: #a1a1aa;
}

#sq-tool-panel .tool-item {
    padding: 0 1;
    border-left: solid #27272a;
    margin-left: 1;
}

#sq-tool-panel .tool-item.running {
    border-left: solid #7c3aed;
}

#sq-tool-panel .tool-item.success {
    border-left: solid #10b981;
}

#sq-tool-panel .tool-item.error {
    border-left: solid #f43f5e;
}

/* ============================================================================
   THINKING INDICATOR: Subtle, informative
   ============================================================================ */

#sq-thinking {
    height: auto;
    max-height: 15%;
    background: #050505;
    border-bottom: solid #7c3aed40;
    padding: 0 1;
    display: none;
}

#sq-thinking.visible {
    display: block;
}

#sq-thinking .thinking-label {
    color: #8b5cf6;
    text-style: italic;
}

#sq-thinking .thinking-text {
    color: #a1a1aa;
    text-style: italic;
}

/* ============================================================================
   CONVERSATION: Main content area
   ============================================================================ */

#sq-conversation {
    height: 1fr;
    background: #000000;
    padding: 1 2;
    overflow-y: auto;
}

/* Message styling */
.sq-message {
    margin-bottom: 1;
    padding: 0 1;
}

.sq-message-user {
    border-left: solid #7c3aed;
}

.sq-message-assistant {
    border-left: solid #ec4899;
}

.sq-message-system {
    border-left: solid #52525b;
    color: #71717a;
}

/* Code blocks - Precise, minimal */
.sq-code-block {
    background: #0c0c0c;
    border: solid #1a1a1a;
    padding: 1;
    margin: 1 0;
}

.sq-code-header {
    background: #0f0f0f;
    padding: 0 1;
    color: #71717a;
    border-bottom: solid #1a1a1a;
}

/* ============================================================================
   PROMPT AREA: Clean input
   ============================================================================ */

#sq-prompt-area {
    height: auto;
    min-height: 3;
    max-height: 8;
    background: #0a0a0a;
    border-top: solid #1a1a1a;
    padding: 1;
}

#sq-prompt-area.hidden {
    display: none;
}

#sq-prompt-input-box {
    background: #050505;
    border: solid #27272a;
    padding: 0 1;
}

#sq-prompt-input-box:focus-within {
    border: solid #7c3aed;
}

#sq-prompt-symbol {
    width: 2;
    color: #7c3aed;
}

#sq-prompt-input {
    background: transparent;
    border: none;
    width: 1fr;
}

/* Mode indicator */
#sq-mode-indicator {
    height: 1;
    padding: 0 1;
}

.sq-mode-auto {
    color: #10b981;
}

.sq-mode-ask {
    color: #f59e0b;
}

.sq-mode-deny {
    color: #f43f5e;
}

/* ============================================================================
   SPLIT VIEW: Code + Chat
   ============================================================================ */

#sq-split-container {
    height: 100%;
    layout: horizontal;
}

#sq-split-left {
    width: 50%;
    border-right: solid #1a1a1a;
}

#sq-split-right {
    width: 50%;
}

#sq-split-divider {
    width: 1;
    background: #1a1a1a;
    cursor: col-resize;
}

#sq-split-divider:hover {
    background: #7c3aed;
}

/* ============================================================================
   DIFF VIEW: Clean, precise
   ============================================================================ */

.sq-diff {
    background: #0c0c0c;
    border: solid #1a1a1a;
    padding: 1;
}

.sq-diff-add {
    background: #22c55e15;
    color: #22c55e;
}

.sq-diff-remove {
    background: #ef444415;
    color: #ef4444;
}

.sq-diff-context {
    color: #71717a;
}

.sq-diff-line-number {
    color: #52525b;
    width: 4;
    text-align: right;
    padding-right: 1;
}

/* ============================================================================
   CONNECTION PANEL: ACP/BYOK status
   ============================================================================ */

#sq-connection-panel {
    background: #050505;
    border: solid #1a1a1a;
    padding: 1;
}

.sq-connection-header {
    color: #a1a1aa;
    margin-bottom: 1;
}

.sq-connection-acp {
    color: #10b981;
}

.sq-connection-byok {
    color: #06b6d4;
}

.sq-connection-local {
    color: #f59e0b;
}

/* ============================================================================
   ANIMATIONS: Subtle, purposeful
   ============================================================================ */

/* Quantum pulse - for active states */
@keyframes sq-pulse {
    0% { color: #7c3aed; }
    50% { color: #a855f7; }
    100% { color: #7c3aed; }
}

.sq-pulse {
    animation: sq-pulse 2s infinite;
}

/* Stream indicator */
@keyframes sq-stream {
    0% { opacity: 0.3; }
    50% { opacity: 1; }
    100% { opacity: 0.3; }
}

.sq-streaming {
    animation: sq-stream 1s infinite;
}

/* ============================================================================
   FOOTER: Minimal
   ============================================================================ */

Footer {
    background: #0a0a0a;
    color: #52525b;
    height: 1;
}

Footer .footer-key {
    color: #7c3aed;
}
"""


# ============================================================================
# TEXT RENDERING HELPERS
# ============================================================================


def render_gradient_text(text: str, gradient: List[str] = None) -> "Text":
    """Render text with a gradient effect."""
    from rich.text import Text

    if gradient is None:
        gradient = GRADIENT_PURPLE

    result = Text()
    for i, char in enumerate(text):
        color = gradient[i % len(gradient)]
        result.append(char, style=f"bold {color}")

    return result


def render_status_indicator(
    connected: bool,
    agent_name: str = "",
    model_name: str = "",
    connection_type: str = "",
) -> "Text":
    """Render a clean status indicator."""
    from rich.text import Text

    result = Text()

    # Connection status
    if connected:
        result.append(SUPERQODE_ICONS["connected"], style=f"bold {COLORS.success}")
        result.append(" ", style="")

        if agent_name:
            result.append(agent_name, style=f"bold {COLORS.text_secondary}")

        if model_name:
            if agent_name:
                result.append(" → ", style=COLORS.text_dim)
            result.append(model_name, style=COLORS.text_muted)

        if connection_type:
            conn_color = {
                "acp": COLORS.success,
                "byok": COLORS.info,
                "local": COLORS.warning,
            }.get(connection_type, COLORS.text_muted)
            result.append(f" [{connection_type.upper()}]", style=conn_color)
    else:
        result.append(SUPERQODE_ICONS["disconnected"], style=COLORS.text_dim)
        result.append(" Not connected", style=COLORS.text_dim)

    return result


def render_tool_indicator(
    name: str,
    kind: str,
    status: str = "running",
    file_path: str = "",
) -> "Text":
    """Render a minimal tool indicator."""
    from rich.text import Text

    result = Text()

    # Status icon
    icon = SUPERQODE_ICONS.get(f"file_{kind}", SUPERQODE_ICONS.get(kind, SUPERQODE_ICONS["other"]))

    status_styles = {
        "pending": COLORS.text_dim,
        "running": COLORS.primary,
        "success": COLORS.success,
        "error": COLORS.error,
    }
    style = status_styles.get(status, COLORS.text_muted)

    result.append(f"{icon} ", style=f"bold {style}")
    result.append(name, style=COLORS.text_secondary)

    if file_path:
        result.append(f"  {file_path}", style=COLORS.text_dim)

    return result


def render_thinking_line(text: str) -> "Text":
    """Render a subtle thinking line."""
    from rich.text import Text

    result = Text()
    result.append(f"{SUPERQODE_ICONS['thinking']} ", style=f"bold {COLORS.primary_light}")

    # Truncate if too long
    display = text[:80] + "…" if len(text) > 80 else text
    result.append(display, style=f"italic {COLORS.text_muted}")

    return result


def render_message_header(
    role: str,
    agent_name: str = "",
    timestamp: str = "",
    token_count: int = 0,
) -> "Text":
    """Render a clean message header."""
    from rich.text import Text

    result = Text()

    if role == "user":
        result.append("▸ ", style=f"bold {COLORS.primary}")
        result.append("You", style=f"bold {COLORS.text_primary}")
    elif role == "assistant":
        result.append("◇ ", style=f"bold {COLORS.secondary}")
        if agent_name:
            result.append(agent_name, style=f"bold {COLORS.text_primary}")
        else:
            result.append("Assistant", style=f"bold {COLORS.text_primary}")
    else:
        result.append("• ", style=COLORS.text_dim)
        result.append(role.title(), style=COLORS.text_muted)

    if timestamp:
        result.append(f"  {timestamp}", style=COLORS.text_ghost)

    if token_count > 0:
        result.append(f"  {token_count} tokens", style=COLORS.text_ghost)

    return result


# ============================================================================
# QUANTUM ANIMATIONS (Character-based)
# ============================================================================

QUANTUM_FRAMES = [
    "◇ ◇ ◇",
    "◆ ◇ ◇",
    "◇ ◆ ◇",
    "◇ ◇ ◆",
    "◇ ◆ ◇",
    "◆ ◇ ◇",
]

STREAM_FRAMES = [
    "▸",
    "▸▸",
    "▸▸▸",
    "▸▸",
    "▸",
    "",
]

THINKING_FRAMES = [
    "◈    ",
    " ◈   ",
    "  ◈  ",
    "   ◈ ",
    "    ◈",
    "   ◈ ",
    "  ◈  ",
    " ◈   ",
]


def get_animation_frame(name: str, tick: int) -> str:
    """Get animation frame by name and tick count."""
    frames = {
        "quantum": QUANTUM_FRAMES,
        "stream": STREAM_FRAMES,
        "thinking": THINKING_FRAMES,
    }

    frame_list = frames.get(name, QUANTUM_FRAMES)
    return frame_list[tick % len(frame_list)]


# ============================================================================
# THEME SYSTEM
# ============================================================================


@dataclass
class Theme:
    """A complete color theme."""

    name: str
    description: str
    colors: ColorPalette


# Built-in themes
THEME_SUPERQODE = Theme(
    name="superqode",
    description="Default SuperQode theme - Purple quantum aesthetics",
    colors=ColorPalette(),  # Default colors
)

THEME_TOKYONIGHT = Theme(
    name="tokyonight",
    description="Tokyo Night - Deep blue with neon accents",
    colors=ColorPalette(
        # Background layers - deep blue
        bg_void="#1a1b26",
        bg_surface="#1f2335",
        bg_elevated="#24283b",
        bg_hover="#292e42",
        bg_active="#3b4261",
        # Border colors
        border_subtle="#292e42",
        border_default="#3b4261",
        border_strong="#565f89",
        border_focus="#7aa2f7",
        # Primary - Blue
        primary_dark="#3d59a1",
        primary="#7aa2f7",
        primary_light="#89b4fa",
        primary_bright="#b4f9f8",
        primary_glow="#c0caf5",
        # Secondary - Magenta
        secondary_dark="#ad8ee6",
        secondary="#bb9af7",
        secondary_light="#c0caf5",
        # Semantic colors
        success="#9ece6a",
        success_light="#a9dc76",
        warning="#e0af68",
        warning_light="#f7c273",
        error="#f7768e",
        error_light="#ff9e64",
        info="#7dcfff",
        info_light="#89ddff",
        # Text colors
        text_primary="#c0caf5",
        text_secondary="#a9b1d6",
        text_muted="#737aa2",
        text_dim="#565f89",
        text_ghost="#414868",
        # Special
        code_bg="#1f2335",
        diff_add="#9ece6a",
        diff_remove="#f7768e",
        diff_change="#e0af68",
    ),
)

THEME_DRACULA = Theme(
    name="dracula",
    description="Dracula - Classic dark with vivid colors",
    colors=ColorPalette(
        # Background layers
        bg_void="#282a36",
        bg_surface="#1e1f29",
        bg_elevated="#21222c",
        bg_hover="#343746",
        bg_active="#44475a",
        # Border colors
        border_subtle="#343746",
        border_default="#44475a",
        border_strong="#6272a4",
        border_focus="#bd93f9",
        # Primary - Purple
        primary_dark="#6d28d9",
        primary="#bd93f9",
        primary_light="#caa9fa",
        primary_bright="#d6bcfa",
        primary_glow="#e2cffc",
        # Secondary - Pink
        secondary_dark="#e64faf",
        secondary="#ff79c6",
        secondary_light="#ff92d0",
        # Semantic colors
        success="#50fa7b",
        success_light="#69ff94",
        warning="#ffb86c",
        warning_light="#ffc67d",
        error="#ff5555",
        error_light="#ff6e6e",
        info="#8be9fd",
        info_light="#9ff2ff",
        # Text colors
        text_primary="#f8f8f2",
        text_secondary="#e4e4ef",
        text_muted="#a9a9b5",
        text_dim="#6272a4",
        text_ghost="#44475a",
        # Special
        code_bg="#1e1f29",
        diff_add="#50fa7b",
        diff_remove="#ff5555",
        diff_change="#ffb86c",
    ),
)

THEME_NORD = Theme(
    name="nord",
    description="Nord - Arctic, calm blue palette",
    colors=ColorPalette(
        # Background layers - polar night
        bg_void="#2e3440",
        bg_surface="#3b4252",
        bg_elevated="#434c5e",
        bg_hover="#4c566a",
        bg_active="#5e6779",
        # Border colors
        border_subtle="#3b4252",
        border_default="#434c5e",
        border_strong="#4c566a",
        border_focus="#88c0d0",
        # Primary - Frost
        primary_dark="#5e81ac",
        primary="#81a1c1",
        primary_light="#88c0d0",
        primary_bright="#8fbcbb",
        primary_glow="#a3d3d2",
        # Secondary - Aurora
        secondary_dark="#b48ead",
        secondary="#b48ead",
        secondary_light="#c4a1b8",
        # Semantic colors
        success="#a3be8c",
        success_light="#b4d89a",
        warning="#ebcb8b",
        warning_light="#f0d899",
        error="#bf616a",
        error_light="#d08770",
        info="#88c0d0",
        info_light="#8fbcbb",
        # Text colors
        text_primary="#eceff4",
        text_secondary="#e5e9f0",
        text_muted="#d8dee9",
        text_dim="#a3adb8",
        text_ghost="#4c566a",
        # Special
        code_bg="#3b4252",
        diff_add="#a3be8c",
        diff_remove="#bf616a",
        diff_change="#ebcb8b",
    ),
)

THEME_MONOKAI = Theme(
    name="monokai",
    description="Monokai Pro - Warm, vibrant colors",
    colors=ColorPalette(
        # Background layers
        bg_void="#2d2a2e",
        bg_surface="#221f22",
        bg_elevated="#2d2a2e",
        bg_hover="#363337",
        bg_active="#403e41",
        # Border colors
        border_subtle="#363337",
        border_default="#403e41",
        border_strong="#5b595c",
        border_focus="#ffd866",
        # Primary - Yellow
        primary_dark="#d9a23a",
        primary="#ffd866",
        primary_light="#ffe17d",
        primary_bright="#ffe999",
        primary_glow="#fff2b5",
        # Secondary - Pink
        secondary_dark="#cc6a7f",
        secondary="#ff6188",
        secondary_light="#ff7a9a",
        # Semantic colors
        success="#a9dc76",
        success_light="#b8e38a",
        warning="#ffd866",
        warning_light="#ffe17d",
        error="#ff6188",
        error_light="#ff7a9a",
        info="#78dce8",
        info_light="#8ce4ed",
        # Text colors
        text_primary="#fcfcfa",
        text_secondary="#f2f2f0",
        text_muted="#939293",
        text_dim="#727072",
        text_ghost="#5b595c",
        # Special
        code_bg="#221f22",
        diff_add="#a9dc76",
        diff_remove="#ff6188",
        diff_change="#ffd866",
    ),
)

THEME_GRUVBOX = Theme(
    name="gruvbox",
    description="Gruvbox - Retro, earthy tones",
    colors=ColorPalette(
        # Background layers
        bg_void="#282828",
        bg_surface="#1d2021",
        bg_elevated="#282828",
        bg_hover="#32302f",
        bg_active="#3c3836",
        # Border colors
        border_subtle="#3c3836",
        border_default="#504945",
        border_strong="#665c54",
        border_focus="#fe8019",
        # Primary - Orange
        primary_dark="#d65d0e",
        primary="#fe8019",
        primary_light="#fe9932",
        primary_bright="#feb24c",
        primary_glow="#fec969",
        # Secondary - Aqua
        secondary_dark="#689d6a",
        secondary="#8ec07c",
        secondary_light="#a0cf8f",
        # Semantic colors
        success="#b8bb26",
        success_light="#c5c93a",
        warning="#fabd2f",
        warning_light="#fcca4b",
        error="#fb4934",
        error_light="#fc5f51",
        info="#83a598",
        info_light="#94b6a8",
        # Text colors
        text_primary="#ebdbb2",
        text_secondary="#d5c4a1",
        text_muted="#928374",
        text_dim="#7c6f64",
        text_ghost="#504945",
        # Special
        code_bg="#1d2021",
        diff_add="#b8bb26",
        diff_remove="#fb4934",
        diff_change="#fabd2f",
    ),
)


# Theme registry
THEMES: Dict[str, Theme] = {
    "superqode": THEME_SUPERQODE,
    "tokyonight": THEME_TOKYONIGHT,
    "dracula": THEME_DRACULA,
    "nord": THEME_NORD,
    "monokai": THEME_MONOKAI,
    "gruvbox": THEME_GRUVBOX,
}

# Active theme (mutable)
_active_theme: str = "superqode"


def get_theme(name: str = None) -> Theme:
    """Get a theme by name, or the active theme if no name given."""
    if name is None:
        name = _active_theme
    return THEMES.get(name, THEME_SUPERQODE)


def set_theme(name: str) -> bool:
    """Set the active theme. Returns True if successful."""
    global _active_theme, COLORS
    if name in THEMES:
        _active_theme = name
        COLORS = THEMES[name].colors
        return True
    return False


def get_active_theme_name() -> str:
    """Get the name of the active theme."""
    return _active_theme


def list_themes() -> List[Tuple[str, str]]:
    """List all available themes as (name, description) tuples."""
    return [(name, theme.description) for name, theme in THEMES.items()]
