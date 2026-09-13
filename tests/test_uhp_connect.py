"""UHP connection settings, persistence, and the ``connect uhp`` command."""

import json

import httpx
import pytest
from click.testing import CliRunner

from superqode.commands.uhp import connect_uhp_server
from superqode.harness.uhp_client import UHPClient
from superqode.main import cli_main
from superqode.providers import uhp as uhp_settings
from superqode.providers.uhp import (
    API_KEY_ENV,
    BASE_URL_ENV,
    HARNESS_ENV,
    UHPSettings,
    resolve_settings,
    save_connection,
)

HARNESSES = {
    "object": "list",
    "harnesses": [
        {"id": "chrn_codex", "name": "Codex", "base": "codex", "defaultModel": "gpt-5"},
        {"id": "chrn_claude", "name": "Claude Code", "base": "claude-code"},
    ],
}


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Keep every test off the real home directory and shell environment."""
    monkeypatch.setattr(uhp_settings.Path, "home", staticmethod(lambda: tmp_path))
    for name in (BASE_URL_ENV, API_KEY_ENV, HARNESS_ENV):
        monkeypatch.delenv(name, raising=False)


def _stub_client(monkeypatch, handler):
    """Route every UHPClient built by the command through a mock transport."""
    original_init = UHPClient.__init__

    def patched(self, base_url, **kwargs):
        kwargs["client"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        original_init(self, base_url, **kwargs)

    monkeypatch.setattr(UHPClient, "__init__", patched)


def _handler(request):
    if request.url.path == "/v1/uhp":
        return httpx.Response(
            200,
            json={
                "object": "uhp.discovery",
                "protocol": "uhp",
                "versions": ["2026-08-11"],
                "default_version": "2026-08-11",
                "conformance_class": "full",
                "capabilities": {"sessions": True, "cancellation": True},
            },
        )
    if request.url.path == "/v1/harnesses":
        return httpx.Response(200, json=HARNESSES)
    return httpx.Response(404, json={"error": {"type": "invalid_request_error", "code": "nf"}})


def test_resolve_prefers_arguments_then_env_then_file(monkeypatch):
    save_connection(UHPSettings(base_url="https://saved", api_key="saved-key"))

    assert resolve_settings().base_url == "https://saved"

    monkeypatch.setenv(BASE_URL_ENV, "https://env")
    assert resolve_settings().base_url == "https://env"
    assert resolve_settings("https://arg").base_url == "https://arg"


def test_saved_connection_is_owner_readable_only():
    path = save_connection(UHPSettings(base_url="https://uhp.test", harness_id="chrn_codex"))

    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["harness_id"] == "chrn_codex"


def test_env_supplied_key_is_not_copied_to_disk(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "shell-key")
    path = save_connection(UHPSettings(base_url="https://uhp.test", api_key="shell-key"))

    assert json.loads(path.read_text())["api_key"] == ""


def test_explicit_key_is_saved(monkeypatch):
    path = save_connection(UHPSettings(base_url="https://uhp.test", api_key="typed-key"))

    assert json.loads(path.read_text())["api_key"] == "typed-key"


def test_unconfigured_server_reports_setup_hint(capsys):
    code = connect_uhp_server()
    out = capsys.readouterr().out

    assert code == 1
    assert "No UHP server is configured." in out
    assert BASE_URL_ENV in out


def test_discovery_lists_harnesses_and_defers_selection(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    code = connect_uhp_server("https://uhp.test", save=False)
    out = capsys.readouterr().out

    assert code == 0
    assert "UHP 2026-08-11" in out
    assert "chrn_codex" in out and "chrn_claude" in out
    assert "superqode connect uhp --harness chrn_codex" in out


def test_selecting_a_harness_saves_the_connection(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    code = connect_uhp_server("https://uhp.test", "key-1", "chrn_claude")
    out = capsys.readouterr().out

    assert code == 0
    assert "Selected:   chrn_claude" in out
    assert resolve_settings().harness_id == "chrn_claude"


def test_single_harness_server_selects_automatically(monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/v1/harnesses":
            return httpx.Response(200, json={"harnesses": [HARNESSES["harnesses"][0]]})
        return httpx.Response(200, json={"default_version": "2026-08-11", "protocol": "uhp"})

    _stub_client(monkeypatch, handler)
    code = connect_uhp_server("https://uhp.test", save=False)
    out = capsys.readouterr().out

    assert code == 0
    assert "Selected:   chrn_codex" in out


def test_server_without_discovery_endpoint_still_lists(monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/v1/uhp":
            return httpx.Response(404, json={"error": {"type": "invalid_request_error"}})
        return httpx.Response(200, json=HARNESSES)

    _stub_client(monkeypatch, handler)
    code = connect_uhp_server("https://uhp.test", save=False)
    out = capsys.readouterr().out

    assert code == 0
    assert "UHP unknown" in out
    assert "chrn_codex" in out


def test_unreachable_server_reports_failure(monkeypatch, capsys):
    def handler(request):
        raise httpx.ConnectError("refused")

    _stub_client(monkeypatch, handler)
    code = connect_uhp_server("https://uhp.test", save=False)

    assert code == 1
    assert "Could not reach the UHP server" in capsys.readouterr().out


def test_json_output_carries_catalog_and_selection(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    code = connect_uhp_server("https://uhp.test", harness_id="chrn_codex", json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["connected"] is True
    assert payload["selected"]["id"] == "chrn_codex"
    assert [h["id"] for h in payload["harnesses"]] == ["chrn_codex", "chrn_claude"]


def test_cli_exposes_connect_uhp(monkeypatch):
    _stub_client(monkeypatch, _handler)
    result = CliRunner().invoke(
        cli_main,
        ["connect", "uhp", "--base-url", "https://uhp.test", "--no-save", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["uhp_version"] == "2026-08-11"


def test_connection_profile_resolves_and_reports_readiness(monkeypatch):
    from superqode.providers.connection_profiles import get_connection_profile

    profile = get_connection_profile("uhp")

    assert profile is not None
    assert profile.connector == "uhp-picker"
    assert profile.available is False

    monkeypatch.setenv(BASE_URL_ENV, "https://uhp.test")
    assert get_connection_profile("uhp").available is True


def test_unknown_harness_id_is_a_failure_not_a_silent_success(monkeypatch, capsys):
    """A typo in --harness must not look like a connected server."""
    _stub_client(monkeypatch, _handler)

    code = connect_uhp_server("https://uhp.test", harness_id="chrn_typo")
    out = capsys.readouterr().out

    assert code == 1
    assert "chrn_typo" in out
    assert resolve_settings().harness_id == ""


def test_unknown_harness_id_reports_json_failure(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    code = connect_uhp_server("https://uhp.test", harness_id="chrn_typo", json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["connected"] is False
    assert payload["requested_harness"] == "chrn_typo"


def test_no_save_says_so_rather_than_claiming_a_saved_connection(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    connect_uhp_server("https://uhp.test", harness_id="chrn_codex", save=False)
    out = capsys.readouterr().out

    assert "was not saved" in out
    assert "The connection is saved." not in out


def test_discovery_class_and_capabilities_are_reported(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    connect_uhp_server("https://uhp.test", harness_id="chrn_codex", json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["uhp_version"] == "2026-08-11"
    assert payload["conformance_class"] == "full"
    assert payload["capabilities"]["cancellation"] is True
    assert payload["saved"] is True


def test_server_on_another_version_is_flagged(monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/v1/uhp":
            return httpx.Response(
                200,
                json={
                    "protocol": "uhp",
                    "versions": ["2027-01-01"],
                    "default_version": "2027-01-01",
                },
            )
        return httpx.Response(200, json=HARNESSES)

    _stub_client(monkeypatch, handler)
    connect_uhp_server("https://uhp.test", harness_id="chrn_codex", save=False)

    assert "lists no version SuperQode speaks" in capsys.readouterr().out


def test_configured_connection_registers_a_runnable_uhp_adapter(monkeypatch):
    """connect uhp must produce a harness, not just a printed catalog."""
    from superqode.harness.discovery import discover_harness_adapters

    entry = next(e for e in discover_harness_adapters() if e.id == "uhp")
    assert entry.available is False
    assert entry.adapter is None

    save_connection(UHPSettings(base_url="https://uhp.test", api_key="k", harness_id="chrn_codex"))
    entry = next(e for e in discover_harness_adapters() if e.id == "uhp")

    assert entry.available is True
    assert entry.adapter is not None
    assert entry.adapter.descriptor.id == "uhp"
    assert entry.adapter.harness_id == "chrn_codex"


def test_connected_without_a_selected_harness_is_not_runnable(monkeypatch):
    from superqode.harness.discovery import discover_harness_adapters

    save_connection(UHPSettings(base_url="https://uhp.test"))
    entry = next(e for e in discover_harness_adapters() if e.id == "uhp")

    assert entry.available is False
    assert "--harness" in entry.issue


def test_env_key_strip_preserves_a_previously_saved_key(monkeypatch):
    save_connection(UHPSettings(base_url="https://uhp.test", api_key="typed-key"))
    monkeypatch.setenv(API_KEY_ENV, "shell-key")

    save_connection(UHPSettings(base_url="https://uhp.test", api_key="shell-key"))

    assert json.loads(uhp_settings.connection_path().read_text())["api_key"] == "typed-key"


def test_a_token_cap_is_saved_and_resolved(monkeypatch, capsys):
    """Providers that bill up front refuse a budget larger than the balance."""
    _stub_client(monkeypatch, _handler)

    connect_uhp_server("https://uhp.test", harness_id="chrn_codex", max_output_tokens=1000)
    out = capsys.readouterr().out

    assert "Token cap:  1000 per task" in out
    assert resolve_settings().max_output_tokens == 1000


def test_no_cap_stays_absent(monkeypatch, capsys):
    _stub_client(monkeypatch, _handler)

    connect_uhp_server("https://uhp.test", harness_id="chrn_codex")
    out = capsys.readouterr().out

    assert "Token cap" not in out
    assert resolve_settings().max_output_tokens is None


def test_the_cap_can_come_from_the_environment(monkeypatch):
    from superqode.providers.uhp import MAX_OUTPUT_TOKENS_ENV

    monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, "512")
    assert resolve_settings().max_output_tokens == 512


def test_a_nonsense_cap_is_ignored_rather_than_sent(monkeypatch):
    from superqode.providers.uhp import MAX_OUTPUT_TOKENS_ENV

    for value in ("0", "-5", "lots", ""):
        monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, value)
        assert resolve_settings().max_output_tokens is None


# ── saved settings belong to the server they were saved against ────────────────


def _save(tmp_path, monkeypatch, **fields):
    import json

    from superqode.providers import uhp as settings

    path = tmp_path / "uhp.json"
    path.write_text(json.dumps({"base_url": "https://saved.example", **fields}))
    monkeypatch.setattr(settings, "connection_path", lambda: path)
    for env in (
        settings.BASE_URL_ENV,
        settings.API_KEY_ENV,
        settings.HARNESS_ENV,
        settings.MAX_OUTPUT_TOKENS_ENV,
    ):
        monkeypatch.delenv(env, raising=False)
    return settings


def test_saved_bearer_does_not_travel_to_another_server(tmp_path, monkeypatch):
    """A credential saved for one host must not be sent to a different one."""
    settings = _save(
        tmp_path,
        monkeypatch,
        api_key="bearer-for-saved",
        harness_id="chrn_saved",
        max_output_tokens=2000,
    )

    elsewhere = settings.resolve_settings(base_url="https://other.example")

    assert elsewhere.api_key == ""
    assert elsewhere.harness_id == "", "chrn_ ids are scoped to the server that issued them"
    assert elsewhere.max_output_tokens is None


def test_saved_settings_still_apply_to_their_own_server(tmp_path, monkeypatch):
    settings = _save(
        tmp_path,
        monkeypatch,
        api_key="bearer-for-saved",
        harness_id="chrn_saved",
        max_output_tokens=2000,
    )

    same = settings.resolve_settings(base_url="https://saved.example")
    assert same.api_key == "bearer-for-saved"
    assert same.harness_id == "chrn_saved"
    assert same.max_output_tokens == 2000

    # And with no base_url at all, the saved connection is the connection.
    default = settings.resolve_settings()
    assert default.base_url == "https://saved.example"
    assert default.api_key == "bearer-for-saved"


def test_same_server_ignores_trailing_slash_and_v1(tmp_path, monkeypatch):
    settings = _save(tmp_path, monkeypatch, api_key="bearer-for-saved")

    for variant in ("https://saved.example/", "https://saved.example/v1", "HTTPS://SAVED.EXAMPLE"):
        assert settings.resolve_settings(base_url=variant).api_key == "bearer-for-saved", variant


def test_explicit_arguments_and_env_still_win(tmp_path, monkeypatch):
    settings = _save(tmp_path, monkeypatch, api_key="bearer-for-saved")

    explicit = settings.resolve_settings(base_url="https://other.example", api_key="mine")
    assert explicit.api_key == "mine"

    monkeypatch.setenv(settings.API_KEY_ENV, "from-env")
    from_env = settings.resolve_settings(base_url="https://other.example")
    assert from_env.api_key == "from-env"
