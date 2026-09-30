"""Local setup must not consume generation time or hold a user's first prompt."""

import asyncio
from types import SimpleNamespace

import pytest

from superqode.app.inputs import SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp
from superqode.providers.local.ollama import OllamaClient


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.delenv("SUPERQODE_LOCAL_WARMUP", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


async def test_ollama_explicit_warmup_optout_checks_once_without_generation(monkeypatch):
    monkeypatch.setenv("SUPERQODE_LOCAL_WARMUP", "0")
    requests, sent = [], []
    health_started, health_release = asyncio.Event(), asyncio.Event()

    async def request(self, method, endpoint, **kwargs):
        requests.append((method, endpoint))
        health_started.set()
        await health_release.wait()
        return {"models": []}

    def forbidden_gateway():
        raise AssertionError("Connection setup must not generate a warmup response")

    monkeypatch.setattr(OllamaClient, "_async_request", request)
    monkeypatch.setattr(
        "superqode.providers.gateway.litellm_gateway.LiteLLMGateway", forbidden_gateway
    )
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        setup = asyncio.create_task(
            app._test_local_connection("ollama", "fixture:7b", log, quiet=True)
        )
        await health_started.wait()
        original = app._handle_message

        def dispatch(text, output):
            if app.is_busy:
                return original(text, output)
            sent.append(text)

        app._handle_message = dispatch
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "my first question"
        await pilot.press("enter")
        await pilot.pause()
        assert sent == ["my first question"]
        assert not getattr(app, "_typeahead_queue", [])
        assert not app.is_busy and not prompt.disabled
        health_release.set()
        await setup
        await pilot.pause()
        assert requests == [("GET", "/api/tags")]
        rendered = "\n".join(line.text for line in log.lines).lower()
        assert "generation checked on first prompt" in rendered


async def test_ollama_unavailable_reports_failure_without_warmup(monkeypatch):
    async def unavailable(self):
        return False

    monkeypatch.setattr(OllamaClient, "is_available", unavailable)
    app = SuperQodeApp()
    failures = []
    app._surface_local_connection_failure = lambda log, message: failures.append(message)
    async with app.run_test():
        await app._test_local_connection(
            "ollama", "fixture", app.query_one("#log", ConversationLog)
        )
        assert failures == ["Ollama connection failed: server unavailable"]
        assert not app.is_busy


async def test_explicit_warmup_preserved_but_does_not_interrupt_active_turn(monkeypatch):
    monkeypatch.setenv("SUPERQODE_LOCAL_WARMUP", "1")
    calls = []

    class Gateway:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content="ok")

    monkeypatch.setattr("superqode.providers.gateway.litellm_gateway.LiteLLMGateway", Gateway)
    app = SuperQodeApp()
    async with app.run_test():
        log = app.query_one("#log", ConversationLog)
        app.is_busy = True
        assert await app._warmup_local_generation("ollama", "fixture", log) is False
        assert app.is_busy and not calls
        app.is_busy = False
        assert await app._warmup_local_generation("ollama", "fixture", log) is True
        assert calls[0]["max_tokens"] == 4
        assert not app.is_busy


@pytest.mark.parametrize("failed", [False, True])
async def test_default_warmup_holds_first_question_until_model_ready(monkeypatch, failed):
    from textual.widgets import Static
    from superqode.app.widgets import StreamingThinkingIndicator

    started, release = asyncio.Event(), asyncio.Event()
    health_started, health_release = asyncio.Event(), asyncio.Event()
    sent, requests = [], []

    async def available(self):
        health_started.set()
        await health_release.wait()
        return True

    class Gateway:
        async def chat_completion(self, **kwargs):
            requests.append(kwargs)
            started.set()
            await release.wait()
            if failed:
                raise asyncio.TimeoutError()
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(OllamaClient, "is_available", available)
    monkeypatch.setattr("superqode.providers.gateway.litellm_gateway.LiteLLMGateway", Gateway)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#log", ConversationLog)
        original = app._handle_message

        def dispatch(text, output):
            if app.is_busy:
                return original(text, output)
            sent.append(text)

        app._handle_message = dispatch
        setup = asyncio.create_task(
            app._test_local_connection("ollama", "fixture", log, quiet=True)
        )
        await health_started.wait()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert not prompt.disabled and app.is_busy
        prompt.value = "my first question"
        await pilot.press("enter")
        await pilot.pause()
        assert not sent
        assert app._typeahead_queue == ["my first question"]
        assert "waiting for model warmup" in str(app.query_one("#queued-input", Static).render())
        assert not requests
        health_release.set()
        await started.wait()
        assert (
            app.query_one("#streaming-thinking", StreamingThinkingIndicator).status
            == "Warming local model…"
        )
        assert requests[0]["think"] is False
        release.set()
        await setup
        await pilot.pause(0.4)
        assert not app._local_warmup_pending
        if failed:
            assert not sent
            assert app._typeahead_queue == ["my first question"]
            assert app._queue_paused
            assert ":queue send" in str(app.query_one("#queued-input", Static).render())
        else:
            assert sent == ["my first question"]
            assert app._typeahead_queue == []
