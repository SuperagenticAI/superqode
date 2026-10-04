"""Mounted optional routing flow, persistence and new-root activation."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Checkbox, Input, Static, Button

from superqode.app.mixins.rlm_commands import RLMCommandMixin
from superqode.app.rlm_routing import save_routing_profile
from superqode.harness.loader import load_harness_spec
from superqode.harness.templates import get_harness_template
from superqode.widgets.rlm_routing import RLMRoutingScreen, RLMRoutingResult

PEER = {
    "name": "reviewer",
    "url": "https://review.example",
    "skill": "superqode-harness",
    "credential_env": "REVIEWER_KEY",
    "hosted": True,
    "credits": 2,
}


class RoutingApp(App):
    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self.result = None

    def on_mount(self):
        self.push_screen(
            RLMRoutingScreen(self.config), callback=lambda result: setattr(self, "result", result)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (110, 38)])
async def test_actual_connect_flow_reaches_optional_a2a_and_back(size, tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp, SelectionAwareInput
    from superqode.app.widgets import ConversationLog
    from superqode.providers.connection_profiles import CONNECT_MENU_HARNESS, CONNECT_MENU_RLM

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_acp_registry_refresh", lambda self: None)
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        app._handle_command(":connect", log)
        for expected in (CONNECT_MENU_HARNESS, CONNECT_MENU_RLM):
            prompt = app.query_one("#prompt-input", SelectionAwareInput)
            prompt.focus()
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app._connect_menu == expected
        await pilot.press("down", "down", "down", "enter")
        await pilot.pause()
        assert isinstance(app.screen, RLMRoutingScreen)
        assert not app.screen.query_one("#routing-enabled", Checkbox).value
        assert not app.screen.query_one("#routing-paid", Checkbox).value
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, RLMRoutingScreen)
        assert app._connect_menu == CONNECT_MENU_RLM
        assert app._awaiting_connect_type
        assert app.action_connect_menu_back()
        await pilot.pause()
        assert app._connect_menu == CONNECT_MENU_HARNESS
        assert not list(tmp_path.glob(".superqode/harnesses/rlm-routing-*.yaml"))
        app._handle_command(":connect harness-rlm", log)
        await pilot.pause()
        app.query_one("#prompt-input", SelectionAwareInput).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app._connect_menu == "models"
        assert app._pure_mode._harness_spec.runtime.backend == "rlm"
        assert not app._pure_mode._harness_spec.runtime.config["a2a"]["enabled"]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (110, 38)])
async def test_optional_routing_defaults_off_and_back_does_not_save(size):
    app = RoutingApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert not app.screen.query_one("#routing-enabled", Checkbox).value
        assert not app.screen.query_one("#routing-paid", Checkbox).value
        assert await pilot.click("#routing-close")
        assert app.result is None


@pytest.mark.asyncio
async def test_paid_opt_in_requires_budget_and_key_but_profile_can_be_saved(monkeypatch):
    monkeypatch.delenv("REVIEWER_KEY", raising=False)
    app = RoutingApp({"enabled": True, "peers": [PEER]})
    async with app.run_test(size=(80, 24)) as pilot:
        screen = app.screen
        assert await pilot.click("#routing-start")
        await pilot.pause()
        assert app.result is None
        assert "paid opt-in" in str(screen.query_one("#routing-error", Static).render())
        screen.query_one("#routing-paid", Checkbox).value = True
        screen.query_one("#routing-budget", Input).value = "10"
        await pilot.pause(0.3)
        assert await pilot.click("#routing-start")
        await pilot.pause()
        assert app.result is None
        assert "REVIEWER_KEY" in str(screen.query_one("#routing-error", Static).render())
        await pilot.pause(0.3)
        assert await pilot.click("#routing-save")
        await pilot.pause()
        assert app.result.action == "save"
        assert app.result.config["hosted_enabled"]
        assert app.result.config["max_hosted_credits"] == 10


@pytest.mark.asyncio
async def test_user_can_add_peer_and_start_without_saving_key_values(monkeypatch):
    monkeypatch.setenv("REVIEWER_KEY", "private-token-must-not-appear")
    app = RoutingApp()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = app.screen
        screen.query_one("#routing-enabled", Checkbox).value = True
        for field, value in {
            "name": "reviewer",
            "url": "https://review.example",
            "env": "REVIEWER_KEY",
            "description": "Review selected context",
        }.items():
            screen.query_one(f"#routing-{field}", Input).value = value
        button = screen.query_one("#routing-upsert", Button)
        button.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(screen.peers) == 1
        assert "private-token" not in str(screen.peers)
        assert "Key is set" in str(screen.query_one("#routing-key-status", Static).render())
        assert await pilot.click("#routing-start")
        await pilot.pause()
        assert app.result.action == "start"
        assert app.result.config["enabled"]
        assert not app.result.config["hosted_enabled"]
        assert "private-token" not in str(app.result.config)


def test_profile_preserves_rlm_sandbox_limits_and_does_not_mutate_original(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEWER_KEY", "private-token-must-not-appear")
    spec = get_harness_template("rlm-monty")
    spec = replace(
        spec,
        runtime=replace(
            spec.runtime, config={**spec.runtime.config, "max_depth": 2, "max_calls": 7}
        ),
    )
    config = {"enabled": True, "hosted_enabled": True, "max_hosted_credits": 10, "peers": [PEER]}
    first = save_routing_profile(spec, config, tmp_path)
    second = save_routing_profile(spec, config, tmp_path)
    assert first != second
    loaded = load_harness_spec(first)
    assert loaded.runtime.backend == "rlm"
    assert loaded.runtime.config["sandbox"] == "monty"
    assert loaded.runtime.config["max_depth"] == 2
    assert loaded.runtime.config["max_calls"] == 7
    assert loaded.runtime.config["a2a"] == config
    assert not spec.runtime.config["a2a"]["enabled"]
    assert "private-token" not in first.read_text()


class Log:
    def __init__(self):
        self.lines = []

    def add_info(self, value):
        self.lines.append(value)

    def add_success(self, value):
        self.lines.append(value)

    def add_error(self, value):
        self.lines.append(value)


def test_start_routes_through_a_new_branch_and_save_alone_does_not_switch(tmp_path):
    class Controller(RLMCommandMixin):
        def __init__(self):
            self._pure_mode = SimpleNamespace(
                session=SimpleNamespace(working_directory=tmp_path),
                get_current_session_id=lambda: "existing-root",
            )
            self.commands = []

        def _harness_cmd(self, command, log):
            self.commands.append(command)

    app = Controller()
    spec = get_harness_template("rlm")
    app._rlm_routing_result(RLMRoutingResult("save", {"enabled": False}), spec, Log())
    assert app.commands == []
    app._rlm_routing_result(RLMRoutingResult("start", {"enabled": False}), spec, Log())
    assert app.commands[0].startswith("switch ")
    assert app.commands[0].endswith(" --fork")
    assert app._pure_mode.get_current_session_id() == "existing-root"


@pytest.mark.asyncio
async def test_inspection_reports_worker_manifest_instead_of_form_without_starting_worker(
    tmp_path, monkeypatch
):
    from superqode.rlm.root_runtime import RootRuntimeClient, _atomic_json

    monkeypatch.setenv("SUPERQODE_RLM_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(RootRuntimeClient, "status", lambda self: SimpleNamespace(alive=True))
    client = RootRuntimeClient("existing-root", {"working_directory": str(tmp_path)})
    client.directory.mkdir(parents=True)
    _atomic_json(client.manifest_path, {"metadata": {"rlm_config": {"a2a": {"enabled": False}}}})

    class Controller(RLMCommandMixin):
        _pure_mode = SimpleNamespace(
            _harness_session_id="existing-root", session=SimpleNamespace(working_directory=tmp_path)
        )

    app = RoutingApp({"enabled": True, "peers": [{"name": "peer", "url": "http://localhost:8000"}]})
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await Controller()._rlm_routing_status(app.screen)
        assert "Active worker A2A: off" in str(
            app.screen.query_one("#routing-status", Static).render()
        )
        assert app.screen.query_one("#routing-enabled", Checkbox).value
        assert not client.commands_path.exists()
