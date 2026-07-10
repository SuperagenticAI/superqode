"""Tests for opt-in Grok CLI session-token reuse (`:grok api`)."""

import base64
import json
import time

import pytest

import superqode.auth as sq_auth
from superqode.auth import LocalAuthStorage, OAuthAuth
from superqode.providers import grok_cli_auth
from superqode.providers.credentials import provider_api_key
from superqode.providers.registry import PROVIDERS


@pytest.fixture
def isolated_auth_store(tmp_path, monkeypatch):
    """Point the singleton auth store at a temp file."""
    store = LocalAuthStorage(tmp_path / "superqode-auth.json")
    monkeypatch.setattr(sq_auth, "_storage", store)
    return store


def _write_cli_auth(tmp_path, payload):
    auth_file = tmp_path / "grok-auth.json"
    auth_file.write_text(json.dumps(payload))
    return auth_file


def _jwt_with_exp(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


# --- reading ~/.grok/auth.json ------------------------------------------------


def test_read_cli_token_documented_schema(tmp_path):
    # The schema xAI's CLI README documents: {"https://accounts.x.ai/sign-in": {"key": ...}}
    auth_file = _write_cli_auth(
        tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-token-123"}}
    )

    token, expires = grok_cli_auth.read_cli_token(auth_file)

    assert token == "sess-token-123"
    # Opaque token: expiry estimated from file mtime + documented 7-day lifetime.
    assert abs(expires - (auth_file.stat().st_mtime + 7 * 24 * 3600)) < 5


def test_read_cli_token_uses_jwt_exp_when_present(tmp_path):
    exp = int(time.time()) + 3600
    auth_file = _write_cli_auth(
        tmp_path, {"https://accounts.x.ai/sign-in": {"key": _jwt_with_exp(exp)}}
    )

    _token, expires = grok_cli_auth.read_cli_token(auth_file)

    assert expires == exp


def test_read_cli_token_fallback_shapes(tmp_path):
    # Enterprise OIDC entries share the {url: {key: ...}} shape under other hosts.
    other_host = tmp_path / "oidc.json"
    other_host.write_text(json.dumps({"https://acme.okta.com": {"key": "oidc-tok"}}))
    assert grok_cli_auth.read_cli_token(other_host)[0] == "oidc-tok"

    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"access_token": "flat-tok"}))
    assert grok_cli_auth.read_cli_token(flat)[0] == "flat-tok"


def test_read_cli_token_missing_or_invalid(tmp_path):
    assert grok_cli_auth.read_cli_token(tmp_path / "nope.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert grok_cli_auth.read_cli_token(bad) is None

    empty = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {}})
    assert grok_cli_auth.read_cli_token(empty) is None


# --- import / remove / resolution ---------------------------------------------


def test_import_and_remove_cli_token(tmp_path, isolated_auth_store):
    auth_file = _write_cli_auth(
        tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-token-xyz"}}
    )

    auth = grok_cli_auth.import_cli_token(auth_file)

    assert isinstance(auth, OAuthAuth)
    assert auth.access == "sess-token-xyz"
    assert not auth.is_expired()
    stored = isolated_auth_store.get("grok-cli")
    assert isinstance(stored, OAuthAuth) and stored.access == "sess-token-xyz"

    assert grok_cli_auth.remove_cli_token() is True
    assert isolated_auth_store.get("grok-cli") is None
    assert grok_cli_auth.remove_cli_token() is False


def test_provider_api_key_resolves_imported_token(tmp_path, isolated_auth_store):
    # grok-cli has no env vars, so resolution must come from the auth store.
    assert PROVIDERS["grok-cli"].env_vars == []
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-abc"}})
    grok_cli_auth.import_cli_token(auth_file)

    assert provider_api_key(PROVIDERS["grok-cli"]) == "sess-abc"


def test_expired_imported_token_is_not_used(isolated_auth_store):
    isolated_auth_store.set(
        "grok-cli", OAuthAuth(access="stale", refresh="", expires=int(time.time()) - 10)
    )

    assert provider_api_key(PROVIDERS["grok-cli"]) is None


# --- provider definition and gateway routing -----------------------------------


def test_grok_cli_provider_def_targets_documented_proxy():
    pdef = PROVIDERS["grok-cli"]

    assert pdef.dynamic is True
    assert pdef.litellm_prefix == "openai/"
    assert pdef.default_base_url == "https://cli-chat-proxy.grok.com/v1"
    # Same override env the official CLI documents for enterprise proxies.
    assert pdef.base_url_env == "GROK_CLI_CHAT_PROXY_BASE_URL"
    assert pdef.extra_headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert pdef.extra_headers["x-grok-model-override"] == "{model}"
    assert pdef.extra_headers["x-grok-client-version"] == "{cli_version}"
    assert pdef.example_models[0] == "grok-build"


def test_detect_cli_version_from_version_json(tmp_path, monkeypatch):
    version_file = tmp_path / "version.json"
    version_file.write_text(json.dumps({"version": "0.2.93", "stable_version": "0.2.93"}))
    monkeypatch.setattr(grok_cli_auth, "GROK_VERSION_FILE", version_file)
    grok_cli_auth.clear_cli_version_cache()

    assert grok_cli_auth.detect_cli_version() == "0.2.93"


def test_detect_cli_version_falls_back_to_minimum(tmp_path, monkeypatch):
    monkeypatch.setattr(grok_cli_auth, "GROK_VERSION_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(grok_cli_auth.shutil, "which", lambda _name: None)
    grok_cli_auth.clear_cli_version_cache()

    assert grok_cli_auth.detect_cli_version() == grok_cli_auth.MIN_CLI_VERSION


def test_gateway_applies_proxy_headers_and_token(tmp_path, isolated_auth_store, monkeypatch):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    monkeypatch.delenv("GROK_CLI_CHAT_PROXY_BASE_URL", raising=False)
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-gw"}})
    grok_cli_auth.import_cli_token(auth_file)
    monkeypatch.setattr(grok_cli_auth, "detect_cli_version", lambda: "0.2.93")

    gateway = LiteLLMGateway.__new__(LiteLLMGateway)  # header logic needs no __init__
    request_kwargs = {}
    gateway._apply_dynamic_provider("grok-cli", request_kwargs, model="grok-4.5")

    assert request_kwargs["api_base"] == "https://cli-chat-proxy.grok.com/v1"
    assert request_kwargs["api_key"] == "sess-gw"
    assert request_kwargs["extra_headers"] == {
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-model-override": "grok-4.5",
        "x-grok-client-version": "0.2.93",
    }


# --- :grok api command routing --------------------------------------------------


class _Log:
    def __init__(self):
        self.infos = []
        self.errors = []

    def add_info(self, msg):
        self.infos.append(msg)

    def add_error(self, msg):
        self.errors.append(msg)


class _AppStub:
    def __init__(self):
        self.connected = []

    def _connect_byok_mode(self, provider, model, log):
        self.connected.append((provider, model))

    def _grok_api_cmd(self, rest, log):
        from superqode.app_main import SuperQodeApp

        SuperQodeApp._grok_api_cmd(self, rest, log)


def test_grok_cmd_routes_api_subcommand():
    from superqode.app_main import SuperQodeApp

    calls = []

    class _Stub:
        def _grok_api_cmd(self, rest, log):
            calls.append(rest)

    SuperQodeApp._grok_cmd(_Stub(), "api grok-4.5", _Log())

    assert calls == ["grok-4.5"]


def test_grok_cmd_connect_uses_subscription_harness_not_acp():
    """:grok connect must use SuperQode harness (token import), not Grok Build ACP."""
    from superqode.app_main import SuperQodeApp

    calls = []

    class _Stub:
        def _grok_api_cmd(self, rest, log):
            calls.append(("api", rest))

        def _connect_acp_cmd(self, command, log):
            calls.append(("acp", command))

    SuperQodeApp._grok_cmd(_Stub(), "connect grok-4.5", _Log())
    SuperQodeApp._grok_cmd(_Stub(), "", _Log())  # default subcommand is connect

    assert calls == [("api", "grok-4.5"), ("api", "")]
    assert not any(c[0] == "acp" for c in calls)


def test_grok_api_connects_default_model(tmp_path, isolated_auth_store, monkeypatch):
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-ok"}})
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("", log)

    assert stub.connected == [("grok-cli", "grok-build")]
    assert not log.errors


def test_grok_api_strips_provider_prefixes(tmp_path, isolated_auth_store, monkeypatch):
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-ok"}})
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("xai/grok-4.5", log)

    assert stub.connected == [("grok-cli", "grok-4.5")]


def test_grok_api_without_cli_login_errors(tmp_path, isolated_auth_store, monkeypatch):
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", tmp_path / "missing.json")

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("", log)

    assert stub.connected == []
    assert any("No Grok CLI login" in e for e in log.errors)


def test_grok_api_expired_session_errors_and_cleans_up(tmp_path, isolated_auth_store, monkeypatch):
    auth_file = _write_cli_auth(
        tmp_path,
        {"https://accounts.x.ai/sign-in": {"key": _jwt_with_exp(int(time.time()) - 100)}},
    )
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("", log)

    assert stub.connected == []
    assert any("expired" in e.lower() for e in log.errors)
    assert isolated_auth_store.get("grok-cli") is None


def test_grok_api_off_removes_token(isolated_auth_store):
    isolated_auth_store.set("grok-cli", OAuthAuth(access="tok", refresh="", expires=0))

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("off", log)

    assert isolated_auth_store.get("grok-cli") is None
    assert stub.connected == []
