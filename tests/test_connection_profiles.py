"""Tests for the connection-profile registry and TUI dispatch routing."""

from __future__ import annotations

import pytest

from superqode.providers.connection_profiles import (
    ConnectionProfile,
    connection_profile_ids,
    get_connection_profile,
    list_connection_profiles,
)


def test_registry_has_expected_profiles():
    ids = connection_profile_ids()
    # Local-first display order: Local, BYOK, ACP, Codex, Claude, Antigravity, Grok.
    assert ids == ["local", "byok", "acp", "codex", "claude", "antigravity", "grok"]


def test_codex_profile_is_runtime_connector():
    codex = get_connection_profile("codex")
    assert codex.connector == "runtime"
    assert codex.runtime == "codex-sdk"
    assert codex.self_contained is True


def test_claude_profile_is_agent_sdk_runtime():
    # The single Claude headline profile is the Agent SDK (API key). Claude over
    # ACP is reached via the generic ACP picker, not a duplicate profile.
    claude = get_connection_profile("claude")
    assert claude.connector == "runtime"
    assert claude.runtime == "claude-agent-sdk"
    assert "api key" in claude.description.lower()
    assert "subscription" not in (claude.label + claude.description).lower()


def test_antigravity_profile_is_signed_in_cli_runtime_connector():
    antigravity = get_connection_profile("antigravity")
    assert antigravity.connector == "runtime"
    assert antigravity.runtime == "antigravity-cli"
    assert antigravity.self_contained is True
    assert "google sign-in" in antigravity.description.lower()


def test_antigravity_detect_requires_compatible_cli(monkeypatch):
    import superqode.providers.connection_profiles as cp
    from superqode.runtime.antigravity_status import AntigravityCLIStatus

    monkeypatch.setattr(
        "superqode.runtime.antigravity_status.probe_antigravity_cli",
        lambda: AntigravityCLIStatus(
            binary="/tmp/agy",
            version_text="1.0.3",
            version=(1, 0, 3),
            issue="run agy update",
        ),
    )

    assert cp._antigravity_cli_ready() is False


def test_grok_profile_defaults_to_grok_build_acp():
    """`:connect grok` runs xAI's own Grok Build agent (ACP), like Codex/Claude.

    SuperQode's harness on the same subscription is the explicit opt-in
    `:grok api` (grok-cli provider), not the bare connect.
    """
    grok = get_connection_profile("grok")

    assert grok.connector == "acp"
    assert grok.acp_agent == "grok"
    assert "subscription" in grok.label.lower()
    # Points users to the SuperQode-harness opt-in.
    assert ":grok api" in grok.description


def test_lookup_by_id_and_label():
    assert get_connection_profile("codex").id == "codex"
    assert get_connection_profile("Codex subscription").id == "codex"
    assert get_connection_profile("nope") is None


def test_codex_detect_uses_local_codex_auth(monkeypatch, tmp_path):
    import superqode.providers.connection_profiles as cp

    # No SDK / no auth -> not ready.
    monkeypatch.setattr(cp.importlib.util, "find_spec", lambda name: None)
    assert cp._codex_ready() is False

    # SDK present + auth.json present -> ready.
    monkeypatch.setattr(cp.importlib.util, "find_spec", lambda name: object())
    home = tmp_path
    (home / ".codex").mkdir()
    (home / ".codex" / "auth.json").write_text("{}")
    monkeypatch.setattr(cp.Path, "home", staticmethod(lambda: home))
    assert cp._codex_ready() is True


def test_grok_detect_requires_cli_subscription_auth(monkeypatch, tmp_path):
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(
        cp.shutil, "which", lambda name: "/usr/local/bin/grok" if name == "grok" else None
    )
    monkeypatch.setattr(cp.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert cp._grok_cli_ready() is False

    (tmp_path / ".grok").mkdir()
    (tmp_path / ".grok" / "auth.json").write_text("{}")
    assert cp._grok_cli_ready() is True

    (tmp_path / ".grok" / "auth.json").unlink()
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    assert cp._grok_cli_ready() is False


def test_available_never_raises():
    bad = ConnectionProfile(
        id="x",
        label="X",
        description="",
        connector="runtime",
        detect=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert bad.available is False  # swallowed


# --- TUI dispatch routing (unbound method on a stub) -------------------------


class _DispatchStub:
    def __init__(self):
        self.calls = []
        self._acp_client = None

    def _reset_connect_selection_states(self):
        self.calls.append(("reset",))

    def _runtime_cmd(self, name, log):
        self.calls.append(("runtime", name))

    def _connect_acp_cmd(self, name, log):
        self.calls.append(("acp", name))

    def _show_byok_providers(self, log):
        self.calls.append(("byok",))

    def _show_local_provider_picker(self, log):
        self.calls.append(("local",))

    def _show_agents(self, log):
        self.calls.append(("acp-picker",))

    def _antigravity_cmd(self, args, log):
        self.calls.append(("antigravity", args))

    def _grok_api_cmd(self, rest, log):
        self.calls.append(("subscription", rest))

    def set_timer(self, *a, **k):
        pass

    def _ensure_input_focus(self):
        pass

    def _record_ex_command(self, cmd, c):
        self.calls.append(("_record_ex_command", cmd, c))


@pytest.fixture
def _dispatch():
    from superqode.app_main import SuperQodeApp

    return SuperQodeApp._dispatch_connection_profile


def test_dispatch_codex_routes_to_runtime(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("codex"), log=None)
    assert ("runtime", "codex-sdk") in stub.calls


def test_dispatch_claude_routes_to_runtime(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("claude"), log=None)
    assert ("runtime", "claude-agent-sdk") in stub.calls


def test_dispatch_antigravity_routes_to_cli_runtime(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("antigravity"), log=None)
    assert ("runtime", "antigravity-cli") in stub.calls


def test_antigravity_commands_select_explicit_harness_routes():
    from superqode.app_main import SuperQodeApp

    class Stub:
        def __init__(self):
            self.calls = []

        def _runtime_cmd(self, runtime, _log):
            self.calls.append(("runtime", runtime))

        def _connect_byok_cmd(self, provider, _log):
            self.calls.append(("byok", provider))

    stub = Stub()
    SuperQodeApp._antigravity_cmd(stub, "cli", log=None)
    SuperQodeApp._antigravity_cmd(stub, "sdk", log=None)
    SuperQodeApp._antigravity_cmd(stub, "superqode", log=None)

    assert stub.calls == [
        ("runtime", "antigravity-cli"),
        ("runtime", "antigravity-sdk"),
        ("byok", "google"),
    ]


def test_antigravity_connection_announcement_never_mentions_codex():
    from superqode.app_main import SuperQodeApp

    class Log:
        def __init__(self):
            self.output = ""

        def write(self, value):
            self.output += str(value)

    class Stub:
        def _set_status_runtime(self, _runtime):
            pass

        def _set_status_model(self, _model):
            pass

        def run_worker(self, *_args, **_kwargs):
            raise AssertionError("Antigravity must not run Codex model resolution")

    log = Log()
    SuperQodeApp._announce_self_contained_connection(Stub(), "antigravity-cli", log)

    assert "Google Sign-In managed by agy" in log.output
    assert ":antigravity status" in log.output
    assert "Codex" not in log.output
    assert ":codex" not in log.output


def test_dispatch_grok_routes_to_grok_build_acp(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("grok"), log=None)
    assert ("acp", "grok") in stub.calls
    assert ("subscription", "grok-build") not in stub.calls


def test_dispatch_local_routes_to_local_picker(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("local"), log=None)
    assert ("local",) in stub.calls


def test_connect_subcommands_route_to_specific_pickers():
    """Exact connect subcommands must not fall back to the top-level picker."""
    from superqode.app_main import SuperQodeApp

    class Stub(_DispatchStub):
        def _show_connect_type_picker(self, log, clear_log=True):
            self.calls.append(("connect-picker",))

        def _dispatch_connection_profile(self, profile, log):
            self.calls.append(("profile", profile.id))

        def _connect_byok_cmd(self, args, log):
            self.calls.append(("byok-cmd", args))

        def _connect_local_cmd(self, args, log):
            self.calls.append(("local-cmd", args))

    stub = Stub()

    SuperQodeApp._handle_command(stub, ":connect acp", log=None)
    SuperQodeApp._handle_command(stub, ":connect byok", log=None)
    SuperQodeApp._handle_command(stub, ":connect local", log=None)
    SuperQodeApp._handle_command(stub, ":connect grok", log=None)
    # ":connect acp grok" must open the ACP connection (grok agent stdio),
    # never the subscription harness profile.
    SuperQodeApp._handle_command(stub, ":connect acp grok", log=None)

    assert ("acp", "") in stub.calls
    assert ("byok-cmd", "") in stub.calls
    assert ("local-cmd", "") in stub.calls
    assert ("profile", "grok") in stub.calls
    assert ("acp", "grok") in stub.calls
    assert stub.calls.count(("profile", "grok")) == 1  # only the bare :connect grok
    assert ("connect-picker",) not in stub.calls


# --- command + completion surface --------------------------------------------


def test_connect_profiles_in_commands_and_completion():
    from superqode.app.constants import COMMANDS
    from superqode.app_main import SuperQodeApp

    assert ":connect codex" in COMMANDS
    assert ":connect claude" in COMMANDS
    assert ":connect antigravity" in COMMANDS
    assert ":connect grok" in COMMANDS
    assert ":grok status" in COMMANDS
    values = {c.value for c in SuperQodeApp._connect_profile_completion_candidates()}
    assert {"codex", "claude", "antigravity", "grok", "byok", "local", "acp"} <= values


def test_no_duplicate_acp_claude_profile():
    """Claude over ACP must NOT be a separate headline profile (it's already in
    the generic ACP picker) — only the Agent SDK Claude profile exists."""
    assert get_connection_profile("claude-agent") is None
    acp_claude_profiles = [
        p for p in list_connection_profiles() if p.connector == "acp" and p.acp_agent == "claude"
    ]
    assert acp_claude_profiles == []


def test_grok_headline_profile_is_the_acp_grok_build_agent():
    """`:connect grok` IS the Grok Build ACP profile (like Codex/Claude subscriptions)."""
    acp_grok = [
        p for p in list_connection_profiles() if p.connector == "acp" and p.acp_agent == "grok"
    ]
    assert [p.id for p in acp_grok] == ["grok"]


def test_acp_bare_agent_name_routes_to_connect():
    """``:acp grok`` must connect Grok Build ACP, not print Unknown or use subscription."""
    from superqode.app_main import SuperQodeApp

    class _Log:
        def add_warning(self, msg):
            pass

        def add_info(self, msg):
            pass

    class Stub(_DispatchStub):
        pass

    stub, log = Stub(), _Log()
    SuperQodeApp._acp_cmd(stub, "grok", log)
    SuperQodeApp._acp_cmd(stub, "opencode", log)
    SuperQodeApp._acp_cmd(stub, "connect grok", log)

    assert stub.calls.count(("acp", "grok")) == 2  # bare name + connect subcommand
    assert ("acp", "opencode") in stub.calls
    assert ("subscription", "grok-build") not in stub.calls
