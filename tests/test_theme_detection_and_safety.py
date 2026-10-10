"""Terminal detection, colour depth, catalog appearance and file-safety checks."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from superqode import design_system as ds
from superqode import theming
from superqode.app.colormode import color_mode, configure_textual_colors, sgr_foreground
from superqode.theming import (
    ThemeError,
    atomic_json,
    colorfgbg_appearance,
    contrast,
    palette_tokens,
    readability_adjustments,
    terminal_appearance,
)
from superqode.theming.library import catalog, catalog_appearance, library_theme, theme_rows
from superqode.theming.terminal import ColorInputFilter, query_sequence, tmux_wrap


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15;0", "dark"),
        ("0;15", "light"),
        ("0;7", "light"),
        ("15;8", "dark"),
        ("0;default;15", "light"),
        ("default;default", None),
        ("", None),
        ("0;255", None),
    ],
)
def test_colorfgbg_follows_xterm_convention(value, expected):
    assert colorfgbg_appearance(value) == expected


def test_osc11_background_wins_and_source_is_recorded(monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")
    assert terminal_appearance({"bg": "#fdf6e3"}) == "light"
    assert theming.DETECTION_SOURCE == "osc11"
    assert terminal_appearance({"scheme": "light"}) == "light"
    assert theming.DETECTION_SOURCE == "color-scheme-report"
    assert terminal_appearance({}) == "dark"
    assert theming.DETECTION_SOURCE == "colorfgbg"
    monkeypatch.delenv("COLORFGBG")
    monkeypatch.delenv("SUPERQODE_TERMINAL_BACKGROUND", raising=False)
    assert terminal_appearance({}) == "dark"
    assert theming.DETECTION_SOURCE == "default"


def test_system_theme_uses_reported_background():
    assert theming.system_theme({"bg": "#ffffff", "fg": "#111111"}).appearance == "light"
    assert theming.system_theme({"bg": "#101010"}).appearance == "dark"


def test_scheme_reports_are_consumed_not_typed():
    seen = []
    framing = ColorInputFilter(seen.append)
    assert framing.feed("a\x1b[?997;2nb") == "ab"
    assert seen == [{"scheme": "light"}]
    framing.feed("\x1b[?997;1n")
    assert seen[-1] == {"scheme": "dark"}


def test_tmux_queries_use_passthrough_and_direct():
    wrapped = tmux_wrap("\x1b]11;?\x07")
    assert wrapped == "\x1bPtmux;\x1b\x1b]11;?\x07\x1b\\"
    both = query_sequence({"TMUX": "/tmp/tmux-1/default,1,0"})
    assert both.startswith("\x1b]10;?") and "\x1bPtmux;" in both
    assert "\x1bPtmux;" not in query_sequence({})


@pytest.mark.parametrize(
    ("environ", "mode"),
    [
        ({"TERM": "dumb"}, "none"),
        ({"TERM": "xterm-256color", "NO_COLOR": "1"}, "none"),
        ({"TERM": "xterm-256color", "NO_COLOR": ""}, "256"),
        ({"TERM": "xterm-256color"}, "256"),
        ({"TERM": "screen-256color", "TMUX": "x"}, "256"),
        ({"TERM": "xterm", "COLORTERM": "truecolor"}, "truecolor"),
        ({"TERM": "xterm-256color", "WT_SESSION": "1"}, "truecolor"),
        ({"TERM": "vt100"}, "standard"),
    ],
)
def test_color_mode(environ, mode):
    assert color_mode(environ) == mode


def test_configure_textual_colors_respects_overrides():
    env = {"TERM": "xterm-256color"}
    assert configure_textual_colors(env) == "256" and env["TEXTUAL_COLOR_SYSTEM"] == "256"
    env = {"TERM": "xterm-256color", "TEXTUAL_COLOR_SYSTEM": "truecolor"}
    configure_textual_colors(env)
    assert env["TEXTUAL_COLOR_SYSTEM"] == "truecolor"
    env = {"TERM": "dumb"}
    configure_textual_colors(env)
    assert env["NO_COLOR"] == "1"


def test_sgr_fallbacks():
    assert sgr_foreground("#a855f7", "truecolor") == "\x1b[38;2;168;85;247m"
    assert sgr_foreground("#a855f7", "256") == "\x1b[38;5;135m"
    assert sgr_foreground("#a855f7", "none") == ""
    assert sgr_foreground("#000000", "standard") == "\x1b[37m"


def test_catalog_records_appearance_and_rows_use_it():
    recorded = catalog()["appearances"]
    assert set(recorded) == set(catalog()["themes"])
    for name in catalog()["themes"][:5]:
        assert catalog_appearance(name) == library_theme(name).appearance


def test_bundled_light_palettes_are_readable():
    from superqode.app import theme_bridge  # noqa: F401 - loads bundled themes

    light = [row["name"] for row in theme_rows() if row["appearance"] == "light"]
    for name in ("paper-light", "solar-dawn", "nordic-snow", "sakura-light"):
        assert name in light
        theme = ds.THEMES[name]
        tokens = palette_tokens(theme)
        surfaces = [tokens[key] for key in ("bg", "surface", "surface2", "code_bg")]
        for role in ("text", "muted", "success", "error", "warning", "diff_add", "diff_remove"):
            assert min(contrast(tokens[role], bg) for bg in surfaces) >= 4.5, (name, role)
        assert tokens["diff_add"] != tokens["diff_remove"]


def test_library_theme_returns_private_copies():
    name = catalog()["themes"][0]
    first = library_theme(name)
    original = first.colors.bg_void
    first.colors.bg_void = "#123456"
    first.tokens["text"] = "#654321"
    first.source = "mutated"
    second = library_theme(name)
    assert second.colors.bg_void == original
    assert second.tokens.get("text") != "#654321"
    assert second.source != "mutated"
    assert second is not first


def test_customizer_does_not_mutate_its_base():
    from superqode.theming.customizer import customize_theme

    base = library_theme(catalog()["themes"][0])
    before = json.dumps(theming.native_document(base), sort_keys=True)
    customize_theme(
        base, "my-edit", accent="#ff0000", background="#101010", surface="#202020", text="#eeeeee"
    )
    assert json.dumps(theming.native_document(base), sort_keys=True) == before


def test_readability_adjustments_reports_lifted_roles():
    theme = ds.THEMES["dracula"]
    assert "dim" in readability_adjustments(theme)
    assert readability_adjustments(ds.THEMES["superqode"]) is not None


def test_no_overwrite_export_falls_back_without_hard_links(tmp_path, monkeypatch):
    def no_link(*_args):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_link)
    target = tmp_path / "out.json"
    atomic_json(target, {"a": 1}, overwrite=False)
    assert json.loads(target.read_text()) == {"a": 1}
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        atomic_json(target, {"a": 2}, overwrite=False)
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_no_overwrite_export_refuses_existing_with_links(tmp_path):
    target = tmp_path / "out.json"
    target.write_text("keep")
    with pytest.raises(FileExistsError):
        atomic_json(target, {"a": 2}, overwrite=False)
    assert target.read_text() == "keep"


def test_new_users_default_to_auto(tmp_path, monkeypatch):
    from superqode.app import theme_bridge

    config = tmp_path / "config.json"
    monkeypatch.setattr(theme_bridge, "_CONFIG_PATH", config)
    assert theme_bridge.load_saved_theme() == "auto"
    config.write_text(json.dumps({"theme": "dracula"}))
    assert theme_bridge.load_saved_theme() == "dracula"


def test_no_internal_event_mentions_in_tracked_files():
    import subprocess

    root = Path(__file__).parents[1]
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git checkout required")
    word = "hack" + "athon"
    hits = []
    # CI workflow files and the test module they reference keep their legacy names.
    allowed = {
        ".github/workflows/ci.yml",
        ".github/workflows/publish.yml",
        "tests/test_tui_" + word + "_journey.py",
    }
    for name in tracked:
        if name in allowed:
            continue
        file = root / name
        if word in name.lower():
            hits.append(name)
        elif file.is_file() and file.suffix not in {".png", ".jpg", ".gif", ".ico", ".svg"}:
            try:
                if word in file.read_text(encoding="utf-8").lower():
                    hits.append(name)
            except (UnicodeDecodeError, OSError):
                pass
    assert hits == []


def test_invalid_theme_still_rejected():
    with pytest.raises(ThemeError):
        theming.theme_from_document({"name": "superqode"})
