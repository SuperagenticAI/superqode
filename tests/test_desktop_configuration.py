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


def test_agent_install_explains_missing_node_and_blocks_subprocess(monkeypatch, tmp_path):
    from superqode.desktop_service.configuration import install_plan, run_install_command

    installed = False
    monkeypatch.setattr("shutil.which", lambda binary: "/vendor/npm" if installed else None)
    plan = install_plan(tmp_path, "qwen-code")
    requirement = plan["requirements"][0]
    assert requirement["name"] == "Node.js and npm"
    assert not requirement["installed"]
    assert requirement["docs_url"] == "https://nodejs.org/en/download"

    async def unexpected_spawn(*args, **kwargs):
        pytest.fail("A missing installer must never start a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)
    with pytest.raises(ValueError, match="Install Node.js and npm.*https://nodejs.org/en/download"):
        asyncio.run(run_install_command(plan["argv"], lambda _: None))
    installed = True
    assert install_plan(tmp_path, "qwen-code")["requirements"][0]["installed"]


@pytest.fixture
def mac_app(monkeypatch, tmp_path):
    from superqode.desktop_service import managed_toolchains

    monkeypatch.setenv("SUPERQODE_APP", "1")
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(tmp_path / "app state"))
    monkeypatch.setattr(managed_toolchains, "sys", type("MacOS", (), {"platform": "darwin"}))
    monkeypatch.setattr(managed_toolchains.platform, "machine", lambda: "arm64")
    return tmp_path / "app state" / "toolchains"


def test_mac_app_review_uses_owned_runtime_without_preparing_it(monkeypatch, tmp_path, mac_app):
    from superqode.desktop_service.configuration import install_plan

    plan = install_plan(tmp_path, "fast-agent")
    assert plan["toolchain"]["language"] == "Python"
    assert plan["toolchain"]["version"] == "3.13"
    assert plan["toolchain"]["packages"][0].startswith("fast-agent-mcp==")
    assert plan["requirements"] == []
    assert install_plan(tmp_path, "fast-agent", "3.12")["digest"] != plan["digest"]
    with pytest.raises(ValueError, match="supported Python version"):
        install_plan(tmp_path, "fast-agent", "../../invalid")
    assert not mac_app.exists()

    monkeypatch.delenv("SUPERQODE_APP")
    terminal = install_plan(tmp_path, "fast-agent")
    assert terminal["argv"] == [
        "uv",
        "tool",
        "install",
        "--python",
        "3.13",
        "-U",
        "fast-agent-mcp",
    ]


def test_mac_app_failed_agent_upgrade_keeps_verified_launch(monkeypatch, tmp_path, mac_app):
    import shlex

    from superqode.desktop_service import configuration, managed_toolchains
    from superqode.desktop_service.connection_controls import cli_plan
    from superqode.desktop_service.routes import acp_routes

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = mac_app / "node" / "bin"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(managed_toolchains, "_install_node", lambda root, version: runtime)
    fail = False

    async def npm(argv, status, *, env, cwd):
        assert argv[:3] == [str(runtime / "node"), str(runtime / "npm"), "install"]
        assert env["PATH"].startswith(str(runtime) + ":")
        assert "OPENAI_API_KEY" not in env
        assert argv[-1].startswith("opencode-ai@")
        if fail:
            raise ValueError("npm failed")
        executable = cwd / "node_modules" / ".bin" / "opencode"
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        executable.chmod(0o700)

    monkeypatch.setattr(configuration, "run_install_command", npm)

    def route(project):
        return next(row for row in acp_routes(project) if row["id"] == "acp:opencode")

    def install(version=""):
        reviewed = configuration.install_plan(tmp_path, "opencode", version)
        return asyncio.run(
            configuration.install_agent(
                tmp_path,
                "opencode",
                lambda _: None,
                version=version,
                expected_digest=reviewed["digest"],
            )
        )

    assert not route(tmp_path)["available"]
    plan = configuration.install_plan(tmp_path, "opencode")
    versions = plan["toolchain"]["versions"]
    with pytest.raises(ValueError, match="installation plan changed"):
        asyncio.run(
            configuration.install_agent(
                tmp_path,
                "opencode",
                lambda _: None,
                version=versions[1],
                expected_digest=plan["digest"],
            )
        )
    install(versions[0])
    first = route(tmp_path)
    assert first["available"]
    argv = shlex.split(first["command"])
    assert argv[1:] == ["acp"]
    assert cli_plan(first)["argv"] == argv[:1]
    fail = True
    with pytest.raises(ValueError, match="npm failed"):
        install(versions[1])
    assert route(tmp_path)["digest"] == first["digest"]
    fail = False
    install(versions[1])
    assert route(tmp_path)["digest"] != first["digest"]
    assert Path(argv[0]).exists()
    assert configuration.install_plan(tmp_path, "opencode")["toolchain"]["version"] == versions[1]
    assert not route(tmp_path / "another project")["available"]


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
