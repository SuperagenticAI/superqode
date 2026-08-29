"""A2A OAuth uses stored tokens; it does not shell out to a vendor CLI."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from superqode.a2a.oauth import (
    CLIENT_ID_ENV,
    REDIRECT_URI,
    A2AOAuthStore,
    StoredOAuth,
    ensure_access_token,
    logout_origin,
    register_oauth_client,
)
from superqode.a2a.security import OAuthNeed
from superqode.mcp.oauth import OAuthTokens


class _Store:
    def __init__(self, record: StoredOAuth | None = None) -> None:
        self.record = record or StoredOAuth()
        self.saved = None
        self.cleared = False

    def load(self, origin):
        del origin
        return self.record

    def load_tokens(self, origin):
        return self.load(origin).tokens

    def save_tokens(self, origin, tokens, *, revocation_endpoint=None):
        del origin
        self.saved = tokens
        self.record.tokens = tokens
        if revocation_endpoint:
            self.record.revocation_endpoint = revocation_endpoint

    def save_client(self, origin, client_id, client_secret=""):
        del origin
        self.record.client_id = client_id
        self.record.client_secret = client_secret

    def clear(self, origin):
        del origin
        self.cleared = True
        self.record = StoredOAuth()
        return True


def _need(**kwargs) -> OAuthNeed:
    params = {
        "scheme": "google",
        "required": True,
        "openid_url": "https://accounts.example/.well-known/openid-configuration",
    }
    params.update(kwargs)
    return OAuthNeed(**params)


@pytest.mark.asyncio
async def test_ensure_access_token_uses_an_unexpired_store(monkeypatch):
    store = _Store(StoredOAuth(tokens=OAuthTokens(access_token="stored-token")))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    token = await ensure_access_token("https://agent.example", _need(), interactive=False)
    assert token == "stored-token"
    assert store.saved is None


@pytest.mark.asyncio
async def test_ensure_access_token_refuses_json_mode_without_a_store(monkeypatch):
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: _Store())
    monkeypatch.setattr(
        "superqode.a2a.oauth.discover_oauth_metadata",
        AsyncMock(return_value={"authorization_endpoint": "https://as.example/auth"}),
    )
    with pytest.raises(Exception, match="Pass --token"):
        await ensure_access_token("https://agent.example", _need(), interactive=False)


@pytest.mark.asyncio
async def test_register_oauth_client_posts_to_the_authorization_server(monkeypatch):
    seen: dict = {}

    async def fake_json_post(url, data):
        seen["url"] = url
        seen["data"] = data
        return {"client_id": "reg-1"}

    monkeypatch.setattr("superqode.a2a.oauth._json_post", fake_json_post)
    result = await register_oauth_client("https://as.example/register")
    assert result["client_id"] == "reg-1"
    assert seen["url"] == "https://as.example/register"
    assert seen["data"]["redirect_uris"] == [REDIRECT_URI]
    assert seen["data"]["application_type"] == "native"


@pytest.mark.asyncio
async def test_browser_flow_refuses_to_walk_the_callback_port(monkeypatch):
    from superqode.a2a.oauth import A2AOAuthError, _browser_flow

    store = _Store(StoredOAuth(client_id="public-client"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)

    class FakeServer:
        def __init__(self, port, callback_path):
            self.port = port
            self.callback_path = callback_path

        async def start(self, *, strict_port=False):
            del strict_port
            raise OSError("Address already in use")

        def get_redirect_uri(self):
            return f"http://localhost:{self.port}{self.callback_path}"

        async def stop(self):
            return None

    monkeypatch.setattr("superqode.mcp.oauth_callback.OAuthCallbackServer", FakeServer)
    with pytest.raises(A2AOAuthError, match="19876"):
        await _browser_flow(
            "https://agent.example",
            _need(),
            metadata={"authorization_endpoint": "https://as.example/auth"},
            client_id="public-client",
            client_secret="",
            on_status=None,
        )


@pytest.mark.asyncio
async def test_browser_flow_exchanges_the_authorization_code(monkeypatch):
    from superqode.a2a.oauth import _browser_flow
    from superqode.mcp.oauth_callback import CallbackResult

    store = _Store(StoredOAuth(client_id="public-client"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    monkeypatch.setattr("superqode.a2a.oauth.webbrowser.open", lambda url: True)

    class FakeServer:
        def __init__(self, port, callback_path):
            self.port = port
            self.callback_path = callback_path

        async def start(self, *, strict_port=False):
            assert strict_port is True
            return None

        def get_redirect_uri(self):
            return REDIRECT_URI

        async def wait_for_callback(self, state, timeout=300):
            del timeout
            assert state == "state-1"
            return CallbackResult(code="code-1", state=state)

        async def stop(self):
            return None

    class FakeProvider:
        def __init__(self, config):
            self.config = config

        async def start_auth_flow(self, origin, metadata=None):
            del origin, metadata
            return "https://as.example/auth?state=state-1&client_id=public-client"

        async def handle_callback(self, code, state, metadata=None):
            del state, metadata
            assert code == "code-1"
            return OAuthTokens(access_token="minted-token")

        async def discover_oauth_metadata(self, server_url):
            del server_url
            return {}

        def _fetch_metadata(self, url):
            del url
            return {}

    monkeypatch.setattr("superqode.mcp.oauth_callback.OAuthCallbackServer", FakeServer)
    monkeypatch.setattr("superqode.a2a.oauth.MCPOAuthProvider", FakeProvider)
    tokens = await _browser_flow(
        "https://agent.example",
        _need(),
        metadata={
            "authorization_endpoint": "https://as.example/auth",
            "token_endpoint": "https://as.example/token",
        },
        client_id="public-client",
        client_secret="",
        on_status=None,
    )
    assert tokens.access_token == "minted-token"


@pytest.mark.asyncio
async def test_missing_client_id_names_the_redirect_uri(monkeypatch):
    from superqode.a2a.oauth import A2AOAuthError

    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: _Store())
    monkeypatch.delenv(CLIENT_ID_ENV, raising=False)
    monkeypatch.setattr(
        "superqode.a2a.oauth.discover_oauth_metadata",
        AsyncMock(
            return_value={
                "authorization_endpoint": "https://as.example/auth",
                "token_endpoint": "https://as.example/token",
            }
        ),
    )
    monkeypatch.setattr("superqode.a2a.oauth._has_local_browser", lambda: True)
    with pytest.raises(A2AOAuthError, match=REDIRECT_URI):
        await ensure_access_token("https://agent.example", _need(), interactive=True)


@pytest.mark.asyncio
async def test_client_credentials_grant_when_secret_is_set(monkeypatch):
    store = _Store(StoredOAuth(client_id="cid", client_secret="csecret"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    monkeypatch.setattr(
        "superqode.a2a.oauth.discover_oauth_metadata",
        AsyncMock(return_value={"token_endpoint": "https://as.example/token"}),
    )

    async def fake_form_post(url, data):
        assert url == "https://as.example/token"
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "cid"
        assert data["client_secret"] == "csecret"
        return {"access_token": "cc-token", "expires_in": 3600}

    monkeypatch.setattr("superqode.a2a.oauth._form_post", fake_form_post)
    token = await ensure_access_token("https://agent.example", _need(), interactive=False)
    assert token == "cc-token"
    assert store.saved.access_token == "cc-token"


@pytest.mark.asyncio
async def test_device_code_flow_polls_until_authorized(monkeypatch):
    from superqode.a2a.oauth import _device_code_flow

    store = _Store(StoredOAuth(client_id="cid"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    calls = {"n": 0}

    async def fake_form_post(url, data):
        if url.endswith("/device"):
            return {
                "device_code": "dev-1",
                "user_code": "ABCD",
                "verification_uri": "https://as.example/verify",
                "interval": 0,
                "expires_in": 60,
            }
        calls["n"] += 1
        assert data["grant_type"].endswith("device_code")
        if calls["n"] == 1:
            return {"error": "authorization_pending"}
        return {"access_token": "device-token"}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("superqode.a2a.oauth._form_post", fake_form_post)
    monkeypatch.setattr("superqode.a2a.oauth.asyncio.sleep", no_sleep)
    tokens = await _device_code_flow(
        "https://agent.example",
        _need(),
        {
            "device_authorization_endpoint": "https://as.example/device",
            "token_endpoint": "https://as.example/token",
        },
        client_id="cid",
        client_secret="",
        on_status=None,
    )
    assert tokens.access_token == "device-token"


def test_oauth_store_round_trip(tmp_path):
    store = A2AOAuthStore(storage_dir=tmp_path, use_keyring=False)
    store.save_client("https://agent.example", "cid", "csecret")
    store.save_tokens(
        "https://agent.example",
        OAuthTokens(access_token="tok"),
        revocation_endpoint="https://as.example/revoke",
    )
    loaded = store.load("https://agent.example")
    assert loaded.client_id == "cid"
    assert loaded.client_secret == "csecret"
    assert loaded.tokens.access_token == "tok"
    assert loaded.revocation_endpoint == "https://as.example/revoke"
    assert store.clear("https://agent.example") is True
    assert store.load("https://agent.example").tokens is None


@pytest.mark.asyncio
async def test_logout_origin_deletes_the_store(tmp_path, monkeypatch):
    store = A2AOAuthStore(storage_dir=tmp_path, use_keyring=False)
    store.save_tokens("https://agent.example", OAuthTokens(access_token="tok"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    cleared, revoked = await logout_origin("https://agent.example")
    assert cleared is True
    assert revoked is False
    assert store.load_tokens("https://agent.example") is None


def test_callback_html_names_the_a2a_agent():
    from superqode.mcp.oauth_callback import ERROR_HTML, SUCCESS_HTML

    assert "A2A agent" in SUCCESS_HTML.replace("__PRODUCT__", "A2A agent")
    assert "MCP server" in SUCCESS_HTML.replace("__PRODUCT__", "MCP server")
    assert "A2A agent" in ERROR_HTML.replace("__PRODUCT__", "A2A agent")


@pytest.mark.asyncio
async def test_strict_callback_port_does_not_walk(monkeypatch):
    from superqode.mcp.oauth_callback import OAuthCallbackServer

    def boom(*_args, **_kwargs):
        raise OSError("Address already in use")

    monkeypatch.setattr("superqode.mcp.oauth_callback.HTTPServer", boom)
    server = OAuthCallbackServer(port=19876, callback_path="/a2a/oauth/callback")
    with pytest.raises(OSError, match="already in use"):
        await server.start(strict_port=True)
    assert server.port == 19876


@pytest.mark.asyncio
async def test_satisfy_or_group_accepts_an_api_key_without_oauth(monkeypatch):
    from superqode.a2a.client import A2AClient
    from superqode.a2a.oauth import satisfy_card_auth

    called = {"oauth": False}

    async def fail_oauth(*_args, **_kwargs):
        called["oauth"] = True
        raise AssertionError("oauth must not run when an API-key group is already satisfied")

    monkeypatch.setattr("superqode.a2a.oauth.ensure_access_token", fail_oauth)
    client = A2AClient("https://agent.example")
    client._card_data = {
        "securitySchemes": {
            "google": {
                "type": "openIdConnect",
                "openIdConnectUrl": "https://accounts.example/.well-known/openid-configuration",
            },
            "apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"},
        },
        "securityRequirements": [{"google": []}, {"apiKey": []}],
    }
    await satisfy_card_auth(
        client,
        "https://agent.example",
        token="secret-key",
        headers={},
        interactive=False,
    )
    assert client._http.headers.get("X-API-Key") == "secret-key"
    assert "Authorization" not in client._http.headers
    assert called["oauth"] is False


@pytest.mark.asyncio
async def test_satisfy_attaches_a_query_api_key():
    from superqode.a2a.client import A2AClient
    from superqode.a2a.oauth import satisfy_card_auth

    client = A2AClient("https://agent.example")
    client._card_data = {
        "securitySchemes": {"apiKey": {"type": "apiKey", "name": "api_key", "in": "query"}},
        "securityRequirements": [{"apiKey": []}],
    }
    await satisfy_card_auth(
        client,
        "https://agent.example",
        token="secret-key",
        headers={},
        interactive=False,
    )
    assert client._query_params["api_key"] == "secret-key"
    assert "api_key=secret-key" in client._with_query("https://agent.example/rpc")


class _FakeKeyring:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service, identity, password):
        self.data[(service, identity)] = password

    def get_password(self, service, identity):
        return self.data.get((service, identity))

    def delete_password(self, service, identity):
        self.data.pop((service, identity), None)


def test_oauth_store_prefers_the_os_keyring(tmp_path):
    ring = _FakeKeyring()
    store = A2AOAuthStore(storage_dir=tmp_path, keyring=ring)
    store.save_tokens("https://agent.example", OAuthTokens(access_token="keyed"))
    assert store.load_tokens("https://agent.example").access_token == "keyed"
    assert list(tmp_path.glob("*.json")) == []
    assert ring.data
    assert store.clear("https://agent.example") is True
    assert store.load_tokens("https://agent.example") is None


@pytest.mark.asyncio
async def test_logout_revokes_tokens_at_the_identity_provider(monkeypatch):
    store = _Store(
        StoredOAuth(
            tokens=OAuthTokens(access_token="access", refresh_token="refresh"),
            client_id="cid",
            revocation_endpoint="https://as.example/revoke",
        )
    )
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    seen: list[dict] = []

    async def fake_form_post(url, data):
        assert url == "https://as.example/revoke"
        seen.append(data)
        return {}

    monkeypatch.setattr("superqode.a2a.oauth._form_post", fake_form_post)
    cleared, revoked = await logout_origin("https://agent.example")
    assert cleared is True
    assert revoked is True
    assert [item["token_type_hint"] for item in seen] == ["refresh_token", "access_token"]
    assert store.cleared is True


@pytest.mark.asyncio
async def test_logout_still_clears_when_revoke_fails(monkeypatch):
    from superqode.a2a.oauth import A2AOAuthError

    store = _Store(
        StoredOAuth(
            tokens=OAuthTokens(access_token="access"),
            revocation_endpoint="https://as.example/revoke",
        )
    )
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)

    async def fail_post(url, data):
        del url, data
        raise A2AOAuthError("revocation refused")

    monkeypatch.setattr("superqode.a2a.oauth._form_post", fail_post)
    cleared, revoked = await logout_origin("https://agent.example")
    assert cleared is True
    assert revoked is False


@pytest.mark.asyncio
async def test_satisfy_requires_tls_cert_when_the_card_asks_for_mtls():
    from superqode.a2a.client import A2AClient, A2AClientError
    from superqode.a2a.oauth import satisfy_card_auth

    client = A2AClient("https://agent.example")
    client._card_data = {
        "securitySchemes": {"mtls": {"type": "mutualTLS"}},
        "securityRequirements": [{"mtls": []}],
    }
    with pytest.raises(A2AClientError, match="tls-cert"):
        await satisfy_card_auth(
            client,
            "https://agent.example",
            token="",
            headers={},
            interactive=False,
        )


@pytest.mark.asyncio
async def test_satisfy_accepts_mutual_tls_when_a_client_cert_is_attached():
    from superqode.a2a.client import A2AClient
    from superqode.a2a.oauth import satisfy_card_auth

    client = A2AClient("https://agent.example")
    client._tls_cert = "/tmp/client.pem"
    client._card_data = {
        "securitySchemes": {"mtls": {"type": "mutualTLS"}},
        "securityRequirements": [{"mtls": []}],
    }
    await satisfy_card_auth(
        client,
        "https://agent.example",
        token="",
        headers={},
        interactive=False,
    )


def test_client_passes_the_certificate_to_httpx(monkeypatch):
    from superqode.a2a.client import A2AClient

    seen: dict = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            del args
            seen.update(kwargs)
            self.headers = {}

        async def aclose(self):
            return None

    monkeypatch.setattr("superqode.a2a.client.httpx.AsyncClient", FakeClient)
    A2AClient("https://agent.example", client_cert="/c.pem", client_key="/k.pem")
    assert seen["cert"] == ("/c.pem", "/k.pem")
