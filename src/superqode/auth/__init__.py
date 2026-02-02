"""
Local Auth Storage for SuperQode.

Simple, minimal local storage for API keys. Inspired by opencode's approach.

Security:
- File permissions set to 0o600 (owner read/write only)
- Stored in ~/.superqode/auth.json
- Never logs or exposes key values

This is OPTIONAL - SuperQode still supports BYOK (env vars) as primary.
Local storage is for users who prefer file-based key management.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


class AuthType(Enum):
    """Type of authentication credential."""

    API = "api"  # Simple API key
    OAUTH = "oauth"  # OAuth with refresh token
    WELLKNOWN = "wellknown"  # Well-known auth (key + token pair)


@dataclass
class ApiAuth:
    """Simple API key authentication."""

    type: str = "api"
    key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "key": self.key}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApiAuth":
        return cls(type=data.get("type", "api"), key=data.get("key", ""))


@dataclass
class OAuthAuth:
    """OAuth authentication with refresh token."""

    type: str = "oauth"
    refresh: str = ""
    access: str = ""
    expires: int = 0
    account_id: Optional[str] = None
    enterprise_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "type": self.type,
            "refresh": self.refresh,
            "access": self.access,
            "expires": self.expires,
        }
        if self.account_id:
            result["account_id"] = self.account_id
        if self.enterprise_url:
            result["enterprise_url"] = self.enterprise_url
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthAuth":
        return cls(
            type=data.get("type", "oauth"),
            refresh=data.get("refresh", ""),
            access=data.get("access", ""),
            expires=data.get("expires", 0),
            account_id=data.get("account_id"),
            enterprise_url=data.get("enterprise_url"),
        )

    def is_expired(self) -> bool:
        """Check if access token is expired."""
        return self.expires > 0 and self.expires < int(datetime.now().timestamp())


@dataclass
class WellKnownAuth:
    """Well-known authentication (key + token pair)."""

    type: str = "wellknown"
    key: str = ""
    token: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "key": self.key, "token": self.token}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WellKnownAuth":
        return cls(
            type=data.get("type", "wellknown"),
            key=data.get("key", ""),
            token=data.get("token", ""),
        )


AuthInfo = Union[ApiAuth, OAuthAuth, WellKnownAuth]


def parse_auth_info(data: Dict[str, Any]) -> Optional[AuthInfo]:
    """Parse auth info from dict based on type."""
    auth_type = data.get("type")
    if auth_type == "api":
        return ApiAuth.from_dict(data)
    if auth_type == "oauth":
        return OAuthAuth.from_dict(data)
    if auth_type == "wellknown":
        return WellKnownAuth.from_dict(data)
    return None


class LocalAuthStorage:
    """
    Local storage for API keys and OAuth tokens.

    Stores credentials in ~/.superqode/auth.json with restricted permissions.

    Usage:
        auth = LocalAuthStorage()

        # Set API key
        auth.set("anthropic", ApiAuth(key="sk-..."))

        # Get credentials
        creds = auth.get("anthropic")

        # Remove
        auth.remove("anthropic")

        # List all
        all_creds = auth.all()
    """

    DEFAULT_PATH = Path.home() / ".superqode" / "auth.json"

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or self.DEFAULT_PATH
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure parent directory exists with proper permissions."""
        parent = self.filepath.parent
        if not parent.exists():
            parent.mkdir(parents=True, mode=0o700)

    def _read_file(self) -> Dict[str, Any]:
        """Read auth file, return empty dict if not exists or invalid."""
        if not self.filepath.exists():
            return {}
        try:
            with open(self.filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _write_file(self, data: Dict[str, Any]) -> None:
        """Write auth file with secure permissions."""
        # Write to temp file first, then rename (atomic)
        temp_path = self.filepath.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)

        # Set permissions before moving
        os.chmod(temp_path, 0o600)

        # Atomic rename
        temp_path.rename(self.filepath)

    def get(self, provider_id: str) -> Optional[AuthInfo]:
        """Get credentials for a provider."""
        data = self._read_file()
        if provider_id not in data:
            return None
        return parse_auth_info(data[provider_id])

    def all(self) -> Dict[str, AuthInfo]:
        """Get all stored credentials."""
        data = self._read_file()
        result: Dict[str, AuthInfo] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                parsed = parse_auth_info(value)
                if parsed:
                    result[key] = parsed
        return result

    def set(self, provider_id: str, info: AuthInfo) -> None:
        """Set credentials for a provider."""
        data = self._read_file()
        data[provider_id] = info.to_dict()
        self._write_file(data)
        logger.debug(f"Saved auth for {provider_id}")

    def remove(self, provider_id: str) -> bool:
        """Remove credentials for a provider. Returns True if removed."""
        data = self._read_file()
        if provider_id not in data:
            return False
        del data[provider_id]
        self._write_file(data)
        logger.debug(f"Removed auth for {provider_id}")
        return True

    def exists(self, provider_id: str) -> bool:
        """Check if credentials exist for a provider."""
        return provider_id in self._read_file()

    def clear(self) -> None:
        """Clear all stored credentials."""
        self._write_file({})
        logger.debug("Cleared all auth")


# Singleton instance
_storage: Optional[LocalAuthStorage] = None


def get_storage() -> LocalAuthStorage:
    """Get the singleton auth storage instance."""
    global _storage
    if _storage is None:
        _storage = LocalAuthStorage()
    return _storage


# Convenience functions
def get(provider_id: str) -> Optional[AuthInfo]:
    """Get credentials for a provider."""
    return get_storage().get(provider_id)


def all() -> Dict[str, AuthInfo]:
    """Get all stored credentials."""
    return get_storage().all()


def set(provider_id: str, info: AuthInfo) -> None:
    """Set credentials for a provider."""
    get_storage().set(provider_id, info)


def remove(provider_id: str) -> bool:
    """Remove credentials for a provider."""
    return get_storage().remove(provider_id)


def exists(provider_id: str) -> bool:
    """Check if credentials exist for a provider."""
    return get_storage().exists(provider_id)
