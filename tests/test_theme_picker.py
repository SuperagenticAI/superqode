"""Tests for the live theme bridge and HTML transcript export."""

import json

from superqode import design_system as ds
from superqode.app import theme_bridge
from superqode.app.constants import THEME
from superqode.rendering.html_export import render_transcript_html


def _reset_default():
    theme_bridge.apply_theme("superqode")


def test_apply_theme_syncs_palette_onto_constants_live():
    _reset_default()
    default_purple = THEME["purple"]

    assert theme_bridge.apply_theme("tokyonight") is True
    # THEME is mutated in place to the design-system theme's accent.
    assert THEME["purple"] == ds.get_theme("tokyonight").colors.primary_bright
    assert THEME["purple"] != default_purple

    assert theme_bridge.apply_theme("superqode") is True
    assert THEME["purple"] == default_purple
    _reset_default()


def test_apply_unknown_theme_is_noop():
    _reset_default()
    before = dict(THEME)
    assert theme_bridge.apply_theme("does-not-exist") is False
    assert dict(THEME) == before


def test_theme_names_cover_all_design_system_themes():
    names = theme_bridge.theme_names()
    assert "superqode" in names
    assert "tokyonight" in names
    assert set(names) == set(dict(ds.list_themes()))


def test_save_and_load_theme_roundtrip(tmp_path, monkeypatch):
    cfg = tmp_path / ".superqode" / "config.json"
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", cfg)

    theme_bridge.save_theme("dracula")
    assert json.loads(cfg.read_text())["theme"] == "dracula"
    assert theme_bridge.load_saved_theme() == "dracula"


def test_save_theme_preserves_other_config_keys(tmp_path, monkeypatch):
    cfg = tmp_path / ".superqode" / "config.json"
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", cfg)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"other": "keep-me"}))

    theme_bridge.save_theme("nord")
    data = json.loads(cfg.read_text())
    assert data["theme"] == "nord"
    assert data["other"] == "keep-me"


def test_save_theme_ignores_unknown_names(tmp_path, monkeypatch):
    cfg = tmp_path / ".superqode" / "config.json"
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", cfg)
    theme_bridge.save_theme("bogus")
    assert not cfg.exists()


def test_load_theme_defaults_when_missing(tmp_path, monkeypatch):
    cfg = tmp_path / ".superqode" / "config.json"
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", cfg)
    assert theme_bridge.load_saved_theme() == ds.get_active_theme_name()


# ----- HTML export -----------------------------------------------------------


def test_html_export_renders_roles_and_markdown():
    messages = [
        ("user", "Fix the bug in app.py", ""),
        (
            "agent",
            "Fixed the **bug** in `app.py`.\n\n```python\nx = 1\n```\n\n- step one\n- step two",
            "Claude",
        ),
        ("info", "this should be skipped", ""),
    ]
    html_doc = render_transcript_html(messages, title="My Session")

    assert "<!DOCTYPE html>" in html_doc
    assert "My Session" in html_doc
    # Agent messages get lightweight markdown; user text stays verbatim.
    assert "<strong>bug</strong>" in html_doc
    assert "<code>app.py</code>" in html_doc
    assert "<pre><code>x = 1</code></pre>" in html_doc
    assert "<li>step one</li>" in html_doc
    assert "Claude" in html_doc
    # Transient info chatter is not exported.
    assert "this should be skipped" not in html_doc


def test_html_export_escapes_html_in_user_text():
    messages = [("user", "<script>alert('x')</script>", "")]
    html_doc = render_transcript_html(messages)
    assert "<script>" not in html_doc
    assert "&lt;script&gt;" in html_doc


def test_html_export_handles_empty_transcript():
    html_doc = render_transcript_html([])
    assert "Empty transcript" in html_doc
