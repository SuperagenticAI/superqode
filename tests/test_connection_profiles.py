"""Tests for the connection-profile registry and TUI dispatch routing."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from superqode.providers.connection_profiles import (
    CONNECT_MENU_AGENTS,
    CONNECT_MENU_BUILD,
    CONNECT_MENU_MODELS,
    CONNECT_MENU_ROOT,
    CONNECT_MENU_SUBSCRIPTIONS,
    ConnectionProfile,
    connection_profile_ids,
    get_connection_profile,
    list_connection_profiles,
)


def test_root_menu_asks_one_question_in_three_answers():
    """The first screen asks who runs the loop, not which protocol to speak.

    Transport belongs one level down: somebody choosing between an agent and
    their own key cannot act on the word "ACP" yet.
    """
    assert connection_profile_ids(menu=CONNECT_MENU_ROOT) == ["agents", "models", "build"]
    # Root entries are a flat list, so they carry no group headers.
    assert all(p.group == "" for p in list_connection_profiles(CONNECT_MENU_ROOT))


def test_agents_menu_holds_three_existing_harness_categories():
    assert connection_profile_ids(menu=CONNECT_MENU_AGENTS) == [
        "agent-subscriptions",
        "agent-acp",
        "other-harnesses",
    ]


def test_agents_carry_openness_and_transport_badges():
    """Openness is two independent facts, so it is two badges, not one bucket.

    Codex ships an Apache-2.0 harness that only drives OpenAI models; Droid is
    a closed harness that runs anything you bring. Neither fits a 2x2.
    """
    codex = get_connection_profile("codex")
    droid = get_connection_profile("droid")

    assert codex.badges == ["open harness", "OpenAI models", "via SDK"]
    assert droid.harness_openness == "closed"
    assert "BYOK" in droid.model_openness
    assert droid.transport == "ACP"


def test_prime_subscription_uses_python_rpc_while_acp_stays_explicit():
    profile = get_connection_profile("prime-agent")

    assert profile.connector == "prime-rpc"
    assert profile.transport == "Python RPC"
    assert profile.acp_agent is None
    assert ":connect acp prime-agent" in profile.description


def test_a_product_you_already_own_is_never_filed_as_installable():
    """Owning Codex is not the same as never having installed it.

    Readiness buckets by remaining effort, so a profile whose vendor product is
    present but whose SuperQode adapter is missing belongs one step away, not
    below a list of products the user has never touched.
    """
    from superqode.providers.connection_profiles import (
        ConnectionProfile,
        group_profiles_by_readiness,
    )

    owned = ConnectionProfile(
        id="owned",
        label="Owned",
        description="",
        connector="runtime",
        menu=CONNECT_MENU_AGENTS,
        detect=lambda: False,
        product_detect=lambda: True,
        unavailable_hint='uv tool install "superqode[some-extra]"',
    )
    never_seen = replace(owned, id="never-seen", label="Never seen", product_detect=lambda: False)

    buckets = dict(group_profiles_by_readiness([owned, never_seen]))

    assert [p.id for p in buckets["One step away"]] == ["owned"]
    assert [p.id for p in buckets["Installable"]] == ["never-seen"]


def test_product_present_never_raises_when_its_probe_does():
    from superqode.providers.connection_profiles import ConnectionProfile

    def explode() -> bool:
        raise OSError("no filesystem today")

    profile = ConnectionProfile(
        id="x",
        label="X",
        description="",
        connector="runtime",
        detect=lambda: False,
        product_detect=explode,
    )

    assert profile.product_present is False


def test_models_and_build_menus_cover_the_other_two_rungs():
    assert connection_profile_ids(menu=CONNECT_MENU_MODELS) == ["local", "byok", "plan"]
    assert connection_profile_ids(menu=CONNECT_MENU_BUILD) == [
        "build-import",
        "build-preset",
        "build-wizard",
        "build-blank",
    ]
    # Importing beats authoring from scratch, so it leads the build menu.
    assert get_connection_profile("build-import").connector == "harness-import"


def test_registry_has_expected_profiles():
    # The flat list is root order first, then each submenu in root order.
    assert connection_profile_ids() == [
        "agents",
        "models",
        "build",
        "agent-subscriptions",
        "agent-acp",
        "other-harnesses",
        "codex",
        "cursor",
        "amp",
        "antigravity",
        "muse",
        "prime-agent",
        "grok",
        "copilot",
        "devin",
        "droid",
        "kiro",
        "glm-cli",
        "qwen-code",
        "kimi-code",
        "deepagents-code",
        "acp",
        "harness-core",
        "harness-rlm",
        "harness-pipy",
        "harness-workbench",
        "harness-presets",
        "harness-repo",
        "local",
        "byok",
        "plan",
        "plan-zai",
        "plan-grok",
        "plan-copilot",
        "plan-moonshot",
        "plan-qwen",
        "plan-opencode",
        "plan-ollama-cloud",
        "plan-deepseek",
        "plan-minimax",
        "build-import",
        "build-preset",
        "build-wizard",
        "build-blank",
    ]
    assert "copilot-acp" in connection_profile_ids(include_legacy=True)


def test_old_root_ids_still_resolve():
    """Anyone with ``:connect subscriptions`` in muscle memory keeps working."""
    for old_id in ("subscriptions", "local", "byok", "acp", "other-harnesses"):
        assert get_connection_profile(old_id) is not None

    subscriptions = get_connection_profile("subscriptions")
    assert subscriptions.connector == "vendor-picker"
    assert subscriptions.available is True


def test_devin_and_glm_are_acp_subscription_profiles():
    devin = get_connection_profile("devin")
    glm = get_connection_profile("glm-cli")

    assert (devin.connector, devin.acp_agent) == ("acp", "devin")
    assert (glm.connector, glm.acp_agent) == ("acp", "glm")
    assert all(p.menu == CONNECT_MENU_SUBSCRIPTIONS for p in (devin, glm))
    assert "devin auth login" in devin.unavailable_hint
    assert "glm-acp-agent" in glm.unavailable_hint


def test_gemini_is_not_a_subscription_profile():
    """Gemini CLI is an API-key route, so it must not sit under Subscriptions.

    Google moved consumer plans to Antigravity, and a subscription entry must
    never put the user on metered API billing. The agent stays reachable
    through the ACP channel.
    """
    import pytest

    with pytest.raises(Exception):
        get_connection_profile("gemini-cli").id


def test_subscription_cli_profiles_detect_their_binaries(monkeypatch):
    import superqode.providers.connection_profiles as cp

    installed = {
        "devin",
        "glm-acp-agent",
        "cursor-agent",
        "amp",
        "acp-amp",
        "droid",
        "kiro-cli",
    }
    monkeypatch.setattr(
        cp.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    assert cp._devin_cli_ready() is True
    assert cp._glm_cli_ready() is True
    assert cp._cursor_cli_ready() is True
    assert cp._amp_cli_ready() is True
    assert cp._droid_cli_ready() is True
    assert cp._kiro_cli_ready() is True

    installed.clear()
    assert cp._devin_cli_ready() is False
    assert cp._glm_cli_ready() is False
    assert cp._cursor_cli_ready() is False
    assert cp._amp_cli_ready() is False
    assert cp._droid_cli_ready() is False
    assert cp._kiro_cli_ready() is False


def test_zai_profile_targets_first_party_byok_provider(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    zai = get_connection_profile("zai")

    assert zai.connector == "byok"
    assert zai.byok_provider == "zai"
    assert zai.available is True
    assert "general api" in zai.description.lower()


def test_codex_profile_is_runtime_connector():
    codex = get_connection_profile("codex")
    assert codex.connector == "runtime"
    assert codex.runtime == "codex-sdk"
    assert codex.self_contained is True


def test_claude_is_not_a_subscription_profile_but_api_route_remains():
    assert "claude" not in connection_profile_ids(menu=CONNECT_MENU_SUBSCRIPTIONS)
    assert get_connection_profile("claude") is None
    assert "claude" not in connection_profile_ids()

    api = get_connection_profile("claude-api")
    assert api.connector == "runtime"
    assert api.runtime == "claude-agent-sdk"
    assert api.menu == CONNECT_MENU_ROOT
    assert "claude-api" not in connection_profile_ids()


def test_claude_harness_shortcut_resolves_only_to_the_api_runtime():
    from superqode.app.harness_picker import harness_connection_profile

    profile = harness_connection_profile("claude")
    assert profile.id == "claude"
    assert profile.label == "Claude Agent SDK (API key)"
    assert profile.connector == "runtime"
    assert profile.runtime == "claude-agent-sdk"


def test_kimi_and_qwen_are_first_party_acp_profiles():
    kimi = get_connection_profile("kimi-code")
    qwen = get_connection_profile("qwen-code")

    assert kimi.connector == "acp"
    assert kimi.acp_agent == "kimi"
    assert "moonshot" in kimi.description.lower()
    assert "kimi-code/install.sh" in kimi.unavailable_hint

    assert qwen.connector == "acp"
    assert qwen.acp_agent == "qwen"
    assert "qwenlm" in qwen.description.lower()
    assert "@qwen-code/qwen-code" in qwen.unavailable_hint
    # Where a vendor is headquartered tells a user nothing about whether they
    # can run it. Both are open harnesses over open weights, and that does.
    assert qwen.badges == kimi.badges == ["open harness", "open weights", "via ACP"]


def test_copilot_is_one_visible_subscription_with_sdk_and_cli_routes():
    profile = get_connection_profile("copilot")
    assert profile.label == "GitHub Copilot"
    assert profile.connector == "copilot"
    assert profile.runtime == "copilot-sdk"
    assert profile.acp_agent == "copilot"
    assert profile.self_contained is True
    assert profile.badges == ["closed harness", "multi-model", "via SDK or CLI"]
    assert "sdk" in profile.description.lower()
    assert "cli" in profile.description.lower()

    cli = get_connection_profile("copilot-cli")
    assert cli.connector == "acp"
    assert cli.acp_agent == "copilot"
    assert cli.self_contained is True
    assert cli.group == ""
    assert "@github/copilot" in cli.unavailable_hint

    visible = [profile.id for profile in list_connection_profiles()]
    assert "copilot-cli" not in visible
    # CLI aliases stay resolvable for muscle memory and remain in the ACP picker.
    assert "copilot-acp" not in visible
    acp = get_connection_profile("copilot-acp")
    assert acp.connector == "acp"
    assert acp.acp_agent == "copilot"


def test_other_harnesses_profile_opens_non_acp_harness_picker():
    profile = get_connection_profile("other-harnesses")

    assert profile.connector == "harness-picker"
    assert "tau" in profile.description.lower()
    assert profile.available is True


def test_antigravity_profile_is_signed_in_cli_runtime_connector():
    antigravity = get_connection_profile("antigravity")
    assert antigravity.connector == "runtime"
    assert antigravity.runtime == "antigravity-cli"
    assert antigravity.self_contained is True
    assert "google sign-in" in antigravity.description.lower()


def test_muse_is_an_external_cli_subscription_profile():
    """Muse Code 0.1.0 ships no ACP server, so it connects as an external CLI."""
    muse = get_connection_profile("muse")

    assert muse.connector == "external-cli"
    assert muse.transport == "CLI"
    assert muse.harness_openness == "closed"
    assert muse in list_connection_profiles(CONNECT_MENU_SUBSCRIPTIONS)


def test_muse_is_ready_only_once_it_has_a_credential(monkeypatch, tmp_path):
    """Owning the binary is not the same as being able to run it.

    Muse accepts either a stored login or META_API_KEY, so readiness needs one
    of them; the binary alone only makes the product 'present'.
    """
    import superqode.providers.connection_profiles as cp

    monkeypatch.delenv("META_API_KEY", raising=False)
    # Muse resolves its store through MUSE_AUTH_PATH and XDG_CONFIG_HOME before
    # falling back to the home directory. Leaving either set in the environment
    # sends the probe outside tmp_path, so patching Path.home alone is not
    # enough: this passes on a machine with no XDG_CONFIG_HOME and fails on CI.
    monkeypatch.delenv("MUSE_AUTH_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(
        cp.shutil, "which", lambda name: "/usr/bin/muse" if name == "muse" else None
    )
    monkeypatch.setattr(cp.Path, "home", classmethod(lambda cls: tmp_path))

    auth = tmp_path / ".config" / "muse"
    auth.mkdir(parents=True)
    auth_file = auth / "auth.json"

    # Installed, never signed in: present but not ready.
    auth_file.write_text('{"schema_version": 1, "providers": {}}', encoding="utf-8")
    assert cp._muse_product_present() is True
    assert cp._muse_cli_ready() is False

    # A stored login makes it ready.
    auth_file.write_text('{"schema_version": 1, "providers": {"meta": {}}}', encoding="utf-8")
    assert cp._muse_cli_ready() is True

    # So does an API key on its own.
    auth_file.write_text('{"schema_version": 1, "providers": {}}', encoding="utf-8")
    monkeypatch.setenv("META_API_KEY", "k")
    assert cp._muse_cli_ready() is True


def test_muse_auth_path_follows_the_same_env_the_launcher_reads(monkeypatch, tmp_path):
    """Muse resolves MUSE_AUTH_PATH, then XDG_CONFIG_HOME, then ~/.config.

    Reading only the last one reports a signed-in user as unauthenticated
    whenever they relocate their config, which is what this probe is for.
    """
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("MUSE_AUTH_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert cp._muse_auth_path() == tmp_path / ".config" / "muse" / "auth.json"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert cp._muse_auth_path() == tmp_path / "xdg" / "muse" / "auth.json"

    monkeypatch.setenv("MUSE_AUTH_PATH", str(tmp_path / "elsewhere.json"))
    assert cp._muse_auth_path() == tmp_path / "elsewhere.json"


def test_muse_signed_in_reads_the_relocated_store(monkeypatch, tmp_path):
    """A credential under XDG_CONFIG_HOME must count as signed in."""
    import superqode.providers.connection_profiles as cp

    monkeypatch.delenv("MUSE_AUTH_PATH", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    store = tmp_path / "xdg" / "muse"
    store.mkdir(parents=True)
    (store / "auth.json").write_text(
        '{"schema_version": 1, "providers": {"meta": {"mechanism": "oauth"}}}', encoding="utf-8"
    )

    assert cp._muse_signed_in() is True


def test_muse_readiness_survives_a_broken_auth_file(monkeypatch, tmp_path):
    """A corrupt or absent credential store must read as 'not signed in'."""
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp.Path, "home", classmethod(lambda cls: tmp_path))
    assert cp._muse_signed_in() is False  # file does not exist

    auth = tmp_path / ".config" / "muse"
    auth.mkdir(parents=True)
    (auth / "auth.json").write_text("not json", encoding="utf-8")
    assert cp._muse_signed_in() is False


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
    # Print/CI path only — Subscriptions must not prefer this over ACP.
    assert grok.runtime == "grok-cli"
    # Points users to the SuperQode-harness opt-in.
    assert ":grok api" in grok.description


def test_lookup_by_id_and_label():
    assert get_connection_profile("codex").id == "codex"
    assert get_connection_profile("Codex").id == "codex"
    assert get_connection_profile("nope") is None


def test_vendor_labels_are_the_product_name_alone():
    """The Subscriptions screen says what a row is, not what screen it is on.

    Six rows used to append "subscription" to the product name while nine did
    not, so the same screen read inconsistently and the longest labels were the
    ones carrying a word the heading already supplied.
    """
    labels = [profile.label for profile in list_connection_profiles(CONNECT_MENU_SUBSCRIPTIONS)]

    assert not [label for label in labels if "subscription" in label.lower()]
    assert {"Codex", "Cursor", "Amp", "Grok", "Factory Droid", "Kiro"} <= set(labels)


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

    def _open_connect_screen(self, log):
        # Every dispatch starts a fresh screen; recorded so tests can assert it.
        self.calls.append(("clear",))

    def _runtime_cmd(self, name, log):
        self.calls.append(("runtime", name))

    def _connect_acp_cmd(self, name, log):
        self.calls.append(("acp", name))

    def _connect_copilot_subscription(self, profile, log):
        from superqode.app_main import SuperQodeApp

        SuperQodeApp._connect_copilot_subscription(self, profile, log)

    def _teach(self, method, *args, **kwargs):
        # The real guard, so these tests prove a connection still lands when
        # the teaching renderers are absent.
        from superqode.app_main import SuperQodeApp

        SuperQodeApp._teach(self, method, *args, **kwargs)

    def _apply_subscription_billing_policy(self, profile, log):
        from superqode.app_main import SuperQodeApp

        SuperQodeApp._apply_subscription_billing_policy(self, profile, log)

    def run_worker(self, work, **_kwargs):
        # The connect path kicks off a background sign-in probe. Record it and
        # close the coroutine so the dispatch decision stays the assertion.
        self.calls.append(("worker",))
        if hasattr(work, "close"):
            work.close()

    async def _report_copilot_login_state(self, log):
        # Probing the vendor CLI spawns a process; the dispatch tests only care
        # that the probe was scheduled.
        self.calls.append(("login-probe",))

    def _show_dependency_install_picker(self, runtime, log):
        self.calls.append(("dependency-picker", runtime))
        return True

    def _show_byok_providers(self, log):
        self.calls.append(("byok",))

    def _connect_byok_cmd(self, args, log):
        self.calls.append(("byok-cmd", args))

    def _show_local_provider_picker(self, log):
        self.calls.append(("local",))

    def _show_agents(self, log):
        self.calls.append(("acp-picker",))

    def _begin_subscription_login(self, product, log, **kwargs):
        self.calls.append(("login", product))

    def _show_connect_type_picker(self, log, clear_log=True, menu=None):
        self.calls.append(("connect-picker", menu))

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


def test_dispatch_kimi_and_qwen_route_to_official_acp_agents(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("kimi-code"), log=None)
    _dispatch(stub, get_connection_profile("qwen-code"), log=None)

    assert ("acp", "kimi") in stub.calls
    assert ("acp", "qwen") in stub.calls


def test_dispatch_unavailable_first_party_acp_profile_shows_setup(_dispatch):
    profile = ConnectionProfile(
        id="qwen-code",
        label="Qwen Code",
        description="First-party agent",
        connector="acp",
        acp_agent="qwen",
        detect=lambda: False,
        unavailable_hint="install Qwen Code, then run `qwen auth`",
    )
    log = SimpleNamespace(messages=[])
    log.add_info = log.messages.append
    stub = _DispatchStub()

    _dispatch(stub, profile, log=log)

    assert not any(call[0] == "acp" for call in stub.calls)
    assert log.messages == ["Qwen Code needs setup: install Qwen Code, then run `qwen auth`"]


def test_dispatch_copilot_prefers_sdk_runtime(_dispatch, monkeypatch):
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp, "_copilot_sdk_ready", lambda: True)
    monkeypatch.setattr(cp, "_copilot_acp_ready", lambda: True)
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("copilot"), log=None)
    assert ("runtime", "copilot-sdk") in stub.calls


def test_dispatch_copilot_falls_back_to_installed_cli(_dispatch, monkeypatch):
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp, "_copilot_sdk_ready", lambda: False)
    monkeypatch.setattr(cp, "_copilot_acp_ready", lambda: True)
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("copilot"), log=None)
    # Subscriptions offer the vendor SDK or its plain CLI, never ACP: the ACP
    # channel is a separate connection source and listing Copilot in both
    # duplicates it.
    assert ("runtime", "copilot-cli") in stub.calls
    assert not any(call[0] == "acp" for call in stub.calls)


def test_dispatch_copilot_without_either_route_opens_safe_extra_picker(_dispatch, monkeypatch):
    import superqode.providers.connection_profiles as cp

    monkeypatch.setattr(cp, "_copilot_sdk_ready", lambda: False)
    monkeypatch.setattr(cp, "_copilot_acp_ready", lambda: False)
    stub = _DispatchStub()

    _dispatch(stub, get_connection_profile("copilot"), log=None)

    assert not any(call[0] in {"runtime", "acp"} for call in stub.calls)
    assert ("dependency-picker", "copilot-sdk") in stub.calls


def test_dispatch_copilot_acp_routes_to_agent(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("copilot-acp"), log=None)
    assert ("acp", "copilot") in stub.calls


def test_dispatch_antigravity_routes_to_cli_runtime(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("antigravity"), log=None)
    assert ("runtime", "antigravity-cli") in stub.calls


def test_dispatch_zai_routes_to_zai_provider_models(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("zai"), log=None)
    assert ("byok-cmd", "zai") in stub.calls


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
    SuperQodeApp._antigravity_cmd(stub, "managed", log=None)
    SuperQodeApp._antigravity_cmd(stub, "superqode", log=None)

    assert stub.calls == [
        ("runtime", "antigravity-cli"),
        ("runtime", "antigravity-sdk"),
        ("runtime", "antigravity-managed"),
        ("byok", "google"),
    ]


def test_antigravity_commands_control_active_cli_runtime():
    from superqode.app_main import SuperQodeApp

    class Runtime:
        name = "antigravity-cli"
        agent_name = None
        reasoning_effort = None

        def set_agent(self, value):
            self.agent_name = None if value == "auto" else value

        def set_reasoning_effort(self, value):
            self.reasoning_effort = None if value == "auto" else value

        def set_model(self, value):
            self.config.model = "" if value == "auto" else value

        config = SimpleNamespace(model="")

    class Log:
        def __init__(self):
            self.messages = []

        def add_info(self, value):
            self.messages.append(("info", value))

        def add_success(self, value):
            self.messages.append(("success", value))

        def add_error(self, value):
            self.messages.append(("error", value))

    runtime = Runtime()

    class Stub:
        def _active_antigravity_runtime(self):
            return runtime

    stub = Stub()
    log = Log()
    SuperQodeApp._antigravity_agent_cmd(stub, "reviewer", log)
    stub._pure_mode = SimpleNamespace(session=SimpleNamespace(model=""))
    stub._set_status_model = lambda model: None
    SuperQodeApp._antigravity_model_cmd(stub, "gemini-test", log)
    SuperQodeApp._antigravity_effort_cmd(stub, "high", log)

    assert runtime.agent_name == "reviewer"
    assert runtime.config.model == "gemini-test"
    assert runtime.reasoning_effort == "high"
    assert [kind for kind, _message in log.messages] == ["success", "success", "success"]


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

        def _sync_self_contained_status(self, _runtime):
            pass

        def _mark_onboarding_complete(self):
            pass

        _teach = SuperQodeApp._teach

        def run_worker(self, *_args, **_kwargs):
            raise AssertionError("Antigravity must not run Codex model resolution")

    log = Log()
    SuperQodeApp._announce_self_contained_connection(Stub(), "antigravity-cli", log)

    assert "Google Sign-In managed by agy" in log.output
    assert ":antigravity status" in log.output
    assert "Codex" not in log.output
    assert ":codex" not in log.output


def test_managed_connection_announcement_uses_managed_route_commands():
    from superqode.app_main import SuperQodeApp

    class Log:
        def __init__(self):
            self.output = ""

        def write(self, value):
            self.output += str(value)

    class Stub:
        def _sync_self_contained_status(self, _runtime):
            pass

        def _mark_onboarding_complete(self):
            pass

        _teach = SuperQodeApp._teach

    log = Log()
    SuperQodeApp._announce_self_contained_connection(Stub(), "antigravity-managed", log)

    assert ":antigravity help" in log.output
    assert ":runtime list" in log.output
    assert "local CLI diagnostics" not in log.output


def test_dispatch_grok_routes_to_grok_build_acp(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("grok"), log=None)
    assert ("acp", "grok") in stub.calls
    assert ("subscription", "grok-build") not in stub.calls


def test_dispatch_subscriptions_opens_the_submenu(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("subscriptions"), log=None)
    assert ("connect-picker", CONNECT_MENU_SUBSCRIPTIONS) in stub.calls


def test_dispatch_devin_and_glm_route_to_their_acp_agents(_dispatch, monkeypatch):
    import superqode.providers.connection_profiles as cp

    installed = {"devin", "glm-acp-agent"}
    monkeypatch.setattr(
        cp.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    stub = _DispatchStub()
    for profile_id in ("devin", "glm-cli"):
        _dispatch(stub, get_connection_profile(profile_id), log=None)

    assert [call for call in stub.calls if call[0] == "acp"] == [
        ("acp", "devin"),
        ("acp", "glm"),
    ]


def test_dispatch_local_routes_to_local_picker(_dispatch):
    stub = _DispatchStub()
    _dispatch(stub, get_connection_profile("local"), log=None)
    assert ("local",) in stub.calls


def test_connect_subcommands_route_to_specific_pickers():
    """Exact connect subcommands must not fall back to the top-level picker."""
    from superqode.app_main import SuperQodeApp

    class Stub(_DispatchStub):
        def _show_connect_type_picker(self, log, clear_log=True, menu=None):
            self.calls.append(("connect-picker", menu))

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
    assert not any(call[0] == "connect-picker" for call in stub.calls)


def test_connect_command_routes_every_profile_id_and_keeps_byok_pairs():
    """Bare profile ids dispatch; `provider model` pairs still go to BYOK."""
    from superqode.app_main import SuperQodeApp

    class Stub(_DispatchStub):
        def _show_connect_type_picker(self, log, clear_log=True, menu=None):
            self.calls.append(("connect-picker", menu))

        def _dispatch_connection_profile(self, profile, log):
            self.calls.append(("profile", profile.id))

        def _connect_byok_cmd(self, args, log):
            self.calls.append(("byok-cmd", args))

    stub = Stub()
    for command in (
        ":connect subscriptions",
        ":connect devin",
        ":connect glm-cli",
        ":connect kimi-code",
        ":connect zai",
        ":connect zai glm-4.6",
    ):
        SuperQodeApp._handle_command(stub, command, log=None)

    assert ("profile", "subscriptions") in stub.calls
    assert ("profile", "devin") in stub.calls
    assert ("profile", "glm-cli") in stub.calls
    assert ("profile", "kimi-code") in stub.calls
    assert ("profile", "zai") in stub.calls
    # A provider/model pair keeps the direct BYOK connect path.
    assert ("byok-cmd", "zai glm-4.6") in stub.calls


# --- command + completion surface --------------------------------------------


def test_connect_profiles_in_commands_and_completion():
    from superqode.app.constants import COMMANDS
    from superqode.app_main import SuperQodeApp

    assert ":connect codex" in COMMANDS
    assert ":copilot" in COMMANDS
    assert ":copilot login" in COMMANDS
    assert ":connect claude" not in COMMANDS
    assert ":connect antigravity" in COMMANDS
    assert ":connect grok" in COMMANDS
    assert ":connect zai" in COMMANDS
    assert ":grok status" in COMMANDS
    values = {c.value for c in SuperQodeApp._connect_profile_completion_candidates()}
    assert {
        "codex",
        "copilot",
        "cursor",
        "amp",
        "antigravity",
        "grok",
        "droid",
        "kiro",
        "other-harnesses",
        "byok",
        "local",
        "acp",
    } <= values
    assert "zai" not in values
    assert "copilot-acp" not in values


def test_copilot_login_starts_the_consent_gated_vendor_flow():
    from superqode.app_main import SuperQodeApp

    class Stub:
        def __init__(self):
            self.calls = []

        def _begin_subscription_login(self, product, log, **kwargs):
            self.calls.append((product, kwargs))
            return True

        def _connect_copilot_subscription(self, profile, log):
            raise AssertionError("login callback must not run before user consent")

    stub = Stub()
    SuperQodeApp._copilot_cmd(stub, "login", log=None)

    assert len(stub.calls) == 1
    product, kwargs = stub.calls[0]
    assert product == "copilot"
    assert kwargs["force"] is True
    assert callable(kwargs["on_success"])


def test_claude_subscription_is_not_a_visible_profile():
    assert get_connection_profile("claude-agent") is None
    acp_claude_profiles = [
        p for p in list_connection_profiles() if p.connector == "acp" and p.acp_agent == "claude"
    ]
    assert acp_claude_profiles == []


def test_grok_headline_profile_is_the_acp_grok_build_agent():
    """`:connect grok` is the Grok Build ACP subscription profile."""
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


def test_subscription_descriptions_state_their_real_transport():
    """A description must not imply a route the profile does not take.

    The Grok entry said "via the official CLI" while the profile actually runs
    `grok agent stdio`, which is ACP. Cursor and Kiro named the sign-in but no
    transport, which read the same way. Users pick from this text, so it has to
    match what the connector does.
    """
    from superqode.providers.connection_profiles import (
        _BROWSE_CONNECTORS,
        _SUBSCRIPTION_PROFILES,
    )

    mismatched = []
    for profile in _SUBSCRIPTION_PROFILES:
        if profile.connector in _BROWSE_CONNECTORS:
            continue  # "Browse all ACP agents" is a menu row, not a transport
        description = profile.description.lower()
        mentions_acp = "acp" in description
        presents_acp_as_transport = "over acp" in description or "via acp" in description
        goes_over_acp = profile.connector == "acp"
        if (goes_over_acp and not mentions_acp) or (
            not goes_over_acp and presents_acp_as_transport
        ):
            mismatched.append((profile.id, profile.connector, profile.description))

    assert mismatched == []


def test_copilot_description_does_not_promise_acp():
    """Copilot uses the SDK or the plain CLI, so it must not mention ACP."""
    profile = get_connection_profile("copilot")

    assert "acp" not in profile.description.lower()
    assert profile.connector == "copilot"


def test_every_way_of_choosing_lands_on_a_clean_screen():
    """Enter, a typed number and a click must all replace the list.

    Only the Enter path used to clear, so choosing a subscription by clicking
    it rendered the result underneath the list it was chosen from, and the
    previous screen's rows stayed above the new one.
    """
    from superqode.app_main import SuperQodeApp

    stub = _DispatchStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("local"), _NullLog())

    assert ("clear",) in stub.calls, "dispatch must start a fresh screen"
    assert stub.calls.index(("clear",)) < stub.calls.index(("local",))


class _NullLog:
    def add_info(self, message):
        pass

    def add_error(self, message):
        pass

    def write(self, renderable):
        pass

    def clear(self):
        pass
