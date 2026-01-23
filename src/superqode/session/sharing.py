"""
Session Sharing - Collaborative Session Features.

Enables sharing and forking of sessions between users:
- Export sessions for sharing
- Import shared sessions
- Fork sessions to create branches
- Session links for collaboration
- Adapted for SuperQode's multi-agent QE workflow
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.parse

from .persistence import Session, SessionStore


class ShareVisibility(Enum):
    """Visibility of a shared session."""

    PRIVATE = "private"  # Only accessible with link
    UNLISTED = "unlisted"  # Not discoverable, but accessible
    PUBLIC = "public"  # Discoverable and accessible


@dataclass
class ShareConfig:
    """Configuration for session sharing."""

    visibility: ShareVisibility = ShareVisibility.PRIVATE
    expires_in: Optional[timedelta] = None
    allow_fork: bool = True
    allow_view_history: bool = True
    password: Optional[str] = None  # Optional password protection


@dataclass
class SharedSession:
    """A shared session with access controls."""

    id: str
    session_id: str
    share_token: str
    visibility: ShareVisibility
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    access_count: int = 0
    fork_count: int = 0
    allow_fork: bool = True
    allow_view_history: bool = True
    password_hash: Optional[str] = None
    created_by: str = ""

    @property
    def is_expired(self) -> bool:
        """Check if share has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def share_url(self) -> str:
        """Get the share URL."""
        return f"/share/{self.share_token}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "share_token": self.share_token,
            "visibility": self.visibility.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_count": self.access_count,
            "fork_count": self.fork_count,
            "allow_fork": self.allow_fork,
            "allow_view_history": self.allow_view_history,
            "password_hash": self.password_hash,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SharedSession":
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            share_token=data["share_token"],
            visibility=ShareVisibility(data["visibility"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            access_count=data.get("access_count", 0),
            fork_count=data.get("fork_count", 0),
            allow_fork=data.get("allow_fork", True),
            allow_view_history=data.get("allow_view_history", True),
            password_hash=data.get("password_hash"),
            created_by=data.get("created_by", ""),
        )


@dataclass
class ExportedSession:
    """A session exported for sharing."""

    session_data: dict
    export_format: str = "superqode-session-v1"
    exported_at: datetime = field(default_factory=datetime.now)
    checksum: str = ""

    def to_json(self) -> str:
        """Export to JSON string."""
        data = {
            "format": self.export_format,
            "exported_at": self.exported_at.isoformat(),
            "session": self.session_data,
            "checksum": self.checksum,
        }
        return json.dumps(data, indent=2)

    def to_compressed(self) -> bytes:
        """Export to compressed bytes."""
        json_data = self.to_json().encode("utf-8")
        return gzip.compress(json_data)

    def to_base64(self) -> str:
        """Export to base64 string for URLs."""
        compressed = self.to_compressed()
        return base64.urlsafe_b64encode(compressed).decode("ascii")

    @classmethod
    def from_json(cls, json_str: str) -> "ExportedSession":
        """Import from JSON string."""
        data = json.loads(json_str)

        if data.get("format") != "superqode-session-v1":
            raise ValueError(f"Unknown export format: {data.get('format')}")

        return cls(
            session_data=data["session"],
            export_format=data["format"],
            exported_at=datetime.fromisoformat(data["exported_at"]),
            checksum=data.get("checksum", ""),
        )

    @classmethod
    def from_compressed(cls, data: bytes) -> "ExportedSession":
        """Import from compressed bytes."""
        json_data = gzip.decompress(data).decode("utf-8")
        return cls.from_json(json_data)

    @classmethod
    def from_base64(cls, b64_str: str) -> "ExportedSession":
        """Import from base64 string."""
        compressed = base64.urlsafe_b64decode(b64_str)
        return cls.from_compressed(compressed)


class SessionSharingManager:
    """
    Manages session sharing and forking.

    Usage:
        store = SessionStore()
        sharing = SessionSharingManager(store)

        # Share a session
        share = sharing.create_share("session-123", ShareConfig())
        print(f"Share URL: {share.share_url}")

        # Fork a shared session
        forked = await sharing.fork_session(share.share_token, "My Fork")

        # Export for offline sharing
        exported = sharing.export_session("session-123")
        with open("session.json", "w") as f:
            f.write(exported.to_json())
    """

    def __init__(
        self,
        session_store: SessionStore,
        shares_dir: Optional[Path] = None,
    ):
        self.session_store = session_store
        self.shares_dir = shares_dir or (session_store.storage_dir / "shares")
        self.shares_dir.mkdir(parents=True, exist_ok=True)

        self._shares: Dict[str, SharedSession] = {}
        self._load_shares()

    def _load_shares(self) -> None:
        """Load shares from disk."""
        index_file = self.shares_dir / "index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text())
                for share_data in data.get("shares", []):
                    share = SharedSession.from_dict(share_data)
                    if not share.is_expired:
                        self._shares[share.share_token] = share
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_shares(self) -> None:
        """Save shares to disk."""
        index_file = self.shares_dir / "index.json"

        # Remove expired shares
        self._shares = {k: v for k, v in self._shares.items() if not v.is_expired}

        data = {
            "shares": [s.to_dict() for s in self._shares.values()],
        }
        index_file.write_text(json.dumps(data, indent=2))

    def _generate_token(self) -> str:
        """Generate a unique share token."""
        return secrets.token_urlsafe(16)

    def _hash_password(self, password: str) -> str:
        """Hash a password for storage."""
        return hashlib.sha256(password.encode()).hexdigest()

    def _verify_password(self, password: str, hash_value: str) -> bool:
        """Verify a password against its hash."""
        return self._hash_password(password) == hash_value

    def create_share(
        self,
        session_id: str,
        config: ShareConfig,
        created_by: str = "",
    ) -> Optional[SharedSession]:
        """Create a share for a session."""
        # Verify session exists
        session = self.session_store.load(session_id)
        if not session:
            return None

        share_token = self._generate_token()
        share_id = f"share-{int(datetime.now().timestamp())}"

        expires_at = None
        if config.expires_in:
            expires_at = datetime.now() + config.expires_in

        password_hash = None
        if config.password:
            password_hash = self._hash_password(config.password)

        share = SharedSession(
            id=share_id,
            session_id=session_id,
            share_token=share_token,
            visibility=config.visibility,
            expires_at=expires_at,
            allow_fork=config.allow_fork,
            allow_view_history=config.allow_view_history,
            password_hash=password_hash,
            created_by=created_by,
        )

        self._shares[share_token] = share
        self._save_shares()

        return share

    def get_share(
        self,
        share_token: str,
        password: Optional[str] = None,
    ) -> Optional[SharedSession]:
        """Get a share by token."""
        share = self._shares.get(share_token)

        if not share:
            return None

        if share.is_expired:
            del self._shares[share_token]
            self._save_shares()
            return None

        # Check password if required
        if share.password_hash:
            if not password or not self._verify_password(password, share.password_hash):
                return None

        # Increment access count
        share.access_count += 1
        self._save_shares()

        return share

    def get_session_for_share(
        self,
        share_token: str,
        password: Optional[str] = None,
    ) -> Optional[Session]:
        """Get the session for a share."""
        share = self.get_share(share_token, password)
        if not share:
            return None

        return self.session_store.load(share.session_id)

    def fork_session(
        self,
        share_token: str,
        new_title: str,
        password: Optional[str] = None,
    ) -> Optional[Session]:
        """Fork a shared session."""
        share = self.get_share(share_token, password)

        if not share or not share.allow_fork:
            return None

        session = self.session_store.load(share.session_id)
        if not session:
            return None

        # Create fork
        forked = session.fork(new_title)

        # Add fork metadata
        forked.metadata["forked_from"] = {
            "session_id": session.id,
            "share_token": share_token,
            "forked_at": datetime.now().isoformat(),
        }

        # Save forked session
        self.session_store.save(forked)

        # Update fork count
        share.fork_count += 1
        self._save_shares()

        return forked

    def revoke_share(self, share_token: str) -> bool:
        """Revoke a share."""
        if share_token in self._shares:
            del self._shares[share_token]
            self._save_shares()
            return True
        return False

    def list_shares(self, session_id: Optional[str] = None) -> List[SharedSession]:
        """List all shares, optionally filtered by session."""
        shares = list(self._shares.values())

        if session_id:
            shares = [s for s in shares if s.session_id == session_id]

        return sorted(shares, key=lambda s: s.created_at, reverse=True)

    def export_session(
        self,
        session_id: str,
        include_history: bool = True,
    ) -> Optional[ExportedSession]:
        """Export a session for sharing."""
        session = self.session_store.load(session_id)
        if not session:
            return None

        session_data = session.to_dict()

        # Optionally strip history
        if not include_history:
            session_data["messages"] = []
            session_data["tool_executions"] = []

        # Calculate checksum
        json_str = json.dumps(session_data, sort_keys=True)
        checksum = hashlib.sha256(json_str.encode()).hexdigest()[:16]

        return ExportedSession(
            session_data=session_data,
            checksum=checksum,
        )

    def import_session(
        self,
        exported: ExportedSession,
        new_title: Optional[str] = None,
    ) -> Session:
        """Import an exported session."""
        # Verify checksum if present
        if exported.checksum:
            json_str = json.dumps(exported.session_data, sort_keys=True)
            expected = hashlib.sha256(json_str.encode()).hexdigest()[:16]
            if expected != exported.checksum:
                raise ValueError("Session data checksum mismatch")

        # Create session from data
        session = Session.from_dict(exported.session_data)

        # Generate new ID for imported session
        session.id = f"session-{int(datetime.now().timestamp())}-import"

        if new_title:
            session.title = new_title

        # Add import metadata
        session.metadata["imported"] = {
            "imported_at": datetime.now().isoformat(),
            "original_id": exported.session_data.get("id"),
            "export_format": exported.export_format,
        }

        # Save session
        self.session_store.save(session)

        return session

    def generate_share_link(
        self,
        share_token: str,
        base_url: str = "https://superqode.dev",
    ) -> str:
        """Generate a shareable link."""
        return f"{base_url}/share/{share_token}"

    def generate_export_link(
        self,
        session_id: str,
        base_url: str = "https://superqode.dev",
    ) -> Optional[str]:
        """Generate a self-contained export link."""
        exported = self.export_session(session_id, include_history=False)
        if not exported:
            return None

        encoded = exported.to_base64()

        # URL encode the data
        params = urllib.parse.urlencode({"data": encoded})
        return f"{base_url}/import?{params}"


def create_quick_share(
    session_id: str,
    store: SessionStore,
    expires_hours: int = 24,
) -> Optional[str]:
    """Quick function to create a share link.

    Returns the share URL or None if session not found.
    """
    manager = SessionSharingManager(store)

    config = ShareConfig(
        visibility=ShareVisibility.PRIVATE,
        expires_in=timedelta(hours=expires_hours),
        allow_fork=True,
    )

    share = manager.create_share(session_id, config)
    if share:
        return manager.generate_share_link(share.share_token)

    return None
