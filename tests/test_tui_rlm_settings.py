"""Mounted profile controls, sandbox contracts and persistence."""

import pytest
from textual.app import App
from textual.widgets import Input, Select, Static

from superqode.app.rlm_routing import save_runtime_profile
from superqode.harness.loader import load_harness_spec
from superqode.harness.templates import get_harness_template
from superqode.widgets.rlm_settings import RLMSettingsScreen


class SettingsApp(App):
    def __init__(self, config=None):
        super().__init__()
        self.config, self.result = config, None

    def on_mount(self):
        self.push_screen(
            RLMSettingsScreen(self.config), callback=lambda value: setattr(self, "result", value)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (110, 38)])
async def test_settings_save_hybrid_docker_budget_and_preserve_a2a(size, tmp_path):
    base = get_harness_template("rlm")
    app = SettingsApp(base.runtime.config)
    async with app.run_test(size=size) as pilot:
        screen = app.screen
        screen.query_one("#rlm-tool-surface", Select).value = "python-bash"
        screen.query_one("#rlm-execution", Select).value = "docker"
        screen.query_one("#rlm-observations", Select).value = "selective"
        screen.query_one("#rlm-call-limit", Input).value = "25"
        assert await pilot.click("#rlm-settings-save")
        await pilot.pause()
        assert app.result.action == "save"
    path = save_runtime_profile(base, app.result.config, tmp_path)
    saved = load_harness_spec(path)
    assert saved.runtime.config["budget"]["max_calls"] == 25
    assert saved.runtime.config["a2a"] == base.runtime.config["a2a"]
    assert saved.agents[0].tools == ("python", "bash")
    assert saved.execution_policy.sandbox == "docker"
    assert not saved.execution_policy.allow_network
    assert saved.metadata["experimental"] and not saved.metadata["pure_permissions"]


@pytest.mark.asyncio
async def test_monty_with_bash_is_rejected_in_settings():
    app = SettingsApp()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = app.screen
        screen.query_one("#rlm-tool-surface", Select).value = "python-bash"
        screen.query_one("#rlm-execution", Select).value = "monty"
        assert await pilot.click("#rlm-settings-start")
        await pilot.pause()
        assert app.result is None
        assert "host or Docker" in str(screen.query_one("#rlm-settings-error", Static).render())


@pytest.mark.asyncio
async def test_actual_connect_reaches_settings_and_back(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.app.widgets import ConversationLog

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_acp_registry_refresh", lambda self: None)
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app._handle_command(":connect rlm-settings", app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert isinstance(app.screen, RLMSettingsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app._connect_menu == "rlm-options"
        assert not list(tmp_path.glob(".superqode/harnesses/rlm-profile-*.yaml"))


def test_rlm_family_usage_keeps_unknowns_visible():
    from superqode.pure_mode import PureMode
    from superqode.harness.events import HarnessEvent

    pure = PureMode.__new__(PureMode)
    pure._last_stats = {}
    pure._handle_runtime_harness_event(
        HarnessEvent(
            type="rlm.usage",
            data={
                "total": {
                    "tokens": 200,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cost_usd": 0.5,
                    "unknown_token_calls": 1,
                    "unknown_cost_calls": 1,
                }
            },
        )
    )
    assert pure._last_stats["total_tokens"] is None
    assert pure._last_stats["cost_usd"] is None
    pure._handle_runtime_harness_event(
        HarnessEvent(
            type="rlm.usage",
            data={
                "total": {"tokens": 200, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.5}
            },
        )
    )
    assert pure._last_stats["prompt_tokens"] == 180
    assert pure._last_stats["total_tokens"] == 200
    assert pure._last_stats["cost_usd"] == 0.5


@pytest.mark.asyncio
async def test_mounted_completion_report_shows_unknown_cost_and_tokens():
    from superqode.app.widgets import ConversationLog

    class ReportApp(App):
        def compose(self):
            yield ConversationLog(id="log")

    app = ReportApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", ConversationLog)
        written = []
        original = log.write

        def record(value, *args, **kwargs):
            written.append(str(value))
            return original(value, *args, **kwargs)

        log.write = record
        log.end_agent_session(True, "complete", None, None, cost=None)
        await pilot.pause()
        assert any("cost unknown" in value and "tokens unknown" in value for value in written)


def test_settings_resolve_inherited_docker_policy_before_display():
    from dataclasses import replace
    from superqode.app.mixins.rlm_commands import RLMCommandMixin

    base = get_harness_template("rlm")
    config = {
        k: v
        for k, v in base.runtime.config.items()
        if k not in {"sandbox", "allow_write", "allow_shell", "allow_network"}
    }
    spec = replace(
        base,
        runtime=replace(base.runtime, config=config),
        execution_policy=replace(
            base.execution_policy, sandbox="docker", allow_write=False, allow_network=False
        ),
    )

    class Host:
        def push_screen(self, screen, callback):
            self.screen = screen

    class Log:
        def add_error(self, text):
            raise AssertionError(text)

    host = Host()
    RLMCommandMixin._open_rlm_settings(host, Log(), spec=spec)
    assert host.screen.sandbox.backend == "docker"
    assert not host.screen.sandbox.policy.allow_write
    assert not host.screen.sandbox.allow_network
