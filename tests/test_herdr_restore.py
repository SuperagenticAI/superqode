"""Resume commands preserve durable sessions and interactive decision settings."""

from __future__ import annotations

import asyncio

from types import SimpleNamespace
import subprocess
import threading

import pytest
from click.testing import CliRunner

from superqode.agent.session_manager import SessionManager
from superqode.app.herdr import resume_command
from superqode.herdr import HerdrReporter, launch_prefix, valid_resume_argv


@pytest.fixture(autouse=True)
def isolate_startup_environment(monkeypatch):
    for key in ("SUPERQODE_HARNESS", "SUPERQODE_PROVIDER", "SUPERQODE_MODEL", "SUPERQODE_CONNECT"):
        monkeypatch.setenv(key, "")


@pytest.mark.parametrize(
    "args,expected",
    [
        (["--resume", "saved"], {"resume": "saved"}),
        (["--tui", "--resume", "saved"], {"resume": "saved"}),
        (["--fork", "saved"], {"fork_from": "saved"}),
        (
            ["--resume", "saved", "--approval-mode", "deny", "--interaction-mode", "plan"],
            {"resume": "saved", "approval_mode": "deny", "interaction_mode": "plan"},
        ),
    ],
)
def test_cli_resume_without_prompt_opens_interactive_session(monkeypatch, tmp_path, args, expected):
    from superqode.main import cli_main

    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr("superqode.app.run_textual_app", lambda **kw: calls.append(kw))
    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code == 0, result.output
    assert calls == [expected]


@pytest.mark.parametrize(
    "args", [["--resume", "one", "--fork", "two"], ["--resume", "one", "--connect", "codex"]]
)
def test_cli_rejects_conflicting_startup_connections(args):
    from superqode.main import cli_main

    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code == 2


def test_explicit_headless_resume_still_requires_prompt():
    from superqode.main import cli_main

    result = CliRunner().invoke(cli_main, ["-p", "--resume", "saved"], input="")
    assert result.exit_code == 2
    assert "Headless mode requires a prompt" in result.output


@pytest.fixture
def session_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("superqode.app.herdr.launch_prefix", lambda: ("superqode",))
    manager = SessionManager()
    manager.start_session("first", provider="ollama", model="test-model", harness_id="core")
    manager.add_user_message("Remember this conversation")
    pure = SimpleNamespace(
        session=SimpleNamespace(connected=True),
        _session_manager=manager,
        _agent=object(),
        runtime_name="builtin",
        get_current_session_id=lambda: manager._current_session_id,
    )
    return SimpleNamespace(_pure_mode=pure, approval_mode="deny", _plan_mode_enabled=True)


def test_resume_command_preserves_session_harness_model_runtime_and_modes(session_app):
    sid, argv = resume_command(session_app)
    assert sid == "first"
    assert argv == (
        "superqode",
        "--tui",
        "--approval-mode",
        "deny",
        "--interaction-mode",
        "plan",
        "--resume",
        "first",
        "--provider",
        "ollama",
        "--model",
        "test-model",
        "--harness",
        "core",
        "--runtime",
        "builtin",
    )


def test_fork_and_session_switch_update_restore_identity(session_app):
    manager = session_app._pure_mode._session_manager
    fork_id = manager.fork_current_session("child")
    sid, argv = resume_command(session_app)
    assert sid == fork_id
    assert argv[argv.index("--resume") + 1] == "child"
    manager.start_session("first")
    assert resume_command(session_app)[0] == "first"


def test_disconnect_and_unsupported_backend_replace_old_resume_with_fresh_launch(session_app):
    session_app._pure_mode.session.connected = False
    sid, argv = resume_command(session_app)
    assert sid == "" and "--resume" not in argv
    assert argv[:2] == ("superqode", "--tui")
    session_app._pure_mode.session.connected = True
    session_app._pure_mode._agent = None
    assert resume_command(session_app)[0] == ""
    assert "--resume" not in resume_command(session_app)[1]


def test_unrepresentable_resume_arguments_keep_state_reporting_available(session_app):
    manager = session_app._pure_mode._session_manager
    meta = manager.get_session_info("first")
    meta.model = "model's name"
    manager.store._save_metadata(meta)
    assert resume_command(session_app)[0] == ""
    assert "--resume" not in resume_command(session_app)[1]


@pytest.mark.parametrize(
    "argv",
    [
        ("/path/to/agent",),
        ("agent", "can't"),
        ("agent", "line\nbreak"),
        ("-agent",),
        ("agent", "é" * 4097),
        ("agent",) * 65,
    ],
)
def test_resume_validation_matches_herdr_portable_contract(argv):
    assert not valid_resume_argv(argv)


def test_source_checkout_resume_keeps_the_checkout(tmp_path, monkeypatch):
    module = tmp_path / "src" / "superqode" / "herdr.py"
    monkeypatch.setattr("superqode.herdr.__file__", str(module))
    monkeypatch.setattr("superqode.herdr.shutil.which", lambda command: "/tools/uv")
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / ".venv").mkdir()
    assert launch_prefix() == ("uv", "run", "--project", str(tmp_path), "--no-sync", "superqode")
    monkeypatch.setattr("superqode.herdr.shutil.which", lambda command: None)
    assert launch_prefix() == ("superqode",)


def test_resume_registration_failure_retries_without_losing_state(monkeypatch):
    calls = []
    received = threading.Event()
    resumed = threading.Event()

    def run(argv, **kwargs):
        calls.append(argv)
        registrations = [a for a in calls if a[2] == "report-agent-session"]
        if argv[2] == "report-agent-session":
            if len(registrations) == 1:
                return SimpleNamespace(returncode=1)
            resumed.set()
        if argv[2] == "report-metadata":
            received.set()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    reporter = HerdrReporter({"HERDR_BIN_PATH": "herdr", "HERDR_PANE_ID": "w1:p1"})
    try:
        kwargs = dict(session_id="saved", resume_argv=("superqode", "--resume", "saved"))
        reporter.report("idle", **kwargs)
        assert received.wait(3)
        reporter.report("idle", **kwargs)
        assert resumed.wait(3)
    finally:
        reporter.close()
    assert sum(a[2] == "report-agent" for a in calls) == 1
    assert sum(a[2] == "report-agent-session" for a in calls) == 2
    assert calls[-1][2] == "release-agent"


def test_herdr_stays_blocked_until_all_pending_approvals_are_resolved(session_app):
    from superqode.app.herdr import sync

    pending = ["first", "second"]
    reports = []
    session_app._pure_mode.get_pending_approvals = lambda: pending
    session_app._herdr_reporter = SimpleNamespace(report=lambda state, **kw: reports.append(state))
    sync(session_app)
    pending.pop()
    sync(session_app)
    pending.pop()
    sync(session_app)
    assert reports == ["blocked", "blocked", "idle"]


@pytest.fixture
def mounted_startup(monkeypatch, tmp_path):
    from superqode.app_main import SuperQodeApp

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for method in ("_start_models_dev_refresh", "_start_acp_registry_refresh", "_prewarm_litellm"):
        monkeypatch.setattr(SuperQodeApp, method, lambda self: None)
    calls = []
    reporter = SimpleNamespace(
        report=lambda state, **kw: calls.append((state, kw)), close=lambda: None
    )
    monkeypatch.setattr(HerdrReporter, "from_env", lambda: reporter)
    manager = SessionManager()
    manager.start_session("saved", provider="ollama", model="test-model", harness_id="core")
    manager.add_user_message("A persisted prompt")
    manager.add_assistant_message("A persisted answer")
    return SuperQodeApp, calls


async def _settle(pilot, ready, timeout=10.0):
    """Startup restore runs after mount; under full-suite load 0.3 s is not
    always enough, so poll for the restored state instead of a fixed sleep."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await pilot.pause(0.05)
        try:
            if ready():
                return
        except (AttributeError, IndexError, KeyError):
            pass
    await pilot.pause(0.3)


async def test_mounted_startup_resumes_without_running_a_new_turn(mounted_startup):
    App, calls = mounted_startup
    app = App(resume="saved", approval_mode="deny", interaction_mode="plan")
    async with app.run_test() as pilot:
        await _settle(
            pilot,
            lambda: app._pure_mode.get_current_session_id() == "saved" and calls[-1][0] == "idle",
        )
        assert app._pure_mode.get_current_session_id() == "saved"
        assert app.current_model == "test-model"
        assert app.approval_mode == "deny"
        assert app._plan_mode_enabled
        assert calls[-1][0] == "idle"
        assert calls[-1][1]["session_id"] == "saved"
        assert "--resume" in calls[-1][1]["resume_argv"]
        assert len(app._pure_mode._session_manager.get_messages()) == 2
        assert not any(state == "working" for state, _ in calls)


async def test_mounted_startup_fork_reports_child_and_keeps_original(mounted_startup):
    App, calls = mounted_startup
    app = App(fork_from="saved")
    async with app.run_test() as pilot:
        await _settle(
            pilot,
            lambda: app._pure_mode.get_current_session_id() not in {None, "", "saved"}
            and calls[-1][1]["session_id"] == app._pure_mode.get_current_session_id(),
        )
        sid = app._pure_mode.get_current_session_id()
        assert sid != "saved"
        assert app._pure_mode._session_manager.get_session_info(sid).parent_session_id == "saved"
        assert calls[-1][1]["session_id"] == sid
        assert app._pure_mode._session_manager.get_session_info("saved") is not None


async def test_missing_startup_session_is_actionable_and_ui_stays_open(mounted_startup):
    App, calls = mounted_startup
    app = App(resume="missing")
    async with app.run_test() as pilot:
        await _settle(pilot, lambda: calls[-1][0] == "blocked")
        assert calls[-1][0] == "blocked"
        assert calls[-1][1]["message"] == "Session restore failed"
        assert calls[-1][1]["session_id"] == ""
        assert app._handle_resume_session("saved", app.query_one("#log"))
        await pilot.pause()
        assert calls[-1][0] == "idle"
        assert calls[-1][1]["session_id"] == "saved"
