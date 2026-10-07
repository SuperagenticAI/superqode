"""Composer image payloads, editable OS dictation, and real overlay interaction."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from textual.containers import Vertical
from textual import events
from textual.widgets import Input, Static

from superqode.acp.client import ACPClient
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.app.constants import THEME
from superqode.app.inputs import SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp
from superqode.image_input import MAX_IMAGE_BYTES, image_message, load_image
from superqode.providers.gateway.base import GatewayResponse, StreamChunk
from superqode.tools.base import ToolRegistry
from superqode.widgets.command_palette import CommandPalette
from superqode.widgets.file_reference import expand_file_references
from superqode.widgets.history_search import HistorySearchModal

# A real 1x1 PNG, so transport tests exercise bytes rather than mocked attachment objects.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII="
)


@pytest.fixture
def screenshot(tmp_path):
    path = tmp_path / "screen shot.png"
    path.write_bytes(PNG)
    return path


@pytest.fixture(autouse=True)
def isolate_startup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    from superqode.history import HistoryManager

    monkeypatch.setattr(
        "superqode.app_main.HistoryManager",
        lambda: HistoryManager(history_file=tmp_path / "history.jsonl"),
    )
    for name in (
        "_prewarm_litellm",
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda self: None)


def test_image_payload_and_text_reference_exclusion(screenshot, tmp_path):
    image = load_image(screenshot)
    assert image.mime_type == "image/png"
    assert base64.b64decode(image.data) == PNG
    parts = image_message("Review this UI", [image])
    assert parts[0] == {"type": "text", "text": "Review this UI"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    plain_path = tmp_path / "screen.png"
    plain_path.write_bytes(PNG)
    assert expand_file_references("Explain @screen.png", tmp_path)[1] == []


def test_image_validation_rejects_invalid_and_large_files(tmp_path):
    path = tmp_path / "invalid.png"
    path.write_bytes(b"this is text")
    with pytest.raises(ValueError, match="recognized"):
        load_image(path)
    path.write_bytes(PNG + b"x" * MAX_IMAGE_BYTES)
    with pytest.raises(ValueError, match="4 MB"):
        load_image(path)


async def test_image_symlink_loop_reports_error_and_keeps_draft(tmp_path):
    path = tmp_path / "loop.png"
    path.symlink_to(path.name)
    with pytest.raises(ValueError, match="Cannot resolve image path"):
        load_image(path)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my draft"
        log = app.query_one("#log", ConversationLog)
        assert not app._stage_image_attachment(path, log)
        await pilot.pause()
        assert prompt.value == "Keep my draft"
        assert not app._staged_images
        assert "Cannot resolve image path" in "\n".join(line.text for line in log.lines)


async def test_paste_command_unknown_home_reports_error_without_clearing_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my draft"
        log = app.query_one("#log", ConversationLog)
        app._handle_paste_image("~superqode_missing_test_user_490a/screen.png", log)
        await pilot.pause()
        assert prompt.value == "Keep my draft"
        assert "Cannot resolve image path" in "\n".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_attachment_limit_and_clear_keep_draft(tmp_path):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Compare these screens"
        for index in range(5):
            path = tmp_path / f"screen-{index}.png"
            path.write_bytes(PNG)
            assert app._stage_image_attachment(path, log) is (index < 4)
        assert len(app._staged_images) == 4
        app._attach_cmd("clear", log)
        await pilot.pause()
        assert not app._staged_images
        assert prompt.value == "Compare these screens"


@pytest.mark.asyncio
async def test_acp_image_capability_and_wire_payload(screenshot, tmp_path):
    client = ACPClient(project_root=tmp_path, command="test-agent")
    client._call_method = AsyncMock(return_value={"stopReason": "end_turn"})
    image = load_image(screenshot)
    with pytest.raises(ValueError, match="advertise image"):
        await client.send_prompt("Review", images=[image])
    client._call_method.assert_not_called()
    client._agent_capabilities = {"promptCapabilities": {"image": True}}
    await client.send_prompt("Review", images=[image])
    blocks = client._call_method.call_args.kwargs["prompt"]
    assert blocks == [{"type": "text", "text": "Review"}, image.acp_part()]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_builtin_sends_images_to_gateway(screenshot, tmp_path, streaming):
    seen = []

    async def stream_completion(**kwargs):
        seen.extend(kwargs["messages"])
        yield StreamChunk(content="Reviewed")

    async def chat_completion(**kwargs):
        seen.extend(kwargs["messages"])
        return GatewayResponse(content="Reviewed")

    gateway = SimpleNamespace(stream_completion=stream_completion, chat_completion=chat_completion)
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.empty(),
        config=AgentConfig(
            provider="test",
            model="vision",
            working_directory=tmp_path,
            enable_session_storage=False,
        ),
    )
    loop._ensure_context_window = AsyncMock()
    image = load_image(screenshot)
    if streaming:
        assert [chunk async for chunk in loop.run_streaming("Review", images=[image])] == [
            "Reviewed"
        ]
    else:
        assert (await loop.run("Review", images=[image])).content == "Reviewed"
    user = next(message for message in seen if message.role == "user")
    assert user.content == image_message("Review", [image])


@pytest.mark.asyncio
async def test_attachment_click_removes_image_without_losing_draft(screenshot):
    app = SuperQodeApp()
    async with app.run_test(size=(70, 30)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Review the layout\nand spacing"
        log = app.query_one("#log", ConversationLog)
        assert app._stage_image_attachment(screenshot, log)
        await pilot.pause()
        assert prompt.value == "Review the layout\nand spacing"
        bar = app.query_one("#attachment-bar", Static)
        assert bar.display
        assert "screen shot.png" in bar.render().plain
        await pilot.click("#attachment-bar", offset=(20, 0))
        await pilot.pause()
        assert not app._staged_images
        assert not app._attached_refs
        assert prompt.value == "Review the layout\nand spacing"
        assert not bar.display


@pytest.mark.asyncio
async def test_image_failure_preserves_draft_and_attachments(screenshot):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._stage_image_attachment(screenshot, log)
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, model="text-only"), _agent=object()
        )
        app._model_supports_vision = lambda model: False
        app._handle_message("Review this screenshot", log)
        await pilot.pause()
        assert app._staged_images
        assert prompt.value == "Review this screenshot"
        assert not app.is_busy
        app._pure_mode = None


def terminal_path(path, form):
    import shlex

    if form == "single_quote":
        return shlex.quote(str(path))
    if form == "double_quote":
        return f'"{path}"'
    if form == "escaped":
        return str(path).replace(" ", "\\ ")
    if form == "uri":
        return path.as_uri()
    return str(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["plain", "single_quote", "double_quote", "escaped", "uri"])
async def test_real_composer_paste_stages_image_without_inserting_path(
    screenshot, monkeypatch, form
):
    app = SuperQodeApp()
    deliveries = []
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.load_text("Review the layout\nand spacing")
        prompt.focus()
        app.post_message(events.Paste(terminal_path(screenshot, form)))
        await pilot.pause()
        assert prompt.value == "Review the layout\nand spacing"
        assert len(app._staged_images) == 1
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, model="vision"), _agent=object()
        )
        monkeypatch.setattr(
            app,
            "_send_to_pure_mode",
            lambda text, log: deliveries.append((text, list(app._current_images))),
        )
        await pilot.press("enter")
        assert deliveries[0][0] == "Review the layout\nand spacing"
        assert deliveries[0][1][0].path == screenshot.resolve()
        assert not app._staged_images
        app.is_busy = False
        app._pure_mode = None


@pytest.mark.asyncio
async def test_submitted_absolute_image_path_is_attachment_not_slash_command(
    screenshot, monkeypatch
):
    app = SuperQodeApp()
    commands = []
    monkeypatch.setattr(app, "_handle_command", lambda text, log: commands.append(text))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.load_text(str(screenshot))
        prompt.focus()
        await pilot.press("enter")
        assert not commands
        assert len(app._staged_images) == 1
        assert not prompt.value
        assert not app.is_busy
        assert "Add a prompt" in app.query_one("#log", ConversationLog).get_all_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["single_quote", "double_quote", "escaped", "uri"])
async def test_text_with_terminal_image_path_sends_multimodal_prompt(screenshot, monkeypatch, form):
    app = SuperQodeApp()
    deliveries = []
    async with app.run_test() as pilot:
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, model="vision"), _agent=object()
        )
        monkeypatch.setattr(
            app,
            "_send_to_pure_mode",
            lambda text, log: deliveries.append((text, list(app._current_images))),
        )
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.load_text(f"Review this\n{terminal_path(screenshot, form)}\nKeep the spacing")
        prompt.focus()
        await pilot.press("enter")
        assert deliveries[0][0] == "Review this\n\nKeep the spacing"
        assert deliveries[0][1][0].path == screenshot.resolve()
        assert not prompt.value
        app.is_busy = False
        app._pure_mode = None


@pytest.mark.asyncio
async def test_missing_image_path_restores_draft_and_keeps_slash_commands_working(
    tmp_path, monkeypatch
):
    app = SuperQodeApp()
    commands = []
    monkeypatch.setattr(app, "_handle_command", lambda text, log: commands.append(text))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        path = str(tmp_path / "missing.jpg")
        prompt.load_text(path)
        prompt.focus()
        await pilot.press("enter")
        assert not commands
        assert prompt.value == path
        assert "Cannot read image" in app.query_one("#log", ConversationLog).get_all_text()
        prompt.value = "/help"
        await pilot.press("enter")
        assert commands == ["/help"]


@pytest.mark.asyncio
async def test_normal_multiline_paste_is_inserted_exactly_once():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Existing "
        prompt.cursor_position = len(prompt.value)
        prompt.focus()
        app.post_message(events.Paste("dictated words\nmore text"))
        await pilot.pause()
        assert prompt.value == "Existing dictated words\nmore text"


@pytest.mark.asyncio
async def test_bare_absolute_image_path_and_text_reach_direct_chat_gateway(tmp_path, monkeypatch):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    path = tmp_path / "header.png"
    path.write_bytes(PNG)
    seen = []

    async def completion(self, **kwargs):
        seen.extend(kwargs["messages"])
        yield StreamChunk(content="Reviewed the header")

    monkeypatch.setattr(LiteLLMGateway, "stream_completion", completion)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, provider="google", model="vision"),
            _agent=object(),
        )
        app._chat_mode = True
        monkeypatch.setattr(app, "_direct_chat_status", lambda: (True, "", "google/vision"))
        workers = []
        start = app._chat_worker
        monkeypatch.setattr(app, "_chat_worker", lambda text, log: workers.append(start(text, log)))
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = f"Review the header {path}"
        prompt.focus()
        await pilot.press("enter")
        await workers[0].wait()
        assert seen[0].content[0] == {"type": "text", "text": "Review the header"}
        assert seen[0].content[1]["type"] == "image_url"
        assert not app.is_busy
        assert "Reviewed the header" in app.query_one("#log", ConversationLog).get_all_text()
        app._pure_mode = None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_direct_chat_image_transport_and_retry(screenshot, monkeypatch, failure):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    seen = []

    async def completion(self, **kwargs):
        seen.extend(kwargs["messages"])
        if failure:
            raise ValueError("Vision unavailable")
        yield StreamChunk(content="Reviewed")

    monkeypatch.setattr(LiteLLMGateway, "stream_completion", completion)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        app._stage_image_attachment(screenshot, log)
        app._pure_mode = SimpleNamespace(session=SimpleNamespace(provider="test", model="vision"))
        images = list(app._staged_images.values())
        app._consume_image_input(images)
        app._last_user_message = "Review screenshot"
        prompt.value = ""
        await app._send_chat_message("Review screenshot", log)
        await pilot.pause()
        assert seen[0].content == image_message("Review screenshot", images)
        assert bool(app._staged_images) == failure
        if failure:
            assert prompt.value == "Review screenshot"
            assert app._chat_history == []
        app._pure_mode = None


@pytest.mark.asyncio
async def test_dictation_guidance_preserves_editable_draft_and_vim_insert(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Existing draft "
        monkeypatch.setattr(app, "_vim_enabled", lambda: True)
        app._set_vim_state("normal")
        app.action_voice_input()
        await pilot.pause()
        assert app._vim_input_mode == "insert"
        assert not prompt.read_only
        assert prompt.value == "Existing draft "
        assert app.focused is prompt
        assert app.query_one("#dictation-guide").display
        await pilot.press("h", "i")
        assert "hi" in prompt.value
        app._handle_command(":voice off", app.query_one("#log", ConversationLog))
        assert not app.query_one("#dictation-guide").display


@pytest.mark.asyncio
async def test_inline_image_mention_reaches_connected_coding_worker(
    screenshot, tmp_path, monkeypatch
):
    path = tmp_path / "screen.png"
    path.write_bytes(PNG)
    app = SuperQodeApp()
    deliveries = []
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True, model="vision"), _agent=object()
        )
        monkeypatch.setattr(
            app,
            "_send_to_pure_mode",
            lambda text, log: deliveries.append((text, list(app._current_images))),
        )
        app._handle_message("Review @screen.png\nKeep the spacing", log)
        await pilot.pause()
        assert deliveries[0][1][0].path == path.resolve()
        assert "\nKeep the spacing" in deliveries[0][0]
        assert not app._staged_images
        assert not app._current_file_context
        app.is_busy = False
        app._pure_mode = None


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 20), (80, 24)])
async def test_palette_keyboard_dispatch_cancel_and_layout(size, monkeypatch):
    app = SuperQodeApp()
    calls = []
    monkeypatch.setattr(app, "_handle_command", lambda command, log: calls.append(command))
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my draft"
        await pilot.press("ctrl+k")
        await pilot.pause()
        palette = app.query_one(CommandPalette)
        assert palette.is_visible
        assert palette.region.right <= size[0]
        assert palette.region.bottom <= size[1]
        search = palette.query_one("#palette-search", Input)
        search.value = "Explore Capabilities"
        await pilot.pause()
        assert app.focused is search
        await pilot.press("enter")
        await pilot.pause()
        assert calls == [":explore"]
        assert prompt.value == "Keep my draft"
        assert app.focused is prompt
        await pilot.press("ctrl+k", "escape")
        await pilot.pause()
        assert not palette.is_visible
        assert app.focused is prompt


def test_all_palette_entries_have_unique_executable_definitions():
    entries = SuperQodeApp()._build_palette_commands()
    assert len({entry.id for entry in entries}) == len(entries)
    assert all(entry.command or entry.action or entry.id == "sidebar" for entry in entries)


@pytest.mark.asyncio
async def test_history_fuzzy_multiline_selection_and_narrow_layout():
    app = SuperQodeApp()
    results = []
    original = "Review the UI\n" + "padding " * 15 + "fix authentication"
    async with app.run_test(size=(40, 20)) as pilot:
        modal = HistorySearchModal(entries=[original, "unrelated"])
        app.push_screen(modal, callback=results.append)
        await pilot.pause()
        box = modal.query_one(Vertical)
        assert box.region.right <= 40
        assert box.region.bottom <= 20
        search = modal.query_one(Input)
        search.value = "fxauth"
        await pilot.pause()
        assert modal._filtered_entries[0][0] == original
        assert "authentication" in modal._build_options("authentication")[0].prompt.plain
        await pilot.press("enter")
        await pilot.pause()
        assert results == [original]


@pytest.mark.asyncio
async def test_overlay_colors_follow_theme_tokens(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+k")
        palette = app.query_one(CommandPalette)
        monkeypatch.setitem(THEME, "purple", "#f3abff")
        monkeypatch.setitem(THEME, "surface2", "#17131d")
        palette.refresh_theme_colors()
        assert palette.styles.border_top[1].hex.lower() == "#f3abff"
        assert palette.query_one(Input).styles.border_top[1].hex.lower() == "#f3abff"
        palette.hide()
        modal = HistorySearchModal(entries=["Review image"])
        app.push_screen(modal)
        await pilot.pause()
        assert modal.query_one(Vertical).styles.background.hex.lower() == "#17131d"
        assert modal.query_one(Vertical).styles.border_top[1].hex.lower() == "#f3abff"
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_empty_history_search_keeps_modal_and_escape_restores_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Unsent draft"
        modal = HistorySearchModal(entries=["Review image"])
        app.push_screen(modal)
        await pilot.pause()
        modal.query_one(Input).value = "zzzzzz"
        await pilot.pause()
        await pilot.press("enter")
        assert app.screen is modal
        await pilot.press("escape")
        app._ensure_input_focus()
        await pilot.pause()
        assert prompt.value == "Unsent draft"
        assert app.focused is prompt


@pytest.mark.asyncio
async def test_coding_worker_restores_images_after_provider_rejection(screenshot, tmp_path):
    from superqode.pure_mode import PureMode

    async def rejected(**kwargs):
        raise ValueError("Provider rejected image input")
        yield  # Make this an async iterator like the real gateway.

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        pure = PureMode()
        pure.session.connected = True
        pure.session.provider = "test"
        pure.session.model = "vision"
        pure._agent = AgentLoop(
            gateway=SimpleNamespace(stream_completion=rejected),
            tools=ToolRegistry.empty(),
            config=AgentConfig(
                provider="test",
                model="vision",
                working_directory=tmp_path,
                enable_session_storage=False,
            ),
        )
        pure._agent._ensure_context_window = AsyncMock()
        app._pure_mode = pure
        log = app.query_one("#log", ConversationLog)
        app._stage_image_attachment(screenshot, log)
        app._consume_image_input(list(app._staged_images.values()))
        app._last_user_message = "Review screenshot"
        app.is_busy = True
        await app._send_to_pure_mode("Review screenshot", log).wait()
        await pilot.pause()
        assert app._staged_images
        assert app.query_one("#prompt-input", SelectionAwareInput).value == "Review screenshot"
        assert not app.is_busy
        app._pure_mode = None


async def _pipy_image_mode(tmp_path, monkeypatch, seen):
    """Real kernel/backend/PiPy loop with an offline provider boundary."""
    from superqode.pure_mode import PureMode
    from superqode.harness.kernel import HarnessKernel
    from superqode.harness.store import MemoryHarnessStore
    from superqode.harness.templates import pipy_template
    from superqode.harness.backends.pipy import PiPyHarnessBackend
    from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter
    from superqode.pipy import CodingSessionOptions, PiPyCodingSession, Model
    from superqode.pipy.ai import FakeStream, text_response
    from superqode.pipy.ai.gateway import _gateway_messages

    async def stream(model, context, options):
        seen.extend(_gateway_messages(context.system_prompt, context.messages))
        return FakeStream([text_response("Image reviewed")])(model, context, options)

    async def factory(request, cwd, path):
        return await PiPyCodingSession.create(
            CodingSessionOptions(
                cwd=cwd,
                model=Model(id="vision", provider="fixture"),
                stream_fn=stream,
                session_root=tmp_path / "sessions",
            )
        )

    monkeypatch.setattr("superqode.harness.pipy_adapter._record_session_path", lambda *a: None)
    adapter = PiPyHarnessProtocolAdapter(session_factory=factory)
    monkeypatch.setattr(
        "superqode.harness.kernel.create_harness_backend",
        lambda *a: PiPyHarnessBackend(adapter=adapter),
    )
    pure = PureMode()
    pure._harness_spec = pipy_template()
    pure._harness_session = await HarnessKernel(
        pure._harness_spec, store=MemoryHarnessStore()
    ).session()
    pure.session.connected = True
    pure.session.provider = "fixture"
    pure.session.model = "vision"
    pure.session.working_directory = tmp_path
    return pure


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_pipy_harness_images_reach_provider_without_metadata_copy(
    screenshot, tmp_path, monkeypatch, streaming
):
    seen = []
    pure = await _pipy_image_mode(tmp_path, monkeypatch, seen)
    image = load_image(screenshot)
    if streaming:
        text = "".join([chunk async for chunk in pure.run_streaming("Review", images=[image])])
    else:
        text = (await pure.run("Review", images=[image])).content
    assert text == "Image reviewed"
    user = next(message for message in seen if message.role == "user")
    assert user.content == image_message("Review", [image])
    store = pure._harness_session.kernel.store
    runs = store.list_runs()
    assert all("images" not in run.metadata for run in runs)


@pytest.mark.asyncio
async def test_pipy_composer_paste_sends_image_through_real_harness(
    screenshot, tmp_path, monkeypatch
):
    seen = []
    pure = await _pipy_image_mode(tmp_path, monkeypatch, seen)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._pure_mode = pure
        app._model_supports_vision = lambda model: True
        log = app.query_one("#log", ConversationLog)
        app._handle_paste_image(str(screenshot), log)
        assert app._prepare_image_input(log)[0].path == screenshot.resolve()
        deliveries = []
        send = app._send_to_pure_mode
        monkeypatch.setattr(
            app, "_send_to_pure_mode", lambda text, log: deliveries.append(send(text, log))
        )
        app._handle_message("Review this screenshot", log)
        await deliveries[-1].wait()
        await pilot.pause()
        user = next(message for message in seen if message.role == "user")
        assert user.content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert not app._staged_images
        assert not app.is_busy
        app._pure_mode = None


@pytest.mark.asyncio
async def test_other_harness_still_rejects_composer_images(screenshot):
    from superqode.pure_mode import PureMode
    from superqode.harness.templates import rlm_template

    pure = PureMode()
    pure._harness_spec = rlm_template()
    with pytest.raises(ValueError, match="does not support composer image"):
        await pure.run("Review", images=[load_image(screenshot)])


@pytest.mark.parametrize(
    "command",
    [
        ":work programs example --json",
        ":work invocations example --json",
        ':work program-run example --code "read files.py"',
        ':work reconcile example task call --actor operator --reason "Verified result"',
        ':benchmark compare "example manifest.json" --repetitions 1',
    ],
)
@pytest.mark.asyncio
async def test_tui_work_and_benchmark_commands_dispatch_cli_arguments(monkeypatch, command):
    import shlex

    app = SuperQodeApp()
    dispatched = []
    async with app.run_test():
        monkeypatch.setattr(
            app, "_run_cli_passthrough", lambda parts, log, label: dispatched.append(parts)
        )
        app._handle_command(command, app.query_one("#log", ConversationLog))
        assert dispatched == [shlex.split(command.removeprefix(":"))]
