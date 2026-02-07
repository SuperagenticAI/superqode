"""Tests for local auth storage."""

import json
import tempfile
from pathlib import Path

import pytest

from superqode.auth import (
    LocalAuthStorage,
    ApiAuth,
    OAuthAuth,
    WellKnownAuth,
    parse_auth_info,
)


@pytest.fixture
def temp_auth_file():
    """Create a temporary auth file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "auth.json"
        yield filepath


class TestLocalAuthStorage:
    """Tests for LocalAuthStorage."""

    def test_empty_storage(self, temp_auth_file):
        """Empty storage returns empty dict."""
        storage = LocalAuthStorage(temp_auth_file)
        assert storage.all() == {}
        assert storage.get("anthropic") is None

    def test_set_and_get_api_auth(self, temp_auth_file):
        """Can set and retrieve API auth."""
        storage = LocalAuthStorage(temp_auth_file)
        auth = ApiAuth(key="sk-test-key-123")

        storage.set("anthropic", auth)

        result = storage.get("anthropic")
        assert result is not None
        assert isinstance(result, ApiAuth)
        assert result.key == "sk-test-key-123"

    def test_set_and_get_oauth_auth(self, temp_auth_file):
        """Can set and retrieve OAuth auth."""
        storage = LocalAuthStorage(temp_auth_file)
        auth = OAuthAuth(
            refresh="refresh-token",
            access="access-token",
            expires=1234567890,
            account_id="acc-123",
        )

        storage.set("openai", auth)

        result = storage.get("openai")
        assert result is not None
        assert isinstance(result, OAuthAuth)
        assert result.refresh == "refresh-token"
        assert result.access == "access-token"
        assert result.expires == 1234567890

    def test_remove(self, temp_auth_file):
        """Can remove auth."""
        storage = LocalAuthStorage(temp_auth_file)
        storage.set("anthropic", ApiAuth(key="test"))

        assert storage.exists("anthropic")
        assert storage.remove("anthropic")
        assert not storage.exists("anthropic")
        assert not storage.remove("anthropic")  # Second remove returns False

    def test_all_returns_multiple(self, temp_auth_file):
        """all() returns all stored credentials."""
        storage = LocalAuthStorage(temp_auth_file)
        storage.set("anthropic", ApiAuth(key="key1"))
        storage.set("openai", ApiAuth(key="key2"))
        storage.set("google", OAuthAuth(refresh="r", access="a", expires=0))

        result = storage.all()
        assert len(result) == 3
        assert "anthropic" in result
        assert "openai" in result
        assert "google" in result

    def test_file_permissions(self, temp_auth_file):
        """File should have 0o600 permissions."""
        storage = LocalAuthStorage(temp_auth_file)
        storage.set("test", ApiAuth(key="secret"))

        # Check file permissions
        mode = temp_auth_file.stat().st_mode & 0o777
        assert mode == 0o600

    def test_clear(self, temp_auth_file):
        """clear() removes all credentials."""
        storage = LocalAuthStorage(temp_auth_file)
        storage.set("anthropic", ApiAuth(key="key1"))
        storage.set("openai", ApiAuth(key="key2"))

        storage.clear()
        assert storage.all() == {}


class TestAuthTypes:
    """Tests for auth type dataclasses."""

    def test_api_auth_to_dict(self):
        """ApiAuth serializes correctly."""
        auth = ApiAuth(key="secret-key")
        d = auth.to_dict()
        assert d == {"type": "api", "key": "secret-key"}

    def test_oauth_auth_to_dict(self):
        """OAuthAuth serializes correctly."""
        auth = OAuthAuth(
            refresh="r-token",
            access="a-token",
            expires=123,
            account_id="acc",
            enterprise_url="https://example.com",
        )
        d = auth.to_dict()
        assert d["type"] == "oauth"
        assert d["refresh"] == "r-token"
        assert d["account_id"] == "acc"
        assert d["enterprise_url"] == "https://example.com"

    def test_wellknown_auth_to_dict(self):
        """WellKnownAuth serializes correctly."""
        auth = WellKnownAuth(key="k", token="t")
        d = auth.to_dict()
        assert d == {"type": "wellknown", "key": "k", "token": "t"}

    def test_oauth_is_expired(self):
        """OAuthAuth.is_expired() works correctly."""
        # Expired
        expired = OAuthAuth(refresh="r", access="a", expires=1)
        assert expired.is_expired()

        # Not expired (far future)
        not_expired = OAuthAuth(refresh="r", access="a", expires=9999999999)
        assert not not_expired.is_expired()

        # Zero means no expiry
        no_expiry = OAuthAuth(refresh="r", access="a", expires=0)
        assert not no_expiry.is_expired()


class TestParseAuthInfo:
    """Tests for parse_auth_info function."""

    def test_parse_api(self):
        """Parses API auth correctly."""
        result = parse_auth_info({"type": "api", "key": "test"})
        assert isinstance(result, ApiAuth)
        assert result.key == "test"

    def test_parse_oauth(self):
        """Parses OAuth auth correctly."""
        result = parse_auth_info(
            {
                "type": "oauth",
                "refresh": "r",
                "access": "a",
                "expires": 123,
            }
        )
        assert isinstance(result, OAuthAuth)
        assert result.refresh == "r"

    def test_parse_wellknown(self):
        """Parses WellKnown auth correctly."""
        result = parse_auth_info({"type": "wellknown", "key": "k", "token": "t"})
        assert isinstance(result, WellKnownAuth)

    def test_parse_unknown_returns_none(self):
        """Unknown type returns None."""
        result = parse_auth_info({"type": "unknown"})
        assert result is None
