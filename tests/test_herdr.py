"""Herdr reporting never blocks the TUI or gives children pane authority."""

from __future__ import annotations

import json
import asyncio
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from superqode.herdr import HerdrReporter, child_env, sdk_env_overrides


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Herdr report did not arrive")
        time.sleep(0.01)


def environment(binary="/missing/herdr"):
    return {
        **os.environ,
        "HERDR_ENV": "1",
        "HERDR_PANE_ID": "w1:p1",
        "HERDR_SOCKET_PATH": "/tmp/test-herdr.sock",
        "HERDR_BIN_PATH": str(binary),
    }


@pytest.mark.parametrize(
    "missing", ["HERDR_ENV", "HERDR_PANE_ID", "HERDR_BIN_PATH", "HERDR_SOCKET_PATH"]
)
def test_incomplete_environment_does_not_start_reporter(monkeypatch, missing):
    for key, value in environment().items():
        if key.startswith("HERDR_"):
            monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    assert HerdrReporter.from_env() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_cli_reports_literal_arguments_metadata_and_ordered_release(tmp_path):
    log = tmp_path / "requests.jsonl"
    binary = tmp_path / "herdr with spaces"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['TEST_HERDR_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    binary.chmod(0o755)
    env = {**environment(binary), "TEST_HERDR_LOG": str(log)}

    def requests():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    reporter = HerdrReporter(env)
    try:
        for index, state in enumerate(("idle", "working", "blocked", "working", "idle")):
            reporter.report(
                state,
                message="Approval needed" if state == "blocked" else "",
                harness="codex",
                model="model $(literal)",
            )
            wait_for(lambda: len(requests()) >= (index + 1) * 2)
        # Duplicate state and metadata need no CLI calls.
        reporter.report("idle", harness="codex", model="model $(literal)")
    finally:
        reporter.close()
    reporter.close()
    calls = requests()
    states = [call[call.index("--state") + 1] for call in calls if call[1] == "report-agent"]
    assert states == ["idle", "working", "blocked", "working", "idle"]
    assert calls[-1][1] == "release-agent"
    assert sum(call[1] == "release-agent" for call in calls) == 1
    assert all(call[:1] == ["pane"] and call[2] == "w1:p1" for call in calls)
    assert any("model=model $(literal)" in call for call in calls)
    assert all("--applies-to-source" in call for call in calls if call[1] == "report-metadata")
    seqs = [int(call[call.index("--seq") + 1]) for call in calls]
    assert seqs == sorted(set(seqs))
    assert not any("--agent-session-id" in call or "--resume" in call for call in calls)
    restarted = HerdrReporter(env)
    restarted.close()
    assert int(requests()[-1][requests()[-1].index("--seq") + 1]) > seqs[-1]


def test_slow_report_keeps_latest_state_and_release_is_last(monkeypatch):
    entered, unblock = threading.Event(), threading.Event()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            entered.set()
            assert unblock.wait(3)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    reporter = HerdrReporter(environment())
    try:
        reporter.report("idle")
        assert entered.wait(3)
        # These return while the writer is blocked. Only the latest survives.
        reporter.report("working")
        reporter.report("blocked")
        reporter.report("idle", harness="review")
        unblock.set()
        wait_for(lambda: any("harness=review" in call for call in calls))
    finally:
        unblock.set()
        reporter.close()
    assert not any("--state" in call and "blocked" in call for call in calls)
    assert not any("--state" in call and "working" in call for call in calls)
    assert calls[-1][2] == "release-agent"
    reporter.report("working")
    assert calls[-1][2] == "release-agent"


@pytest.mark.parametrize("failure", [OSError("missing"), subprocess.TimeoutExpired("herdr", 0.5)])
def test_reporting_failures_are_ignored_and_retry_on_next_update(monkeypatch, failure):
    attempted = threading.Event()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 0.5
        if len(calls) == 1:
            attempted.set()
            raise failure
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    reporter = HerdrReporter(environment())
    try:
        reporter.report("working")
        assert attempted.wait(3)
        reporter.report("working")
        wait_for(lambda: len(calls) >= 3)
    finally:
        reporter.close()
    assert calls[-1][2] == "release-agent"


def test_child_environment_keeps_credentials_and_parent_intact(monkeypatch):
    from superqode.providers.subscription_env import subscription_child_env
    from superqode.tools.env_policy import build_shell_env

    env = {**environment(), "HERDR_AGENT": "claude", "OPENAI_API_KEY": "test-key"}
    clean = child_env(env)
    assert not any(key.startswith("HERDR_") for key in clean)
    assert clean["OPENAI_API_KEY"] == "test-key"
    assert env["HERDR_ENV"] == "1"
    for key, value in env.items():
        if key.startswith("HERDR_"):
            monkeypatch.setenv(key, value)
    assert all(value == "" for value in sdk_env_overrides().values())
    assert "HERDR_PANE_ID" in sdk_env_overrides()
    assert not any(key.startswith("HERDR_") for key in build_shell_env(env))
    subscription_env, _ = subscription_child_env("claude", env)
    assert not any(key.startswith("HERDR_") for key in subscription_env)
    assert os.environ["HERDR_ENV"] == "1"


async def test_mounted_tui_reports_work_approval_question_completion_and_exit(monkeypatch):
    from superqode.app_main import SuperQodeApp

    calls, closed = [], []
    reporter = SimpleNamespace(
        report=lambda state, **kw: calls.append((state, kw)), close=lambda: closed.append(True)
    )
    monkeypatch.setattr(HerdrReporter, "from_env", lambda: reporter)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_acp_registry_refresh", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert calls[-1][0] == "idle"
        app._set_status_runtime("codex-sdk")
        app._set_status_model("test-model")
        app.is_busy = True
        await pilot.pause()
        assert calls[-1][0] == "working"
        assert calls[-1][1]["model"] == "test-model"
        log = app.query_one("#log")
        app._show_permission_prompt("bash", {"command": "echo test"}, log)
        await pilot.pause()
        assert calls[-1][0] == "blocked"
        assert calls[-1][1]["message"] == "Approval needed"
        assert app._handle_permission_input("no")
        await pilot.pause()
        assert calls[-1][0] == "working"
        # A timed-out runtime approval clears its block, too.
        await asyncio.to_thread(
            app._request_runtime_permission, "bash", {"command": "echo test"}, log, timeout=0.05
        )
        await pilot.pause()
        assert calls[-1][0] == "working"
        app._permission_pending = True
        app._awaiting_agent_question = True
        app._permission_pending = False
        await pilot.pause()
        assert calls[-1][0] == "blocked"
        assert calls[-1][1]["message"] == "Answer needed"
        app._awaiting_agent_question = False
        await pilot.pause()
        assert calls[-1][0] == "working"
        app.is_busy = False
        await pilot.pause()
        assert calls[-1][0] == "idle"
    assert closed == [True]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell env command")
async def test_shell_child_has_no_herdr_authority(tmp_path, monkeypatch):
    from superqode.tools import shell_session
    from superqode.tools.base import ToolContext

    for key, value in environment().items():
        if key.startswith("HERDR_"):
            monkeypatch.setenv(key, value)
    try:
        result = await shell_session.ShellSessionTool().execute(
            {"action": "open", "command": "env", "yield_ms": 3000},
            ToolContext(session_id="test", working_directory=tmp_path),
        )
        assert result.success
        assert "HERDR_" not in result.output
        assert os.environ["HERDR_PANE_ID"] == "w1:p1"
    finally:
        shell_session._cleanup_all_sessions()
