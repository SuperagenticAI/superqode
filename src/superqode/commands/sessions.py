"""
Session Management Commands for the TUI.

Provides /sessions and /resume commands to list and resume
previous conversation sessions from JSONL storage.
"""

from __future__ import annotations

from typing import List, Optional

from ..agent.session_manager import SessionManager, SessionMetadata


class SessionCommands:
    """Handle session-related commands in TUI."""

    def __init__(self, storage_dir: str = ".superqode/sessions"):
        self.manager = SessionManager(storage_dir=storage_dir)

    def list_sessions(self, limit: int = 10) -> str:
        """List recent sessions."""
        sessions = self.manager.list_all_sessions()

        if not sessions:
            return "No sessions found. Start a new conversation to create one."

        lines = ["Recent Sessions:", "-" * 50]
        for i, s in enumerate(sessions[:limit]):
            from datetime import datetime

            date = datetime.fromisoformat(s.updated_at).strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"{i + 1}. {s.session_id[:8]} | {s.model or 'N/A'} | {date} | {s.message_count} msgs"
            )

        lines.append("-" * 50)
        lines.append("Use /resume <id> to continue a session")
        return "\n".join(lines)

    def resume_session(self, session_id: str) -> Optional[str]:
        """Resume a session and get its messages."""
        metadata = self.manager.get_session_info(session_id)
        if not metadata:
            return f"Session '{session_id}' not found."

        # Start session to load messages
        self.manager.start_session(session_id=session_id)
        messages = self.manager.get_messages()

        if not messages:
            return f"Session '{session_id[:8]}' is empty."

        # Format messages for display
        lines = [f"Resuming session: {session_id[:8]}", "=" * 50]
        for msg in messages:
            role = msg.role.upper()
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            lines.append(f"\n[{role}] {content}")

        return "\n".join(lines)

    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self.manager.current_session_id

    def start_new_session(self, provider: str = "", model: str = "") -> str:
        """Start a new session."""
        session_id = self.manager.start_session(provider=provider, model=model)
        return session_id

    def delete_session(self, session_id: str) -> str:
        """Delete a session."""
        self.manager.delete_session(session_id)
        return f"Session '{session_id}' deleted."


def create_session_commands(storage_dir: str = ".superqode/sessions") -> SessionCommands:
    """Create session commands handler."""
    return SessionCommands(storage_dir=storage_dir)