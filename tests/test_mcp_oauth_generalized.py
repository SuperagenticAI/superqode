"""Tests for generalized MCP OAuth.

Three areas:
1. HuggingFace token auto-injection (``mcp/hf_auth.py``).
2. RFC 9728 Protected Resource Metadata discovery in ``MCPOAuthProvider``.
3. Pluggable ``TokenStorage`` protocol + keyring backend round-trip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

from superqode.mcp.auth_storage import (
    KeyringTokenStorage,
    MCPAuthStorage,
    TokenStorage,
    _FileTokenStorageAdapter,
    _has_keyring,
    make_default_token_storage,
)
from superqode.mcp.hf_auth import (
    get_huggingface_token,
    is_huggingface_url,
    maybe_inject_hf_auth,
)
from superqode.mcp.oauth import (
    MCPOAuthProvider,
    OAuthCallbackTimeoutError,
    OAuthConfig,
    OAuthError,
    OAuthFlowCancelledError,
    OAuthMetadataError,
    OAuthTokens,
)


# ---------------------------------------------------------------------------
# HuggingFace URL matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://huggingface.co/mcp", True),
        ("https://hf.co/api", True),
        ("https://my-space.hf.space/x", True),
        ("https://sub.huggingface.co/foo", True),
        ("https://Sub.HF.CO/bar", True),  # case-insensitive
        # Spoofing attempts — must NOT match.
        ("https://evil.hf.space.com/x", False),
        ("https://huggingface.co.evil.com/x", False),
        ("https://hf.co.evil.example/x", False),
        # Non-HF.
        ("https://openai.com", False),
        ("https://localhost:8080", False),
        # Garbage.
        ("", False),
        ("not a url", False),
    ],
)
def test_is_huggingface_url(url, expected):
    """Verifies the suffix-with-leading-dot match — the whole reason
    this matters is that ``evil.hf.space.com`` must not get our token."""
    assert is_huggingface_url(url) is expected


def test_get_huggingface_token_prefers_hf_token_env(monkeypatch):
    """``HF_TOKEN`` is the canonical variable; it wins over everything."""
    monkeypatch.setenv("HF_TOKEN", "primary-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "secondary-token")
    assert get_huggingface_token(token_file_reader=lambda: "from-file") == "primary-token"


def test_get_huggingface_token_falls_back_to_hub_var(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hub-token")
    assert get_huggingface_token(token_file_reader=lambda: None) == "hub-token"


def test_get_huggingface_token_falls_back_to_file(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    assert get_huggingface_token(token_file_reader=lambda: "from-cli-login") == "from-cli-login"


def test_get_huggingface_token_returns_none_when_nothing_set(monkeypatch):
    """No env, no file = no token. The MCP client must not send a
    blank ``Bearer `` header — that's worse than no auth at all."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    assert get_huggingface_token(token_file_reader=lambda: None) is None


def test_get_huggingface_token_ignores_whitespace(monkeypatch):
    """A common gotcha: env vars with leading/trailing whitespace must
    be treated as unset, not as a 1-char token."""
    monkeypatch.setenv("HF_TOKEN", "   ")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    assert get_huggingface_token(token_file_reader=lambda: None) is None


def test_maybe_inject_hf_auth_adds_bearer_for_hf_url(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "abc123")
    out = maybe_inject_hf_auth("https://huggingface.co/mcp", {"X-Other": "y"})
    assert out["Authorization"] == "Bearer abc123"
    assert out["X-Other"] == "y"


def test_maybe_inject_hf_auth_noop_for_non_hf_url(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "abc")
    out = maybe_inject_hf_auth("https://example.com/mcp", {"X": "1"})
    assert "Authorization" not in out
    assert out == {"X": "1"}


def test_maybe_inject_hf_auth_does_not_overwrite_user_auth(monkeypatch):
    """If the user explicitly set Authorization, respect it. They may
    be testing with a service-account token that differs from HF_TOKEN."""
    monkeypatch.setenv("HF_TOKEN", "from-env")
    out = maybe_inject_hf_auth(
        "https://huggingface.co/mcp",
        {"authorization": "Bearer user-provided"},
    )
    assert out["authorization"] == "Bearer user-provided"


def test_maybe_inject_hf_auth_no_token_no_header(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    # Disable HF_HOME so it doesn't accidentally read your local cache.
    monkeypatch.setenv("HF_HOME", "/nonexistent-dir-for-test")
    out = maybe_inject_hf_auth("https://huggingface.co/mcp")
    assert "Authorization" not in out


def test_maybe_inject_hf_auth_returns_new_dict():
    """Input must not be mutated — caller's headers dict may be
    reused across multiple requests with different URLs."""
    inp = {"X": "1"}
    out = maybe_inject_hf_auth("https://example.com", inp)
    assert out is not inp


# ---------------------------------------------------------------------------
# RFC 9728 Protected Resource Metadata discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_discovery_uses_prm_when_available(monkeypatch):
    """RFC 9728 is the newer pattern modern MCP servers use. If
    ``/.well-known/oauth-protected-resource`` returns auth-server
    pointers, we should follow them and merge the AS metadata."""
    provider = MCPOAuthProvider()

    fetched: list = []

    def fake_fetch(url):
        fetched.append(url)
        if url.endswith("/oauth-protected-resource"):
            return {
                "resource": "https://server.example",
                "authorization_servers": ["https://auth.example"],
            }
        if url.endswith("/oauth-authorization-server"):
            return {
                "issuer": "https://auth.example",
                "authorization_endpoint": "https://auth.example/authorize",
                "token_endpoint": "https://auth.example/token",
            }
        return None

    monkeypatch.setattr(provider, "_fetch_metadata", fake_fetch)

    meta = await provider.discover_oauth_metadata("https://server.example")
    assert meta["authorization_endpoint"] == "https://auth.example/authorize"
    assert meta["token_endpoint"] == "https://auth.example/token"
    # Both endpoints were probed (PRM first, then AS).
    assert any("oauth-protected-resource" in u for u in fetched)
    assert any("oauth-authorization-server" in u for u in fetched)


@pytest.mark.asyncio
async def test_metadata_discovery_falls_back_to_rfc_8414(monkeypatch):
    """When PRM returns nothing, the older RFC 8414 endpoint must
    still be tried. This preserves compatibility with the many MCP
    servers that haven't migrated to PRM yet."""
    provider = MCPOAuthProvider()

    def fake_fetch(url):
        if url.endswith("/oauth-protected-resource"):
            return None  # PRM not implemented
        if url.endswith("/oauth-authorization-server"):
            return {
                "authorization_endpoint": "https://server.example/authorize",
                "token_endpoint": "https://server.example/token",
            }
        return None

    monkeypatch.setattr(provider, "_fetch_metadata", fake_fetch)

    meta = await provider.discover_oauth_metadata("https://server.example")
    assert meta["authorization_endpoint"] == "https://server.example/authorize"


@pytest.mark.asyncio
async def test_metadata_discovery_returns_empty_when_both_fail(monkeypatch):
    """Both endpoints down/missing = empty dict, not exception. The
    OAuth flow path will then construct default endpoint URLs and let
    the actual auth request fail loudly with a real HTTP error — which
    is more debuggable than a discovery-time exception."""
    provider = MCPOAuthProvider()
    monkeypatch.setattr(provider, "_fetch_metadata", lambda _: None)
    meta = await provider.discover_oauth_metadata("https://server.example")
    assert meta == {}


@pytest.mark.asyncio
async def test_metadata_discovery_caches_result(monkeypatch):
    """The cache must avoid a second HTTP probe within the same
    process — these are read-mostly URLs and we make repeat calls
    during a single OAuth flow."""
    provider = MCPOAuthProvider()
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        if url.endswith("/oauth-authorization-server"):
            return {"authorization_endpoint": "x", "token_endpoint": "y"}
        return None

    monkeypatch.setattr(provider, "_fetch_metadata", fake_fetch)

    await provider.discover_oauth_metadata("https://server.example")
    before = calls["n"]
    await provider.discover_oauth_metadata("https://server.example")
    assert calls["n"] == before  # second call was a cache hit


@pytest.mark.asyncio
async def test_prm_with_invalid_authorization_servers_skips_to_fallback(monkeypatch):
    """A malformed PRM (e.g. empty/garbage ``authorization_servers``)
    must not block the RFC 8414 fallback from running."""
    provider = MCPOAuthProvider()

    def fake_fetch(url):
        if url.endswith("/oauth-protected-resource"):
            return {"authorization_servers": []}  # legal but useless
        if url.endswith("/oauth-authorization-server"):
            return {
                "authorization_endpoint": "https://server.example/authorize",
                "token_endpoint": "https://server.example/token",
            }
        return None

    monkeypatch.setattr(provider, "_fetch_metadata", fake_fetch)

    meta = await provider.discover_oauth_metadata("https://server.example")
    assert meta["authorization_endpoint"] == "https://server.example/authorize"


# ---------------------------------------------------------------------------
# Typed OAuth exceptions
# ---------------------------------------------------------------------------


def test_oauth_typed_exceptions_share_base():
    """Callers should be able to catch all OAuth failures via the
    base class, while still being able to discriminate."""
    assert issubclass(OAuthCallbackTimeoutError, OAuthError)
    assert issubclass(OAuthFlowCancelledError, OAuthError)
    assert issubclass(OAuthMetadataError, OAuthError)
    # TimeoutError mixin so generic ``except TimeoutError`` still works.
    assert issubclass(OAuthCallbackTimeoutError, TimeoutError)


# ---------------------------------------------------------------------------
# TokenStorage protocol + file backend adapter
# ---------------------------------------------------------------------------


def test_file_storage_adapter_satisfies_protocol(tmp_path, monkeypatch):
    """The existing file storage must satisfy the new Protocol so
    callers can pass it everywhere the protocol is accepted, with no
    code changes from the pre-B7 world."""
    monkeypatch.setenv("HOME", str(tmp_path))
    file_store = MCPAuthStorage()
    adapter = _FileTokenStorageAdapter(file_store)

    # Duck-type check — these three methods are the protocol.
    assert hasattr(adapter, "save_tokens")
    assert hasattr(adapter, "load_tokens")
    assert hasattr(adapter, "delete_tokens")

    # And a real round-trip exercises the wiring.
    tokens = OAuthTokens(access_token="a", refresh_token="b")
    adapter.save_tokens("https://example.com", tokens)
    loaded = adapter.load_tokens("https://example.com")
    assert loaded is not None
    assert loaded.access_token == "a"
    assert adapter.delete_tokens("https://example.com") is True


def test_make_default_token_storage_returns_a_storage():
    """Whichever backend is preferred, the helper must return
    *something* — fallback chain is the whole point."""
    storage = make_default_token_storage()
    assert hasattr(storage, "save_tokens")
    assert hasattr(storage, "load_tokens")
    assert hasattr(storage, "delete_tokens")


@pytest.mark.skipif(not _has_keyring(), reason="OS keyring backend not available")
def test_keyring_storage_round_trip():
    """When keyring is available, save/load/delete must round-trip.
    Uses a unique service name per run so we don't trample real
    user data if the test is run in a desktop session."""
    import uuid

    service = f"superqode-mcp-test-{uuid.uuid4().hex[:8]}"
    storage = KeyringTokenStorage(service=service)

    tokens = OAuthTokens(
        access_token="kr-access",
        refresh_token="kr-refresh",
        scope="read",
    )
    try:
        storage.save_tokens("https://example.com/mcp", tokens)
        loaded = storage.load_tokens("https://example.com/mcp")
        assert loaded is not None
        assert loaded.access_token == "kr-access"
        assert loaded.refresh_token == "kr-refresh"
        assert loaded.scope == "read"

        # Different URL = different entry — no cross-talk.
        other = storage.load_tokens("https://other.example/mcp")
        assert other is None
    finally:
        storage.delete_tokens("https://example.com/mcp")


@pytest.mark.skipif(not _has_keyring(), reason="OS keyring backend not available")
def test_keyring_storage_identity_is_url_independent_per_server():
    """Two URLs must produce different identity slots — otherwise one
    server's token would shadow another's."""
    a = KeyringTokenStorage._identity("https://server-a.example")
    b = KeyringTokenStorage._identity("https://server-b.example")
    same_a = KeyringTokenStorage._identity("https://server-a.example")
    assert a != b
    assert a == same_a  # stable for the same URL


def test_keyring_storage_load_returns_none_on_corrupt_json(monkeypatch, tmp_path):
    """A keyring entry someone hand-edited to invalid JSON must not
    crash the entire MCP connect — fall back to "no token", which
    triggers a fresh OAuth flow."""
    pytest.importorskip("keyring")

    class _FakeKeyring:
        def __init__(self):
            self._store: Dict[tuple, str] = {}

        def set_password(self, service, identity, payload):
            self._store[(service, identity)] = payload

        def get_password(self, service, identity):
            return self._store.get((service, identity))

        def delete_password(self, service, identity):
            self._store.pop((service, identity), None)

    fake = _FakeKeyring()
    fake.set_password(
        KeyringTokenStorage.SERVICE,
        KeyringTokenStorage._identity("https://example.com"),
        "{not valid json",
    )

    storage = KeyringTokenStorage()
    monkeypatch.setattr(storage, "_keyring", fake)

    assert storage.load_tokens("https://example.com") is None


def test_keyring_storage_load_returns_none_on_backend_failure(monkeypatch):
    """If the keyring backend dies between save and load (Linux
    desktop session timeout, locked Keychain on macOS), don't propagate
    the exception — let the caller re-auth cleanly."""
    pytest.importorskip("keyring")

    class _ExplodingKeyring:
        def get_password(self, *_):
            raise RuntimeError("backend lost")

        def set_password(self, *_):
            pass

        def delete_password(self, *_):
            pass

    storage = KeyringTokenStorage()
    monkeypatch.setattr(storage, "_keyring", _ExplodingKeyring())
    assert storage.load_tokens("https://example.com") is None
