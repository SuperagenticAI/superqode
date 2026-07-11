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


def _fake_grok_cli_installed(monkeypatch) -> None:
    """Pretend the Grok CLI binary is on PATH.

    CI runners (and many developer machines without Grok) have no ``grok``
    binary. ``_import_grok_token`` / ``_show_grok_models`` short-circuit with
    install guidance when ``shutil.which("grok")`` is None; tests that cover
    login / token paths need the binary check to pass first.
    """
    import superqode.app_main as am

    monkeypatch.setattr(
        am.shutil,
        "which",
        lambda name, *args, **kwargs: ("/usr/local/bin/grok" if name == "grok" else None),
    )


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

    def _import_grok_token(self, log):
        from superqode.app_main import SuperQodeApp

        return SuperQodeApp._import_grok_token(self, log)


def test_grok_cmd_routes_api_subcommand():
    from superqode.app_main import SuperQodeApp

    calls = []

    class _Stub:
        def _grok_api_cmd(self, rest, log):
            calls.append(rest)

    SuperQodeApp._grok_cmd(_Stub(), "api grok-4.5", _Log())

    assert calls == ["grok-4.5"]


def test_grok_cmd_connect_defaults_to_grok_build_acp():
    """:grok connect (and bare :grok) runs Grok Build ACP, like Codex/Claude.

    SuperQode's harness on the subscription is the explicit `:grok api` opt-in.
    """
    from superqode.app_main import SuperQodeApp

    calls = []

    class _Stub:
        def _grok_api_cmd(self, rest, log):
            calls.append(("api", rest))

        def _connect_acp_cmd(self, command, log):
            calls.append(("acp", command))

    SuperQodeApp._grok_cmd(_Stub(), "connect grok-4.5", _Log())
    SuperQodeApp._grok_cmd(_Stub(), "", _Log())  # default subcommand is connect
    SuperQodeApp._grok_cmd(_Stub(), "api grok-4.5", _Log())  # explicit harness opt-in

    assert calls == [
        ("acp", "grok grok-4.5"),
        ("acp", "grok"),
        ("api", "grok-4.5"),
    ]


def test_grok_api_connects_default_model(tmp_path, isolated_auth_store, monkeypatch):
    _fake_grok_cli_installed(monkeypatch)
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-ok"}})
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("", log)

    assert stub.connected == [("grok-cli", "grok-build")]
    assert not log.errors


def test_grok_api_strips_provider_prefixes(tmp_path, isolated_auth_store, monkeypatch):
    _fake_grok_cli_installed(monkeypatch)
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-ok"}})
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("xai/grok-4.5", log)

    assert stub.connected == [("grok-cli", "grok-4.5")]


def test_grok_api_without_cli_login_errors(tmp_path, isolated_auth_store, monkeypatch):
    _fake_grok_cli_installed(monkeypatch)
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", tmp_path / "missing.json")

    stub, log = _AppStub(), _Log()
    stub._grok_api_cmd("", log)

    assert stub.connected == []
    assert any("No Grok CLI login" in e for e in log.errors)


def test_grok_api_expired_session_errors_and_cleans_up(tmp_path, isolated_auth_store, monkeypatch):
    _fake_grok_cli_installed(monkeypatch)
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


# --- CLI model catalog (`grok models`) ------------------------------------------


def test_parse_cli_models_output_authenticated():
    text = """
Default model: grok-build

Available models:
  - grok-build (default)
  - grok-4.5
  * grok-composer-2.5-fast  fast agentic coding
  grok-4.3
"""
    parsed = grok_cli_auth.parse_cli_models_output(text)
    assert parsed["default"] == "grok-build"
    assert parsed["models"] == ["grok-build", "grok-4.5", "grok-composer-2.5-fast", "grok-4.3"]


def test_parse_cli_models_output_unauthenticated():
    # Exact shape observed from `grok models` when logged out.
    text = "You are not authenticated.\n\nDefault model: grok-build\n\nAvailable models:\n"
    parsed = grok_cli_auth.parse_cli_models_output(text)
    assert parsed["default"] == "grok-build"
    assert parsed["models"] == []


def test_cached_cli_models_runs_once_and_clears(monkeypatch):
    calls = []

    class _Proc:
        stdout = "Default model: grok-build\n\nAvailable models:\n  grok-4.5\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    grok_cli_auth.clear_cli_models_cache()
    monkeypatch.setattr(grok_cli_auth.shutil, "which", lambda name: "/usr/local/bin/grok")
    monkeypatch.setattr(grok_cli_auth.subprocess, "run", fake_run)

    first = grok_cli_auth.cached_cli_models()
    second = grok_cli_auth.cached_cli_models()
    assert first["models"] == ["grok-4.5"]
    assert second is first
    assert len(calls) == 1

    grok_cli_auth.clear_cli_models_cache()
    grok_cli_auth.cached_cli_models()
    assert len(calls) == 2
    grok_cli_auth.clear_cli_models_cache()


def test_grok_cli_picker_uses_live_cli_catalog(monkeypatch):
    """The picker must show what `grok models` reports (e.g. grok-composer)."""
    from superqode.providers.models import get_models_for_provider

    monkeypatch.setattr(
        grok_cli_auth,
        "cached_cli_models",
        lambda: {"default": "grok-build", "models": ["grok-4.5", "grok-composer-2.5-fast"]},
    )

    models = get_models_for_provider("grok-cli")

    # Default alias is prepended; CLI order is preserved; new families appear.
    assert list(models) == ["grok-build", "grok-4.5", "grok-composer-2.5-fast"]
    composer = models["grok-composer-2.5-fast"]
    assert composer.provider == "grok-cli"
    assert "grok models" in composer.description
    # Known ids keep their curated metadata.
    assert models["grok-4.5"].context_window == 500000


def test_grok_cli_picker_falls_back_to_builtin_when_logged_out(monkeypatch):
    from superqode.providers import models as model_db
    from superqode.providers.models import get_models_for_provider

    monkeypatch.setattr(grok_cli_auth, "cached_cli_models", lambda: {"default": "", "models": []})
    monkeypatch.setattr(model_db, "_use_live_data", False)
    monkeypatch.setattr(model_db, "_live_models", None)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)

    models = get_models_for_provider("grok-cli")

    assert "grok-build" in models  # builtin snapshot still works offline
    assert "grok-4.5" in models


# --- :grok models / :grok model TUI surface --------------------------------------


def test_grok_cmd_routes_models_and_model_subcommands():
    from superqode.app_main import SuperQodeApp

    calls = []

    class _Stub:
        def _show_grok_models(self, log):
            calls.append("models")

        def _show_grok_model_picker(self, log):
            calls.append("picker")

        def _grok_api_cmd(self, rest, log):
            calls.append(("api", rest))

    SuperQodeApp._grok_cmd(_Stub(), "models", _Log())
    SuperQodeApp._grok_cmd(_Stub(), "model", _Log())
    SuperQodeApp._grok_cmd(_Stub(), "model grok-4.5", _Log())

    assert calls == ["models", "picker", ("api", "grok-4.5")]


class _PanelLog(_Log):
    def __init__(self):
        super().__init__()
        self.panels = []

    def write_feedback(self, content):
        self.panels.append(content.plain if hasattr(content, "plain") else str(content))


def test_show_grok_models_lists_live_cli_catalog(monkeypatch):
    from superqode.app_main import SuperQodeApp

    monkeypatch.setattr(grok_cli_auth, "clear_cli_models_cache", lambda: None)
    monkeypatch.setattr(
        grok_cli_auth,
        "cached_cli_models",
        lambda: {"default": "grok-build", "models": ["grok-4.5", "grok-composer-2.5-fast"]},
    )

    log = _PanelLog()
    SuperQodeApp._show_grok_models(object.__new__(SuperQodeApp), log)

    panel = " ".join(log.panels)
    assert "grok-composer-2.5-fast" in panel
    assert "grok-build" in panel  # default alias is shown and marked
    assert "signed-in CLI catalog" in panel


def test_show_grok_models_falls_back_when_logged_out(monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.providers import models as model_db

    # CLI present but not signed in → login guidance (not the install path).
    _fake_grok_cli_installed(monkeypatch)
    monkeypatch.setattr(grok_cli_auth, "clear_cli_models_cache", lambda: None)
    monkeypatch.setattr(grok_cli_auth, "cached_cli_models", lambda: {"default": "", "models": []})
    monkeypatch.setattr(model_db, "_use_live_data", False)
    monkeypatch.setattr(model_db, "_live_models", None)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)

    log = _PanelLog()
    SuperQodeApp._show_grok_models(object.__new__(SuperQodeApp), log)

    panel = " ".join(log.panels)
    assert "grok-4.5" in panel  # builtin snapshot
    assert "builtin fallback" in panel
    assert "grok login" in panel


def test_grok_model_picker_requires_login(tmp_path, isolated_auth_store, monkeypatch):
    from superqode.app_main import SuperQodeApp

    _fake_grok_cli_installed(monkeypatch)
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", tmp_path / "missing.json")

    class _Stub:
        def __init__(self):
            self.picker_calls = []

        def _import_grok_token(self, log):
            return SuperQodeApp._import_grok_token(self, log)

        def _show_provider_models(self, provider, log, use_picker=False):
            self.picker_calls.append(provider)

    stub, log = _Stub(), _Log()
    SuperQodeApp._show_grok_model_picker(stub, log)
    assert stub.picker_calls == []
    assert any("No Grok CLI login" in e for e in log.errors)

    # With a login present the BYOK picker opens for grok-cli.
    auth_file = _write_cli_auth(tmp_path, {"https://accounts.x.ai/sign-in": {"key": "sess-ok"}})
    monkeypatch.setattr(grok_cli_auth, "GROK_AUTH_FILE", auth_file)
    stub, log = _Stub(), _Log()
    SuperQodeApp._show_grok_model_picker(stub, log)
    assert stub.picker_calls == ["grok-cli"]
