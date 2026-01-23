"""
SuperQode Approval System - Accept/Reject File Changes

A beautiful approval UI for coding agent file modifications.
Features gradient styling and keyboard shortcuts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Callable, Any
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.box import ROUNDED, HEAVY, DOUBLE


class ApprovalAction(Enum):
    """Possible approval actions."""

    PENDING = "pending"
    APPROVED = "approved"
    APPROVED_ALWAYS = "approved_always"
    REJECTED = "rejected"
    REJECTED_ALWAYS = "rejected_always"
    SKIPPED = "skipped"


@dataclass
class ApprovalRequest:
    """A request for user approval."""

    id: str
    title: str
    description: str
    file_path: Optional[str] = None
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    command: Optional[str] = None
    danger_level: int = 0  # 0=safe, 1=unknown, 2=dangerous, 3=destructive
    action: ApprovalAction = ApprovalAction.PENDING
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


# SuperQode approval colors
APPROVAL_COLORS = {
    "approve": "#22c55e",
    "approve_bg": "#22c55e20",
    "reject": "#ef4444",
    "reject_bg": "#ef444420",
    "pending": "#f59e0b",
    "pending_bg": "#f59e0b20",
    "header": "#a855f7",
    "border": "#2a2a2a",
    "muted": "#71717a",
}

# Icons for approval UI
APPROVAL_ICONS = {
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
    "file": "📄",
    "command": "💻",
    "warning": "⚠️",
    "danger": "🚨",
    "question": "❓",
    "approve": "👍",
    "reject": "👎",
    "skip": "⏭️",
    "view": "👁️",
    "diff": "📊",
}


class ApprovalManager:
    """Manages approval requests and user decisions."""

    def __init__(self, console: Console):
        self.console = console
        self.requests: List[ApprovalRequest] = []
        self.always_approve: set = set()  # Patterns to always approve
        self.always_reject: set = set()  # Patterns to always reject
        self.history: List[ApprovalRequest] = []

    def add_request(self, request: ApprovalRequest) -> None:
        """Add a new approval request."""
        # Check if auto-approve/reject applies
        if request.file_path:
            if any(p in request.file_path for p in self.always_approve):
                request.action = ApprovalAction.APPROVED_ALWAYS
                self.history.append(request)
                return
            if any(p in request.file_path for p in self.always_reject):
                request.action = ApprovalAction.REJECTED_ALWAYS
                self.history.append(request)
                return

        self.requests.append(request)

    def get_pending(self) -> List[ApprovalRequest]:
        """Get all pending requests."""
        return [r for r in self.requests if r.action == ApprovalAction.PENDING]

    def approve(self, request_id: str, always: bool = False) -> bool:
        """Approve a request."""
        for req in self.requests:
            if req.id == request_id:
                req.action = ApprovalAction.APPROVED_ALWAYS if always else ApprovalAction.APPROVED
                if always and req.file_path:
                    # Add pattern for future auto-approve
                    self.always_approve.add(req.file_path)
                self.history.append(req)
                self.requests.remove(req)
                return True
        return False

    def reject(self, request_id: str, always: bool = False) -> bool:
        """Reject a request."""
        for req in self.requests:
            if req.id == request_id:
                req.action = ApprovalAction.REJECTED_ALWAYS if always else ApprovalAction.REJECTED
                if always and req.file_path:
                    self.always_reject.add(req.file_path)
                self.history.append(req)
                self.requests.remove(req)
                return True
        return False

    def skip(self, request_id: str) -> bool:
        """Skip a request (defer decision)."""
        for req in self.requests:
            if req.id == request_id:
                req.action = ApprovalAction.SKIPPED
                return True
        return False

    def approve_all(self) -> int:
        """Approve all pending requests."""
        count = 0
        for req in list(self.requests):
            if req.action == ApprovalAction.PENDING:
                req.action = ApprovalAction.APPROVED
                self.history.append(req)
                self.requests.remove(req)
                count += 1
        return count

    def reject_all(self) -> int:
        """Reject all pending requests."""
        count = 0
        for req in list(self.requests):
            if req.action == ApprovalAction.PENDING:
                req.action = ApprovalAction.REJECTED
                self.history.append(req)
                self.requests.remove(req)
                count += 1
        return count


def render_approval_request(
    request: ApprovalRequest, console: Console, show_diff: bool = False
) -> None:
    """Render a single approval request."""
    # Header with gradient effect
    header = Text()

    # Icon based on type
    if request.command:
        icon = APPROVAL_ICONS["command"]
        type_label = "Command"
    else:
        icon = APPROVAL_ICONS["file"]
        type_label = "File Change"

    # Danger indicator
    danger_icons = ["", "", APPROVAL_ICONS["warning"], APPROVAL_ICONS["danger"]]
    danger_icon = danger_icons[min(request.danger_level, 3)]

    header.append(f" {icon} ", style="bold")
    header.append(type_label, style="bold white")
    if danger_icon:
        header.append(f" {danger_icon}", style="")

    # Status badge
    status_colors = {
        ApprovalAction.PENDING: ("⏳ Pending", APPROVAL_COLORS["pending"]),
        ApprovalAction.APPROVED: ("✅ Approved", APPROVAL_COLORS["approve"]),
        ApprovalAction.REJECTED: ("❌ Rejected", APPROVAL_COLORS["reject"]),
    }
    status_text, status_color = status_colors.get(
        request.action, ("❓ Unknown", APPROVAL_COLORS["muted"])
    )
    header.append("  ", style="")
    header.append(f"[{status_text}]", style=f"bold {status_color}")

    # Build content
    content = Text()
    content.append(f"\n{request.title}\n", style="bold white")

    if request.description:
        content.append(f"{request.description}\n", style=APPROVAL_COLORS["muted"])

    if request.file_path:
        content.append(f"\n📁 ", style="")
        content.append(request.file_path, style="bold cyan")
        content.append("\n", style="")

    if request.command:
        content.append(f"\n💻 ", style="")
        content.append(request.command, style="bold yellow")
        content.append("\n", style="")

    # Action hints
    content.append("\n", style="")
    content.append("  [A]", style=f"bold {APPROVAL_COLORS['approve']}")
    content.append(" Approve  ", style=APPROVAL_COLORS["approve"])
    content.append("[Shift+A]", style=f"bold {APPROVAL_COLORS['approve']}")
    content.append(" Always  ", style="dim")
    content.append("[R]", style=f"bold {APPROVAL_COLORS['reject']}")
    content.append(" Reject  ", style=APPROVAL_COLORS["reject"])
    content.append("[Shift+R]", style=f"bold {APPROVAL_COLORS['reject']}")
    content.append(" Never  ", style="dim")
    content.append("[V]", style="bold cyan")
    content.append(" View Diff", style="cyan")

    # Determine border color based on danger level
    border_colors = ["#22c55e", "#f59e0b", "#f97316", "#ef4444"]
    border_color = border_colors[min(request.danger_level, 3)]

    console.print(
        Panel(
            content,
            title=header,
            title_align="left",
            border_style=border_color,
            box=ROUNDED,
            padding=(1, 2),
        )
    )


def render_approval_list(requests: List[ApprovalRequest], console: Console) -> None:
    """Render a list of approval requests."""
    if not requests:
        console.print("  [dim]No pending approvals[/dim]")
        return

    # Summary header
    pending = sum(1 for r in requests if r.action == ApprovalAction.PENDING)

    header = Text()
    header.append(f" {APPROVAL_ICONS['pending']} ", style="bold")
    header.append(f"{pending} Pending Approval(s)", style="bold white")

    console.print(
        Panel(header, border_style=APPROVAL_COLORS["header"], box=ROUNDED, padding=(0, 1))
    )
    console.print()

    # Render each request
    for i, request in enumerate(requests):
        if request.action == ApprovalAction.PENDING:
            console.print(f"  [dim]#{i + 1}[/dim]")
            render_approval_request(request, console)
            console.print()


def render_approval_summary(manager: ApprovalManager, console: Console) -> None:
    """Render a summary of approval history."""
    if not manager.history:
        console.print("  [dim]No approval history[/dim]")
        return

    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=ROUNDED,
        border_style=APPROVAL_COLORS["border"],
    )

    table.add_column("Status", width=10)
    table.add_column("Type", width=8)
    table.add_column("Target", style="cyan")
    table.add_column("Time", style="dim", width=10)

    for req in manager.history[-10:]:  # Last 10
        # Status
        if req.action in (ApprovalAction.APPROVED, ApprovalAction.APPROVED_ALWAYS):
            status = f"[green]✅ Yes[/green]"
        else:
            status = f"[red]❌ No[/red]"

        # Type
        req_type = "Cmd" if req.command else "File"

        # Target
        target = req.command[:30] if req.command else (req.file_path or "Unknown")
        if len(target) > 30:
            target = target[:27] + "..."

        # Time
        time_str = req.timestamp.strftime("%H:%M:%S")

        table.add_row(status, req_type, target, time_str)

    console.print(table)
