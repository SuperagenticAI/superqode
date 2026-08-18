"""Tests for the Open/Closed harness connect catalog."""

from __future__ import annotations

from pathlib import Path

from superqode.harness.hub import _OPENNESS_BY_ID
from superqode.providers.harness_catalog import (
    CONNECT_MENU_DEFAULT,
    HARNESS_CATALOG,
    get_entry,
    list_entries,
    parse_connect_menu_flag,
)


def test_visible_open_rows_include_the_full_key_set():
    ids = [entry.id for entry in list_entries("open")]
    for required in (
        "tau",
        "deepseek-harness",
        "deepagents",
        "opencode-key",
        "prime-agent-key",
        "jcode",
        "grok-key",
        "qwen-code-key",
        "fast-agent",
        "pi",
        "goose-key",
        "cline-key",
        "openhands-key",
        "mistral-vibe-key",
        "hermes-key",
        "letta",
        "warp",
        "kimi-code-key",
    ):
        assert required in ids
    assert "deepagents-code" not in ids
    assert "gemini" not in ids
    for entry in list_entries("open"):
        assert entry.openness == "open"
        assert entry.list_visible is True


def test_closed_list_includes_factory_muse_qoder_poolside():
    ids = [entry.id for entry in list_entries("closed")]
    assert "droid-key" in ids
    assert "junie-key" in ids
    assert "muse-key" in ids
    assert "qoder-key" in ids
    assert "poolside-key" in ids
    assert "zcode" in ids
    droid_key = get_entry("droid-key")
    assert droid_key is not None
    assert droid_key.openness == "closed"
    assert droid_key.wired is True
    assert droid_key.list_visible is True
    assert droid_key.vendor_owned is True
    spec = droid_key.auth[0]
    assert spec.after_auth == "vendor-key-acp"
    assert spec.connector == "vendor-key"
    assert spec.env_vars == ("FACTORY_API_KEY",)
    assert spec.inject_env is True
    assert spec.byok_provider == "factory"
    assert spec.byok_providers == ()
    assert spec.local_providers == ()
    assert spec.detect is not None
    assert "install Factory Droid" in spec.unavailable_hint


def test_deepagents_sdk_is_open_and_deepagents_code_is_not_on_open():
    sdk = get_entry("deepagents")
    code = get_entry("deepagents-code")

    assert sdk is not None
    assert sdk.openness == "open"
    assert sdk.vendor_owned is False
    assert sdk in list_entries("open")

    assert code is not None
    assert code.openness == "open"
    assert "subscription" in code.modes()
    assert "acp" in code.modes()
    assert "open" not in code.connect_menus()
    assert code not in list_entries("open")
    assert "byok" not in code.modes()
    assert "local" not in code.modes()


def test_grok_openness_is_open_via_hub_id():
    grok = get_entry("grok")
    grok_key = get_entry("grok-key")

    assert grok is not None
    assert grok.hub_id == "grok"
    assert grok.openness == _OPENNESS_BY_ID[grok.hub_id].openness
    assert grok.openness == "open"

    assert grok_key is not None
    assert grok_key.hub_id == "grok"
    assert grok_key.openness == _OPENNESS_BY_ID[grok_key.hub_id].openness
    assert grok_key.openness == "open"


def test_droid_and_muse_openness_is_closed():
    for entry_id in ("droid", "droid-key", "muse", "muse-key", "junie", "junie-key"):
        entry = get_entry(entry_id)
        assert entry is not None
        assert entry.hub_id is not None
        assert entry.openness == _OPENNESS_BY_ID[entry.hub_id].openness
        assert entry.openness == "closed"


def test_catalog_openness_matches_hub_when_hub_id_is_set():
    for entry in HARNESS_CATALOG:
        if not entry.hub_id:
            continue
        assert entry.openness == _OPENNESS_BY_ID[entry.hub_id].openness, entry.id


def test_every_drawn_row_states_its_openness_to_the_hub_as_well():
    """A row without a `hub_id` skipped the agreement check above.

    Six visible rows had none, so `:hub` and `hub list --openness` disagreed
    with the Open and Closed lists about the same harness.
    """
    unlinked = [
        entry.id
        for entry in HARNESS_CATALOG
        if entry.list_visible and entry.openness in {"open", "closed"} and not entry.hub_id
    ]

    assert unlinked == [], f"these drawn rows tell the Hub nothing: {unlinked}"


def test_connect_menu_flag_defaults_to_v1(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPERQODE_CONNECT_MENU", raising=False)
    assert parse_connect_menu_flag(config_path=tmp_path / "missing.json") == "v1"
    assert CONNECT_MENU_DEFAULT == "v1"


def test_connect_menu_env_overrides_config(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        '{"connect_menu": "v2", "byok": {"last_provider": "keep-me"}}', encoding="utf-8"
    )
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", "v1")
    assert parse_connect_menu_flag(config_path=config) == "v1"

    monkeypatch.delenv("SUPERQODE_CONNECT_MENU", raising=False)
    assert parse_connect_menu_flag(config_path=config) == "v2"


def test_factory_subscription_implies_vendors_membership():
    droid = get_entry("droid")
    assert droid is not None
    assert "subscription" in droid.modes()
    assert "vendors" in droid.connect_menus()


def test_droid_key_is_closed_not_vendors():
    droid_key = get_entry("droid-key")
    assert droid_key is not None
    assert "vendors" not in droid_key.connect_menus()
    assert "closed" in droid_key.connect_menus()
    assert "open" not in droid_key.connect_menus()


def test_letta_and_warp_are_visible_open_setup_cards():
    letta = get_entry("letta")
    warp = get_entry("warp")
    assert letta is not None
    assert warp is not None
    assert letta in list_entries("open")
    assert warp in list_entries("open")
    assert letta.openness == warp.openness == "open"
    assert letta.license == "Apache-2.0"
    assert warp.license == "AGPL-3.0"
    assert letta.hub_id == "ecosystem:letta"
    assert warp.hub_id == "ecosystem:warp"
    assert letta.auth[0].after_auth == "setup-card"
    assert warp.auth[0].after_auth == "setup-card"
    assert "LETTA_API_KEY" in letta.auth[0].env_vars
    assert "WARP_API_KEY" in warp.auth[0].env_vars
    assert "closed" not in letta.connect_menus()
    assert "closed" not in warp.connect_menus()


def test_gemini_cli_is_not_an_open_row():
    assert get_entry("gemini") is None
    assert get_entry("gemini-cli") is None
    assert all("gemini" not in entry.id for entry in HARNESS_CATALOG)
    assert all(entry.id != "gemini" for entry in list_entries("open"))


def test_switch_and_model_allowlists_match_the_hosted_adapters():
    from superqode.providers.harness_catalog import auth_allowlist

    tau = get_entry("tau")
    dsh = get_entry("deepseek-harness")
    sdk = get_entry("deepagents")

    assert auth_allowlist(tau, "byok") is None
    assert auth_allowlist(tau, "local") is None
    assert auth_allowlist(dsh, "byok") == ("deepseek",)
    dsh_local = auth_allowlist(dsh, "local")
    assert dsh_local
    assert "anthropic" not in dsh_local
    assert "google" not in dsh_local
    assert auth_allowlist(sdk, "byok") == ("anthropic", "google")
    assert auth_allowlist(sdk, "local") == (
        "ollama",
        "lmstudio",
        "mlx",
        "llamacpp",
        "openai-compatible",
    )
    assert "deepagents-code" not in (auth_allowlist(sdk, "byok") or ())


def test_a_closed_row_reports_whether_its_cli_is_installed():
    """Qoder and Poolside claimed "ready" on any machine.

    Factory and Junie probe PATH, so the two rows without a probe were the odd
    ones out: the list said ready and the attach then failed.
    """
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_CLOSED,
        list_connection_profiles,
    )

    for entry_id in ("qoder-key", "poolside-key"):
        entry = get_entry(entry_id)
        spec = next(item for item in entry.auth if item.detect is not None)
        assert spec.unavailable_hint

    unprobed = [
        profile.id
        for profile in list_connection_profiles(CONNECT_MENU_CLOSED)
        if profile.acp_agent and profile.detect is None
    ]
    assert unprobed == []


def test_poolside_offers_the_local_endpoint_its_row_promises():
    """The row said "or a local OpenAI-compat endpoint" and could not do it.

    `vendor-key-acp` goes straight to the key card, so the declared provider
    lists were unreachable. Poolside names the variable for a standalone
    endpoint, so the local half is real and the row now uses the attach path.
    """
    from superqode.providers.harness_catalog import auth_allowlist

    entry = get_entry("poolside-key")
    spec = next(item for item in entry.auth if item.mode == "local")

    assert spec.after_auth == "acp-attach"
    assert spec.connector == "key-harness"
    assert spec.base_url_env == "POOLSIDE_STANDALONE_BASE_URL"
    assert spec.byok_provider == "poolside"
    assert auth_allowlist(entry, "byok") == ("poolside",)
    assert auth_allowlist(entry, "local")


def test_the_connect_menu_flag_is_not_reread_on_every_row(tmp_path, monkeypatch):
    """`connect_menu_version()` runs while drawing each picker row.

    An uncached read meant a stat and a JSON parse per keystroke. The cache is
    keyed by mtime and size, so editing the file still takes effect.
    """
    monkeypatch.delenv("SUPERQODE_CONNECT_MENU", raising=False)
    config = tmp_path / "config.json"
    config.write_text('{"connect_menu": "v2"}', encoding="utf-8")

    reads = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self == config:
            reads.append(1)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    for _ in range(5):
        assert parse_connect_menu_flag(config_path=config) == "v2"
    assert len(reads) == 1

    # A later edit is still picked up: the stamp changes with the contents.
    config.write_text('{"connect_menu": "v1"}', encoding="utf-8")
    assert parse_connect_menu_flag(config_path=config) == "v1"
    assert len(reads) == 2


def test_both_readers_agree_on_where_the_user_config_lives(monkeypatch, tmp_path):
    """The TUI writes this file and the flag reads it; one path, not two."""
    from superqode.app.mixins.connect import ConnectMixin
    from superqode.providers.harness_catalog import user_config_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class Stub(ConnectMixin):
        pass

    assert Stub()._user_config_path() == user_config_path()
    assert user_config_path() == tmp_path / ".superqode" / "config.json"
