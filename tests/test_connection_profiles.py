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
    # Local-first display order: Local, BYOK, ACP, Codex, Claude, Antigravity.
    assert ids == ["local", "byok", "acp", "codex", "claude", "antigravity"]


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


def test_antigravity_profile_is_external_cli_connector():
    antigravity = get_connection_profile("antigravity")
    assert antigravity.connector == "external-cli"
    assert antigravity.runtime is None
    assert "gemini cli migration" in antigravity.description.lower()


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


def test_dispatch_antigravity_routes_to_external_cli(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("antigravity"), log=None)
    assert ("antigravity", "connect") in stub.calls


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

        def _connect_byok_cmd(self, args, log):
            self.calls.append(("byok-cmd", args))

        def _connect_local_cmd(self, args, log):
            self.calls.append(("local-cmd", args))

    stub = Stub()

    SuperQodeApp._handle_command(stub, ":connect acp", log=None)
    SuperQodeApp._handle_command(stub, ":connect byok", log=None)
    SuperQodeApp._handle_command(stub, ":connect local", log=None)

    assert ("acp", "") in stub.calls
    assert ("byok-cmd", "") in stub.calls
    assert ("local-cmd", "") in stub.calls
    assert ("connect-picker",) not in stub.calls


# --- command + completion surface --------------------------------------------


def test_connect_profiles_in_commands_and_completion():
    from superqode.app.constants import COMMANDS
    from superqode.app_main import SuperQodeApp

    assert ":connect codex" in COMMANDS
    assert ":connect claude" in COMMANDS
    assert ":connect antigravity" in COMMANDS
    values = {c.value for c in SuperQodeApp._connect_profile_completion_candidates()}
    assert {"codex", "claude", "antigravity", "byok", "local", "acp"} <= values


def test_no_duplicate_acp_claude_profile():
    """Claude over ACP must NOT be a separate headline profile (it's already in
    the generic ACP picker) — only the Agent SDK Claude profile exists."""
    assert get_connection_profile("claude-agent") is None
    acp_claude_profiles = [
        p for p in list_connection_profiles() if p.connector == "acp" and p.acp_agent == "claude"
    ]
    assert acp_claude_profiles == []
