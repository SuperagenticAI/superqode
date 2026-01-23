"""
SuperQode History Manager - Command & Session History

Manages command history with:
- JSON-based persistent storage
- Async file operations
- Search and filtering
- Session tracking
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class HistoryEntry:
    """A single history entry."""

    input: str
    timestamp: float
    session_id: Optional[str] = None
    mode: Optional[str] = None
    agent: Optional[str] = None
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionInfo:
    """Information about a session."""

    session_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    mode: Optional[str] = None
    agent: Optional[str] = None
    command_count: int = 0


class HistoryManager:
    """Manages command history with persistence."""

    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = history_file or Path.home() / ".superqode" / "history.jsonl"
        self._entries: List[HistoryEntry] = []
        self._loaded = False
        self._current_session: Optional[str] = None
        self._position = 0  # For navigation

    async def load(self) -> bool:
        """Load history from file."""
        if self._loaded:
            return True

        def _read_history() -> List[HistoryEntry]:
            entries = []
            try:
                self.history_file.parent.mkdir(parents=True, exist_ok=True)
                self.history_file.touch(exist_ok=True)

                with self.history_file.open("r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                entries.append(HistoryEntry(**data))
                            except (json.JSONDecodeError, TypeError):
                                continue
            except Exception:
                pass
            return entries

        self._entries = await asyncio.to_thread(_read_history)
        self._loaded = True
        self._position = len(self._entries)
        return True

    async def append(
        self,
        input_text: str,
        mode: Optional[str] = None,
        agent: Optional[str] = None,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HistoryEntry:
        """Append a new entry to history."""
        if not input_text.strip():
            return None

        entry = HistoryEntry(
            input=input_text,
            timestamp=datetime.now().timestamp(),
            session_id=self._current_session,
            mode=mode,
            agent=agent,
            success=success,
            metadata=metadata or {},
        )

        self._entries.append(entry)
        self._position = len(self._entries)

        # Write to file
        def _write_entry():
            try:
                with self.history_file.open("a") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
            except Exception:
                pass

        await asyncio.to_thread(_write_entry)
        return entry

    def append_sync(
        self,
        input_text: str,
        mode: Optional[str] = None,
        agent: Optional[str] = None,
        success: bool = True,
    ) -> Optional[HistoryEntry]:
        """Synchronous version of append."""
        if not input_text.strip():
            return None

        entry = HistoryEntry(
            input=input_text,
            timestamp=datetime.now().timestamp(),
            session_id=self._current_session,
            mode=mode,
            agent=agent,
            success=success,
        )

        self._entries.append(entry)
        self._position = len(self._entries)

        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with self.history_file.open("a") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception:
            pass

        return entry

    def get_previous(self) -> Optional[str]:
        """Get previous history entry (for up arrow)."""
        if not self._entries or self._position <= 0:
            return None

        self._position -= 1
        return self._entries[self._position].input

    def get_next(self) -> Optional[str]:
        """Get next history entry (for down arrow)."""
        if self._position >= len(self._entries) - 1:
            self._position = len(self._entries)
            return ""

        self._position += 1
        return self._entries[self._position].input

    def reset_position(self) -> None:
        """Reset navigation position to end."""
        self._position = len(self._entries)

    def search(self, query: str, limit: int = 20) -> List[HistoryEntry]:
        """Search history entries."""
        query_lower = query.lower()
        results = []

        for entry in reversed(self._entries):
            if query_lower in entry.input.lower():
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def get_recent(self, count: int = 20) -> List[HistoryEntry]:
        """Get most recent entries."""
        return list(reversed(self._entries[-count:]))

    def get_by_mode(self, mode: str, limit: int = 20) -> List[HistoryEntry]:
        """Get entries for a specific mode."""
        results = []
        for entry in reversed(self._entries):
            if entry.mode == mode:
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def get_by_agent(self, agent: str, limit: int = 20) -> List[HistoryEntry]:
        """Get entries for a specific agent."""
        results = []
        for entry in reversed(self._entries):
            if entry.agent == agent:
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def clear(self) -> None:
        """Clear all history."""
        self._entries.clear()
        self._position = 0
        try:
            self.history_file.unlink(missing_ok=True)
        except Exception:
            pass

    def set_session(self, session_id: str) -> None:
        """Set the current session ID."""
        self._current_session = session_id

    @property
    def size(self) -> int:
        """Get the number of history entries."""
        return len(self._entries)

    @property
    def entries(self) -> List[HistoryEntry]:
        """Get all entries."""
        return self._entries.copy()


def render_history(
    entries: List[HistoryEntry], console, limit: int = 20, show_metadata: bool = False
) -> None:
    """Render history entries."""
    from rich.text import Text
    from rich.panel import Panel
    from rich.box import ROUNDED

    if not entries:
        console.print("  [dim]No history[/dim]")
        return

    header = Text()
    header.append(" 📜 ", style="bold")
    header.append("Command History", style="bold white")
    header.append(f" ({len(entries)} entries)", style="dim")

    console.print(Panel(header, border_style="#a855f7", box=ROUNDED, padding=(0, 1)))

    for i, entry in enumerate(entries[:limit]):
        line = Text()

        # Timestamp
        dt = datetime.fromtimestamp(entry.timestamp)
        time_str = dt.strftime("%H:%M:%S")
        line.append(f"  {time_str} ", style="dim")

        # Mode/Agent indicator
        if entry.agent:
            line.append(f"[{entry.agent}] ", style="bold cyan")
        elif entry.mode:
            line.append(f"[{entry.mode}] ", style="bold green")

        # Success indicator
        if not entry.success:
            line.append("✗ ", style="red")

        # Command
        cmd = entry.input[:60] + "..." if len(entry.input) > 60 else entry.input
        line.append(cmd, style="white")

        console.print(line)

    if len(entries) > limit:
        console.print(f"  [dim]... and {len(entries) - limit} more[/dim]")
