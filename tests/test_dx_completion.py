"""Automation framing, configured defaults, recovery, and trusted command regressions."""

import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import click
from click.testing import CliRunner
import pytest

from superqode.agent.loop import AgentConfig, AgentLoop, AgentResponse
from superqode.agent.session_manager import SessionManager
from superqode.cli_output import DiagnosticStream
from superqode.main import cli_main
from superqode.project_commands import command_scope, discover_project_commands
from superqode.project_trust import set_project_trust
from superqode.providers.default_model import ModelTarget, resolve_default_model
from superqode.providers.gateway.base import GatewayResponse
from superqode.tools.base import ToolRegistry
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager
from superqode.undo_manager import UndoManager
from test_agent_loop_harness import ScriptedGateway


@pytest.fixture
def native_default(monkeypatch):
    monkeypatch.setattr(
        "superqode.providers.default_model.resolve_default_model",
        lambda *a, **k: ModelTarget("test", "model", "test"),
    )


@pytest.mark.parametrize("mode", ["json", "jsonl"])
def test_machine_setup_failures_are_json(mode, native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner(mix_stderr=False).invoke(cli_main, ["-p", "--mode", mode], input="")
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["type"] == "superqode.error"
    assert payload["success"] is False
    assert payload["error_code"] == "invalid_request"
    assert "prompt" in payload["error"]
    assert not result.stderr


@pytest.mark.parametrize("mode", ["json", "jsonl"])
def test_output_remains_machine_readable_when_dependency_prints(
    mode, native_default, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROVIDER_API_KEY", "secret-test-value")

    async def run(**kwargs):
        print("\x1b[31mProvider banner\x1b[0m API_KEY=secret-test-value")
        if kwargs.get("on_event"):
            kwargs["on_event"]("tool_start", {"tool": "read"})
            kwargs["on_event"]("tool_end", {"tool": "read", "success": True})
        return AgentResponse("done", [], 1, 1, "complete")

    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner(mix_stderr=False).invoke(
        cli_main, ["-p", "--mode", mode, "--changes", "none", "hello"]
    )
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[-1]["type"] == "superqode.result"
    assert rows[-1]["content"] == "done" and rows[-1]["success"]
    if mode == "jsonl":
        assert [row["sequence"] for row in rows] == list(range(1, 5))
        assert [row["type"] for row in rows][1:3] == ["superqode.tool_start", "superqode.tool_end"]
    assert "Provider banner" in result.stderr
    assert "secret-test-value" not in result.stderr
    assert "\x1b" not in result.stderr


def test_raw_sdk_errors_do_not_leak_secrets(native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run(**kwargs):
        return AgentResponse(
            "",
            [],
            0,
            1,
            "error",
            error="BadRequestError request={'credential': 'unpatterned-secret', 'prompt': 'private user task'}",
        )

    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner(mix_stderr=False).invoke(cli_main, ["-p", "--mode", "json", "hello"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert "superqode doctor" in payload["error"]
    assert "unpatterned-secret" not in result.output
    assert "private user task" not in result.output


def test_split_diagnostic_writes_are_redacted(monkeypatch):
    monkeypatch.setenv("PROVIDER_API_KEY", "abc-secret-token")
    output = io.StringIO()
    stream = DiagnosticStream(output)
    stream.write("credential=abc-sec")
    stream.write("ret-token\n")
    assert "abc-secret-token" not in output.getvalue()


def test_debug_log_redacts_stored_credentials_and_is_private(tmp_path, monkeypatch):
    import logging
    from superqode.auth import ApiAuth
    from superqode.debug_logging import configure_debug_log

    monkeypatch.setattr("superqode.auth.all", lambda: {"test": ApiAuth(key="opaque-credential")})
    monkeypatch.setenv("SUPERQODE_DEBUG", "")
    monkeypatch.setenv("SUPERQODE_LOG_FILE", "")
    path = tmp_path / "debug.log"
    handler = configure_debug_log(path)
    try:
        logging.getLogger("superqode.test").debug("credential=opaque-credential")
        assert "opaque-credential" not in path.read_text()
        assert "[redacted]" in path.read_text()
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        logging.getLogger("superqode").removeHandler(handler)
        handler.close()
        assert handler.stream.closed


def test_debug_log_supports_python_without_descriptor_chmod(tmp_path, monkeypatch):
    import logging
    from superqode.debug_logging import configure_debug_log

    monkeypatch.delattr(os, "fchmod", raising=False)
    handler = configure_debug_log(tmp_path / "logs/debug.log")
    try:
        logging.getLogger("superqode.test").debug("portable log entry")
        assert "portable log entry" in (tmp_path / "logs/debug.log").read_text()
    finally:
        logging.getLogger("superqode").removeHandler(handler)
        handler.close()


def test_defaults_use_installed_local_model_and_respect_explicit_selection(monkeypatch):
    import superqode.providers.default_model as defaults

    monkeypatch.delenv("SUPERQODE_PROVIDER", raising=False)
    monkeypatch.delenv("SUPERQODE_MODEL", raising=False)
    monkeypatch.setattr(defaults, "provider_api_key", lambda _: None)
    monkeypatch.setattr(
        defaults,
        "installed_models",
        lambda provider: ["qwen-local:latest"] if provider == "ollama" else [],
    )
    target = resolve_default_model()
    assert target.provider == "ollama" and target.model == "qwen-local:latest"
    explicit = resolve_default_model("anthropic", "my-selected-model")
    assert explicit.model == "my-selected-model" and explicit.provider == "anthropic"
    monkeypatch.setattr(defaults, "installed_models", lambda _: [])
    assert resolve_default_model() is None


def test_continue_restores_project_connection(native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("saved", provider="ollama", model="installed")
    manager.add_user_message("prior task")

    async def run(**kwargs):
        assert kwargs["session_id"] == "saved"
        assert kwargs["provider"] == "ollama" and kwargs["model"] == "installed"
        assert kwargs["runtime"] == "builtin"
        return AgentResponse("continued", [], 0, 1, "complete")

    # Test restoration with the actual resolver, which accepts explicit pairs.
    monkeypatch.setattr(
        "superqode.providers.default_model.resolve_default_model", resolve_default_model
    )
    monkeypatch.delenv("SUPERQODE_PROVIDER", raising=False)
    monkeypatch.delenv("SUPERQODE_MODEL", raising=False)
    monkeypatch.setenv("SUPERQODE_RUNTIME", "codex-cli")
    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner(mix_stderr=False).invoke(
        cli_main, ["--continue", "-p", "--mode", "json", "continue this task"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["content"] == "continued"


@pytest.mark.asyncio
async def test_compact_now_retains_transcript_and_resumes_from_summary(tmp_path):
    directory = str(tmp_path / "sessions")
    manager = SessionManager(directory)
    manager.start_session("compact", provider="test", model="model")
    manager.add_user_message("first question " * 50)
    manager.add_assistant_message("first answer " * 50)
    manager.add_user_message("current question")
    manager.add_assistant_message("current answer")
    original = manager.get_messages()
    gateway = ScriptedGateway(
        [GatewayResponse(content="Summary: preserve file paths and pending tests")]
    )
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.core(),
        config=AgentConfig(
            provider="test",
            model="model",
            working_directory=tmp_path,
            enable_session_storage=True,
            session_storage_dir=directory,
            session_id="compact",
        ),
    )
    result = await loop.compact_now("Focus on pending tests")
    assert result["success"]
    assert manager.get_messages() == original
    manager.add_user_message("new question")
    restored = loop._load_stored_messages()
    assert "Summary: preserve" in restored[0].content
    assert restored[-1].content == "new question"
    loop.run_active = True
    assert not (await loop.compact_now())["success"]
    loop.run_active = False
    manager.rewind_to_user_message(2)
    assert "summary" not in " ".join(m.content.lower() for m in loop._load_stored_messages())
    backup = manager.store.last_rewind_backup
    assert len(manager.store.get_messages(backup)) == 5


@pytest.fixture
def git_project(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, check=True
        ).stdout

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "file.txt").write_text("original")
    git("add", "file.txt")
    git("commit", "-m", "initial")
    return tmp_path, git


def test_undo_redo_are_durable_and_preserve_index_and_later_edits(git_project):
    from superqode.app.task_changes import TaskChanges

    root, git = git_project
    file = root / "file.txt"
    file.write_text("staged")
    git("add", "file.txt")
    file.write_text("my prior edit")
    original_index, head = git("ls-files", "--stage"), git("rev-parse", "HEAD")
    task = TaskChanges(root).capture()
    undo = UndoManager(root)
    undo.initialize()
    undo.register_task(task)
    file.write_text("agent edit")
    (root / "created.txt").write_bytes(b"\x00binary")
    task.finish([])
    undo.seal_task(task)
    file.write_text("later user edit")
    assert undo.undo() is None
    assert "changed after" in undo.last_error
    assert (root / "created.txt").exists()
    file.write_text("agent edit")
    assert undo.undo()
    assert file.read_text() == "my prior edit"
    assert not (root / "created.txt").exists()
    restored = UndoManager(root)
    assert restored.initialize() and restored.can_redo()
    assert restored.redo()
    assert file.read_text() == "agent edit"
    assert (root / "created.txt").read_bytes() == b"\x00binary"
    assert git("ls-files", "--stage") == original_index
    assert git("rev-parse", "HEAD") == head


def test_review_file_undo_survives_restart_and_leaves_other_changes(git_project):
    from superqode.app.task_changes import TaskChanges
    from superqode.app.mixins.helper_diff_review import HelperDiffReviewMixin

    root, git = git_project
    (root / "first.txt").write_text("original first")
    (root / "second.txt").write_text("original second")
    git("add", ".")
    git("commit", "-m", "baseline")
    manager = UndoManager(root)
    assert manager.initialize()
    task = TaskChanges(root).capture()
    manager.register_task(task)
    (root / "first.txt").write_text("agent first")
    (root / "second.txt").write_text("agent second")
    task.finish([])
    manager.seal_task(task)
    view = SimpleNamespace(
        is_busy=False, _undo_manager=manager, _task_changes_history={task.id: task}
    )
    result = HelperDiffReviewMixin._undo_task_file(view, task.id, "first.txt")
    assert result == "Undid task changes in first.txt."
    restored = UndoManager(root)
    assert restored.initialize() and restored.undo()
    assert (root / "first.txt").read_text() == "original first"
    assert (root / "second.txt").read_text() == "original second"
    assert restored.redo()
    assert (root / "first.txt").read_text() == "original first"
    assert (root / "second.txt").read_text() == "agent second"


@pytest.mark.parametrize("operation", ["restore", "restore_file"])
@pytest.mark.parametrize("failure_on", [1, 2])
def test_checkpoint_restore_storage_failure_keeps_original_files(
    operation, failure_on, git_project, monkeypatch
):
    from superqode.app.task_changes import TaskChanges

    root, git = git_project
    (root / "file.txt").write_text("original")
    manager = UndoManager(root)
    assert manager.initialize()
    task = TaskChanges(root).capture()
    manager.register_task(task)
    (root / "file.txt").write_text("agent result")
    task.finish([])
    manager.seal_task(task)
    save = manager._save
    count = 0

    def fail(*args, **kwargs):
        nonlocal count
        count += 1
        if count == failure_on:
            raise OSError("Disk is full")
        return save(*args, **kwargs)

    monkeypatch.setattr(manager, "_save", fail)
    args = [task.id] + (["file.txt"] if operation == "restore_file" else [])
    assert not getattr(manager, operation)(*args)
    assert (root / "file.txt").read_text() == "agent result"
    assert manager.can_undo() and not manager.can_redo()
    assert manager.last_error
    restored = UndoManager(root)
    assert restored.initialize() and restored.undo()
    assert (root / "file.txt").read_text() == "original"


def test_project_commands_require_trust_and_can_only_narrow_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    directory = tmp_path / ".superqode" / "commands"
    directory.mkdir(parents=True)
    (directory / "review.md").write_text(
        "---\ndescription: Review code\nallowed_tools: [read]\n---\nReview $ARGUMENTS"
    )
    (directory / "unsafe.md").write_text("---\napproval_mode: auto\n---\nWrite anything")
    (directory / "broken.md").write_text("---\nallowed_tools: [\n---\nBroken YAML")
    (directory / "m.md").write_text("This must not replace the mode alias.")
    (directory / "cancel.md").write_text("This must not replace navigation.")
    (directory / "header-text.md").write_text(
        '---\ndescription: "Before---after"\n---\nInspect the header'
    )
    assert discover_project_commands(tmp_path) == {}
    set_project_trust(tmp_path, True)
    commands = discover_project_commands(tmp_path)
    assert set(commands) == {"review", "header-text"}
    assert commands["header-text"].description == "Before---after"
    assert commands["review"].expand("src") == "Review src"
    manager = PermissionManager(PermissionConfig(default=Permission.ALLOW))
    with command_scope(commands["review"].allowed_tools):
        assert manager.check_permission("read", {}) == Permission.ALLOW
        assert manager.check_permission("write", {}) == Permission.DENY
        with command_scope(frozenset({"write"})):
            assert manager.check_permission("read", {}) == Permission.DENY
    assert manager.check_permission("write", {}) == Permission.ALLOW
    set_project_trust(tmp_path, False)
    assert discover_project_commands(tmp_path) == {}


def test_registry_drives_routes_help_and_palette():
    from superqode.app_main import SuperQodeApp
    from superqode.command_registry import COMMANDS, COMMAND_ROUTES, command_metadata

    metadata = command_metadata()
    app = SuperQodeApp()
    palette = {item.command for item in app._build_palette_commands()}
    for root, handler in COMMAND_ROUTES.items():
        assert callable(getattr(app, handler))
        assert ":" + root in COMMANDS
        assert ":" + root in metadata
        assert ":" + root in palette


def test_version_and_help_do_not_import_agent_or_ui_implementations():
    script = "from superqode.main import cli_main; import sys; from click.testing import CliRunner; r=CliRunner(mix_stderr=False).invoke(cli_main,['--help']); assert r.exit_code == 0; assert 'superqode.agent.loop' not in sys.modules; assert 'superqode.app.widgets' not in sys.modules; assert 'aiohttp' not in sys.modules"
    result = subprocess.run([os.sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_native_headless_emits_tool_events_from_real_loop(tmp_path, monkeypatch):
    from superqode.headless import run_headless

    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("project file")
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "read-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": json.dumps({"path": "file.txt"})},
                    }
                ],
            ),
            GatewayResponse(content="Read successfully"),
        ]
    )
    monkeypatch.setattr("superqode.headless.LiteLLMGateway", lambda: gateway)
    events = []
    result = asyncio.run(
        run_headless(
            "Read file.txt and report its contents",
            "test",
            "model",
            working_directory=tmp_path,
            on_event=lambda kind, data: events.append((kind, data)),
        )
    )
    assert result.stopped_reason == "complete"
    assert ("tool_start", {"tool": "read"}) in events
    assert ("tool_end", {"tool": "read", "success": True}) in events
    assert all("arguments" not in data and "output" not in data for _, data in events)


@pytest.mark.asyncio
async def test_command_scope_precedes_runtime_grants(tmp_path):
    gateway = ScriptedGateway([])
    loop = AgentLoop(
        gateway=gateway,
        tools=ToolRegistry.core(),
        config=AgentConfig(provider="test", model="model", working_directory=tmp_path),
        permission_manager=PermissionManager(PermissionConfig(default=Permission.ALLOW)),
    )
    with command_scope(frozenset({"read"})):
        denied = await loop._check_tool_permission_inner("bash", {"command": "echo permitted"})
        assert denied and not denied.success
        assert "allowed_tools" in denied.error
        assert {tool.name for tool in loop._get_tool_definitions()} == {"read"}
    assert "bash" in {tool.name for tool in loop._get_tool_definitions()}


@pytest.mark.parametrize("theme", ["superqode", "light"])
@pytest.mark.asyncio
async def test_effective_hotkeys_support_scope_and_preserve_draft(theme, tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp, SelectionAwareInput
    from superqode.app.widgets import ConversationLog
    from textual.widgets import Input, OptionList
    from superqode.widgets.hotkeys import HotkeysScreen

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".superqode" / "keybindings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "app": {"toggle_sidebar": "f2", "focus_input": "f6", "call_unknown_method()": "f7"},
                "SelectionAwareInput": {"clear_prompt": "alt+u"},
            }
        )
    )
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_run_startup_connect",
        "_report_catalog_freshness",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None, raising=False)
    app = SuperQodeApp(theme_selection=theme)
    async with app.run_test(size=(80, 24)) as pilot:
        editor = app.query_one("#prompt-input", SelectionAwareInput)
        editor.value = "my unsent draft"
        editor.cursor_position = 4
        app._handle_command(":hotkeys", app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert isinstance(app.screen, HotkeysScreen)
        app.screen.query_one(Input).value = "focus_input"
        await pilot.pause()
        values = app.screen.query_one(OptionList)
        assert values.option_count == 1
        assert "f6" in str(values.get_option_at_index(0).prompt)
        assert "unknown action" in " ".join(app._keymap.warnings)
        await pilot.press("escape")
        await pilot.pause()
        assert editor.value == "my unsent draft" and editor.cursor_position == 4
        assert "ctrl+d" not in app._bindings.key_to_bindings
        await pilot.press("alt+u")
        assert editor.value == ""


@pytest.mark.asyncio
async def test_project_command_worker_keeps_restriction_and_survives_cancel(tmp_path, monkeypatch):
    from textual import work
    from superqode.app_main import SuperQodeApp
    from superqode.app.widgets import ConversationLog
    from superqode.project_commands import command_tool_allowed

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    directory = tmp_path / ".superqode" / "commands"
    directory.mkdir(parents=True)
    (directory / "inspect-project.md").write_text(
        "---\nallowed_tools: [read]\n---\nInspect $ARGUMENTS"
    )
    set_project_trust(tmp_path, True)
    observed = []
    started = asyncio.Event()

    class Probe(SuperQodeApp):
        @work(exclusive=True)
        async def _send_to_pure_mode(self, text, log):
            observed.append((text, command_tool_allowed("read"), command_tool_allowed("write")))
            started.set()
            await asyncio.Event().wait()

    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_run_startup_connect",
        "_report_catalog_freshness",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(Probe, name, lambda *a, **k: None, raising=False)
    app = Probe()
    async with app.run_test() as pilot:
        app._pure_mode = SimpleNamespace(
            session=SimpleNamespace(connected=True), _agent=object(), runtime_name="builtin"
        )
        app._handle_command(":inspect-project src", app.query_one("#log", ConversationLog))
        await asyncio.wait_for(started.wait(), 2)
        assert observed == [("Inspect src", True, False)]
        assert command_tool_allowed("write")
        app.workers.cancel_group(app, "default")
        await pilot.pause()
        assert app._exception is None
        assert command_tool_allowed("write")
        app._pure_mode = None


def test_undo_storage_failure_preserves_files_and_corrupt_paths_are_rejected(tmp_path, monkeypatch):
    from superqode.app.task_changes import TaskChanges

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "draft.txt"
    path.write_text("developer draft")
    manager = UndoManager(tmp_path)
    assert manager.initialize()
    task = TaskChanges(tmp_path).capture()
    manager.register_task(task)
    path.write_text("agent edit")
    task.finish([])
    manager.seal_task(task)
    original = manager._save
    calls = 0

    def failing_save(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("storage unavailable")
        return original(*args)

    monkeypatch.setattr(manager, "_save", failing_save)
    assert manager.undo() is None
    assert path.read_text() == "agent edit"
    assert "rolled back" in manager.last_error
    assert manager.can_undo() and not manager.can_redo()
    state = tmp_path / ".superqode" / "checkpoints" / "state.json"
    payload = json.loads(state.read_text())
    payload["checkpoints"][0]["before"][".git/config"] = {"content": None, "mode": 420}
    state.write_text(json.dumps(payload))
    restored = UndoManager(tmp_path)
    assert restored.initialize() and not restored.can_undo()
    assert path.read_text() == "agent edit"


def test_jsonl_sequence_survives_finalization_failure(native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run(**kwargs):
        kwargs["on_event"]("progress", {"message": "Working"})
        return AgentResponse("done", [], 0, 1, "complete")

    def fail(*args, **kwargs):
        raise OSError("change summary unavailable")

    monkeypatch.setattr("superqode.headless.run_headless", run)
    monkeypatch.setattr("superqode.workspace.change_summary.summarize_workspace_changes", fail)
    result = CliRunner(mix_stderr=False).invoke(cli_main, ["-p", "--mode", "jsonl", "hello"])
    assert result.exit_code == 1
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [row["sequence"] for row in rows] == [1, 2, 3]
    assert rows[-1]["type"] == "superqode.error"


@pytest.mark.parametrize("mode", ["json", "jsonl"])
def test_missing_rubric_has_machine_setup_guidance(mode, native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner(mix_stderr=False).invoke(
        cli_main, ["-p", "--mode", mode, "--rubric", "@missing.md", "hello"]
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "invalid_request"
    assert "rubric file" in payload["error"]


def test_rewind_metadata_failure_rolls_back_history(tmp_path, monkeypatch):
    manager = SessionManager(str(tmp_path / "sessions"))
    manager.start_session("rewind", provider="test", model="model")
    manager.add_user_message("first")
    manager.add_assistant_message("answer")
    manager.add_user_message("second")
    original = manager.get_messages()
    save = manager.store._save_metadata

    def failing(metadata):
        if metadata.session_id == "rewind":
            raise OSError("metadata unavailable")
        save(metadata)

    monkeypatch.setattr(manager.store, "_save_metadata", failing)
    with pytest.raises(OSError, match="metadata unavailable"):
        manager.rewind_to_user_message(2)
    assert manager.get_messages() == original
    assert manager.store.get_metadata("rewind").message_count == len(original)
    assert manager.store.get_messages(manager.store.last_rewind_backup) == original
    assert manager.context_messages(limit=0) == []


def test_doctor_uses_explicit_model_and_does_not_recommend_unconfigured_run(tmp_path, monkeypatch):
    import superqode.providers.default_model as defaults

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("superqode.providers.recommendations.provider_doctor_cards", lambda _: [])
    monkeypatch.setattr("superqode.providers.recommendations.recommend_models", lambda *a, **k: [])
    monkeypatch.setattr(defaults, "configured_target", lambda *a, **k: None)
    result = CliRunner().invoke(
        cli_main, ["--provider", "ollama", "--model", "my-installed-model", "doctor", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["default_model"]["provider"] == "ollama"
    assert payload["default_model"]["model"] == "my-installed-model"
    assert not payload["ready"] and not payload["selected_route_configured"]
    assert not any("summarize this repo" in item for item in payload["next_steps"])


@pytest.mark.parametrize("mode,expected", [("ask", False), ("auto", True), ("deny", False)])
def test_headless_approval_mode_controls_real_native_file_tool(
    mode, expected, tmp_path, monkeypatch
):
    from superqode.headless import run_headless

    monkeypatch.chdir(tmp_path)
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "write-1",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps({"path": "result.txt", "content": "READY"}),
                        },
                    }
                ],
            ),
            GatewayResponse(content="Finished"),
        ]
    )
    monkeypatch.setattr("superqode.headless.LiteLLMGateway", lambda: gateway)
    result = asyncio.run(
        run_headless(
            "Write result.txt",
            "test",
            "model",
            working_directory=tmp_path,
            runtime="builtin",
            approval_mode=mode,
        )
    )
    assert result.stopped_reason == ("needs_approval" if mode == "ask" else "complete")
    assert (tmp_path / "result.txt").exists() == expected


@pytest.mark.parametrize("session_option", ["--continue", "--fork"])
def test_continue_restores_vendor_profile_and_subscription(session_option, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session(
        "vendor",
        provider="openai",
        model="vendor-model",
        harness_id="codex",
        harness_source="runtime",
    )
    manager.add_user_message("previous task")
    metadata = manager.get_session_info("vendor")
    metadata.runtime = "codex-cli"
    metadata.billing_requested = "subscription"
    metadata.harness_path = "review"
    manager.store._save_metadata(metadata)
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return AgentResponse("continued", [], 0, 1, "complete")

    monkeypatch.setattr("superqode.headless.run_headless", run)
    args = ["-p", session_option, *(["ven"] if session_option == "--fork" else []), "hello"]
    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code == 0, result.output
    assert calls[-1]["profile_name"] == "review"
    assert calls[-1]["runtime"] == "codex-cli"
    assert calls[-1]["billing_requested"] == "subscription"
    metadata.harness_path = ""
    manager.store._save_metadata(metadata)
    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code == 0, result.output
    assert calls[-1]["profile_name"] == "core"


def test_native_headless_fork_keeps_original_history(tmp_path, monkeypatch):
    from superqode.headless import run_headless

    directory = str(tmp_path / ".superqode/sessions")
    manager = SessionManager(directory)
    manager.start_session("original", provider="test", model="model")
    manager.add_user_message("original question")
    manager.add_assistant_message("original answer")
    original = manager.get_messages()
    gateway = ScriptedGateway([GatewayResponse(content="branch answer")])
    monkeypatch.setattr("superqode.headless.LiteLLMGateway", lambda: gateway)
    response = asyncio.run(
        run_headless(
            "branch question",
            "test",
            "model",
            working_directory=tmp_path,
            runtime="builtin",
            fork_from="orig",
        )
    )
    assert response.content == "branch answer"
    assert manager.store.get_messages("original") == original
    branches = [
        item for item in manager.list_all_sessions() if item.parent_session_id == "original"
    ]
    assert len(branches) == 1
    assert manager.store.get_messages(branches[0].session_id)[-1].content == "branch answer"


def test_backend_fork_uses_native_fork_before_turn(tmp_path, monkeypatch):
    from superqode.headless import run_headless

    directory = str(tmp_path / ".superqode/sessions")
    manager = SessionManager(directory)
    manager.start_session("vendor-source")
    manager.add_user_message("original question")
    events = []

    class Runtime:
        async def fork_thread(self, source):
            events.append(("fork", source))

        async def run(self, prompt):
            events.append(("run", prompt))
            return AgentResponse("branch answer", [], 0, 1, "complete")

        async def aclose(self):
            events.append(("close",))

    def create(name, **kwargs):
        assert name == "codex-cli"
        assert kwargs["config"].session_id is None
        return Runtime()

    monkeypatch.setattr("superqode.headless.create_runtime", create)
    asyncio.run(
        run_headless(
            "branch question",
            "openai",
            "model",
            working_directory=tmp_path,
            runtime="codex-cli",
            fork_from="vendor",
        )
    )
    assert events == [("fork", "vendor-source"), ("run", "branch question"), ("close",)]
    assert len(manager.list_all_sessions()) == 1


def test_headless_fork_rejects_unsupported_backend_without_copy(tmp_path):
    from superqode.headless import run_headless
    from superqode.runtime.errors import HeadlessSetupError

    manager = SessionManager(str(tmp_path / ".superqode/sessions"))
    manager.start_session("source")
    manager.add_user_message("original")
    with pytest.raises(HeadlessSetupError, match="own fork command"):
        asyncio.run(
            run_headless(
                "branch",
                "test",
                "model",
                working_directory=tmp_path,
                runtime="claude-agent-sdk",
                fork_from="source",
            )
        )
    assert len(manager.list_all_sessions()) == 1


def test_headless_auto_preserves_profile_denials(tmp_path, monkeypatch):
    from dataclasses import replace
    from superqode.headless import get_harness_profiles, run_headless

    profile = replace(
        get_harness_profiles()["core"],
        permissions=PermissionConfig(default=Permission.ASK, tools={"write": Permission.DENY}),
    )
    monkeypatch.setattr("superqode.headless.get_harness_profiles", lambda: {"core": profile})
    gateway = ScriptedGateway(
        [
            GatewayResponse(
                content="",
                tool_calls=[
                    {
                        "id": "write-1",
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps({"path": "result.txt", "content": "READY"}),
                        },
                    }
                ],
            ),
            GatewayResponse(content="Cannot write"),
        ]
    )
    monkeypatch.setattr("superqode.headless.LiteLLMGateway", lambda: gateway)
    asyncio.run(
        run_headless(
            "Write result.txt",
            "test",
            "model",
            working_directory=tmp_path,
            runtime="builtin",
            approval_mode="auto",
        )
    )
    assert not (tmp_path / "result.txt").exists()
    assert profile.permissions.default == Permission.ASK
    assert profile.permissions.tools["write"] == Permission.DENY


def test_thrown_sdk_value_error_does_not_expose_request(native_default, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run(**kwargs):
        raise ValueError("SDK request={'prompt':'private task', 'token':'opaque-private-value'}")

    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner(mix_stderr=False).invoke(cli_main, ["-p", "--mode", "json", "hello"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "private task" not in result.output
    assert "opaque-private-value" not in result.output


def test_headless_does_not_silently_accept_unenforceable_policy(tmp_path, monkeypatch):
    from superqode.headless import run_headless
    from superqode.runtime.errors import HeadlessSetupError

    monkeypatch.chdir(tmp_path)
    with pytest.raises(HeadlessSetupError, match="owns its approval policy"):
        asyncio.run(
            run_headless("hello", "test", "model", runtime="antigravity-sdk", approval_mode="deny")
        )


def test_needs_approval_has_actionable_machine_error():
    from superqode.headless import response_to_json

    payload = json.loads(
        response_to_json(AgentResponse("", [], 0, 1, "needs_approval"), "test", "model", "core")
    )
    assert not payload["success"]
    assert payload["error_code"] == "needs_approval"
    assert "interactive TUI" in payload["error"]
