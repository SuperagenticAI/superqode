"""
JSONL Session Storage for Agent Conversations.

Stores conversation history in JSONL format for fast appends
and easy resumption of previous sessions.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class SessionMetadata:
    """Metadata for a session."""

    session_id: str
    created_at: str
    updated_at: str
    provider: str = ""
    model: str = ""
    message_count: int = 0
    total_tokens: int = 0
    parent_session_id: Optional[str] = None
    title: str = ""


@dataclass
class SessionMessage:
    """A single message in a session."""

    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    tool_calls: Optional[List[Dict]] = None
    tool_name: Optional[str] = None
    tool_result: Optional[str] = None


class SessionStore:
    """JSONL-based session storage."""

    def __init__(self, base_dir: str = ".superqode/sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get path for session file."""
        return self.base_dir / f"{session_id}.jsonl"

    def create_session(
        self,
        session_id: str,
        provider: str = "",
        model: str = "",
        parent_session_id: Optional[str] = None,
        title: str = "",
    ) -> SessionMetadata:
        """Create a new session."""
        now = datetime.now().isoformat()
        metadata = SessionMetadata(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            provider=provider,
            model=model,
            parent_session_id=parent_session_id,
            title=title,
        )
        self._save_metadata(metadata)
        return metadata

    def _save_metadata(self, metadata: SessionMetadata):
        """Save session metadata."""
        meta_path = self.base_dir / f"{metadata.session_id}.meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "session_id": metadata.session_id,
                    "created_at": metadata.created_at,
                    "updated_at": metadata.updated_at,
                    "provider": metadata.provider,
                    "model": metadata.model,
                    "message_count": metadata.message_count,
                    "total_tokens": metadata.total_tokens,
                    "parent_session_id": metadata.parent_session_id,
                    "title": metadata.title,
                },
                indent=2,
            )
        )

    def get_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        """Get session metadata."""
        meta_path = self.base_dir / f"{session_id}.meta.json"
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return SessionMetadata(**data)
        except (json.JSONDecodeError, KeyError):
            return None

    def append_message(self, session_id: str, message: SessionMessage):
        """Append a message to session."""
        path = self._session_path(session_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message.__dict__, ensure_ascii=False) + "\n")

        # Update metadata
        metadata = self.get_metadata(session_id)
        if metadata:
            metadata.updated_at = datetime.now().isoformat()
            metadata.message_count += 1
            self._save_metadata(metadata)

    def append_tool_result(
        self,
        session_id: str,
        tool_name: str,
        result: str,
    ):
        """Append a tool result message."""
        message = SessionMessage(
            role="tool",
            content=result,
            tool_name=tool_name,
        )
        self.append_message(session_id, message)

    def get_messages(self, session_id: str, limit: Optional[int] = None) -> List[SessionMessage]:
        """Get all messages from session."""
        path = self._session_path(session_id)
        if not path.exists():
            return []

        if limit is not None and limit <= 0:
            return []

        messages: list[SessionMessage] | deque[SessionMessage]
        messages = deque(maxlen=limit) if limit else []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(SessionMessage(**data))
                    except json.JSONDecodeError:
                        continue
        return list(messages)

    def list_sessions(self) -> List[SessionMetadata]:
        """List all sessions."""
        sessions = []
        for meta_file in self.base_dir.glob("*.meta.json"):
            try:
                data = json.loads(meta_file.read_text())
                sessions.append(SessionMetadata(**data))
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def delete_session(self, session_id: str):
        """Delete a session."""
        path = self._session_path(session_id)
        meta_path = self.base_dir / f"{session_id}.meta.json"

        if path.exists():
            path.unlink()
        if meta_path.exists():
            meta_path.unlink()

    def get_session_size(self, session_id: str) -> int:
        """Get session file size in bytes."""
        path = self._session_path(session_id)
        if path.exists():
            return path.stat().st_size
        return 0

    def fork_session(self, session_id: str, new_session_id: str) -> SessionMetadata:
        """Fork an existing session into a new one.

        Args:
            session_id: The ID of the session to fork from
            new_session_id: The ID for the new session

        Returns:
            The new session metadata
        """
        old_path = self._session_path(session_id)
        old_meta_path = self.base_dir / f"{session_id}.meta.json"

        new_path = self._session_path(new_session_id)
        new_meta_path = self.base_dir / f"{new_session_id}.meta.json"

        if not old_path.exists():
            raise FileNotFoundError(f"Session {session_id} not found")

        import shutil

        shutil.copy2(old_path, new_path)

        # Load and update metadata
        metadata = self.get_metadata(session_id)
        if metadata:
            parent_session_id = metadata.session_id
            metadata.session_id = new_session_id
            metadata.created_at = datetime.now().isoformat()
            metadata.updated_at = metadata.created_at
            metadata.parent_session_id = parent_session_id
            metadata.title = metadata.title or f"Fork of {parent_session_id}"
            self._save_metadata(metadata)
            return metadata
        else:
            # Create minimal metadata if missing
            return self.create_session(new_session_id, parent_session_id=session_id)


class SessionManager:
    """Manages agent sessions with JSONL storage."""

    def __init__(
        self,
        storage_dir: str = ".superqode/sessions",
        max_sessions: int = 100,
    ):
        self.store = SessionStore(storage_dir)
        self.max_sessions = max_sessions
        self._current_session_id: Optional[str] = None

    @property
    def current_session_id(self) -> Optional[str]:
        return self._current_session_id

    def start_session(
        self,
        session_id: Optional[str] = None,
        provider: str = "",
        model: str = "",
    ) -> str:
        """Start a new session or resume existing."""
        if session_id and self.store.get_metadata(session_id):
            self._current_session_id = session_id
            return session_id

        # Create new session
        import uuid

        new_id = session_id or str(uuid.uuid4())[:8]
        self.store.create_session(new_id, provider, model)
        self._current_session_id = new_id
        return new_id

    def add_user_message(self, content: str):
        """Add user message to current session."""
        if not self._current_session_id:
            raise RuntimeError("No active session. Call start_session first.")
        self.store.append_message(
            self._current_session_id,
            SessionMessage(role="user", content=content),
        )

    def add_assistant_message(self, content: str, tool_calls: Optional[List[Dict]] = None):
        """Add assistant message to current session."""
        if not self._current_session_id:
            raise RuntimeError("No active session. Call start_session first.")
        self.store.append_message(
            self._current_session_id,
            SessionMessage(role="assistant", content=content, tool_calls=tool_calls),
        )

    def add_tool_result(self, tool_name: str, result: str):
        """Add tool result to current session."""
        if not self._current_session_id:
            raise RuntimeError("No active session. Call start_session first.")
        self.store.append_tool_result(self._current_session_id, tool_name, result)

    def get_messages(self, limit: Optional[int] = None) -> List[SessionMessage]:
        """Get messages from current session."""
        if not self._current_session_id:
            return []
        return self.store.get_messages(self._current_session_id, limit=limit)

    def list_all_sessions(self) -> List[SessionMetadata]:
        """List all sessions."""
        return self.store.list_sessions()

    def get_session_info(self, session_id: str) -> Optional[SessionMetadata]:
        """Get session info."""
        return self.store.get_metadata(session_id)

    def delete_session(self, session_id: str):
        """Delete a session."""
        self.store.delete_session(session_id)
        if self._current_session_id == session_id:
            self._current_session_id = None

    def fork_current_session(self, new_session_id: Optional[str] = None) -> str:
        """Fork the current session into a new one.

        Args:
            new_session_id: Optional ID for the new session

        Returns:
            The new session ID
        """
        if not self._current_session_id:
            raise RuntimeError("No active session to fork")

        import uuid

        fork_id = new_session_id or f"{self._current_session_id}-fork-{str(uuid.uuid4())[:4]}"
        self.store.fork_session(self._current_session_id, fork_id)
        self._current_session_id = fork_id
        return fork_id

    def cleanup_old_sessions(self) -> int:
        """Delete old sessions beyond max_sessions limit."""
        sessions = self.store.list_sessions()
        if len(sessions) <= self.max_sessions:
            return 0

        deleted = 0
        for session in sessions[self.max_sessions :]:
            self.store.delete_session(session.session_id)
            deleted += 1
        return deleted


def create_session_manager(
    storage_dir: str = ".superqode/sessions",
    max_sessions: int = 100,
) -> SessionManager:
    """Create a session manager."""
    return SessionManager(storage_dir=storage_dir, max_sessions=max_sessions)
