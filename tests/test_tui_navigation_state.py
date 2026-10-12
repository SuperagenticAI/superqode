"""Only the visible inline view may select rows or finish a delayed render."""

import asyncio
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest
from textual import events
from textual.widgets import Button

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog, ColorfulStatusBar
from superqode.providers.connection_profiles import ConnectionProfile
from superqode.widgets.connection_browser import ConnectionBrowserScreen
from superqode.widgets.developer_trial import DeveloperTrialScreen
from superqode.widgets.model_picker import ModelOption, ModelPickerWidget


AGENTS = {
    "review-a": {"name": "Review Agent A", "short_name": "review-a"},
    "review-b": {"name": "Review Agent B", "short_name": "review-b"},
}
ACP_PROFILE = ConnectionProfile("review-acp", "ACP", "Browse coding agents", "acp-picker")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("superqode.app.theme_bridge._CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for key in ("SUPERQODE_CONNECT", "SUPERQODE_HARNESS"):
        monkeypatch.delenv(key, raising=False)
    for name in (
        "_prewarm_litellm",
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)

    async def catalog(self, reuse_snapshot=False):
        self._acp_picker_snapshot = (AGENTS, set(AGENTS))
        self._acp_picker_snapshot_at = monotonic()
        return self._acp_picker_snapshot

    monkeypatch.setattr(SuperQodeApp, "_acp_picker_catalog", catalog)


def text(log):
    return "\n".join(line.text for line in log.lines)


async def until(pilot, ready):
    async with asyncio.timeout(5):
        while not ready():
            await pilot.pause(0.05)


async def command(app, pilot, value):
    prompt = app.query_one("#prompt-input", SelectionAwareInput)
    prompt.value = value
    prompt.focus()
    await pilot.press("enter")
    await pilot.pause()


async def back(app, pilot, method):
    if method == "mouse":
        bar = app.query_one("#status-bar", ColorfulStatusBar)
        bar._render_for_width(bar.size.width)
        cells = [
            (x, y)
            for y in range(bar.size.height)
            for x in range(bar.size.width)
            if bar.action_at(x, y) == "back"
        ]
        x, y = cells[len(cells) // 2]
        await pilot.click(
            "#status-bar", offset=(x + bar.content_offset.x, y + bar.content_offset.y)
        )
    else:
        await pilot.press(method)
    await pilot.pause()


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("vim", [False, True])
async def test_connect_agents_keyboard_selects_the_visible_agent(size, vim, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    app = SuperQodeApp()
    connected = []
    monkeypatch.setattr(app, "_connect_agent", lambda agent: connected.append(agent))
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda agent: True)
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        await command(app, pilot, ":connect")
        # XTermParser includes CR on a real Enter key; Pilot.press does not.
        prompt.post_message(events.Key("enter", "\r"))
        await until(pilot, lambda: app._connect_menu == "agents")
        await pilot.press("down")
        await pilot.pause()
        assert app._byok_highlighted_connect_type_index == 1
        await command(app, pilot, ":connect acp")
        await until(
            pilot, lambda: app._awaiting_acp_agent_selection and len(app._acp_agent_list) == 2
        )
        await pilot.press("down")
        await until(pilot, lambda: app._acp_highlighted_agent_index == 1)
        prompt.post_message(events.Key("enter", "\r"))
        await pilot.pause()
        assert connected == ["review-b"]


async def test_vim_normal_picker_accepts_number_and_terminal_enter(monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    app = SuperQodeApp()
    connected = []
    monkeypatch.setattr(app, "_connect_agent", lambda agent: connected.append(agent))
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda agent: True)
    async with app.run_test() as pilot:
        await command(app, pilot, ":connect acp")
        await until(pilot, lambda: app._awaiting_acp_agent_selection)
        assert app._vim_input_mode == "normal"
        await pilot.press("j", "k", "2")
        await pilot.pause()
        app.query_one("#prompt-input").post_message(events.Key("enter", "\r"))
        await until(pilot, lambda: connected == ["review-b"])


@pytest.mark.parametrize("vim", [False, True])
async def test_agent_number_ten_accepts_zero_in_the_numeric_buffer(vim, monkeypatch):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    app = SuperQodeApp()
    agents = {
        f"review-{i:02}": {"name": f"Agent {i:02}", "short_name": f"review-{i:02}"}
        for i in range(1, 11)
    }
    connected = []

    async def catalog(reuse_snapshot=False):
        app._acp_picker_snapshot = agents, set(agents)
        app._acp_picker_snapshot_at = monotonic()
        return app._acp_picker_snapshot

    monkeypatch.setattr(app, "_acp_picker_catalog", catalog)
    monkeypatch.setattr(app, "_connect_agent", connected.append)
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda agent: True)
    async with app.run_test() as pilot:
        await command(app, pilot, ":connect acp all")
        await until(pilot, lambda: len(app._acp_agent_list) == 10)
        await pilot.press("1", "0")
        app.query_one("#prompt-input").post_message(events.Key("enter", "\r"))
        await until(pilot, lambda: connected == ["review-10"])


@pytest.mark.parametrize("method", ["j-enter", "number"])
async def test_vim_routes_registered_picker_keys_to_the_visible_prompt(method, monkeypatch):
    from superqode.app.prompt_stack import PromptSpec

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    app = SuperQodeApp()
    selected = []
    async with app.run_test() as pilot:
        app._prompts.push(
            PromptSpec(
                "test-picker", options=lambda: ["first", "second"], on_select=selected.append
            )
        )
        app._set_vim_state("normal")
        if method == "number":
            await pilot.press("2")
        else:
            await pilot.press("j")
            app.query_one("#prompt-input").post_message(events.Key("enter", "\r"))
        await until(pilot, lambda: selected == ["second"])


async def test_vim_setup_text_prompt_remains_editable(monkeypatch):
    from superqode.app.prompt_stack import PromptSpec

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1")
    app = SuperQodeApp()
    answers = []
    async with app.run_test() as pilot:
        app._prompts.push(
            PromptSpec(
                "test-text", kind="text", on_text=lambda value: answers.append(value) or True
            )
        )
        app._set_vim_state("normal")
        await pilot.press("h", "i")
        prompt = app.query_one("#prompt-input")
        assert not prompt.read_only
        assert prompt.value == "hi"
        prompt.post_message(events.Key("enter", "\r"))
        await until(pilot, lambda: answers == ["hi"])


async def test_connection_status_keeps_the_sidebar_under_user_control():
    from superqode.sidebar import CollapsibleSidebar

    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        sidebar = app.query_one("#sidebar", CollapsibleSidebar)
        app.current_agent = "review-a"
        app.current_mode = "agent"
        app._refresh_harness_panel()
        app._show_harness_status(log)
        await pilot.pause()
        assert not app.sidebar_visible
        assert not sidebar.has_class("visible")
        assert app.focused.id == "prompt-input"
        app.action_sidebar_files()
        await pilot.pause()
        app._show_harness_status(log)
        await pilot.pause()
        assert app.sidebar_visible
        assert sidebar.current_view == "files"


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("method", ["b", "escape", "mouse"])
async def test_back_from_acp_routes_keys_to_the_visible_menu(size, method):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect")
        app._dispatch_connection_profile(ACP_PROFILE, log)
        await until(pilot, lambda: "Coding agents over ACP" in text(log))
        await back(app, pilot, method)
        assert app._awaiting_connect_type
        assert not app._awaiting_acp_agent_selection
        assert "Coding agents over ACP" not in text(log)
        await pilot.press("down")
        await pilot.pause()
        assert "Coding agents over ACP" not in text(log)
        assert app._byok_highlighted_connect_type_index == 1


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_help_releases_picker_keys_and_back_reopens_it(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect")
        await command(app, pilot, ":help")
        assert "SuperQode Commands" in text(log)
        await pilot.press("down")
        await pilot.pause()
        assert "SuperQode Commands" in text(log)
        assert not app._in_selection_mode()
        await pilot.press("b")
        await pilot.pause()
        assert app._awaiting_connect_type
        assert "SuperQode Commands" not in text(log)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("fails", [False, True])
async def test_acp_load_cannot_replace_the_page_after_back(size, fails, monkeypatch):
    started, finish = asyncio.Event(), asyncio.Event()
    app = SuperQodeApp()

    async def catalog(reuse):
        started.set()
        await finish.wait()
        if fails:
            raise OSError("late catalogue failure")
        return AGENTS, set(AGENTS)

    monkeypatch.setattr(app, "_acp_picker_catalog", catalog)
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect")
        app._dispatch_connection_profile(ACP_PROFILE, log)
        await started.wait()
        worker = next(worker for worker in app.workers if worker.group == "acp-picker")
        await back(app, pilot, "b")
        before = text(log)
        finish.set()
        await worker.wait()
        await pilot.pause()
        assert text(log) == before
        assert not app._awaiting_acp_agent_selection
        assert "late catalogue failure" not in text(log)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_mouse_provider_choice_discards_digits_from_the_previous_page(size, monkeypatch):
    monkeypatch.setattr("superqode.providers.models.get_models_for_provider", lambda *a: {})
    app = SuperQodeApp()
    connections = []
    monkeypatch.setattr(
        app, "_connect_byok_mode", lambda provider, model, *a: connections.append((provider, model))
    )
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect byok")
        await until(pilot, lambda: not app._just_showed_byok_picker)
        await pilot.press("1")
        row = next(
            i
            for i, line in enumerate(log.lines)
            if (match := app._PICKER_ROW.match(line.text)) and match.group(1) == "2"
        )
        provider = app._byok_connect_list[1][0]
        log.lock_viewport()
        log.scroll_to(y=row, animate=False, force=True)
        await pilot.pause()
        await pilot.click("#log", offset=(10, row - int(log.scroll_offset.y)))
        await pilot.pause()
        assert app._selection_digit_buffer == ""
        assert app.query_one("#prompt-input").value == ""
        await pilot.press("down")
        await pilot.pause()
        model = app._byok_model_list[app._byok_highlighted_model_index]
        assert app._byok_highlighted_model_index == 1
        await pilot.press("enter")
        await pilot.pause()
        assert connections == [(provider, model)]


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("leave", [":home", ":agent", "escape"])
async def test_abandoning_inline_trial_setup_cancels_automatic_return(size, leave, monkeypatch):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        draft = "My original task"
        prompt.value = draft
        app._trial_cmd(log)
        await until(
            pilot, lambda: isinstance(app.screen, DeveloperTrialScreen) and app.screen.is_mounted
        )
        app.screen.query_one("#trial-connect", Button).press()
        await until(
            pilot,
            lambda: isinstance(app.screen, ConnectionBrowserScreen) and app.screen.is_mounted,
        )
        app.screen.dismiss("acp")
        await until(pilot, lambda: "Coding agents over ACP" in text(log))
        if leave == "escape":
            # Walk all the way out, rather than just returning to a parent menu.
            async with asyncio.timeout(5):
                while app.default_screen.has_class("connection-setup"):
                    await pilot.press("escape")
                    await pilot.pause()
        else:
            await command(app, pilot, leave)
        assert not app._trial_state().awaiting_connection
        assert draft in prompt.value
        monkeypatch.setattr(app, "_has_live_connection", lambda: True)
        app._mark_onboarding_complete()
        await pilot.pause(0.4)
        assert app.screen is app.default_screen


@pytest.mark.parametrize("delay_redraw", [False, True])
async def test_model_refresh_cannot_restore_a_provider_picker_after_home(delay_redraw, monkeypatch):
    app = SuperQodeApp()
    started, finish = asyncio.Event(), asyncio.Event()

    async def refresh(**kwargs):
        started.set()
        await finish.wait()
        return True

    client = SimpleNamespace(refresh=refresh)
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    monkeypatch.setattr(app, "_apply_live_models", lambda client: None)
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect byok")
        app.action_refresh_byok_models()
        await started.wait()
        if delay_redraw:
            finish.set()
            await until(pilot, lambda: "Models refreshed successfully" in text(log))
        await command(app, pilot, ":home")
        before = text(log)
        finish.set()
        await pilot.pause(0.5)
        assert text(log) == before
        assert not app._awaiting_byok_provider


async def test_catalogue_revalidation_cannot_update_a_later_visit(monkeypatch):
    app = SuperQodeApp()
    started, finish = asyncio.Event(), asyncio.Event()
    redraws = []

    async def catalog():
        started.set()
        await finish.wait()
        agents = {**AGENTS, "late": {"name": "Late Agent", "short_name": "late"}}
        return agents, set(agents)

    monkeypatch.setattr(app, "_build_acp_picker_catalog", catalog)
    monkeypatch.setattr(app, "_reshow_acp_agents", lambda log: redraws.append(True))
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect")
        app._dispatch_connection_profile(ACP_PROFILE, log)
        await until(pilot, lambda: "Coding agents over ACP" in text(log))
        app._acp_picker_snapshot_at = 0
        worker = app._revalidate_acp_catalog(log)
        await started.wait()
        await back(app, pilot, "b")
        app._dispatch_connection_profile(ACP_PROFILE, log)
        await until(pilot, lambda: "Coding agents over ACP" in text(log))
        before = text(log)
        finish.set()
        await worker.wait()
        await pilot.pause()
        assert app._awaiting_acp_agent_selection
        assert text(log) == before
        assert not redraws


async def test_replacing_an_interactive_picker_removes_its_old_focus_target():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        picker = ModelPickerWidget("Example", [ModelOption("first", "First")])
        app._model_picker_widget = picker
        app._picker_provider_id = "example"
        app._picker_log = app.query_one("#log", ConversationLog)
        app._awaiting_byok_model = True
        await app.mount(picker)
        await pilot.pause()
        assert app.focused.id == "picker-search"
        app._handle_command(":help", app._picker_log)
        await until(pilot, lambda: not picker.is_attached)
        await pilot.pause(0.2)
        assert app._model_picker_widget is None
        assert app.focused.id == "prompt-input"
        assert not app._awaiting_byok_model


async def test_leaving_a_picker_does_not_erase_a_new_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await command(app, pilot, ":connect byok")
        await pilot.press("1")
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "Keep my new draft"
        app._show_help(log)
        await pilot.pause()
        assert prompt.value == "Keep my new draft"
        assert app._selection_digit_buffer == ""
