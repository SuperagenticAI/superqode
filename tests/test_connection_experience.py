"""Connection boundaries: no implicit billing, truthful status and safe navigation."""

import asyncio
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Button

from superqode.acp.client import cancel_prompt_with_grace
from superqode.app.project_ui_state import (
    get_connection_preferences,
    remember_connection,
    save_ui_state,
    set_connection_favorites,
    load_ui_state,
    ui_state_path,
)
from superqode.providers import connection_diagnostics as diagnostics
from superqode.providers.health import HealthChecker, ProviderStatus
from superqode.providers.registry import PROVIDERS
from superqode.widgets.connection_browser import ConnectionBrowserScreen, filter_connections


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(diagnostics, "provider_api_key", lambda definition: "test-key")


@pytest.mark.asyncio
async def test_cloud_metadata_check_never_generates_or_probes_network(configured, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Implicit network request")

    monkeypatch.setattr(diagnostics, "_read_models", forbidden)
    gateway = SimpleNamespace(chat_completion=forbidden)
    result = await diagnostics.check_model_connection("openai", "selected-model", gateway=gateway)
    assert result.status == "configured"
    assert not result.inference_verified
    assert "not verified" in result.message


@pytest.mark.asyncio
async def test_explicit_inference_is_minimal_and_isolated(configured):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content="OK")

    result = await diagnostics.check_model_connection(
        "openai",
        "selected-model",
        infer=True,
        gateway=SimpleNamespace(chat_completion=generate),
    )
    assert result.inference_verified
    assert len(calls) == 1
    assert calls[0]["tools"] is None
    assert calls[0]["max_tokens"] == 8
    assert [message.content for message in calls[0]["messages"]] == ["Reply with OK."]
    assert calls[0]["model"] == "selected-model"


@pytest.mark.asyncio
async def test_missing_credential_does_not_create_gateway(monkeypatch):
    monkeypatch.setattr(diagnostics, "provider_api_key", lambda definition: None)
    from superqode.providers.gateway import GatewayFactory

    monkeypatch.setattr(
        GatewayFactory, "create", lambda: pytest.fail("Should not construct gateway")
    )
    result = await diagnostics.check_model_connection("openai", "model", infer=True)
    assert result.status == "unconfigured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,rows,model,status,context",
    [
        ("ollama", {"models": [{"name": "custom:latest"}]}, "custom", "reachable", None),
        ("ollama", {"models": [{"name": "custom-plus:latest"}]}, "custom", "model_missing", None),
        ("vllm", {"data": [{"id": "loaded", "max_model_len": 8192}]}, "loaded", "reachable", 8192),
        (
            "lmstudio",
            {"data": [{"id": "loaded", "loaded_context_length": True}]},
            "loaded",
            "reachable",
            None,
        ),
    ],
)
async def test_local_metadata_uses_exact_model_and_loaded_context(
    monkeypatch, provider, rows, model, status, context
):
    urls = []

    def read(url, api_key=None):
        urls.append(url)
        return rows

    monkeypatch.setattr(diagnostics, "_read_models", read)
    result = await diagnostics.check_model_connection(provider, model)
    assert result.status == status
    assert result.context_window == context
    assert not result.inference_verified
    assert urls[0].endswith("/api/tags" if provider == "ollama" else "/v1/models")


@pytest.mark.parametrize(
    "error,status",
    [
        (
            HTTPError("https://user:secret@server/?token=secret", 401, "secret", {}, None),
            "auth_error",
        ),
        (HTTPError("https://server", 404, "secret", {}, None), "model_missing"),
        (HTTPError("https://server", 429, "secret", {}, None), "rate_limited"),
        (TimeoutError("secret"), "timeout"),
        (URLError("secret"), "unreachable"),
        (ValueError("secret"), "error"),
    ],
)
def test_failure_messages_do_not_expose_raw_credentials(error, status):
    actual, message = diagnostics.failure_message(error)
    assert actual == status
    assert "secret" not in message
    assert (
        diagnostics.public_endpoint("https://user:secret@server/v1?token=secret#secret")
        == "https://server/v1"
    )


@pytest.mark.asyncio
async def test_provider_health_does_not_call_saved_credentials_ready(monkeypatch):
    import superqode.providers.health as health

    monkeypatch.setattr(health, "provider_api_key", lambda definition: "stored-oauth-token")
    checker = HealthChecker()
    result = await checker.check_provider("openai", force=True)
    assert result.status == ProviderStatus.CONFIGURED
    assert not result.is_ready
    assert not result.model_available
    assert checker.get_ready_providers() == []
    local = await checker.check_provider("ollama", force=True)
    assert local.status == ProviderStatus.UNKNOWN
    assert "not verified" in local.message
    monkeypatch.setattr(health, "provider_api_key", lambda definition: None)
    result = checker._check_configuration("grok-cli", PROVIDERS["grok-cli"])
    assert result.status == ProviderStatus.NOT_CONFIGURED


def test_connection_preferences_are_bounded_and_preserve_session(tmp_path):
    save_ui_state({"last_session_id": "session", "sidebar_width": 42}, cwd=tmp_path)
    set_connection_favorites(["codex", "codex", "local"], cwd=tmp_path)
    for i in range(40):
        remember_connection(f"profile-{i}", cwd=tmp_path)
    remember_connection("profile-0", cwd=tmp_path)
    favorites, recent = get_connection_preferences(tmp_path)
    assert favorites == ["codex", "local"]
    assert len(recent) == 30
    assert recent[:2] == ["profile-0", "profile-39"]
    assert load_ui_state(tmp_path)["last_session_id"] == "session"
    ui_state_path(tmp_path).write_text(
        json.dumps(
            {"favorite_connections": [None, {}, "local", "local"], "recent_connections": "bad"}
        )
    )
    assert get_connection_preferences(tmp_path) == (["local"], [])
    ui_state_path(tmp_path).write_text("broken JSON")
    assert get_connection_preferences(tmp_path) == ([], [])


PROFILES = [
    SimpleNamespace(id="byok", label="API key", description="Cloud provider", badges=()),
    SimpleNamespace(
        id="codex", label="Codex subscription", description="SDK account", badges=("SDK",)
    ),
    SimpleNamespace(id="local", label="Local models", description="Ollama server", badges=()),
]


def test_search_tokens_favorites_and_recent_order():
    assert [p.id for p in filter_connections(PROFILES, "", ["local"], ["codex"])] == [
        "local",
        "codex",
        "byok",
    ]
    assert [p.id for p in filter_connections(PROFILES, "SUBSCRIPTION sdk", [], [])] == ["codex"]
    assert filter_connections(PROFILES, "missing", [], []) == []


class BrowserApp(App):
    def __init__(self, cwd, query="", loader=None):
        super().__init__()
        self.cwd = cwd
        self.query = query
        self.loader = loader or (lambda: PROFILES)
        self.chosen = []

    def compose(self) -> ComposeResult:
        yield Input(value="My unfinished prompt", id="draft")

    def on_mount(self):
        self.push_screen(
            ConnectionBrowserScreen(cwd=self.cwd, query=self.query, loader=self.loader),
            self.chosen.append,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(60, 18), (80, 24), (120, 40)])
async def test_browser_search_favorite_escape_and_small_screen(tmp_path, size):
    app = BrowserApp(tmp_path)
    async with app.run_test(size=size) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#connection-results", OptionList).region.height >= 2
        search = screen.query_one("#connection-search", Input)
        search.value = "codex sdk"
        await pilot.pause()
        assert [p.id for p in screen.matching_profiles] == ["codex"]
        await pilot.press("ctrl+s")
        assert get_connection_preferences(tmp_path)[0] == ["codex"]
        search.value = "nothing matches"
        await pilot.pause()
        assert screen.query_one("#connection-select", Button).disabled
        await pilot.press("enter")
        assert app.chosen == []
        await pilot.press("escape")
        assert app.chosen == [None]
        assert app.query_one("#draft", Input).value == "My unfinished prompt"


@pytest.mark.asyncio
@pytest.mark.parametrize("mouse", [False, True])
async def test_browser_keyboard_and_click_select_same_profile(tmp_path, mouse):
    app = BrowserApp(tmp_path, query="codex")
    async with app.run_test(size=(80, 30)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        if mouse:
            await pilot.click("#connection-select")
        else:
            await pilot.press("enter")
        assert app.chosen == ["codex"]


@pytest.mark.asyncio
async def test_browser_typing_during_loading_is_not_lost(tmp_path):
    import threading

    started, finish = threading.Event(), threading.Event()

    def load():
        started.set()
        finish.wait(3)
        return PROFILES

    app = BrowserApp(tmp_path, loader=load)
    async with app.run_test() as pilot:
        await asyncio.to_thread(started.wait, 2)
        app.screen.query_one("#connection-search", Input).value = "local"
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [p.id for p in app.screen.matching_profiles] == ["local"]


@pytest.mark.asyncio
@pytest.mark.parametrize("responsive", [True, False])
async def test_acp_cancel_preserves_cooperative_session_and_bounds_recovery(responsive):
    cancelled = asyncio.Event()
    stopped = []

    async def cancel():
        if responsive:
            cancelled.set()
        return True

    async def stop():
        stopped.append(True)

    async def prompt():
        await cancelled.wait()
        return "cancelled"

    task = asyncio.create_task(prompt())
    preserved = await cancel_prompt_with_grace(
        SimpleNamespace(cancel=cancel, stop=stop), task, timeout=1.0 if responsive else 0.05
    )
    assert preserved is responsive
    assert stopped == ([] if responsive else [True])
    assert task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,expected",
    [(' {"echo":"OK"}', True), ('{"echo":"wrong"}', False), ("not JSON", False)],
)
async def test_local_tool_probe_validates_returned_arguments_without_execution(arguments, expected):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            content="",
            tool_calls=[{"function": {"name": "connection_probe", "arguments": arguments}}],
        )

    result = await diagnostics.check_model_connection(
        "ollama",
        "unknown-custom-model",
        tools=True,
        gateway=SimpleNamespace(chat_completion=generate),
    )
    assert result.tools_verified is expected
    assert calls[0]["tools"][0].name == "connection_probe"
    assert len(calls[0]["messages"]) == 1


@pytest.mark.asyncio
async def test_empty_inference_does_not_claim_generation_verified(configured):
    async def generate(**kwargs):
        return SimpleNamespace(content="")

    result = await diagnostics.check_model_connection(
        "openai", "model", infer=True, gateway=SimpleNamespace(chat_completion=generate)
    )
    assert result.status == "empty_response"
    assert not result.inference_verified


@pytest.mark.asyncio
async def test_check_task_cancellation_is_not_swallowed(configured):
    started = asyncio.Event()

    async def generate(**kwargs):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        diagnostics.check_model_connection(
            "openai", "model", infer=True, gateway=SimpleNamespace(chat_completion=generate)
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_browser_close_during_catalog_loading_is_safe(tmp_path):
    import threading

    finish = threading.Event()

    def load():
        finish.wait(3)
        return PROFILES

    app = BrowserApp(tmp_path, loader=load)
    async with app.run_test() as pilot:
        await pilot.press("escape")
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.chosen == [None]
        assert app.query_one("#draft", Input).value == "My unfinished prompt"


def test_search_catalog_includes_unfeatured_acp_agents(monkeypatch):
    from superqode.widgets.connection_browser import load_connection_profiles

    monkeypatch.setattr(
        "superqode.app.harness_picker.acp_picker_items",
        lambda **kwargs: [
            SimpleNamespace(
                id="acp:unfeatured",
                display_name="Unfeatured agent (ACP)",
                description="A registry agent",
                target={"short_name": "unfeatured"},
                available=False,
                issue="Install the launcher",
            ),
        ],
    )
    profiles = load_connection_profiles()
    selected = next(profile for profile in profiles if profile.id == "acp:unfeatured")
    assert selected.acp_agent == "unfeatured"
    assert not selected.available
    assert selected.unavailable_hint == "Install the launcher"
    assert any(profile.id == "build" and "(Advanced)" in profile.label for profile in profiles)
