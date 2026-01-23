"""
Session Persistence - Save and Restore Conversations.

Provides comprehensive session persistence including:
- Conversation history (messages, tool calls)
- Session state (files, tasks, quality issues)
- Session forking and sharing
- Export to various formats
- Tailored for SuperQode's multi-agent QE workflow
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import time


class MessageRole(Enum):
    """Role of message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class Message:
    """A single message in the conversation."""

    id: str
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    agent_name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "agent_name": self.agent_name,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            id=data["id"],
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            agent_name=data.get("agent_name"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ToolExecution:
    """Record of a tool execution."""

    id: str
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: int = 0
    agent_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "agent_name": self.agent_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolExecution":
        return cls(
            id=data["id"],
            tool_name=data["tool_name"],
            arguments=data["arguments"],
            result=data["result"],
            success=data["success"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            duration_ms=data.get("duration_ms", 0),
            agent_name=data.get("agent_name"),
        )


@dataclass
class SessionSnapshot:
    """Snapshot of session state at a point in time."""

    id: str
    name: str
    message_count: int
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""


@dataclass
class Session:
    """A complete conversation session."""

    id: str
    title: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    project_path: str = ""

    # Conversation
    messages: List[Message] = field(default_factory=list)
    tool_executions: List[ToolExecution] = field(default_factory=list)

    # State
    files_modified: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)

    # Metadata
    agents_used: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    parent_session_id: Optional[str] = None  # For forked sessions

    # Snapshots for undo/redo
    snapshots: List[SessionSnapshot] = field(default_factory=list)

    # Additional data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(
        self,
        role: MessageRole,
        content: str,
        agent_name: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
    ) -> Message:
        """Add a message to the session."""
        msg_id = f"msg-{len(self.messages) + 1}-{int(time.time() * 1000) % 10000}"

        message = Message(
            id=msg_id,
            role=role,
            content=content,
            agent_name=agent_name,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )

        self.messages.append(message)
        self.updated_at = datetime.now()

        if agent_name and agent_name not in self.agents_used:
            self.agents_used.append(agent_name)

        return message

    def add_tool_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        success: bool,
        duration_ms: int = 0,
        agent_name: Optional[str] = None,
    ) -> ToolExecution:
        """Record a tool execution."""
        exec_id = f"tool-{len(self.tool_executions) + 1}-{int(time.time() * 1000) % 10000}"

        execution = ToolExecution(
            id=exec_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            success=success,
            duration_ms=duration_ms,
            agent_name=agent_name,
        )

        self.tool_executions.append(execution)
        self.updated_at = datetime.now()

        return execution

    def create_snapshot(self, name: str, description: str = "") -> SessionSnapshot:
        """Create a snapshot of current state."""
        snap_id = f"snap-{len(self.snapshots) + 1}-{int(time.time())}"

        snapshot = SessionSnapshot(
            id=snap_id,
            name=name,
            message_count=len(self.messages),
            description=description,
        )

        self.snapshots.append(snapshot)
        return snapshot

    def revert_to_snapshot(self, snapshot_id: str) -> bool:
        """Revert session to a snapshot."""
        for snapshot in self.snapshots:
            if snapshot.id == snapshot_id:
                # Truncate messages and tool executions
                self.messages = self.messages[: snapshot.message_count]

                # Find corresponding tool executions
                if self.messages:
                    last_msg_time = self.messages[-1].timestamp
                    self.tool_executions = [
                        t for t in self.tool_executions if t.timestamp <= last_msg_time
                    ]
                else:
                    self.tool_executions = []

                self.updated_at = datetime.now()
                return True

        return False

    def fork(self, new_title: str) -> "Session":
        """Create a forked copy of this session."""
        fork_id = f"session-{int(time.time())}-fork"

        forked = Session(
            id=fork_id,
            title=new_title,
            project_path=self.project_path,
            messages=list(self.messages),
            tool_executions=list(self.tool_executions),
            files_modified=list(self.files_modified),
            files_created=list(self.files_created),
            agents_used=list(self.agents_used),
            tags=list(self.tags),
            parent_session_id=self.id,
            metadata=dict(self.metadata),
        )

        return forked

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "project_path": self.project_path,
            "messages": [m.to_dict() for m in self.messages],
            "tool_executions": [t.to_dict() for t in self.tool_executions],
            "files_modified": self.files_modified,
            "files_created": self.files_created,
            "agents_used": self.agents_used,
            "tags": self.tags,
            "parent_session_id": self.parent_session_id,
            "snapshots": [
                {
                    "id": s.id,
                    "name": s.name,
                    "message_count": s.message_count,
                    "created_at": s.created_at.isoformat(),
                    "description": s.description,
                }
                for s in self.snapshots
            ],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        session = cls(
            id=data["id"],
            title=data["title"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            project_path=data.get("project_path", ""),
        )

        session.messages = [Message.from_dict(m) for m in data.get("messages", [])]
        session.tool_executions = [
            ToolExecution.from_dict(t) for t in data.get("tool_executions", [])
        ]
        session.files_modified = data.get("files_modified", [])
        session.files_created = data.get("files_created", [])
        session.agents_used = data.get("agents_used", [])
        session.tags = data.get("tags", [])
        session.parent_session_id = data.get("parent_session_id")
        session.metadata = data.get("metadata", {})

        for snap_data in data.get("snapshots", []):
            session.snapshots.append(
                SessionSnapshot(
                    id=snap_data["id"],
                    name=snap_data["name"],
                    message_count=snap_data["message_count"],
                    created_at=datetime.fromisoformat(snap_data["created_at"]),
                    description=snap_data.get("description", ""),
                )
            )

        return session


class SessionStore:
    """
    Persistent storage for sessions.

    Stores sessions as compressed JSON files with indexing for fast listing.

    Usage:
        store = SessionStore()

        # Create and save a session
        session = Session(id="session-1", title="Fix bug")
        session.add_message(MessageRole.USER, "Fix the null reference bug")
        store.save(session)

        # List sessions
        sessions = store.list_sessions()

        # Load a session
        session = store.load("session-1")

        # Resume last session
        session = store.load_latest()
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or (Path.home() / ".superqode" / "sessions")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._index_file = self.storage_dir / "index.json"
        self._index: Dict[str, dict] = {}

        self._load_index()

    def _load_index(self) -> None:
        """Load session index from file."""
        if self._index_file.exists():
            try:
                self._index = json.loads(self._index_file.read_text())
            except json.JSONDecodeError:
                self._index = {}

    def _save_index(self) -> None:
        """Save session index to file."""
        self._index_file.write_text(json.dumps(self._index, indent=2))

    def _session_path(self, session_id: str) -> Path:
        """Get path for a session file."""
        return self.storage_dir / f"{session_id}.json.gz"

    def save(self, session: Session, compress: bool = True) -> None:
        """Save a session to storage."""
        data = json.dumps(session.to_dict(), indent=2)

        file_path = self._session_path(session.id)

        if compress:
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write(data)
        else:
            file_path = file_path.with_suffix("")  # Remove .gz
            file_path.write_text(data)

        # Update index
        self._index[session.id] = {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "project_path": session.project_path,
            "message_count": len(session.messages),
            "agents_used": session.agents_used,
            "tags": session.tags,
        }
        self._save_index()

    def load(self, session_id: str) -> Optional[Session]:
        """Load a session from storage."""
        file_path = self._session_path(session_id)

        if not file_path.exists():
            # Try uncompressed
            file_path = file_path.with_suffix("")
            if not file_path.exists():
                return None

        try:
            if file_path.suffix == ".gz":
                with gzip.open(file_path, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(file_path.read_text())

            return Session.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return None

    def delete(self, session_id: str) -> bool:
        """Delete a session from storage."""
        file_path = self._session_path(session_id)

        if file_path.exists():
            file_path.unlink()
        elif file_path.with_suffix("").exists():
            file_path.with_suffix("").unlink()
        else:
            return False

        self._index.pop(session_id, None)
        self._save_index()
        return True

    def list_sessions(
        self,
        project_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[dict]:
        """List sessions with optional filtering."""
        sessions = list(self._index.values())

        # Filter by project
        if project_path:
            sessions = [s for s in sessions if s.get("project_path") == project_path]

        # Filter by tags
        if tags:
            sessions = [s for s in sessions if set(tags).issubset(set(s.get("tags", [])))]

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)

        return sessions[:limit]

    def load_latest(self, project_path: Optional[str] = None) -> Optional[Session]:
        """Load the most recently updated session."""
        sessions = self.list_sessions(project_path=project_path, limit=1)

        if sessions:
            return self.load(sessions[0]["id"])

        return None

    def search(self, query: str, limit: int = 20) -> List[dict]:
        """Search sessions by title or content."""
        query_lower = query.lower()
        results = []

        for session_id, info in self._index.items():
            # Search in title
            if query_lower in info.get("title", "").lower():
                results.append(info)
                continue

            # Search in tags
            if any(query_lower in tag.lower() for tag in info.get("tags", [])):
                results.append(info)

        # Sort by relevance (title matches first)
        results.sort(
            key=lambda s: (
                0 if query_lower in s.get("title", "").lower() else 1,
                s.get("updated_at", ""),
            ),
            reverse=True,
        )

        return results[:limit]

    def export_session(
        self,
        session_id: str,
        output_path: Path,
        format: str = "json",
    ) -> bool:
        """Export a session to a file.

        Formats: json, markdown, text
        """
        session = self.load(session_id)
        if not session:
            return False

        if format == "json":
            output_path.write_text(json.dumps(session.to_dict(), indent=2))

        elif format == "markdown":
            lines = [
                f"# {session.title}",
                "",
                f"**Created:** {session.created_at.strftime('%Y-%m-%d %H:%M')}",
                f"**Project:** {session.project_path}",
                "",
                "---",
                "",
            ]

            for msg in session.messages:
                role_emoji = {"user": "👤", "assistant": "🤖", "system": "⚙️", "tool": "🔧"}
                emoji = role_emoji.get(msg.role.value, "💬")

                lines.append(f"### {emoji} {msg.role.value.title()}")
                if msg.agent_name:
                    lines.append(f"*Agent: {msg.agent_name}*")
                lines.append("")
                lines.append(msg.content)
                lines.append("")

            output_path.write_text("\n".join(lines))

        elif format == "text":
            lines = [f"Session: {session.title}", "=" * 50, ""]

            for msg in session.messages:
                lines.append(f"[{msg.role.value.upper()}] {msg.timestamp.strftime('%H:%M:%S')}")
                lines.append(msg.content)
                lines.append("-" * 40)

            output_path.write_text("\n".join(lines))

        else:
            return False

        return True

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Delete sessions older than specified days."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0

        for session_id, info in list(self._index.items()):
            updated = datetime.fromisoformat(info.get("updated_at", ""))
            if updated < cutoff:
                if self.delete(session_id):
                    deleted += 1

        return deleted


def create_session(
    title: str = "",
    project_path: Optional[Path] = None,
) -> Session:
    """Create a new session."""
    session_id = f"session-{int(time.time())}"

    if not title:
        title = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    return Session(
        id=session_id,
        title=title,
        project_path=str(project_path) if project_path else "",
    )
