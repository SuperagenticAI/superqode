"""Connection checks must initialize agents without starting paid coding turns."""

import asyncio
import json
import time

import pytest

from test_desktop_service import desktop, desktop_acp_route  # noqa: F401
from superqode.desktop_service.connection_probe import probe_route


def test_acp_probe_advertises_models_without_a_coding_task(desktop_acp_route):
    (service, project, root), route = desktop_acp_route
    operation = service.dispatch(
        "connect.auth.start",
        {"action": "probe", "project": project["id"], "reference": route["id"]},
    )
    for _ in range(100):
        result = service.dispatch("connect.auth.poll", operation)
        if result["state"] != "running":
            break
        time.sleep(0.025)
    assert result["state"] == "completed", result
    state = result["result"]
    assert state["connected"] is True
    assert len(state["session"]["models"]["availableModels"]) == 2
    assert service.dispatch("jobs.list", {}) == []
    assert not (root / "main.py").exists()  # The fixture writes this on coding turns.


def test_missing_adapter_is_actionable_without_starting_a_process(tmp_path):
    with pytest.raises(ValueError, match="Install the ACP adapter"):
        asyncio.run(
            probe_route(
                tmp_path,
                {"available": False, "issue": "Install the ACP adapter"},
                lambda message: None,
            )
        )


def test_codex_probe_only_returns_account_identity_and_models(tmp_path, monkeypatch):
    calls = []

    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs["billing_requested"] == "subscription"

        async def verify_account(self):
            calls.append("verify")

        async def account(self):
            return {
                "account": {"type": "chatgpt", "email": "person@example.invalid"},
                "accessToken": "never-return-this",
            }

        async def models(self):
            return {
                "data": [
                    {
                        "model": "coding-model",
                        "displayName": "Coding model",
                        "private": "never-return-this",
                    }
                ]
            }

        async def aclose(self):
            calls.append("close")

    monkeypatch.setattr("superqode.runtime.codex_cli.CodexCLIRuntime", Runtime)
    result = asyncio.run(
        probe_route(
            tmp_path,
            {
                "available": True,
                "runtime": "codex-cli",
                "subscription_vendor": "codex",
            },
            lambda message: None,
        )
    )
    assert result["connected"] is True
    assert result["identity"] == "person@example.invalid"
    assert result["models"] == [{"id": "coding-model", "name": "Coding model"}]
    assert "never-return-this" not in json.dumps(result)
    assert calls == ["verify", "close"]


def test_codex_rejected_subscription_does_not_fallback_to_api_billing(tmp_path, monkeypatch):
    closed = []

    class Runtime:
        def __init__(self, **kwargs):
            assert kwargs["billing_requested"] == "subscription"

        async def verify_account(self):
            raise ValueError("Sign in with ChatGPT")

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr("superqode.runtime.codex_cli.CodexCLIRuntime", Runtime)
    with pytest.raises(ValueError, match="Sign in with ChatGPT"):
        asyncio.run(
            probe_route(
                tmp_path,
                {
                    "available": True,
                    "runtime": "codex-cli",
                    "subscription_vendor": "codex",
                },
                lambda message: None,
            )
        )
    assert closed == [True]


@pytest.mark.asyncio
async def test_opencode_probe_uses_shared_free_pricing_without_inventing_acp_models(
    tmp_path, monkeypatch
):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            return True

        async def stop(self):
            pass

        def get_agent_capabilities(self):
            return {}

        def get_session_models(self):
            return {
                "availableModels": [
                    {"modelId": "opencode/free-test", "name": "Free test"},
                    {"modelId": "vendor/paid-test", "name": "Paid test"},
                ]
            }

        def get_session_modes(self):
            return {}

        def get_session_config_options(self):
            return []

    async def catalog():
        return [
            {"id": "opencode/free-test", "is_free": True},
            {"id": "vendor/paid-test", "is_free": False},
            {"id": "unadvertised/model", "is_free": True},
        ]

    monkeypatch.setattr("superqode.desktop_service.acp_worker.DesktopACPClient", Client)
    monkeypatch.setattr("superqode.providers.opencode_models.get_opencode_models", catalog)
    result = await probe_route(
        tmp_path,
        {"available": True, "desktop_kind": "acp", "command": "opencode acp"},
        lambda message: None,
    )
    models = result["session"]["models"]["availableModels"]
    assert [m["modelId"] for m in models] == ["opencode/free-test", "vendor/paid-test"]
    assert [m["free"] for m in models] == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_acp_model_config_selection_never_silently_falls_back(accepted):
    from superqode.desktop_service.acp_worker import select_session_model

    calls = []

    class Client:
        def get_session_config_options(self):
            return [{"id": "model-choice", "category": "model", "type": "select"}]

        async def set_config_option(self, key, value):
            calls.append((key, value))
            return accepted

        async def set_model(self, model):
            raise AssertionError("Must not use legacy method when model config was advertised")

    assert await select_session_model(Client(), "opencode/free-test") is accepted
    assert calls == [("model-choice", "opencode/free-test")]
