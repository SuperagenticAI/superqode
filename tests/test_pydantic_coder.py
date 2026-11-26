"""Shared catalog, native setup, isolated installation and credential boundaries."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys

from click.testing import CliRunner
import pytest

from superqode.pydantic_coder import COMMAND, IDENTITY, VERSIONS, installed
from superqode.pydantic_coder import setup as coder_setup
from superqode.commands.pydantic_coder import pydantic_coder
from superqode.agents.discovery import read_agents
from superqode.agents.install_commands import managed_agent_install
from superqode.commands.acp import check_agent_installed
from superqode.desktop_service.configuration import install_plan
from superqode.desktop_service.routes import acp_routes


def agent():
    return asyncio.run(read_agents())[IDENTITY]


def test_catalog_and_native_route_check_the_private_runtime_not_the_host_cli(tmp_path, monkeypatch):
    target = tmp_path / "runtime/bin/python"
    monkeypatch.setenv("SUPERQODE_PYDANTIC_CODER_PYTHON", str(target))
    assert not check_agent_installed(agent())
    route = next(r for r in acp_routes(tmp_path) if r["id"] == "acp:pydantic-coder")
    assert not route["available"]
    assert route["install"]
    assert route["experimental"]
    assert route["command"].startswith(sys.executable)
    assert "superqode.pydantic_coder.launcher" in route["command"]
    target.parent.mkdir(parents=True)
    target.touch(mode=0o700)
    (target.parent.parent / "superqode-pydantic-coder.json").write_text(json.dumps(VERSIONS))
    assert installed()
    assert check_agent_installed(agent())
    assert next(r for r in acp_routes(tmp_path) if r["id"] == route["id"])["available"]
    (target.parent.parent / "superqode-pydantic-coder.json").write_text("{}")
    assert not installed()


def test_native_install_uses_bundled_setup_not_path_or_registry_commands(tmp_path, monkeypatch):
    from superqode.desktop_service import configuration

    plan = install_plan(tmp_path, "acp:pydantic-coder")
    assert plan["argv"] == [sys.executable, "-m", "superqode.pydantic_coder.setup", "--install"]
    assert plan["requirements"][0]["name"] == "uv"
    monkeypatch.setenv("SUPERQODE_APP", "1")
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(tmp_path / "app-state"))
    assert install_plan(tmp_path, "acp:pydantic-coder")["requirements"] == []
    assert managed_agent_install({**agent(), "identity": "untrusted.example"}) is None
    assert managed_agent_install({**agent(), "user_defined": True}) is None
    assert configuration.installer_requirements(["uv", "tool", "install", "fixture"])


@pytest.mark.parametrize("action,install", [("setup", True), ("doctor", False)])
def test_cli_setup_and_doctor_dispatch_without_loading_v2(monkeypatch, tmp_path, action, install):
    calls = []
    monkeypatch.setattr(
        coder_setup,
        "setup_runtime",
        lambda target, install: calls.append((target, install)) or VERSIONS,
    )
    target = tmp_path / "runtime/bin/python"
    result = CliRunner().invoke(pydantic_coder, [action, "--python", str(target)])
    assert result.exit_code == 0, result.output
    assert calls == [(target, install)]


def test_install_is_explicit_isolated_and_verified(tmp_path, monkeypatch):
    target = tmp_path / "runtime/bin/python"
    target.parent.mkdir(parents=True)
    target.touch()
    (target.parent.parent / "pyvenv.cfg").touch()
    calls = []
    monkeypatch.setattr(coder_setup, "find_uv", lambda: "/fixture/uv")
    monkeypatch.setenv("GITHUB_TOKEN", "never-forward-this")

    def run(argv, **kwargs):
        calls.append(argv)
        if "--check" in argv:
            assert "GITHUB_TOKEN" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(VERSIONS))

    monkeypatch.setattr(coder_setup.subprocess, "run", run)
    assert coder_setup.setup_runtime(target, install=True) == VERSIONS
    assert "pydantic-ai-harness[coder,acp]==0.75.0" in calls[0]
    assert (
        json.loads((target.parent.parent / "superqode-pydantic-coder.json").read_text()) == VERSIONS
    )
    calls.clear()
    coder_setup.setup_runtime(target, install=False)
    assert len(calls) == 1 and "--check" in calls[0]
    with pytest.raises(ValueError, match="separate virtual environment"):
        coder_setup.setup_runtime(Path(sys.prefix) / "bin/python", install=True)


def test_missing_and_incompatible_runtimes_are_actionable(tmp_path, monkeypatch):
    result = CliRunner().invoke(pydantic_coder, ["doctor", "--python", str(tmp_path / "missing")])
    assert result.exit_code == 1
    assert "pydantic-coder setup" in result.output
    assert "Traceback" not in result.output
    target = tmp_path / "python"
    target.touch()
    monkeypatch.setattr(
        coder_setup.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="{}")
    )
    with pytest.raises(ValueError, match="check failed"):
        coder_setup.setup_runtime(target)


def test_launcher_does_not_download_and_passes_only_supported_credentials(
    tmp_path, monkeypatch, capsys
):
    from superqode.pydantic_coder import launcher
    from superqode.providers import credentials

    monkeypatch.setattr(launcher, "installed", lambda: False)
    assert launcher.main([]) == 1
    assert "setup" in capsys.readouterr().err
    monkeypatch.setattr(credentials, "provider_api_key", lambda definition: None)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:9999/v1")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "unrelated-secret")
    monkeypatch.setenv("PYTHONPATH", "poison")
    env = launcher.worker_environment()
    assert env["OPENAI_API_KEY"] == "fixture-key"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:9999/v1"
    assert "GITHUB_TOKEN" not in env and "PYTHONPATH" not in env


@pytest.mark.asyncio
async def test_cli_connect_uses_explicit_denial_instead_of_the_legacy_autoapproval(
    monkeypatch, tmp_path
):
    from superqode.acp import client as acp_client
    from superqode.commands import pydantic_coder as command
    from rich.console import Console
    from rich.prompt import Confirm

    prompts = iter(["write fixture", "/quit"])
    decisions = []
    monkeypatch.setattr("superqode.pydantic_coder.installed", lambda: True)
    monkeypatch.setattr(Console, "input", lambda *a, **kw: next(prompts))
    monkeypatch.setattr(Confirm, "ask", lambda *a, **kw: False)

    class Client:
        def __init__(self, root, command, **kwargs):
            self.permission = kwargs["on_permission_request"]

        async def start(self):
            return True

        def get_session_id(self):
            return "fixture-session"

        async def send_prompt(self, prompt):
            decisions.append(
                await self.permission(
                    [
                        {"kind": "allow_once", "optionId": "allow"},
                        {"kind": "reject_once", "optionId": "reject"},
                    ],
                    {"title": "Write fixture"},
                )
            )
            return "end_turn"

        async def stop(self):
            pass

    monkeypatch.setattr(acp_client, "ACPClient", Client)
    assert await command.connect_interactive(tmp_path) == 0
    assert decisions == ["reject"]
