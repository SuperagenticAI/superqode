"""
MCP Auth Storage - Secure Storage for OAuth Credentials.

Provides secure storage for MCP server authentication credentials
including OAuth tokens and API keys.

Security Features:
- File permissions set to 0o600 (owner read/write only)
- Credentials bound to server URL
- Token expiry tracking
- Automatic cleanup of expired tokens
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .oauth import OAuthTokens

logger = logging.getLogger(__name__)


@dataclass
class ServerCredentials:
    """Credentials for an MCP server."""

    server_url: str
    server_url_hash: str  # Hash for filename safety
    oauth_tokens: Optional[OAuthTokens] = None
    api_key: Optional[str] = None
    bearer_token: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        result: Dict[str, Any] = {
            "server_url": self.server_url,
            "server_url_hash": self.server_url_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if self.oauth_tokens:
            result["oauth_tokens"] = self.oauth_tokens.to_dict()

        if self.api_key:
            result["api_key"] = self.api_key

        if self.bearer_token:
            result["bearer_token"] = self.bearer_token

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerCredentials":
        """Create from dictionary."""
        oauth_tokens = None
        if "oauth_tokens" in data:
            oauth_tokens = OAuthTokens.from_dict(data["oauth_tokens"])

        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])

        updated_at = None
        if data.get("updated_at"):
            updated_at = datetime.fromisoformat(data["updated_at"])

        return cls(
            server_url=data["server_url"],
            server_url_hash=data["server_url_hash"],
            oauth_tokens=oauth_tokens,
            api_key=data.get("api_key"),
            bearer_token=data.get("bearer_token"),
            created_at=created_at,
            updated_at=updated_at,
        )


class MCPAuthStorage:
    """
    Secure storage for MCP OAuth credentials.

    Stores credentials in ~/.superqode/mcp-auth/ with one file per server.
    Files are created with restricted permissions (0o600).

    Usage:
        storage = MCPAuthStorage()

        # Save tokens
        storage.save_tokens(server_url, tokens)

        # Load tokens
        tokens = storage.load_tokens(server_url)

        # Clear tokens
        storage.clear_tokens(server_url)
    """

    DEFAULT_DIR = Path.home() / ".superqode" / "mcp-auth"

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or self.DEFAULT_DIR
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Ensure storage directory exists with proper permissions."""
        if not self.storage_dir.exists():
            self.storage_dir.mkdir(parents=True, mode=0o700)
        else:
            # Ensure permissions are correct
            current_mode = self.storage_dir.stat().st_mode & 0o777
            if current_mode != 0o700:
                self.storage_dir.chmod(0o700)

    def _url_hash(self, url: str) -> str:
        """Generate a safe hash from a URL for use as filename."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _get_credentials_path(self, server_url: str) -> Path:
        """Get the path to the credentials file for a server."""
        url_hash = self._url_hash(server_url)
        return self.storage_dir / f"{url_hash}.json"

    def save_tokens(
        self,
        server_url: str,
        tokens: OAuthTokens,
    ) -> None:
        """
        Save OAuth tokens for a server.

        Args:
            server_url: The MCP server URL
            tokens: OAuth tokens to save
        """
        creds_path = self._get_credentials_path(server_url)

        # Load existing credentials or create new
        try:
            credentials = self._load_credentials(server_url)
            if credentials:
                credentials.oauth_tokens = tokens
                credentials.updated_at = datetime.now()
            else:
                credentials = ServerCredentials(
                    server_url=server_url,
                    server_url_hash=self._url_hash(server_url),
                    oauth_tokens=tokens,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
        except Exception:
            credentials = ServerCredentials(
                server_url=server_url,
                server_url_hash=self._url_hash(server_url),
                oauth_tokens=tokens,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        # Write to file with secure permissions
        self._save_credentials(credentials)
        logger.debug(f"Saved OAuth tokens for {server_url}")

    def load_tokens(self, server_url: str) -> Optional[OAuthTokens]:
        """
        Load OAuth tokens for a server.

        Args:
            server_url: The MCP server URL

        Returns:
            OAuthTokens if found and valid, None otherwise
        """
        credentials = self._load_credentials(server_url)
        if credentials and credentials.oauth_tokens:
            return credentials.oauth_tokens
        return None

    def clear_tokens(self, server_url: str) -> None:
        """
        Clear OAuth tokens for a server.

        Args:
            server_url: The MCP server URL
        """
        creds_path = self._get_credentials_path(server_url)

        if creds_path.exists():
            # Load credentials to check if we should keep other data
            credentials = self._load_credentials(server_url)
            if credentials:
                credentials.oauth_tokens = None
                credentials.updated_at = datetime.now()

                # If no other credentials, delete the file
                if not credentials.api_key and not credentials.bearer_token:
                    creds_path.unlink()
                    logger.debug(f"Deleted credentials file for {server_url}")
                else:
                    self._save_credentials(credentials)
                    logger.debug(f"Cleared OAuth tokens for {server_url}")

    def save_api_key(self, server_url: str, api_key: str) -> None:
        """
        Save an API key for a server.

        Args:
            server_url: The MCP server URL
            api_key: The API key to save
        """
        credentials = self._load_credentials(server_url)
        if credentials:
            credentials.api_key = api_key
            credentials.updated_at = datetime.now()
        else:
            credentials = ServerCredentials(
                server_url=server_url,
                server_url_hash=self._url_hash(server_url),
                api_key=api_key,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        self._save_credentials(credentials)
        logger.debug(f"Saved API key for {server_url}")

    def load_api_key(self, server_url: str) -> Optional[str]:
        """Load an API key for a server."""
        credentials = self._load_credentials(server_url)
        if credentials:
            return credentials.api_key
        return None

    def save_bearer_token(self, server_url: str, token: str) -> None:
        """
        Save a bearer token for a server.

        Args:
            server_url: The MCP server URL
            token: The bearer token to save
        """
        credentials = self._load_credentials(server_url)
        if credentials:
            credentials.bearer_token = token
            credentials.updated_at = datetime.now()
        else:
            credentials = ServerCredentials(
                server_url=server_url,
                server_url_hash=self._url_hash(server_url),
                bearer_token=token,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        self._save_credentials(credentials)
        logger.debug(f"Saved bearer token for {server_url}")

    def load_bearer_token(self, server_url: str) -> Optional[str]:
        """Load a bearer token for a server."""
        credentials = self._load_credentials(server_url)
        if credentials:
            return credentials.bearer_token
        return None

    def get_credentials(self, server_url: str) -> Optional[ServerCredentials]:
        """Get all credentials for a server."""
        return self._load_credentials(server_url)

    def list_servers(self) -> list[str]:
        """List all servers with stored credentials."""
        servers = []
        for creds_file in self.storage_dir.glob("*.json"):
            try:
                with open(creds_file, "r") as f:
                    data = json.load(f)
                    if "server_url" in data:
                        servers.append(data["server_url"])
            except Exception:
                pass
        return servers

    def clear_all(self) -> None:
        """Clear all stored credentials."""
        for creds_file in self.storage_dir.glob("*.json"):
            try:
                creds_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete {creds_file}: {e}")
        logger.info("Cleared all MCP credentials")

    def cleanup_expired(self) -> int:
        """
        Clean up expired OAuth tokens.

        Returns the number of expired tokens removed.
        """
        count = 0
        for server_url in self.list_servers():
            credentials = self._load_credentials(server_url)
            if credentials and credentials.oauth_tokens:
                tokens = credentials.oauth_tokens
                if tokens.is_expired() and not tokens.refresh_token:
                    # Token is expired and can't be refreshed
                    self.clear_tokens(server_url)
                    count += 1
                    logger.debug(f"Cleaned up expired token for {server_url}")
        return count

    def _load_credentials(self, server_url: str) -> Optional[ServerCredentials]:
        """Load credentials from file."""
        creds_path = self._get_credentials_path(server_url)

        if not creds_path.exists():
            return None

        try:
            with open(creds_path, "r") as f:
                data = json.load(f)

            # Verify URL matches (security check)
            if data.get("server_url") != server_url:
                logger.warning(f"URL mismatch in credentials file: {creds_path}")
                return None

            return ServerCredentials.from_dict(data)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Invalid credentials file {creds_path}: {e}")
            return None

    def _save_credentials(self, credentials: ServerCredentials) -> None:
        """Save credentials to file with secure permissions."""
        creds_path = self._get_credentials_path(credentials.server_url)

        # Write to temp file first
        temp_path = creds_path.with_suffix(".tmp")

        try:
            # Create file with restricted permissions
            fd = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(credentials.to_dict(), f, indent=2)

            # Atomic rename
            temp_path.rename(creds_path)

        except Exception as e:
            # Clean up temp file if exists
            if temp_path.exists():
                temp_path.unlink()
            raise e


# Global storage instance
_global_storage: Optional[MCPAuthStorage] = None


def get_auth_storage() -> MCPAuthStorage:
    """Get the global auth storage instance."""
    global _global_storage

    if _global_storage is None:
        _global_storage = MCPAuthStorage()

    return _global_storage
