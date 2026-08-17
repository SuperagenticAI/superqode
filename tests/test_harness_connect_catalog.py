"""Tests for the Open/Closed harness connect catalog."""

from __future__ import annotations

from superqode.harness.hub import _OPENNESS_BY_ID
from superqode.providers.harness_catalog import (
    CONNECT_MENU_DEFAULT,
    HARNESS_CATALOG,
    get_entry,
    list_entries,
    parse_connect_menu_flag,
)


def test_tau_dsh_deepagents_are_the_only_visible_open_rows():
    ids = [entry.id for entry in list_entries("open")]
    assert ids == ["tau", "deepseek-harness", "deepagents"]
    for entry in list_entries("open"):
        assert entry.openness == "open"
        assert entry.list_visible is True
        assert entry.wired is True


def test_closed_list_is_empty():
    assert list_entries("closed") == []


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
    for entry_id in ("droid", "droid-key", "muse", "muse-key"):
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


def test_gemini_cli_is_not_an_open_row():
    assert get_entry("gemini") is None
    assert get_entry("gemini-cli") is None
    assert all("gemini" not in entry.id for entry in HARNESS_CATALOG)
    assert all(entry.id != "gemini" for entry in list_entries("open"))
