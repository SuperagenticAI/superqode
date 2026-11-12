"""Native CLI settings must reach real processes without sending discovery prompts."""

import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_desktop_connect_workflow import desktop  # noqa: F401
from superqode.desktop_service.connection_controls import (
    apply_runtime_controls,
    cli_output,
    cli_plan,
    parse_agy_models,
    run_command,
)
from superqode.desktop_service.connection_probe import probe_route


@pytest.fixture
def agy(tmp_path, monkeypatch):
    binary = tmp_path / "agy"
    trace = tmp_path / "trace.jsonl"
    binary.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        f"with open({str(trace)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "assert '--version' in sys.argv or 'GEMINI_API_KEY' not in os.environ\n"
        "if sys.argv[1:] == ['--version']: print('agy 1.1.5')\n"
        "elif sys.argv[1:] == ['models']: print('Available models:\\ngemini-fast\\ngemini-capable\\ngemini-fast')\n"
        "elif '--print' in sys.argv: print('model choice applied')\n"
        "else: print('CLI information')\n"
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-be-used")
    from superqode.runtime.antigravity_status import clear_antigravity_cli_cache

    clear_antigravity_cli_cache()
    yield binary, trace
    clear_antigravity_cli_cache()


def poll(service, operation):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        record = service.dispatch("connect.auth.poll", operation)
        if record["state"] != "running":
            return record
        time.sleep(0.02)
    pytest.fail("Control operation did not finish")


def test_agy_discovery_and_selected_options_reach_real_worker(desktop, agy):
    service, project, _ = desktop
    _, trace = agy
    metadata = poll(
        service,
        service.dispatch(
            "connect.auth.start",
            {
                "project": project["id"],
                "reference": "connection:antigravity",
                "action": "probe",
            },
        ),
    )
    assert metadata["state"] == "completed", metadata
    session = metadata["result"]["session"]
    assert [row["id"] for row in session["models"]["availableModels"]] == [
        "gemini-fast",
        "gemini-capable",
    ]
    assert {row["id"] for row in session["config_options"]} == {"agent", "effort"}
    assert service.dispatch("jobs.list", {}) == []
    assert all("--print" not in json.loads(line) for line in trace.read_text().splitlines())
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": "connection:antigravity",
            "prompt": "hello",
            "model": "gemini-capable",
            "acp_options": {"config": {"agent": "researcher", "effort": "high"}},
        },
    )
    from test_desktop_service import wait_job

    record = wait_job(service, job["id"])
    assert record["status"] == "completed", record
    commands = [json.loads(line) for line in trace.read_text().splitlines()]
    turn = next(args for args in commands if "--print" in args)
    for flag, value in [
        ("--model", "gemini-capable"),
        ("--agent", "researcher"),
        ("--effort", "high"),
    ]:
        assert turn[turn.index(flag) + 1] == value
    assert "must-not-be-used" not in json.dumps(record)


def test_native_catalog_requires_matching_route_and_explicit_command(desktop, agy):
    service, project, _ = desktop
    params = {"project": project["id"], "reference": "connection:antigravity"}
    catalog = service.dispatch("connect.controls", params)
    assert {row["id"] for row in catalog["commands"]} >= {"models", "agents", "plugins", "help"}
    assert catalog["cli"]["argv"] == [str(agy[0])]
    with pytest.raises(ValueError, match="changed"):
        service.dispatch(
            "connect.command.start", {**params, "command": "models", "expected_digest": "wrong"}
        )
    result = poll(
        service,
        service.dispatch(
            "connect.command.start",
            {
                **params,
                "command": "models",
                "expected_digest": catalog["digest"],
            },
        ),
    )
    assert result["state"] == "completed"
    assert "gemini-fast" in result["result"]["text"]
    assert service.dispatch("jobs.list", {}) == []
    rejected = poll(
        service,
        service.dispatch(
            "connect.command.start",
            {
                **params,
                "command": "update; echo hacked",
                "expected_digest": catalog["digest"],
            },
        ),
    )
    assert rejected["state"] == "failed"


@pytest.mark.asyncio
async def test_cli_timeout_and_cancellation_reap_process(tmp_path):
    import signal

    if os.name == "nt":
        pytest.skip("Process group assertions are POSIX-specific")
    pid_file = tmp_path / "pid"
    script = (
        "import os,time; open("
        + repr(str(pid_file))
        + ",'w').write(str(os.getpid())); time.sleep(60)"
    )
    with pytest.raises(ValueError, match="did not respond"):
        await cli_output(tmp_path, [sys.executable, "-c", script], timeout=0.3)
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    pid_file.unlink()
    task = asyncio.create_task(cli_output(tmp_path, [sys.executable, "-c", script]))
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), signal.SIGCONT)


@pytest.mark.asyncio
async def test_cli_errors_redact_keys_and_do_not_return_silent_success(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_API_KEY", "secret-test-value")
    with pytest.raises(ValueError, match="bad key: \\[REDACTED\\]"):
        await cli_output(
            tmp_path,
            [
                sys.executable,
                "-c",
                "import os,sys; sys.stderr.write('bad key: '+os.environ['FIXTURE_API_KEY']); sys.exit(3)",
            ],
        )
    with pytest.raises(ValueError, match="too large"):
        await cli_output(tmp_path, [sys.executable, "-c", "print('x'*300000)"])


def test_settings_fail_closed_and_never_offer_unrestricted_sandbox():
    runtime = SimpleNamespace(
        set_model=Mock(),
        set_agent=Mock(),
        set_reasoning_effort=Mock(),
        set_sandbox_backend=Mock(),
        set_approval_policy=Mock(),
    )
    plan = apply_runtime_controls(
        runtime,
        {"runtime": "codex-cli"},
        {
            "config": {
                "effort": "high",
                "sandbox": "read-only",
                "approval": "on-request",
                "plan": "on",
            },
        },
    )
    assert plan == "on"
    runtime.set_reasoning_effort.assert_called_once_with("high")
    runtime.set_sandbox_backend.assert_called_once_with("read-only")
    runtime.set_approval_policy.assert_called_once_with("on-request")
    for config in [
        {"unknown": "anything"},
        {"sandbox": "danger-full-access"},
        {"effort": "invalid"},
    ]:
        with pytest.raises(ValueError):
            apply_runtime_controls(runtime, {"runtime": "codex-cli"}, {"config": config})
    with pytest.raises(ValueError, match="session modes"):
        apply_runtime_controls(runtime, {"runtime": "copilot-sdk"}, {"mode": "autopilot"})


def test_agy_parser_ignores_headings_and_preserves_real_ids():
    assert parse_agy_models("Models\n# example\n----\nmodel/a\nmodel/a\ngemini-3\nnot an id") == [
        {"id": "model/a", "name": "model/a"},
        {"id": "gemini-3", "name": "gemini-3"},
    ]


def test_custom_acp_launcher_is_not_guessed_as_interactive(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    assert cli_plan({"command": "npx untrusted-acp --stdio", "agent_id": "custom"}) is None
    assert (
        cli_plan({"command": "ssh host opencode acp", "agent_id": "opencode", "custom": True})
        is None
    )
    assert cli_plan({"command": "opencode acp", "agent_id": "opencode"})["argv"] == [
        "/bin/opencode"
    ]


@pytest.mark.asyncio
async def test_grok_discovery_uses_subscription_cli_without_importing_token(tmp_path, monkeypatch):
    binary = tmp_path / "grok"
    binary.write_text(
        "#!"
        + sys.executable
        + "\nimport sys\nassert sys.argv[1:] == ['models']\nprint('Default model: grok-fast\\nAvailable models:\\n* grok-fast\\n* grok-capable')\n"
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    imported = Mock(side_effect=AssertionError("Must not import credentials"))
    monkeypatch.setattr("superqode.providers.grok_cli_auth.import_cli_token", imported)
    metadata = await probe_route(
        tmp_path,
        {"available": True, "runtime": "grok-cli", "subscription_vendor": "grok"},
        lambda _: None,
    )
    assert [m["id"] for m in metadata["session"]["models"]["availableModels"]] == [
        "grok-fast",
        "grok-capable",
    ]
    imported.assert_not_called()


@pytest.mark.asyncio
async def test_codex_inventory_is_bounded_redacted_and_closed(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    runtime = SimpleNamespace(
        verify_account=AsyncMock(),
        inspect=AsyncMock(
            return_value={
                "data": [{"name": "skill", "api_key": "hidden"}],
                "nextCursor": "next-page",
            }
        ),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr("superqode.runtime.codex_cli.CodexCLIRuntime", lambda **kwargs: runtime)
    result = await run_command(
        tmp_path,
        {"available": True, "runtime": "codex-cli", "subscription_vendor": "codex"},
        "skills",
        lambda _: None,
    )
    assert "hidden" not in json.dumps(result)
    assert result["next_cursor"] == "next-page"
    runtime.verify_account.assert_awaited_once()
    runtime.inspect.assert_awaited_once_with("skills", cursor=None)
    runtime.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_model_inventory_advances_to_the_next_page(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, call

    from superqode.agent.loop import AgentConfig
    from superqode.runtime.codex_cli import CodexCLIRuntime

    runtime = CodexCLIRuntime(
        config=AgentConfig(provider="agent", model="", working_directory=tmp_path)
    )
    monkeypatch.setattr(runtime, "verify_account", AsyncMock())
    monkeypatch.setattr(runtime, "_ensure_started", AsyncMock())
    monkeypatch.setattr(runtime, "aclose", AsyncMock())
    request = AsyncMock(
        side_effect=[
            {"data": [{"id": "model-one"}], "nextCursor": "page-two"},
            {"data": [{"id": "model-two"}], "nextCursor": None},
        ]
    )
    monkeypatch.setattr(runtime, "_timed_request", request)
    monkeypatch.setattr("superqode.runtime.codex_cli.CodexCLIRuntime", lambda **kwargs: runtime)
    route = {"available": True, "runtime": "codex-cli"}

    first = await run_command(tmp_path, route, "models", lambda _: None)
    second = await run_command(tmp_path, route, "models", lambda _: None, first["next_cursor"])

    assert second["data"]["data"] == [{"id": "model-two"}]
    assert not second["next_cursor"]
    assert request.await_args_list == [
        call("model/list", {"includeHidden": False}),
        call("model/list", {"includeHidden": False, "cursor": "page-two"}),
    ]
