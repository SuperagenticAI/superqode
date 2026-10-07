"""Composer payload fidelity, bounded previews and explicit shell staging."""

import pytest
from textual import events
from textual.widgets import Button, TextArea
from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.app.draft_recovery import DraftStore
from superqode.app.mixins.composer_blocks import MAX_BLOCK_CHARS, PREVIEW_CHARS
from superqode.widgets.composer_block_preview import ComposerBlockPreview


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


async def test_paste_folds_in_place_and_sends_exact_payload(monkeypatch):
    app = SuperQodeApp()
    sent = []
    monkeypatch.setattr(app, "_handle_message", lambda text, log: sent.append(text))
    payload = "  first\r\n" + "line\n" * 30 + "last  \n"
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "before  after"
        prompt.cursor_position = 7
        prompt.focus()
        await pilot.pause()
        app.post_message(events.Paste(payload))
        await pilot.pause()
        assert len(prompt.value) < 60
        assert prompt.value.startswith("before [Block ")
        assert prompt.value.endswith(" after")
        assert app._expand_composer_blocks(prompt.value) == "before " + payload + " after"
        await pilot.press("enter")
        await pilot.pause()
        assert sent == ["before " + payload + " after"]
        assert prompt.value == ""


async def test_small_paste_and_shell_commands_remain_literal():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.focus()
        await pilot.pause()
        app.post_message(events.Paste("small\ntext"))
        await pilot.pause()
        assert prompt.value == "small\ntext"
        prompt.value = ">echo "
        assert not app._fold_composer_paste("a" * 2500)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_preview_is_bounded_and_back_preserves_draft(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert app._stage_composer_block("x" * 100000)
        value, cursor = prompt.value, prompt.cursor_position
        app.action_preview_composer_block()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposerBlockPreview)
        assert len(screen.query_one("#block-text", TextArea).text) == PREVIEW_CHARS
        assert screen.query_one("#block-back", Button).region.bottom <= size[1]
        await pilot.click("#block-next")
        assert screen.preview_offset == PREVIEW_CHARS
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.value == value and prompt.cursor_position == cursor and prompt.has_focus


async def test_remove_block_preserves_surrounding_text():
    app = SuperQodeApp()
    async with app.run_test():
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "prefix "
        prompt.cursor_position = len(prompt.value)
        app._stage_composer_block("many\n" * 30)
        key = next(iter(app._composer_blocks))
        prompt.insert(" suffix")
        app.action_remove_composer_block(key)
        assert prompt.value == "prefix  suffix"
        assert not app._composer_blocks


async def test_shell_output_stages_only_selected_excerpt_and_does_not_send(monkeypatch):
    app = SuperQodeApp()
    sent = []
    monkeypatch.setattr(app, "_handle_message", lambda text, log: sent.append(text))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Explain this: "
        prompt.cursor_position = len(prompt.value)
        app._remember_shell_output("pytest", "  exact output\n" + "x" * 100000, 1)
        app.action_preview_shell_output()
        await pilot.pause()
        viewer = app.screen.query_one("#block-text", TextArea)
        assert len(viewer.text) == PREVIEW_CHARS
        viewer.load_text("chosen excerpt\n")
        await pilot.click("#block-use")
        await pilot.pause()
        assert not sent
        expanded = app._expand_composer_blocks(prompt.value)
        assert (
            expanded
            == "Explain this: Local shell output\nCommand: pytest\nExit code: 1\n\nchosen excerpt\n"
        )
        await pilot.press("enter")
        assert sent == [expanded]


async def test_shell_preview_does_not_stage_on_escape():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "draft"
        app._remember_shell_output("echo", "output\n", 0)
        app.action_preview_shell_output()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.value == "draft"
        assert not getattr(app, "_composer_blocks", {})


async def test_draft_restart_preserves_block_content(tmp_path):
    app = SuperQodeApp()
    app._draft_store = DraftStore(tmp_path)
    async with app.run_test():
        app._stage_composer_block(" exact\r\n" * 30)
        saved = app.query_one("#prompt-input", SelectionAwareInput).value
        app._flush_draft_recovery()
    restored = SuperQodeApp()
    restored._draft_store = DraftStore(tmp_path)
    async with restored.run_test():
        prompt = restored.query_one("#prompt-input", SelectionAwareInput)
        assert prompt.value == saved
        assert restored._expand_composer_blocks(saved) == " exact\r\n" * 30


async def test_missing_block_refuses_send_and_restores_draft(monkeypatch):
    app = SuperQodeApp()
    sent = []
    monkeypatch.setattr(app, "_handle_message", lambda text, log: sent.append(text))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "[Block 012345abcdef]"
        await pilot.press("enter")
        assert not sent
        assert prompt.value == "[Block 012345abcdef]"


async def test_oversized_block_does_not_enter_composer():
    app = SuperQodeApp()
    async with app.run_test():
        assert not app._stage_composer_block("x" * (MAX_BLOCK_CHARS + 1))
        assert not app.query_one("#prompt-input", SelectionAwareInput).value


async def test_real_local_shell_capture_preserves_whitespace(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    app = SuperQodeApp()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="  first\n", stderr="error\n", returncode=1),
    )
    async with app.run_test() as pilot:
        worker = app._run_shell("printf", app.query_one("#log", ConversationLog))
        await worker.wait()
        await pilot.pause()
        assert app._shell_output["text"] == "  first\nerror\n"
        assert app._shell_output["returncode"] == 1


async def test_folded_paste_replaces_selection():
    from textual.widgets.text_area import Selection

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "before replace after"
        prompt.selection = Selection((0, 7), (0, 14))
        payload = "exact\n" * 30
        app._stage_composer_block(payload)
        assert app._expand_composer_blocks(prompt.value) == "before " + payload + " after"
        prompt.insert("question")
        assert "question after" in prompt.value


async def test_shell_selection_stages_only_selection():
    from textual.widgets.text_area import Selection

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._remember_shell_output("echo", "prefix chosen suffix", 0)
        app.action_preview_shell_output()
        await pilot.pause()
        viewer = app.screen.query_one("#block-text", TextArea)
        viewer.selection = Selection((0, 7), (0, 13))
        await pilot.click("#block-use")
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert app._expand_composer_blocks(prompt.value).endswith("\n\nchosen")


async def test_oversized_preview_paste_is_rejected():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._remember_shell_output("echo", "original", 0)
        app.action_preview_shell_output()
        await pilot.pause()
        app.post_message(events.Paste("x" * (PREVIEW_CHARS + 1)))
        await pilot.pause()
        assert app.screen.query_one("#block-text", TextArea).text == "original"


async def test_repeated_marker_cannot_bypass_total_limit():
    app = SuperQodeApp()
    async with app.run_test():
        app._stage_composer_block("x" * MAX_BLOCK_CHARS)
        token = app.query_one("#prompt-input", SelectionAwareInput).value
        with pytest.raises(ValueError, match="Expanded message exceeds"):
            app._expand_composer_blocks(token * 3)


async def test_stage_refuses_command_draft():
    app = SuperQodeApp()
    async with app.run_test():
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = ">echo "
        assert not app._stage_composer_block("output", "Shell output")
        assert prompt.value == ">echo "


async def test_large_submitted_message_has_bounded_display_and_full_evidence():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._welcome_active = False
        log = app.query_one("#log", ConversationLog)
        text = "original line\n" * 80000
        before = len(log.lines)
        log.add_user(text)
        await pilot.pause()
        assert log._messages[-1] == ("user", text, "")
        assert len(log.lines) - before < 200
