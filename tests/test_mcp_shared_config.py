"""Shared configuration and host controls across CLI and harnesses."""

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from superqode.mcp.config import resolve_mcp_config, load_mcp_config, find_mcp_config_file
from superqode.harness.pipy_mcp import PiPyMCPTools
from superqode.main import cli_main


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)
    return home


def write_config(path, servers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))


def test_layers_and_disabled_override(isolated_home, tmp_path):
    write_config(
        isolated_home / ".superqode/mcp.json",
        {"docs": {"url": "https://global.invalid"}, "other": {"command": "global"}},
    )
    write_config(
        tmp_path / ".superqode/mcp.json",
        {"docs": {"url": "https://project.invalid", "enabled": False}},
    )
    resolution = resolve_mcp_config(cwd=tmp_path)
    assert set(resolution.servers) == {"docs", "other"}
    assert not resolution.servers["docs"].enabled
    assert resolution.sources["docs"] == str(tmp_path / ".superqode/mcp.json")
    inline = resolve_mcp_config(
        {"mcp_servers": {"docs": {"url": "https://inline.invalid"}}}, cwd=tmp_path
    )
    assert inline.servers["docs"].config.url == "https://inline.invalid"
    assert inline.sources["docs"] == "runtime.config"
    assert set(load_mcp_config()) == {"docs", "other"}


def test_runtime_working_directory_is_resolved_after_import(tmp_path, monkeypatch):
    for name in ("one", "two"):
        write_config(
            tmp_path / name / ".superqode/mcp.json", {name: {"command": "fixture", "cwd": "tools"}}
        )
    monkeypatch.chdir(tmp_path / "one")
    assert find_mcp_config_file() == tmp_path / "one/.superqode/mcp.json"
    selected = resolve_mcp_config(cwd=tmp_path / "two")
    assert set(selected.servers) == {"two"}
    assert selected.servers["two"].config.cwd == str(tmp_path / "two/tools")


def test_invalid_override_masks_global_and_other_servers_survive(isolated_home, tmp_path):
    write_config(isolated_home / ".superqode/mcp.json", {"same": {"command": "must-not-run"}})
    write_config(
        tmp_path / ".superqode/mcp.json",
        {"same": {"transport": "typo", "command": "broken"}, "good": {"command": "fixture"}},
    )
    result = resolve_mcp_config(cwd=tmp_path)
    assert set(result.servers) == {"good"}
    assert result.errors and "same" in result.errors[0]


def test_explicit_path_and_inline_only(tmp_path, isolated_home):
    write_config(isolated_home / ".superqode/mcp.json", {"global": {"command": "fixture"}})
    write_config(tmp_path / "chosen.json", {"chosen": {"command": "fixture"}})
    assert set(resolve_mcp_config({"mcp_config": "chosen.json"}, cwd=tmp_path).servers) == {
        "chosen"
    }
    assert resolve_mcp_config({"mcp_config": False}, cwd=tmp_path).servers == {}
    assert resolve_mcp_config({"mcp_config": "missing.json"}, cwd=tmp_path).errors


def test_env_substitution_in_headers_and_commands_are_literal(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_TOKEN", "secret-fixture")
    result = resolve_mcp_config(
        {
            "mcp_config": False,
            "mcp_servers": {
                "remote": {
                    "url": "https://fixture.invalid",
                    "headers": {"Authorization": "Bearer ${FIXTURE_TOKEN}"},
                },
                "local": {
                    "command": "echo $(must-not-execute)",
                    "env": {"TOKEN": "${FIXTURE_TOKEN}"},
                },
            },
        },
        cwd=tmp_path,
    )
    assert result.servers["remote"].config.headers["Authorization"] == "Bearer secret-fixture"
    assert result.servers["local"].config.command == "echo $(must-not-execute)"


async def test_failed_background_server_does_not_hold_first_prompt(tmp_path, monkeypatch):
    from superqode.mcp.client import MCPClientManager

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def connect(self, sid):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(MCPClientManager, "connect", connect)
    write_config(tmp_path / ".superqode/mcp.json", {"slow": {"command": "fixture"}})
    bridge = await asyncio.wait_for(PiPyMCPTools.create({}, cwd=tmp_path), 0.2)
    assert len(bridge.tools) == 2
    await started.wait()
    await bridge.close()
    assert cancelled.is_set() and not bridge._startup


async def test_non_auto_connect_server_is_still_discoverable(tmp_path, monkeypatch):
    from superqode.mcp.client import MCPClientManager

    calls = []

    async def connect(self, sid):
        calls.append(sid)
        return True

    monkeypatch.setattr(MCPClientManager, "connect", connect)
    bridge = await PiPyMCPTools.create(
        {
            "mcp_config": False,
            "mcp_servers": {
                "manual": {"command": "fixture", "autoConnect": False},
                "disabled": {"command": "fixture", "enabled": False},
            },
        },
        cwd=tmp_path,
    )
    try:
        await bridge.tools[0].execute("search", {"query": "anything"})
        assert calls == ["manual"]
        with pytest.raises(ValueError, match="disabled"):
            await bridge._connected("disabled")
    finally:
        await bridge.close()


def test_cli_list_is_non_connecting_and_redacts_credentials(tmp_path):
    write_config(
        tmp_path / ".superqode/mcp.json",
        {
            "remote": {
                "url": "https://fixture.invalid",
                "headers": {"Authorization": "secret-fixture"},
            },
            "disabled": {"command": "must-not-execute", "enabled": False},
        },
    )
    result = CliRunner().invoke(cli_main, ["mcp", "list", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["servers"]) == 2
    assert all(s["state"] == "disconnected" for s in payload["servers"])
    assert "secret-fixture" not in result.output and "fixture.invalid" not in result.output


def test_cli_invalid_config_returns_failure(tmp_path):
    write_config(
        tmp_path / ".superqode/mcp.json", {"bad": {"command": "fixture", "enabled": "false"}}
    )
    result = CliRunner().invoke(cli_main, ["mcp", "list", "--cwd", str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.output)["errors"]


async def test_reload_closes_changed_and_removed_transports(tmp_path, monkeypatch):
    from superqode.mcp.client import MCPClientManager

    manager = MCPClientManager()
    write_config(
        tmp_path / ".superqode/mcp.json",
        {"same": {"command": "one"}, "removed": {"command": "two"}},
    )
    manager.load_config()
    calls = []

    async def disconnect(sid):
        calls.append(sid)

    monkeypatch.setattr(manager, "disconnect", disconnect)
    write_config(
        tmp_path / ".superqode/mcp.json",
        {"same": {"command": "new"}, "added": {"command": "three"}},
    )
    await manager.reload_config(cwd=tmp_path)
    assert set(calls) == {"same", "removed"}
    assert set(manager.get_server_configs()) == {"same", "added"}


async def test_host_login_and_logout_use_shared_manager(tmp_path, monkeypatch):
    bridge = await PiPyMCPTools.create(
        {
            "mcp_config": False,
            "mcp_servers": {"remote": {"url": "https://fixture.invalid", "autoConnect": False}},
        },
        cwd=tmp_path,
    )
    actions = []

    async def login(sid):
        actions.append(("login", sid))
        return True

    async def reconnect(sid):
        actions.append(("reconnect", sid))
        return True

    async def disconnect(sid):
        actions.append(("disconnect", sid))

    async def clear(sid):
        actions.append(("clear", sid))

    monkeypatch.setattr(bridge.manager, "authenticate_server", login)
    monkeypatch.setattr(bridge.manager, "reconnect", reconnect)
    monkeypatch.setattr(bridge.manager, "disconnect", disconnect)
    monkeypatch.setattr(bridge.manager, "clear_server_credentials", clear)
    try:
        assert (await bridge.control("login", "remote"))["success"]
        assert (await bridge.control("logout", "remote"))["success"]
        assert actions == [
            ("login", "remote"),
            ("reconnect", "remote"),
            ("disconnect", "remote"),
            ("clear", "remote"),
        ]
    finally:
        await bridge.close()
