"""Theme changes are cosmetic: preserve tasks while repainting every surface."""

import json
import os
import re

import pytest
from click.testing import CliRunner
from rich.console import Console
from textual.document._document import Selection
from textual.widgets import OptionList

from superqode import design_system as ds
from superqode.app import theme_bridge as bridge
from superqode.app.constants import THEME
from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.theming import ThemeError, contrast, load_theme_file, palette_tokens, resolve_colors
from superqode.theming.terminal import ColorInputFilter
from superqode.widgets.theme_picker import ThemePicker

FENCE = chr(96) * 3


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    registry = dict(ds.THEMES)
    old_terminal = dict(bridge._terminal_colors)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    # Mounted apps update these process defaults. Record even absent keys so
    # monkeypatch removes any values introduced during the test on teardown.
    for key in ("SUPERQODE_PROVIDER", "SUPERQODE_MODEL"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
        monkeypatch.delenv(key)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)
    bridge.apply_theme("superqode")
    yield
    ds.THEMES.clear()
    ds.THEMES.update(registry)
    bridge._terminal_colors.clear()
    bridge._terminal_colors.update(old_terminal)
    bridge.apply_theme("superqode")


def custom_file(tmp_path, **changes):
    data = {
        "version": 1,
        "name": "trial-theme",
        "appearance": "dark",
        "colors": {"bg_void": "#161821"},
        "tokens": {"error": "#e95678"},
    }
    data.update(changes)
    path = tmp_path / "palette.json"
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize(
    "value, expected",
    [
        ("#abc", "#aabbcc"),
        (196, "#ff0000"),
        ("okhsl(0 0% 0%)", "#000000"),
        ("okhsl(0 0% 100%)", "#ffffff"),
        ("oklch(100% 0 0)", "#ffffff"),
        ("alias", "#123456"),
    ],
)
def test_color_forms(value, expected):
    assert (
        resolve_colors({"text": value}, {"alias": "base", "base": "#123456"}, "dark")["text"]
        == expected
    )


@pytest.mark.parametrize("value", [True, 256, -1, "missing", "okhsl(nan 20% 40%)", "#nope"])
def test_bad_colors_are_actionable_errors(value):
    with pytest.raises(ThemeError):
        resolve_colors({"text": value}, {}, "dark")


def test_variable_cycles_are_rejected():
    with pytest.raises(ThemeError, match="Circular"):
        resolve_colors({"text": "a"}, {"a": "b", "b": "a"}, "dark")


def test_unused_variable_cycle_is_rejected_when_loading(tmp_path):
    with pytest.raises(ThemeError, match="Circular"):
        load_theme_file(custom_file(tmp_path, vars={"a": "b", "b": "a"}))


def test_legacy_palette_aliases_update_without_mutating_presets():
    from superqode.design_system import COLORS
    from superqode.widgets.split_view import COLORS as file_colors

    original = ds.get_theme("superqode").colors.text_secondary
    assert bridge.apply_theme("light")
    assert COLORS is file_colors
    assert file_colors.text_secondary == THEME["text"]
    assert file_colors.text_dim == THEME["dim"]
    assert ds.get_theme("superqode").colors.text_secondary == original


def test_css_conversion_preserves_selectors_and_pseudo_classes():
    from superqode.theming.css import theme_css

    css = "#acp-token:focus, #a2a-headers:focus { color: #a1a1aa; background: #000000; }"
    converted = theme_css(css)
    assert converted.startswith("#acp-token:focus, #a2a-headers:focus {")
    assert "color: $sq-muted; background: $sq-bg;" in converted


@pytest.mark.parametrize(
    "changes", [{"version": 2}, {"unknown": 1}, {"colors": {"typo": "#fff"}}, {"description": []}]
)
def test_native_schema_rejects_invalid_documents(tmp_path, changes):
    with pytest.raises(ThemeError):
        load_theme_file(custom_file(tmp_path, **changes))


def test_import_roundtrip_and_collision(tmp_path):
    path = custom_file(tmp_path)
    name = bridge.import_theme(path)
    imported = load_theme_file(bridge.theme_directory() / f"{name}.json")
    assert imported.tokens["error"] == "#e95678"
    assert bridge.apply_theme(name)
    with pytest.raises(ThemeError, match="already exists"):
        bridge.import_theme(path)


def test_invalid_config_is_never_destroyed():
    bridge._CONFIG_PATH.write_text("{broken")
    assert bridge.save_theme("light")
    assert bridge._CONFIG_PATH.read_text() == "{broken"


def test_failed_atomic_replace_keeps_existing_settings(monkeypatch):
    bridge._CONFIG_PATH.write_text('{"other": "keep", "theme": "nord"}')
    import superqode.theming as theming

    monkeypatch.setattr(
        theming.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    assert "disk full" in bridge.save_theme("light")
    assert json.loads(bridge._CONFIG_PATH.read_text()) == {"other": "keep", "theme": "nord"}
    assert list(bridge._CONFIG_PATH.parent.iterdir()) == [bridge._CONFIG_PATH]


@pytest.mark.parametrize("name", bridge.theme_names())
def test_every_preset_has_readable_instruction_and_status_text(name):
    palette = palette_tokens(ds.get_theme(name))
    for role in ("text", "muted", "dim", "success", "warning", "error", "syntax_comment"):
        for surface in ("bg", "surface", "surface2", "code_bg", "tool_error_bg"):
            assert contrast(palette[role], palette[surface]) >= 4.5, (name, role, surface)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_switch_repaints_retained_output_without_changing_task_state(size):
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.reset_conversation()
        app._welcome_active = False
        log.add_user("review this")
        log.add_error("Earlier failure")
        log.add_assistant(f"{FENCE}python\nprint('hello')\n{FENCE}")
        log._session_tool_calls.append({"name": "bash", "status": "success", "output": "evidence"})
        for index in range(40):
            log.add_info(f"retained line {index}")
        log._streaming_response = "response in progress"
        log._streamed_offset = 8
        log._set_viewport_mode("user_locked")
        log.scroll_to(y=3, animate=False, force=True)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft\nnext task"
        prompt.selection = Selection((0, 1), (0, 4))
        queue = ["queued task"]
        app._typeahead_queue = queue
        app._queue_paused = True
        await pilot.pause()
        before = ([line.text for line in log.lines], list(log._messages), log.scroll_y)
        old_error = THEME["error"]
        assert app._apply_and_persist_theme("light")
        await pilot.pause()
        assert app.screen.styles.background.hex.lower() == THEME["bg"]
        assert app.current_theme.dark is False
        assert "-light-mode" in app.classes and "-dark-mode" not in app.classes
        assert log.styles.background.hex.lower() == THEME["bg"]
        assert [line.text for line in log.lines] == before[0]
        assert log._messages == before[1]
        assert log.scroll_y == before[2]
        assert log.viewport_mode == "user_locked"
        assert log._streaming_response == "response in progress"
        assert log._streamed_offset == 8
        assert log._session_tool_calls[0]["output"] == "evidence"
        assert prompt.value == "draft\nnext task"
        assert prompt.selection == Selection((0, 1), (0, 4))
        assert app._typeahead_queue is queue
        assert app._queue_paused
        from superqode.app.theme_bridge import recolor_strip

        failure = next(line for line in log.lines if "Earlier failure" in line.text)
        colors = {
            segment.style.color.name
            for segment in recolor_strip(failure)
            if segment.style and segment.style.color
        }
        assert THEME["error"] in colors and old_error not in colors


@pytest.mark.parametrize("source", ["tail", "feedback"])
@pytest.mark.parametrize("lock", ["public", "mode"])
async def test_pending_follow_scroll_respects_new_reading_lock(monkeypatch, source, lock):
    from rich.text import Text

    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.reset_conversation()
        for index in range(40):
            log.add_info(f"retained line {index}")
        await pilot.pause()
        callbacks = []

        def defer(callback, *args, **kwargs):
            callbacks.append(lambda: callback(*args, **kwargs))
            return True

        monkeypatch.setattr(log, "call_after_refresh", defer)
        if source == "tail":
            log.scroll_end(animate=False)
        else:
            log.write_feedback(Text("Feedback heading"))
        assert callbacks
        if lock == "public":
            log.lock_viewport()
        else:
            log._set_viewport_mode("user_locked")
        log.scroll_to(y=3, animate=False, force=True, immediate=True)
        assert log.scroll_y == 3
        for callback in callbacks:
            callback()
        assert log.scroll_y == 3
        assert log.viewport_mode == "user_locked"


async def test_preview_search_cancel_and_apply_are_isolated():
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        original = dict(THEME)
        app.push_screen(ThemePicker(current="superqode"))
        await pilot.pause()
        picker = app.screen
        options = picker.query_one("#theme-list", OptionList)
        options.highlighted = picker._names.index("ayu-light")
        await pilot.pause()
        assert THEME == original
        assert not bridge._CONFIG_PATH.exists()
        assert (
            picker.query_one("#theme-preview").styles.background.hex.lower()
            == palette_tokens(ds.get_theme("ayu-light"))["bg"]
        )
        assert picker.query_one(".hints").region.bottom <= picker.region.bottom
        await pilot.press("escape")
        assert THEME == original


async def test_hot_reload_invalid_and_deleted_files_keep_the_last_good_palette(tmp_path):
    name = bridge.import_theme(custom_file(tmp_path))
    app = SuperQodeApp(theme_selection=name)
    async with app.run_test() as pilot:
        app._poll_theme_file()
        path = bridge.theme_directory() / f"{name}.json"
        data = json.loads(path.read_text())
        data["colors"]["bg_void"] = "#181a22"
        path.write_text(json.dumps(data))
        app._poll_theme_file()
        await pilot.pause()
        assert THEME["bg"] == "#181a22"
        path.write_text("{partial")
        app._poll_theme_file()
        assert THEME["bg"] == "#181a22"
        path.unlink()
        app._poll_theme_file()
        assert THEME["bg"] == "#181a22"


def test_cli_theme_creation_validation_and_temporary_override(tmp_path, monkeypatch):
    from superqode.main import cli_main

    runner = CliRunner()
    path = tmp_path / "theme.json"
    assert runner.invoke(cli_main, ["theme", "init", str(path)]).exit_code == 0
    checked = runner.invoke(cli_main, ["theme", "check", str(path), "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["valid"]
    startup = []
    monkeypatch.setattr("superqode.app.run_textual_app", lambda **kw: startup.append(kw))
    result = runner.invoke(cli_main, ["--theme", "light"])
    assert result.exit_code == 0, result.output
    assert startup[0]["theme_selection"] == "light"
    assert not bridge._CONFIG_PATH.exists()


@pytest.mark.parametrize("flag", ["--theme", "--use-theme"])
def test_explicit_tui_launcher_retains_global_startup_options(monkeypatch, flag):
    from superqode.main import cli_main

    startup = []
    monkeypatch.setattr("superqode.app.run_textual_app", lambda **kw: startup.append(kw))
    result = CliRunner().invoke(cli_main, [flag, "light", "--approval-mode", "deny", "tui"])
    assert result.exit_code == 0, result.output
    assert startup == [{"theme_selection": "light", "approval_mode": "deny"}]
    assert not bridge._CONFIG_PATH.exists()


def test_html_export_and_syntax_follow_palette():
    from superqode.rendering.html_export import render_transcript_html
    from superqode.rendering.markdown import render_agent_markdown

    bridge.apply_theme("light")
    document = render_transcript_html([("error", "failure", "")])
    assert "background:" + THEME["export_bg"] in document
    assert f"color:{THEME['error']}" in document
    console = Console(width=80, color_system="truecolor", force_terminal=True)
    segments = list(
        console.render(render_agent_markdown(f"{FENCE}python\nreturn 'value'\n{FENCE}"))
    )
    assert any(
        segment.style and segment.style.meta.get("sq_fg") == "syntax_keyword"
        for segment in segments
    )


@pytest.mark.parametrize("name", ["ayu-mirage", "halcyon-rivet", "light"])
def test_exported_inline_code_remains_readable(name):
    from superqode.rendering.html_export import render_transcript_html

    palette = palette_tokens(ds.get_theme(name))
    document = render_transcript_html(
        [("assistant", "Use " + chr(96) + "name" + chr(96), "")], palette=palette
    )
    background = re.search(r"\.msg code \{[^}]*background:([^;]+)", document)[1]
    foreground = re.search(r"\.msg code \{[^}]*color:([^;]+)", document)[1]
    assert contrast(foreground, background) >= 4.5


@pytest.mark.parametrize("split", range(1, 31))
def test_fragmented_osc_replies_do_not_become_keystrokes(split):
    response = "\x1b]11;rgb:ffff/0000/8080\x1b\\"
    seen = []
    framing = ColorInputFilter(seen.append)
    output = framing.feed("a" + response[:split]) + framing.feed(response[split:] + "b")
    assert output == "ab"
    assert seen == [{"bg": "#ff0080"}]


def test_bracketed_paste_preserves_literal_colour_sequences():
    data = "\x1b[200~code \x1b]11;rgb:ffff/0000/0000\x07\x1b[201~"
    seen = []
    framing = ColorInputFilter(seen.append)
    assert "".join(framing.feed(char) for char in data) == data
    assert not seen


@pytest.mark.parametrize("split", range(3, 29))
def test_delayed_color_fragments_survive_the_escape_key_timeout(monkeypatch, split):
    from superqode.theming import terminal

    now = [1.0]
    monkeypatch.setattr(terminal.time, "monotonic", lambda: now[0])
    response = "\x1b]11;rgb:ffff/0000/8080\x1b\\"
    seen = []
    framing = ColorInputFilter(seen.append)
    output = framing.feed(response[:split])
    now[0] += 2.0
    output += framing.tick() + framing.feed(response[split:] + "draft")
    assert output == "draft"
    assert seen == [{"bg": "#ff0080"}]


@pytest.mark.parametrize("keys", ["\x03", "\x15", "\r", "draft", "\x1b[A"])
@pytest.mark.parametrize("prefix", ["\x1b]1", "\x1b]10", "\x1b]4", "\x1b]11;rgb:ff"])
def test_truncated_color_reply_cannot_swallow_normal_keys(keys, prefix):
    framing = ColorInputFilter(lambda _: None)
    assert framing.feed(prefix) == ""
    assert framing.feed(keys) == keys


@pytest.mark.parametrize("keys", ["draft", "face code", "debug this"])
def test_typing_one_byte_at_a_time_recovers_from_a_truncated_report(keys):
    framing = ColorInputFilter(lambda _: None)
    assert framing.feed("\x1b]11;rgb:ff") == ""
    assert "".join(framing.feed(char) for char in keys) == keys


def test_fresh_color_reply_and_paste_recover_from_an_unfinished_report():
    seen = []
    framing = ColorInputFilter(seen.append)
    assert framing.feed("\x1b]11;rgb:ff") == ""
    assert framing.feed("\x1b]11;rgb:aa/bb/cc\x07draft") == "draft"
    assert seen == [{"bg": "#aabbcc"}]
    assert framing.feed("\x1b]11;rgb:ff") == ""
    paste = "\x1b[200~literal \x1b]11;rgb:aa/bb/cc\x07\x1b[201~"
    assert framing.feed(paste) == paste
    assert seen == [{"bg": "#aabbcc"}]


def test_color_framing_retains_escape_key_timeout_and_normalizes_ansi_indices(monkeypatch):
    from superqode.theming import terminal

    now = [1.0]
    monkeypatch.setattr(terminal.time, "monotonic", lambda: now[0])
    seen = []
    framing = ColorInputFilter(seen.append)
    assert framing.feed("\x1b") == ""
    now[0] += 0.2
    assert framing.tick() == "\x1b"
    assert framing.feed("\x1b]4;01;rgb:ff/00/00\x07") == ""
    assert seen == [{"1": "#ff0000"}]


@pytest.mark.parametrize(
    "name", __import__("superqode.theming.library", fromlist=["catalog"]).catalog()["themes"]
)
def test_every_offline_palette_validates_and_is_readable(name):
    from superqode.theming.library import library_theme

    theme = library_theme(name)
    assert theme.name == name
    palette = palette_tokens(theme)
    for role in ("text", "muted", "dim", "success", "error", "warning", "syntax_keyword"):
        for surface in ("bg", "surface", "surface2", "code_bg", "tool_error_bg"):
            assert contrast(palette[role], palette[surface]) >= 4.5


def test_offline_catalog_install_all_is_repeatable_and_preserves_selection():
    from superqode.main import cli_main
    from superqode.theming.library import catalog, theme_rows

    runner = CliRunner()
    assert len(theme_rows()) == 83
    assert len(theme_rows("Awesome Pi")) == 71
    assert {row["name"] for row in theme_rows("light")} >= {"light", "ayu-light"}
    result = runner.invoke(cli_main, ["theme", "browse", "alien", "--json"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["themes"][0]
    assert row["name"] == "alien-candy" and not row["installed"]
    assert row["license"] == "MIT" and catalog()["revision"] in row["url"]
    assert not bridge.theme_directory().exists()
    bridge.save_theme("light")
    config = bridge._CONFIG_PATH.read_bytes()
    result = runner.invoke(cli_main, ["theme", "install", "--all"])
    assert result.exit_code == 0, result.output
    assert all(row["installed"] for row in theme_rows())
    files = {path.name: path.read_bytes() for path in bridge.theme_directory().glob("*.json")}
    assert len(files) == 69
    assert bridge._CONFIG_PATH.read_bytes() == config
    result = runner.invoke(cli_main, ["theme", "install", "--all"])
    assert result.exit_code == 0, result.output
    assert {
        path.name: path.read_bytes() for path in bridge.theme_directory().glob("*.json")
    } == files
    assert bridge._CONFIG_PATH.read_bytes() == config
    assert runner.invoke(cli_main, ["theme", "install"]).exit_code == 2
    assert runner.invoke(cli_main, ["theme", "install", "../bad"]).exit_code == 1
    assert runner.invoke(cli_main, ["theme", "install", "alien-candy", "--all"]).exit_code == 2


def test_catalog_conflicts_and_atomic_import_do_not_overwrite(tmp_path, monkeypatch):
    from superqode.theming.library import install_theme
    from superqode.theming import atomic_json

    path = custom_file(tmp_path, name="alien-candy")
    bridge.import_theme(path)
    destination = bridge.theme_directory() / "alien-candy.json"
    original = destination.read_bytes()
    with pytest.raises(ThemeError, match="different colors"):
        install_theme("alien-candy")
    assert destination.read_bytes() == original
    with pytest.raises(FileExistsError):
        atomic_json(destination, {"overwrite": "never"}, overwrite=False)
    assert destination.read_bytes() == original
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_gallery_search_preview_install_and_restart(size):
    from textual.widgets import Input
    from superqode.theming.library import library_theme

    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my coding draft"
        log = app.query_one("#log", ConversationLog)
        before = dict(THEME)
        app._handle_theme("browse", log)
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ThemePicker)
        assert picker.query_one("#theme-list", OptionList).option_count == 83
        await pilot.click("#theme-installed")
        assert picker.query_one("#theme-list", OptionList).option_count == 14
        await pilot.click("#theme-all")
        picker.query_one("#theme-search", Input).value = "alien-candy"
        await pilot.pause()
        assert picker._selected_name() == "alien-candy"
        assert THEME == before and not bridge.theme_directory().exists()
        preview = picker.query_one("#theme-preview")
        assert (
            preview.styles.background.hex.lower()
            == palette_tokens(library_theme("alien-candy"))["bg"]
        )
        assert len(preview.lines) <= preview.content_size.height
        assert picker.query_one(".hints").region.bottom <= picker.region.bottom
        picker.query_one("#theme-search", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app._current_theme == "alien-candy"
        assert prompt.value == "Keep my coding draft"
        assert (bridge.theme_directory() / "alien-candy.json").is_file()
        assert bridge.load_saved_theme() == "alien-candy"
        assert json.loads(bridge._CONFIG_PATH.read_text())["theme"] == "alien-candy"


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_bare_import_dialog_preview_error_retry_apply_and_cancel(tmp_path, size):
    from textual.widgets import Button, Input
    from superqode.widgets.theme_picker import ThemeImportDialog

    path = custom_file(tmp_path)
    spaced = tmp_path / "palette with spaces.json"
    path.rename(spaced)
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Preserve this draft"
        log = app.query_one("#log", ConversationLog)
        before = dict(THEME)
        app._handle_theme("import", log)
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ThemeImportDialog)
        await pilot.press("enter")
        assert "path first" in str(dialog.query_one("#import-status").render())
        entry = dialog.query_one("#import-path", Input)
        entry.value = str(tmp_path / "missing.json")
        await pilot.pause()
        assert dialog.query_one("#import-confirm", Button).disabled
        entry.value = str(spaced)
        await pilot.pause()
        assert not dialog.query_one("#import-confirm", Button).disabled
        assert THEME == before and not bridge.theme_directory().exists()
        assert (
            len(dialog.query_one("#import-preview").lines)
            <= dialog.query_one("#import-preview").content_size.height
        )
        assert dialog.query_one(".hints").region.bottom <= dialog.region.bottom
        await pilot.press("escape")
        assert THEME == before and not bridge.theme_directory().exists()
        app._handle_theme("import", log)
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#import-path", Input).value = str(spaced)
        await pilot.pause()
        # Revalidate on submission: an external edit must not import stale preview data.
        spaced.write_text("{broken")
        await pilot.press("enter")
        assert isinstance(app.screen, ThemeImportDialog)
        assert not bridge.theme_directory().exists()
        spaced.write_text(
            json.dumps({"version": 1, "name": "trial-theme", "colors": {"bg_void": "#161821"}})
        )
        await pilot.click("#import-confirm")
        await pilot.pause()
        assert app._current_theme == "trial-theme"
        assert prompt.value == "Preserve this draft"
        assert bridge.load_saved_theme() == "trial-theme"
        app._handle_theme("import", log)
        await pilot.pause()
        app.screen.query_one("#import-path", Input).value = str(spaced)
        await pilot.pause()
        assert app.screen.query_one("#import-confirm", Button).disabled
        assert "already exists" in str(app.screen.query_one("#import-status").render())
        await pilot.press("escape")


async def test_nested_import_cancel_and_gallery_no_matches_are_safe(tmp_path):
    from textual.widgets import Input
    from superqode.widgets.theme_picker import ThemeImportDialog

    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        picker = app.screen
        await pilot.click("#theme-import")
        await pilot.pause()
        assert isinstance(app.screen, ThemeImportDialog)
        await pilot.press("escape")
        assert app.screen is picker
        picker.query_one("#theme-search", Input).value = "no matching palette xyz"
        await pilot.pause()
        picker.query_one("#theme-search", Input).focus()
        await pilot.press("enter")
        assert app.screen is picker
        assert not bridge.theme_directory().exists()
        await pilot.press("escape")
        assert app._current_theme == "superqode"


async def test_direct_catalog_selection_and_install_error_preserve_state(tmp_path, monkeypatch):
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft"
        app._handle_theme("install alien-candy", log)
        await pilot.pause()
        assert app._current_theme == "alien-candy"
        app._handle_theme("cosmic-lagoon", log)
        await pilot.pause()
        assert app._current_theme == "cosmic-lagoon"
        original = dict(THEME)
        monkeypatch.setattr(
            bridge,
            "atomic_json",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError("read-only themes directory")),
        )
        app._handle_theme("install amethyst-drift", log)
        await pilot.pause()
        assert app._current_theme == "cosmic-lagoon" and THEME == original
        assert prompt.value == "draft"
        assert "amethyst-drift" not in ds.THEMES
        assert any("read-only themes directory" in line.text for line in log.lines)
        app._handle_theme("help", log)
        app._handle_theme("draculla", log)
        assert any("Did you mean: dracula" in line.text for line in log.lines)


def test_import_rejects_non_regular_files(tmp_path):
    with pytest.raises(ThemeError, match="regular JSON file"):
        load_theme_file(tmp_path)
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "palette.json"
        os.mkfifo(fifo)
        with pytest.raises(ThemeError, match="regular JSON file"):
            load_theme_file(fifo)


async def test_command_dispatch_nested_import_and_keyboard_browsing(tmp_path):
    from textual.widgets import Input
    from superqode.widgets.theme_picker import ThemeImportDialog

    path = custom_file(tmp_path)
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._handle_command(":theme import", log)
        await pilot.pause()
        assert isinstance(app.screen, ThemeImportDialog)
        await pilot.press("escape")
        app._handle_command(":theme browse", log)
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-search", Input).focus()
        picker.query_one("#theme-search", Input).value = "alien"
        await pilot.pause()
        await pilot.press("down")
        assert picker.query_one("#theme-list", OptionList).has_focus
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, ThemeImportDialog)
        app.screen.query_one("#import-path", Input).value = str(path)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is app.default_screen
        assert app._current_theme == "trial-theme"
        assert bridge.load_saved_theme() == "trial-theme"
        assert {item.value for item in app._theme_completion_candidates()} >= {
            "browse",
            "import",
            "install",
            "help",
        }


async def test_theme_timer_does_not_repaint_during_shutdown(tmp_path, monkeypatch):
    from superqode.widgets.command_palette import CommandPalette

    bridge.import_theme(custom_file(tmp_path))
    app = SuperQodeApp(theme_selection="trial-theme")
    async with app.run_test(size=(80, 24)):

        def unexpected_repaint(*args):
            raise AssertionError("Theme repaint touched dismantled widgets")

        monkeypatch.setattr(CommandPalette, "refresh_theme_colors", unexpected_repaint)
        app._theme_file_signature = None
        app._running = False
        try:
            app._poll_theme_file()
            app._refresh_theme_view()
        finally:
            app._running = True


async def test_tui_install_all_runs_cli_and_discoverable_themes(tmp_path, monkeypatch):
    import asyncio
    import subprocess
    from superqode.theming.library import theme_rows

    # Use the real CLI subprocess with its settings redirected to the fixture.
    # This avoids touching the developer's ~/.superqode directory.
    shim = tmp_path / "isolated_theme_cli.py"
    shim.write_text(
        "from pathlib import Path\n"
        "from superqode.app import theme_bridge\n"
        f"theme_bridge._CONFIG_PATH = Path({str(bridge._CONFIG_PATH)!r})\n"
        "from superqode.main import cli_main\n"
        "cli_main()\n"
    )
    run = subprocess.run

    def isolated_run(command, **kwargs):
        if command[1:3] == ["-m", "superqode.main"]:
            command = [command[0], str(shim), *command[3:]]
        return run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", isolated_run)
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        bridge.save_theme("light")
        saved = bridge._CONFIG_PATH.read_bytes()
        log = app.query_one("#log", ConversationLog)
        app._handle_command(":theme install --all", log)
        workers = [worker for worker in app.workers if worker.name == "_superqode_cli_cmd"]
        assert len(workers) == 1
        await asyncio.wait_for(app.workers.wait_for_complete(workers), timeout=10)
        await pilot.pause()
        assert any("Theme installation completed" in line.text for line in log.lines)
        assert bridge._CONFIG_PATH.read_bytes() == saved
        assert app._current_theme == "superqode"
        app._handle_command(":theme", log)
        await pilot.pause()
        assert all(row["installed"] for row in theme_rows())
        assert app.screen.query_one("#theme-list", OptionList).option_count == 83
        await pilot.press("escape")


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_every_catalog_theme_repaints_mounted_session(size):
    from superqode.theming.library import catalog, install_theme

    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Developer draft"
        prompt.selection = Selection((0, 1), (0, 5))
        log = app.query_one("#log", ConversationLog)
        log.reset_conversation()
        app._welcome_active = False
        log.add_assistant("Review this diff and code.")
        await pilot.pause()
        before = [line.text for line in log.lines]
        for name in catalog()["themes"]:
            install_theme(name)
            assert app._apply_and_persist_theme(name)
            await pilot.pause()
            assert app.screen.styles.background.hex.lower() == THEME["bg"]
            assert prompt.value == "Developer draft"
            assert prompt.selection == Selection((0, 1), (0, 5))
            assert [line.text for line in log.lines] == before
        assert bridge.load_saved_theme() == catalog()["themes"][-1]


async def test_picker_applies_edited_catalog_theme_without_reinstalling():
    from superqode.theming.library import install_theme

    install_theme("alien-candy")
    path = bridge.theme_directory() / "alien-candy.json"
    data = json.loads(path.read_text())
    data["tokens"]["error"] = "#ef6789"
    path.write_text(json.dumps(data))
    assert not bridge.discover_themes()
    modified = path.read_bytes()
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        picker = app.screen
        picker.query_one("#theme-list", OptionList).highlighted = picker._names.index("alien-candy")
        await pilot.press("enter")
        await pilot.pause()
        assert app._current_theme == "alien-candy"
        assert path.read_bytes() == modified
        assert bridge.load_saved_theme() == "alien-candy"


def test_catalog_description_edit_is_not_a_color_conflict():
    from superqode.theming.library import install_theme

    install_theme("alien-candy")
    path = bridge.theme_directory() / "alien-candy.json"
    data = json.loads(path.read_text())
    data["description"] = "My own description"
    path.write_text(json.dumps(data))
    assert not bridge.discover_themes()
    modified = path.read_bytes()
    assert install_theme("alien-candy") == "alien-candy"
    assert path.read_bytes() == modified


def test_deep_config_cannot_crash_a_theme_save():
    original = '{"other":' + "[" * 4000 + "0" + "]" * 4000 + "}"
    bridge._CONFIG_PATH.write_text(original)
    assert bridge.load_saved_theme() == "superqode"
    assert bridge.save_theme("light")
    assert bridge._CONFIG_PATH.read_text() == original


@pytest.mark.parametrize(
    "background", ["#707070", "#717171", "#727272", "#737373", "#747474", "#757575", "#808080"]
)
def test_system_theme_supports_gray_terminal_backgrounds(background):
    from superqode.theming import system_theme

    palette = palette_tokens(system_theme({"bg": background, "fg": "#eeeeee"}))
    assert palette["bg"] == background
    for surface in ("bg", "surface", "surface2", "hover", "active", "code_bg"):
        assert contrast(palette["text"], palette[surface]) >= 4.5


async def test_appearance_pair_picker_highlights_the_active_palette():
    bridge.set_terminal_colors({"bg": "#ffffff", "fg": "#111111"})
    app = SuperQodeApp(theme_selection="light/tokyonight")
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert app.screen._selected_name() == "light"
        await pilot.press("escape")
        assert app._current_theme == "light/tokyonight"


async def test_auto_preview_tracks_terminal_appearance_changes():
    import asyncio

    from superqode.theming.terminal import TerminalColorReply

    bridge.set_terminal_colors({"bg": "#101010", "fg": "#eeeeee"})
    app = SuperQodeApp(theme_selection="auto")
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_theme("", app.query_one("#log", ConversationLog))
        await pilot.pause()
        picker = app.screen
        app.on_terminal_color_reply(TerminalColorReply({"bg": "#ffffff", "fg": "#111111"}))
        async with asyncio.timeout(5):
            while app._terminal_theme_refresh_timer is not None:
                await pilot.pause(0.01)
        await pilot.pause()
        preview = picker.query_one("#theme-preview")
        assert preview.styles.background.hex.lower() == palette_tokens(ds.get_theme("auto"))["bg"]
        assert app._current_theme == "auto"
        await pilot.press("escape")


def test_named_startup_theme_takes_priority_over_a_same_named_project_file(tmp_path):
    (tmp_path / "light").write_text("This is a project file, not a palette")
    app = SuperQodeApp(theme_selection="light")
    assert app._current_theme == "light"
    assert THEME["bg"] == palette_tokens(ds.get_theme("light"))["bg"]


async def test_symlinked_user_theme_hot_reload_and_explicit_startup(tmp_path):
    path = custom_file(tmp_path)
    directory = bridge.theme_directory()
    directory.mkdir()
    link = directory / "linked-theme.json"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("Creating file symlinks is unavailable on this host")
    assert not bridge.discover_themes()
    app = SuperQodeApp(theme_selection=str(path))
    async with app.run_test(size=(80, 24)) as pilot:
        app._poll_theme_file()
        data = json.loads(path.read_text())
        data["colors"]["bg_void"] = "#242631"
        path.write_text(json.dumps(data))
        app._poll_theme_file()
        await pilot.pause()
        assert THEME["bg"] == "#242631"
        assert not bridge.discover_themes()
        # Repointing the link remains a user-file update, rather than a duplicate.
        replacement = tmp_path / "replacement.json"
        previous_stat = path.stat()
        data["colors"]["bg_void"] = "#202532"
        replacement.write_text(json.dumps(data))
        os.utime(replacement, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
        assert replacement.stat().st_size == previous_stat.st_size
        link.unlink()
        link.symlink_to(replacement)
        app._poll_theme_file()
        await pilot.pause()
        assert THEME["bg"] == "#202532"
        assert not bridge.discover_themes()


async def test_theme_directory_symlink_preserves_live_edits(tmp_path):
    directory = tmp_path / "dotfiles-themes"
    directory.mkdir()
    path = custom_file(directory)
    try:
        bridge.theme_directory().symlink_to(directory, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable on this host")
    assert not bridge.discover_themes()
    app = SuperQodeApp(theme_selection="trial-theme")
    async with app.run_test(size=(80, 24)) as pilot:
        app._poll_theme_file()
        data = json.loads(path.read_text())
        data["colors"]["bg_void"] = "#202532"
        path.write_text(json.dumps(data))
        app._poll_theme_file()
        await pilot.pause()
        assert THEME["bg"] == "#202532"
        assert not bridge.discover_themes()


async def test_builtin_theme_is_not_watched_when_launched_from_theme_directory(monkeypatch):
    directory = bridge.theme_directory()
    directory.mkdir()
    monkeypatch.chdir(directory)
    app = SuperQodeApp(theme_selection="superqode")
    async with app.run_test(size=(80, 24)):
        notices = []
        monkeypatch.setattr(app, "notify", lambda *args, **kwargs: notices.append(args))
        app._poll_theme_file()
        assert not notices
        assert app._theme_file_signature is None


def test_saving_a_project_theme_installs_a_copy_for_the_next_launch(tmp_path):
    path = custom_file(tmp_path)
    original = path.read_bytes()
    name = bridge.load_project_theme(path)
    assert not bridge.theme_directory().exists()
    assert not bridge.save_theme(f"light/{name}")
    assert path.read_bytes() == original
    installed = bridge.theme_directory() / f"{name}.json"
    assert installed.is_file()
    ds.THEMES.pop(name)
    assert bridge.load_saved_theme() == f"light/{name}"
    assert ds.THEMES[name].source == str(installed.absolute())


def test_saving_a_project_theme_does_not_overwrite_a_destination_collision(tmp_path):
    name = bridge.load_project_theme(custom_file(tmp_path))
    bridge.theme_directory().mkdir()
    installed = bridge.theme_directory() / f"{name}.json"
    installed.write_text("Keep this existing file")
    bridge._CONFIG_PATH.write_text(json.dumps({"theme": "light", "other": "keep"}))
    original = bridge._CONFIG_PATH.read_bytes()
    assert bridge.save_theme(name)
    assert installed.read_text() == "Keep this existing file"
    assert bridge._CONFIG_PATH.read_bytes() == original


def test_preferences_refuse_non_regular_and_oversized_files(tmp_path):
    if hasattr(os, "mkfifo"):
        os.mkfifo(bridge._CONFIG_PATH)
        assert bridge.load_saved_theme() == "superqode"
        assert "regular" in bridge.save_theme("light")
        bridge._CONFIG_PATH.unlink()
    bridge._CONFIG_PATH.write_bytes(b" " * (bridge.MAX_CONFIG_BYTES + 1))
    assert bridge.load_saved_theme() == "superqode"
    assert "1 MiB" in bridge.save_theme("light")
    assert bridge._CONFIG_PATH.stat().st_size == bridge.MAX_CONFIG_BYTES + 1


async def test_overlong_json_integer_is_an_inline_import_error(tmp_path):
    from textual.widgets import Input
    from superqode.main import cli_main

    path = tmp_path / "large-number.json"
    path.write_text(
        '{"version":1,"name":"large-number","colors":{"text_primary":' + "1" * 5000 + "}}"
    )
    with pytest.raises(ThemeError, match="Cannot read theme"):
        load_theme_file(path)
    checked = CliRunner().invoke(cli_main, ["theme", "check", str(path), "--json"])
    assert checked.exit_code == 1
    assert "Cannot read theme" in checked.output
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_command(":theme import", app.query_one("#log", ConversationLog))
        await pilot.pause()
        app.screen.query_one("#import-path", Input).value = str(path)
        await pilot.pause()
        assert app.screen.query_one("#import-confirm").disabled
        assert "Cannot read theme" in str(app.screen.query_one("#import-status").render())
        await pilot.press("escape")
