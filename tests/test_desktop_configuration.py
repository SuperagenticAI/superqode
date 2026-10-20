"""Native configuration and asynchronous authentication use shared validators."""

import asyncio
import json
from pathlib import Path
import time

import pytest
import yaml

from superqode.desktop_service.configuration import configured_spec, vendor_key_route, options
from superqode.desktop_service.authentication import AuthenticationActions
from superqode.desktop_service.service import DesktopService


def test_guided_wizard_uses_shared_builder_and_no_tool_boundaries(tmp_path):
    catalog = options()
    assert any(r["id"] == "coding" for r in catalog["starters"])
    result = configured_spec(
        tmp_path,
        {
            "mode": "wizard",
            "answers": {
                "name": "review-only",
                "starter": "no-tool",
                "allow_write": True,
                "allow_shell": True,
            },
        },
    )
    spec = yaml.safe_load(result["yaml"])
    assert spec["name"] == "review-only"
    assert not spec["execution_policy"]["allow_write"]
    assert not spec["execution_policy"]["allow_shell"]


def test_rlm_native_forms_validate_sandbox_budgets_and_routing(tmp_path):
    with pytest.raises(ValueError):
        configured_spec(
            tmp_path, {"mode": "rlm", "config": {"tool_surface": "python-bash", "sandbox": "monty"}}
        )
    with pytest.raises(ValueError):
        configured_spec(tmp_path, {"mode": "rlm-routing", "config": {"enabled": True, "peers": []}})
    with pytest.raises(ValueError):
        configured_spec(
            tmp_path,
            {"mode": "rlm-routing", "config": {"hosted_enabled": True, "max_hosted_credits": 0}},
        )
    result = configured_spec(
        tmp_path,
        {
            "mode": "rlm",
            "config": {"sandbox": "docker", "tool_surface": "python", "budget": {"max_calls": 3}},
        },
    )
    data = yaml.safe_load(result["yaml"])
    assert data["runtime"]["config"]["budget"]["max_calls"] == 3
    assert data["execution_policy"]["sandbox"] == "docker"
    assert not list(tmp_path.iterdir())


def test_vendor_key_routes_are_distinct_from_subscription_routes(tmp_path):
    for entry, variable in [
        ("droid-key", "FACTORY_API_KEY"),
        ("fx-key", "AI_GATEWAY_API_KEY"),
        ("muse-key", "META_API_KEY"),
    ]:
        route = vendor_key_route(tmp_path, entry)
        assert variable in route["env_vars"]
        assert route["subscription_vendor"] is None
        assert route["auth"] == "byok"
    service = DesktopService(tmp_path / "state")
    project = service.open_project(str(tmp_path))
    try:
        service.dispatch(
            "connect.vendor.key",
            {"project": project["id"], "entry": "droid-key", "key": "private-vendor-fixture"},
        )
        service.dispatch("connect.systemone.key", {"key": "private-systemone-fixture"})
        assert "private-" not in json.dumps(service.dispatch("settings.get", {}))
        assert b"private-" not in (service.root / "desktop.sqlite").read_bytes()
    finally:
        service.close()


def test_authentication_is_cancelable_and_does_not_block_other_operations():
    manager = AuthenticationActions()

    async def operation(status):
        status("Continue in browser")
        await asyncio.sleep(30)

    identity = manager.start(operation)["id"]
    for _ in range(100):
        if manager.poll(identity)["messages"]:
            break
        time.sleep(0.01)
    manager.cancel(identity)
    for _ in range(100):
        if manager.poll(identity)["state"] != "running":
            break
        time.sleep(0.01)
    assert manager.poll(identity)["state"] == "cancelled"


@pytest.mark.asyncio
async def test_oauth_cancel_always_closes_callback(monkeypatch):
    from superqode.a2a import oauth
    import superqode.mcp.oauth_callback as callbacks

    stopped = []
    ready = asyncio.Event()

    class Callback:
        def __init__(self, **kwargs):
            pass

        async def start(self, **kwargs):
            pass

        async def stop(self):
            stopped.append(True)

        def get_redirect_uri(self):
            return oauth.REDIRECT_URI

        async def wait_for_callback(self, state, timeout):
            ready.set()
            await asyncio.sleep(30)

    class Provider:
        async def start_auth_flow(self, *args, **kwargs):
            return "https://identity.example/authorize?state=fixture"

    async def client(*args, **kwargs):
        return "client", ""

    async def provider(*args, **kwargs):
        return Provider(), {}

    monkeypatch.setattr(callbacks, "OAuthCallbackServer", Callback)
    monkeypatch.setattr(oauth, "_ensure_client", client)
    monkeypatch.setattr(oauth, "_provider", provider)
    monkeypatch.setattr(oauth.webbrowser, "open", lambda url: True)
    task = asyncio.create_task(
        oauth._browser_flow(
            "https://agent.example",
            None,
            metadata={},
            client_id="client",
            client_secret="",
            on_status=None,
        )
    )
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped


@pytest.mark.asyncio
async def test_remote_oauth_refresh_is_registered_for_redaction(monkeypatch):
    from types import SimpleNamespace
    from superqode.desktop_service.remote_worker import refresh_oauth
    import superqode.a2a.oauth as oauth

    async def token(*args, **kwargs):
        assert kwargs["interactive"] is False
        return "new-oauth-fixture-secret"

    monkeypatch.setattr(oauth, "ensure_access_token", token)
    client = SimpleNamespace(_http=SimpleNamespace(headers={}))
    secrets = []
    await refresh_oauth(
        client,
        {"url": "https://agent.example", "oauth_needs": [{"scheme": "oauth", "required": True}]},
        {"oauth": True},
        secrets,
    )
    assert secrets == ["new-oauth-fixture-secret"]
    assert client._http.headers["Authorization"] == "Bearer new-oauth-fixture-secret"
