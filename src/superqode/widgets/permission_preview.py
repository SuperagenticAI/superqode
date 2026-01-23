"""
Permission Preview Screen - Visual Permission Request Display.

Shows permission requests with full context including:
- File diff previews with multiple view modes
- Multi-file navigator
- Synchronized scrolling for split view
- Command analysis
- Impact assessment
- Quick action buttons

Provides users with all information needed to make informed permission decisions.

Enhanced Features:
- Multi-file navigator with file type icons
- Split/Unified/Auto diff view modes
- Synchronized scrolling between old/new panes
- j/k navigation
- Full diff context with scrolling
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich.console import RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static, OptionList, Select
from textual.widgets.option_list import Option
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from textual import events


class PreviewType(Enum):
    """Type of preview to show."""

    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    SHELL_COMMAND = "shell_command"
    NETWORK = "network"


@dataclass
class PermissionContext:
    """Context for a permission request."""

    request_id: str
    preview_type: PreviewType
    title: str
    description: str

    # File-related
    file_path: Optional[str] = None
    original_content: Optional[str] = None
    new_content: Optional[str] = None

    # Command-related
    command: Optional[str] = None
    working_dir: Optional[str] = None

    # Analysis
    risk_level: str = "medium"  # low, medium, high, critical
    risk_factors: List[str] = None
    affected_files: List[str] = None

    # Agent info
    agent_name: str = ""
    reason: str = ""

    def __post_init__(self):
        if self.risk_factors is None:
            self.risk_factors = []
        if self.affected_files is None:
            self.affected_files = []


# Risk level colors and icons
RISK_STYLES = {
    "low": {"color": "#22c55e", "icon": "🟢", "label": "Low Risk"},
    "medium": {"color": "#eab308", "icon": "🟡", "label": "Medium Risk"},
    "high": {"color": "#f97316", "icon": "🟠", "label": "High Risk"},
    "critical": {"color": "#ef4444", "icon": "🔴", "label": "Critical"},
}


class PermissionPreview(Static):
    """
    Permission preview widget showing request details.

    Displays file diffs, command analysis, and risk assessment
    to help users make informed permission decisions.
    """

    DEFAULT_CSS = """
    PermissionPreview {
        height: auto;
        border: solid #3f3f46;
        padding: 1;
        margin: 1;
    }

    PermissionPreview.high-risk {
        border: solid #f97316;
    }

    PermissionPreview.critical {
        border: solid #ef4444;
    }
    """

    # Reactive state
    expanded: reactive[bool] = reactive(True)

    def __init__(
        self,
        context: PermissionContext,
        on_allow: Optional[Callable[[], None]] = None,
        on_deny: Optional[Callable[[], None]] = None,
        on_allow_all: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.context = context
        self._on_allow = on_allow
        self._on_deny = on_deny
        self._on_allow_all = on_allow_all

        # Set risk class
        if context.risk_level in ("high", "critical"):
            self.add_class(context.risk_level)

    def on_key(self, event: events.Key) -> None:
        """Handle key events for quick actions."""
        if event.key == "y":
            if self._on_allow:
                self._on_allow()
            event.prevent_default()
        elif event.key == "n":
            if self._on_deny:
                self._on_deny()
            event.prevent_default()
        elif event.key == "a":
            if self._on_allow_all:
                self._on_allow_all()
            event.prevent_default()
        elif event.key == "space":
            self.expanded = not self.expanded
            self.refresh()
            event.prevent_default()

    def _render_diff(self) -> Text:
        """Render file diff preview."""
        result = Text()

        if not self.context.original_content and not self.context.new_content:
            result.append("  No content preview available\n", style="#6b7280")
            return result

        original = self.context.original_content or ""
        new = self.context.new_content or ""

        original_lines = original.splitlines() if original else []
        new_lines = new.splitlines() if new else []

        # Simple diff display
        if not original_lines:
            # New file
            result.append("  [NEW FILE]\n", style="bold #22c55e")
            for i, line in enumerate(new_lines[:20]):  # Limit preview
                result.append(f"  {i + 1:4} │ ", style="#6b7280")
                result.append(f"+{line}\n", style="#22c55e")
            if len(new_lines) > 20:
                result.append(f"  ... and {len(new_lines) - 20} more lines\n", style="#6b7280")
        elif not new_lines:
            # File deletion
            result.append("  [FILE DELETED]\n", style="bold #ef4444")
            for i, line in enumerate(original_lines[:10]):
                result.append(f"  {i + 1:4} │ ", style="#6b7280")
                result.append(f"-{line}\n", style="#ef4444")
            if len(original_lines) > 10:
                result.append(f"  ... and {len(original_lines) - 10} more lines\n", style="#6b7280")
        else:
            # Modified file - show unified diff style
            result.append("  [MODIFIED]\n", style="bold #eab308")

            # Very simple diff - just show changes
            max_lines = max(len(original_lines), len(new_lines))
            shown = 0

            for i in range(min(max_lines, 30)):
                orig = original_lines[i] if i < len(original_lines) else None
                new = new_lines[i] if i < len(new_lines) else None

                if orig == new:
                    if shown < 10:  # Show some context
                        result.append(f"  {i + 1:4} │ ", style="#6b7280")
                        result.append(f" {orig}\n", style="#a1a1aa")
                        shown += 1
                else:
                    if orig:
                        result.append(f"  {i + 1:4} │ ", style="#6b7280")
                        result.append(f"-{orig}\n", style="#ef4444")
                    if new:
                        result.append(f"  {i + 1:4} │ ", style="#6b7280")
                        result.append(f"+{new}\n", style="#22c55e")
                    shown += 1

            if max_lines > 30:
                result.append(f"  ... and more changes\n", style="#6b7280")

        return result

    def _render_command(self) -> Text:
        """Render command preview."""
        result = Text()

        if not self.context.command:
            return result

        result.append("  Command:\n", style="bold #a1a1aa")
        result.append(f"  $ {self.context.command}\n", style="bold #e2e8f0")

        if self.context.working_dir:
            result.append(f"  Working Directory: {self.context.working_dir}\n", style="#6b7280")

        return result

    def _render_risk_assessment(self) -> Text:
        """Render risk assessment section."""
        result = Text()

        style = RISK_STYLES.get(self.context.risk_level, RISK_STYLES["medium"])

        result.append("\n")
        result.append(f"  {style['icon']} Risk: ", style="#a1a1aa")
        result.append(f"{style['label']}\n", style=f"bold {style['color']}")

        if self.context.risk_factors:
            result.append("  Factors:\n", style="#a1a1aa")
            for factor in self.context.risk_factors:
                result.append(f"    • {factor}\n", style="#6b7280")

        return result

    def _render_actions(self) -> Text:
        """Render action hints."""
        result = Text()

        result.append("\n")
        result.append("  ─────────────────────────────────────────\n", style="#3f3f46")
        result.append("  ", style="")
        result.append("[y]", style="bold #22c55e")
        result.append(" Allow  ", style="#a1a1aa")
        result.append("[n]", style="bold #ef4444")
        result.append(" Deny  ", style="#a1a1aa")
        result.append("[a]", style="bold #3b82f6")
        result.append(" Always Allow  ", style="#a1a1aa")
        result.append("[space]", style="bold #6b7280")
        result.append(" Toggle Details\n", style="#a1a1aa")

        return result

    def render(self) -> RenderableType:
        """Render the permission preview."""
        content = Text()

        style = RISK_STYLES.get(self.context.risk_level, RISK_STYLES["medium"])

        # Header
        content.append(f"  {style['icon']} ", style="")
        content.append(self.context.title, style=f"bold {style['color']}")
        content.append("\n")

        # Agent info
        if self.context.agent_name:
            content.append(f"  Agent: {self.context.agent_name}\n", style="#6b7280")

        # Description
        if self.context.description:
            content.append(f"  {self.context.description}\n", style="#a1a1aa")

        # File path
        if self.context.file_path:
            content.append("  File: ", style="#6b7280")
            content.append(f"{self.context.file_path}\n", style="bold #3b82f6")

        # Expanded content
        if self.expanded:
            content.append("\n")

            if self.context.preview_type in (PreviewType.FILE_WRITE, PreviewType.FILE_DELETE):
                content.append(self._render_diff())
            elif self.context.preview_type == PreviewType.SHELL_COMMAND:
                content.append(self._render_command())

            content.append(self._render_risk_assessment())

        # Actions
        content.append(self._render_actions())

        border_color = (
            style["color"] if self.context.risk_level in ("high", "critical") else "#3f3f46"
        )

        return Panel(
            content,
            title=f"[bold {style['color']}]⚠ Permission Request[/]",
            border_style=border_color,
            padding=(0, 0),
        )


class PermissionPreviewScreen(Container):
    """
    Full screen permission preview with multiple requests.

    Shows a queue of pending permission requests with
    batch approval options.
    """

    DEFAULT_CSS = """
    PermissionPreviewScreen {
        width: 100%;
        height: 100%;
        background: #0f0f0f;
        padding: 1;
    }

    PermissionPreviewScreen .header {
        height: 3;
        margin-bottom: 1;
    }

    PermissionPreviewScreen .content {
        height: 1fr;
        overflow-y: auto;
    }

    PermissionPreviewScreen .footer {
        height: 3;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        requests: List[PermissionContext],
        on_decision: Callable[[str, str], None],  # (request_id, action)
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.requests = requests
        self._on_decision = on_decision
        self._current_index = 0

    def compose(self):
        """Compose the screen layout."""
        # Header
        with Horizontal(classes="header"):
            yield Static(
                f"[bold #3b82f6]Permission Requests[/] ({len(self.requests)} pending)",
                id="header-title",
            )

        # Content - current preview
        with Container(classes="content"):
            if self.requests:
                yield PermissionPreview(
                    self.requests[self._current_index],
                    on_allow=lambda: self._handle_decision("allow"),
                    on_deny=lambda: self._handle_decision("deny"),
                    on_allow_all=lambda: self._handle_decision("allow_all"),
                    id="current-preview",
                )

        # Footer
        with Horizontal(classes="footer"):
            yield Static(
                "[←/→] Navigate  [y] Allow  [n] Deny  [a] Allow All  [Esc] Close",
                id="footer-hints",
            )

    def _handle_decision(self, action: str) -> None:
        """Handle a permission decision."""
        if not self.requests:
            return

        request = self.requests[self._current_index]
        self._on_decision(request.request_id, action)

        # Move to next request
        self.requests.pop(self._current_index)

        if not self.requests:
            # All requests handled
            self.remove()
            return

        # Adjust index
        if self._current_index >= len(self.requests):
            self._current_index = len(self.requests) - 1

        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Refresh the current preview."""
        # Remove old preview
        old = self.query_one("#current-preview", PermissionPreview)
        old.remove()

        # Add new preview
        content = self.query_one(".content", Container)
        content.mount(
            PermissionPreview(
                self.requests[self._current_index],
                on_allow=lambda: self._handle_decision("allow"),
                on_deny=lambda: self._handle_decision("deny"),
                on_allow_all=lambda: self._handle_decision("allow_all"),
                id="current-preview",
            )
        )

        # Update header
        header = self.query_one("#header-title", Static)
        header.update(f"[bold #3b82f6]Permission Requests[/] ({len(self.requests)} pending)")

    def on_key(self, event: events.Key) -> None:
        """Handle navigation keys."""
        if event.key == "left" and self._current_index > 0:
            self._current_index -= 1
            self._refresh_preview()
            event.prevent_default()
        elif event.key == "right" and self._current_index < len(self.requests) - 1:
            self._current_index += 1
            self._refresh_preview()
            event.prevent_default()
        elif event.key == "escape":
            self.remove()
            event.prevent_default()


def analyze_command_risk(command: str) -> Dict[str, Any]:
    """Analyze a shell command for risk factors."""
    risk_factors = []
    risk_level = "low"

    # Dangerous patterns
    dangerous_patterns = [
        (r"rm\s+-rf", "Recursive forced deletion", "critical"),
        (r"rm\s+-r", "Recursive deletion", "high"),
        (r">\s*/dev/", "Writing to device", "critical"),
        (r"mkfs", "Filesystem creation", "critical"),
        (r"dd\s+", "Direct disk write", "critical"),
        (r"chmod\s+777", "World-writable permissions", "high"),
        (r"curl.*\|\s*(bash|sh)", "Remote code execution", "critical"),
        (r"wget.*\|\s*(bash|sh)", "Remote code execution", "critical"),
        (r"sudo\s+", "Elevated privileges", "high"),
        (r">\s*~", "Writing to home directory", "medium"),
        (r"pip\s+install", "Package installation", "medium"),
        (r"npm\s+install", "Package installation", "medium"),
    ]

    import re

    for pattern, description, level in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            risk_factors.append(description)
            if level == "critical":
                risk_level = "critical"
            elif level == "high" and risk_level not in ("critical",):
                risk_level = "high"
            elif level == "medium" and risk_level == "low":
                risk_level = "medium"

    return {
        "risk_level": risk_level,
        "risk_factors": risk_factors,
    }


def create_file_write_preview(
    file_path: str,
    original_content: Optional[str],
    new_content: str,
    agent_name: str = "",
    reason: str = "",
) -> PermissionContext:
    """Create a permission context for file write."""
    import hashlib

    request_id = hashlib.sha256(
        f"write:{file_path}:{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12]

    risk_factors = []
    risk_level = "low"

    # Analyze risk
    if file_path.endswith((".env", ".key", ".pem")):
        risk_factors.append("Sensitive file type")
        risk_level = "high"

    if file_path.startswith(("/etc/", "/usr/", "/bin/", "/sbin/")):
        risk_factors.append("System directory")
        risk_level = "critical"

    if original_content is None:
        risk_factors.append("Creating new file")

    return PermissionContext(
        request_id=f"req-{request_id}",
        preview_type=PreviewType.FILE_WRITE,
        title=f"Write to {Path(file_path).name}",
        description=reason or "Agent wants to modify this file",
        file_path=file_path,
        original_content=original_content,
        new_content=new_content,
        risk_level=risk_level,
        risk_factors=risk_factors,
        agent_name=agent_name,
        reason=reason,
    )


def create_command_preview(
    command: str,
    working_dir: str = "",
    agent_name: str = "",
    reason: str = "",
) -> PermissionContext:
    """Create a permission context for shell command."""
    import hashlib

    request_id = hashlib.sha256(f"cmd:{command}:{datetime.now().isoformat()}".encode()).hexdigest()[
        :12
    ]

    # Analyze command risk
    analysis = analyze_command_risk(command)

    return PermissionContext(
        request_id=f"req-{request_id}",
        preview_type=PreviewType.SHELL_COMMAND,
        title="Execute Shell Command",
        description=reason or "Agent wants to run this command",
        command=command,
        working_dir=working_dir,
        risk_level=analysis["risk_level"],
        risk_factors=analysis["risk_factors"],
        agent_name=agent_name,
        reason=reason,
    )


# ============================================================================
# Enhanced Permission Preview Components
# ============================================================================


class DiffViewMode(Enum):
    """Diff view mode."""

    UNIFIED = "unified"
    SPLIT = "split"
    AUTO = "auto"


# File type icons for navigator
FILE_TYPE_ICONS = {
    ".py": "",
    ".js": "",
    ".ts": "",
    ".tsx": "",
    ".jsx": "",
    ".html": "",
    ".css": "",
    ".json": "",
    ".md": "",
    ".yaml": "",
    ".yml": "",
    ".toml": "",
    ".sh": "",
    ".bash": "",
    ".zsh": "",
    ".go": "",
    ".rs": "",
    ".java": "",
    ".rb": "",
    ".php": "",
    ".c": "",
    ".cpp": "",
    ".h": "",
    ".sql": "",
    ".txt": "",
    ".env": "",
    ".gitignore": "",
}

PREVIEW_TYPE_ICONS = {
    PreviewType.FILE_WRITE: "",
    PreviewType.FILE_DELETE: "",
    PreviewType.SHELL_COMMAND: "",
    PreviewType.NETWORK: "",
}


def get_file_icon(file_path: str) -> str:
    """Get icon for a file based on extension."""
    if not file_path:
        return ""

    path = Path(file_path)
    ext = path.suffix.lower()

    # Check exact filename matches first
    if path.name in FILE_TYPE_ICONS:
        return FILE_TYPE_ICONS[path.name]

    # Check extension
    return FILE_TYPE_ICONS.get(ext, "")


class PermissionNavigator(OptionList):
    """
    List of pending permission requests.

    Shows all requests with icons and allows navigation.
    """

    DEFAULT_CSS = """
    PermissionNavigator {
        width: 25;
        height: 100%;
        border-right: solid #3f3f46;
        background: #0f0f0f;
    }

    PermissionNavigator > .option-list--option {
        padding: 0 1;
    }

    PermissionNavigator > .option-list--option-highlighted {
        background: #27272a;
    }
    """

    def __init__(
        self,
        requests: List[PermissionContext],
        on_select: Optional[Callable[[int], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.requests = requests
        self._on_select = on_select

    def on_mount(self) -> None:
        """Populate the navigator on mount."""
        for i, req in enumerate(self.requests):
            icon = PREVIEW_TYPE_ICONS.get(req.preview_type, "")

            # Get file icon if applicable
            if req.file_path:
                file_icon = get_file_icon(req.file_path)
                label = f"{icon} {file_icon} {Path(req.file_path).name}"
            elif req.command:
                label = f"{icon} {req.command[:20]}..."
            else:
                label = f"{icon} {req.title[:20]}"

            # Add risk indicator
            risk_indicators = {
                "low": "[green]●[/]",
                "medium": "[yellow]●[/]",
                "high": "[orange1]●[/]",
                "critical": "[red]●[/]",
            }
            risk_dot = risk_indicators.get(req.risk_level, "[white]●[/]")

            self.add_option(Option(f"{risk_dot} {label}", id=str(i)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if self._on_select:
            index = int(str(event.option.id))
            self._on_select(index)


class DiffModeSelector(Select):
    """Dropdown to select diff view mode."""

    DEFAULT_CSS = """
    DiffModeSelector {
        width: 16;
        margin: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(
            options=[
                ("Unified", DiffViewMode.UNIFIED.value),
                ("Split", DiffViewMode.SPLIT.value),
                ("Auto", DiffViewMode.AUTO.value),
            ],
            value=DiffViewMode.UNIFIED.value,
            **kwargs,
        )


class DiffPane(ScrollableContainer):
    """Single pane of a split diff view."""

    DEFAULT_CSS = """
    DiffPane {
        width: 1fr;
        height: 100%;
        border: round #3f3f46;
        padding: 0 1;
    }

    DiffPane.old {
        border: round #ef4444;
    }

    DiffPane.new {
        border: round #22c55e;
    }
    """

    def __init__(
        self,
        content: str,
        side: str = "old",
        on_scroll: Optional[Callable[[int, int], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.content = content
        self.side = side
        self._on_scroll = on_scroll
        self.add_class(side)

    def compose(self):
        """Compose the diff pane."""
        lines = self.content.split("\n") if self.content else []

        for i, line in enumerate(lines):
            color = "#a1a1aa" if self.side == "old" else "#e4e4e7"
            yield Static(f"{i + 1:4} │ {line}", classes="diff-line")


class SyncedDiffView(Horizontal):
    """Side-by-side diff with synchronized scrolling."""

    DEFAULT_CSS = """
    SyncedDiffView {
        width: 100%;
        height: 100%;
    }

    SyncedDiffView .diff-header {
        height: 2;
        background: #18181b;
        padding: 0 1;
    }

    SyncedDiffView .diff-header.old {
        color: #ef4444;
    }

    SyncedDiffView .diff-header.new {
        color: #22c55e;
    }
    """

    def __init__(
        self,
        old_content: str,
        new_content: str,
        file_path: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.old_content = old_content or ""
        self.new_content = new_content or ""
        self.file_path = file_path

    def compose(self):
        """Compose the split diff view."""
        with Vertical(classes="diff-column"):
            yield Static("--- Original", classes="diff-header old")
            yield DiffPane(
                self.old_content,
                side="old",
                on_scroll=self._sync_scroll,
                id="old-pane",
            )

        with Vertical(classes="diff-column"):
            yield Static("+++ Modified", classes="diff-header new")
            yield DiffPane(
                self.new_content,
                side="new",
                on_scroll=self._sync_scroll,
                id="new-pane",
            )

    def _sync_scroll(self, x: int, y: int) -> None:
        """Sync scroll position between panes."""
        # This would be called when one pane scrolls
        # to update the other pane's position
        pass


class UnifiedDiffView(ScrollableContainer):
    """Unified diff view showing changes inline."""

    DEFAULT_CSS = """
    UnifiedDiffView {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    UnifiedDiffView .diff-add {
        color: #22c55e;
        background: #052e16;
    }

    UnifiedDiffView .diff-del {
        color: #ef4444;
        background: #450a0a;
    }

    UnifiedDiffView .diff-context {
        color: #71717a;
    }

    UnifiedDiffView .diff-header {
        color: #3b82f6;
        text-style: bold;
    }
    """

    def __init__(
        self,
        old_content: str,
        new_content: str,
        file_path: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.old_content = old_content or ""
        self.new_content = new_content or ""
        self.file_path = file_path

    def compose(self):
        """Compose the unified diff view."""
        # Generate unified diff
        import difflib

        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{self.file_path}" if self.file_path else "a/file",
            tofile=f"b/{self.file_path}" if self.file_path else "b/file",
            lineterm="",
        )

        for line in diff:
            line = line.rstrip("\n")
            if line.startswith("+++") or line.startswith("---"):
                yield Static(line, classes="diff-header")
            elif line.startswith("@@"):
                yield Static(line, classes="diff-header")
            elif line.startswith("+"):
                yield Static(line, classes="diff-add")
            elif line.startswith("-"):
                yield Static(line, classes="diff-del")
            else:
                yield Static(line, classes="diff-context")


class EnhancedPermissionPreviewScreen(Container):
    """
    Enhanced permission preview with multi-file support.

    Features:
    - Multi-file navigator (left sidebar)
    - Diff view mode selector
    - Split or unified diff view
    - j/k navigation
    - Action buttons
    """

    BINDINGS = [
        Binding("y", "allow_once", "Allow", priority=True),
        Binding("n", "deny", "Deny", priority=True),
        Binding("a", "allow_always", "Always Allow", priority=True),
        Binding("j", "next_request", "Next", priority=True),
        Binding("k", "prev_request", "Previous", priority=True),
        Binding("v", "toggle_diff_mode", "Toggle View", priority=True),
        Binding("?", "show_help", "Help", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    DEFAULT_CSS = """
    EnhancedPermissionPreviewScreen {
        width: 100%;
        height: 100%;
        background: #0f0f0f;
    }

    #preview-header {
        height: 3;
        background: #18181b;
        padding: 0 1;
    }

    #preview-title {
        color: #f59e0b;
        text-style: bold;
    }

    #preview-body {
        height: 1fr;
    }

    #diff-container {
        width: 1fr;
    }

    #diff-toolbar {
        height: 3;
        background: #18181b;
        padding: 0 1;
    }

    #preview-footer {
        height: 4;
        background: #18181b;
        padding: 1;
    }

    #action-buttons {
        align: center middle;
    }

    .action-btn {
        margin: 0 1;
        min-width: 14;
    }

    .allow-btn {
        background: #22c55e;
    }

    .deny-btn {
        background: #ef4444;
    }

    .always-btn {
        background: #3b82f6;
    }

    #key-hints {
        color: #52525b;
        text-align: center;
    }
    """

    diff_mode: reactive[DiffViewMode] = reactive(DiffViewMode.UNIFIED)
    current_index: reactive[int] = reactive(0)

    def __init__(
        self,
        requests: List[PermissionContext],
        on_decision: Callable[[str, str], None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.requests = requests
        self._on_decision = on_decision

    def compose(self):
        """Compose the enhanced preview screen."""
        from textual.widgets import Button

        # Header
        with Horizontal(id="preview-header"):
            yield Static(
                f" Permission Requests ({len(self.requests)} pending)",
                id="preview-title",
            )

        # Body
        with Horizontal(id="preview-body"):
            # Navigator
            yield PermissionNavigator(
                self.requests,
                on_select=self._on_navigator_select,
                id="navigator",
            )

            # Diff container
            with Vertical(id="diff-container"):
                # Toolbar
                with Horizontal(id="diff-toolbar"):
                    yield Static("View Mode:", classes="toolbar-label")
                    yield DiffModeSelector(id="diff-mode-selector")
                    yield Static(self._get_request_info(), id="request-info")

                # Diff view (will be updated based on mode)
                yield self._create_diff_view()

        # Footer with actions
        with Vertical(id="preview-footer"):
            with Horizontal(id="action-buttons"):
                yield Button("Allow [y]", id="btn-allow", classes="action-btn allow-btn")
                yield Button("Deny [n]", id="btn-deny", classes="action-btn deny-btn")
                yield Button("Always [a]", id="btn-always", classes="action-btn always-btn")

            yield Static(
                "[j/k] Navigate  [v] Toggle View  [y] Allow  [n] Deny  [a] Always  [Esc] Cancel",
                id="key-hints",
            )

    def _get_current_request(self) -> Optional[PermissionContext]:
        """Get the current request."""
        if 0 <= self.current_index < len(self.requests):
            return self.requests[self.current_index]
        return None

    def _get_request_info(self) -> str:
        """Get info string for current request."""
        req = self._get_current_request()
        if not req:
            return ""

        risk_style = RISK_STYLES.get(req.risk_level, RISK_STYLES["medium"])
        return f"{risk_style['icon']} {req.title}"

    def _create_diff_view(self):
        """Create the appropriate diff view based on mode."""
        req = self._get_current_request()
        if not req:
            return Static("No requests")

        old_content = req.original_content or ""
        new_content = req.new_content or ""
        file_path = req.file_path or ""

        if self.diff_mode == DiffViewMode.SPLIT:
            return SyncedDiffView(
                old_content,
                new_content,
                file_path,
                id="diff-view",
            )
        else:
            return UnifiedDiffView(
                old_content,
                new_content,
                file_path,
                id="diff-view",
            )

    def _on_navigator_select(self, index: int) -> None:
        """Handle navigator selection."""
        self.current_index = index
        self._refresh_diff_view()

    def _refresh_diff_view(self) -> None:
        """Refresh the diff view."""
        # Update request info
        info = self.query_one("#request-info", Static)
        info.update(self._get_request_info())

        # Replace diff view
        old_view = self.query_one("#diff-view")
        old_view.remove()

        container = self.query_one("#diff-container", Vertical)
        container.mount(self._create_diff_view())

    def watch_diff_mode(self, mode: DiffViewMode) -> None:
        """Handle diff mode change."""
        self._refresh_diff_view()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle diff mode selector change."""
        if event.select.id == "diff-mode-selector":
            self.diff_mode = DiffViewMode(event.value)

    def on_button_pressed(self, event) -> None:
        """Handle button presses."""
        from textual.widgets import Button

        if not isinstance(event.button, Button):
            return

        if event.button.id == "btn-allow":
            self.action_allow_once()
        elif event.button.id == "btn-deny":
            self.action_deny()
        elif event.button.id == "btn-always":
            self.action_allow_always()

    def action_allow_once(self) -> None:
        """Allow the current request once."""
        self._handle_decision("allow")

    def action_deny(self) -> None:
        """Deny the current request."""
        self._handle_decision("deny")

    def action_allow_always(self) -> None:
        """Always allow this type of request."""
        self._handle_decision("allow_always")

    def action_next_request(self) -> None:
        """Go to next request."""
        if self.current_index < len(self.requests) - 1:
            self.current_index += 1
            self._refresh_diff_view()
            # Update navigator selection
            nav = self.query_one("#navigator", PermissionNavigator)
            nav.highlighted = self.current_index

    def action_prev_request(self) -> None:
        """Go to previous request."""
        if self.current_index > 0:
            self.current_index -= 1
            self._refresh_diff_view()
            # Update navigator selection
            nav = self.query_one("#navigator", PermissionNavigator)
            nav.highlighted = self.current_index

    def action_toggle_diff_mode(self) -> None:
        """Toggle between unified and split view."""
        if self.diff_mode == DiffViewMode.UNIFIED:
            self.diff_mode = DiffViewMode.SPLIT
        else:
            self.diff_mode = DiffViewMode.UNIFIED

    def action_show_help(self) -> None:
        """Show help dialog."""
        # Could show a help modal here
        pass

    def action_cancel(self) -> None:
        """Cancel and close."""
        self.remove()

    def _handle_decision(self, action: str) -> None:
        """Handle a permission decision."""
        req = self._get_current_request()
        if not req:
            return

        self._on_decision(req.request_id, action)

        # Remove the request
        self.requests.pop(self.current_index)

        if not self.requests:
            self.remove()
            return

        # Adjust index
        if self.current_index >= len(self.requests):
            self.current_index = len(self.requests) - 1

        # Refresh navigator
        nav = self.query_one("#navigator", PermissionNavigator)
        nav.remove()

        body = self.query_one("#preview-body", Horizontal)
        body.mount(
            PermissionNavigator(
                self.requests,
                on_select=self._on_navigator_select,
                id="navigator",
            ),
            before=self.query_one("#diff-container"),
        )

        self._refresh_diff_view()

        # Update title
        title = self.query_one("#preview-title", Static)
        title.update(f" Permission Requests ({len(self.requests)} pending)")
