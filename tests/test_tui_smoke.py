from rich.console import Console
from types import SimpleNamespace
import asyncio
import concurrent.futures
import subprocess

import pytest

from superqode.app_main import SelectionAwareInput, SuperQodeApp, render_welcome
from superqode.app.widgets import ConversationLog
from superqode.harness import (
    AgentSpec,
    FileHarnessStore,
    HarnessEvent,
    HarnessSpec,
    WorkflowMode,
    WorkflowSpec,
)
from superqode.tools.question_tool import Question, QuestionType
from superqode.widgets.sidebar_panels import HarnessPanel


def _noop_hook(*_args, **_kwargs):
    return None


class FakeLog:
    def __init__(self):
        self.items = []
        self.auto_scroll = True
        self._last_error = ""
        self._last_response = ""
        self.pushed_screen = None

    def clear(self):
        self.items.clear()

    def write(self, content):
        self.items.append(content)

    def scroll_home(self, animate=False):
        self.scrolled_home = True

    def add_info(self, text):
        self.items.append(text)

    def add_success(self, text):
        self.items.append(text)

    def add_error(self, text):
        self.items.append(text)

    def add_tool_call(
        self,
        tool_name,
        status="running",
        file_path="",
        command="",
        output="",
        arguments=None,
        diff_text="",
        duration=None,
        additions=None,
        deletions=None,
    ):
        self.items.append(
            {
                "tool_name": tool_name,
                "status": status,
                "file_path": file_path,
                "command": command,
                "output": output,
                "arguments": arguments or {},
            }
        )

    def get_last_error(self):
        return self._last_error

    def get_last_response(self):
        return self._last_response

    def get_last_message(self, role=None):
        return "last prompt"

    def get_all_text(self):
        return "full transcript"


class FakePureMode:
    def __init__(self):
        self._agent = object()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeACPLoopRunner:
    def __init__(self):
        self.cancel_called = False

    def run(self, coro, timeout=None):
        self.cancel_called = True
        return asyncio.run(coro)


class FakeACPClient:
    def __init__(self):
        self.cancelled = False
        self._process = None

    async def cancel(self):
        self.cancelled = True
        return True


def render_plain(renderable) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def make_app() -> SuperQodeApp:
    app = SuperQodeApp()
    app.set_timer = lambda *args, **kwargs: None
    app._ensure_input_focus = lambda: None
    return app


def test_welcome_positions_superqode_as_coding_harness():
    welcome = render_welcome([])

    text = render_plain(welcome)

    assert "SuperQode = Multi-agent coding harness" in text
    assert ":connect local" in text
    assert "Agentic Code Needs Super Quality Engineering" not in text


def test_opencode_acp_model_normalization_preserves_provider_ids():
    assert (
        SuperQodeApp._normalize_acp_model_id("opencode", "deepseek/deepseek-v4-pro")
        == "deepseek/deepseek-v4-pro"
    )
    assert SuperQodeApp._normalize_acp_model_id("opencode", "big-pickle") == "opencode/big-pickle"
    assert SuperQodeApp._normalize_acp_model_id("opencode", "opencode/auto") is None


def test_prompt_height_wraps_and_caps_long_text():
    assert SelectionAwareInput._height_for_text("", 40) == 1
    assert SelectionAwareInput._height_for_text("short prompt", 40) == 1
    assert SelectionAwareInput._height_for_text("x" * 90, 40) == 3
    assert SelectionAwareInput._height_for_text("x" * 1000, 40) == 6
    assert SelectionAwareInput._height_for_text("line 1\nline 2", 40) == 2


def test_connect_local_picker_lists_ds4():
    app = make_app()
    log = FakeLog()

    app._show_local_provider_picker(log)

    text = render_plain(log.items[-1])
    assert "DwarfStar 4" in text
    assert "ds4" in text
    assert "recommended" in text


def test_work_command_renders_last_run_trace():
    app = make_app()
    log = FakeLog()
    app.current_provider = "ds4"
    app.current_model = "deepseek-v4-flash"
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app._last_run_summary = {
        "provider": "ds4",
        "model": "deepseek-v4-flash",
        "duration": 1.25,
        "tool_count": 2,
        "files_read": ["pyproject.toml"],
        "files_modified": ["src/example.py"],
        "commands_run": ["uv run pytest"],
        "tools": [
            {
                "name": "read_file",
                "kind": "read",
                "status": "success",
                "duration": 0.02,
                "path": "pyproject.toml",
            }
        ],
    }

    app._work_cmd("verbose", log)

    text = render_plain(log.items[-1])
    assert "Last Work Summary" in text
    assert "ds4/deepseek-v4-flash" in text
    assert "pyproject.toml" in text
    assert "read_file" in text
    assert "success" in text


def test_harness_panel_renders_workbench_for_local_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    harness_path = tmp_path / "harness.yaml"
    harness_path.write_text(
        """
name: demo-workbench
runtime:
  backend: builtin
agents:
  - id: coder
    role: implementation
    tools: [read_file, grep]
workflow:
  mode: single
validation:
  enabled: true
  custom_steps:
    - name: syntax
      command: python --version
""".strip()
        + "\n",
        encoding="utf-8",
    )

    text = render_plain(HarnessPanel()._render_summary())

    assert "Harness Workbench" in text
    assert "Active Harness" in text
    assert "demo-workbench" in text
    assert "readiness ready" in text
    assert "backend     builtin" in text
    assert "tools     grep, read_file" in text
    assert "Planned Graph" in text
    assert "coder" in text


def test_harness_panel_surfaces_policy_hooks_and_recent_signals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness_path = tmp_path / "harness.yaml"
    harness_path.write_text(
        """
name: policy-workbench
context:
  session_storage: .superqode/sessions
execution_policy:
  allow_shell: true
  permission_rules:
    - tool: bash
      argument: command
      pattern: "git *"
      action: allow
    - tool: bash
      action: deny
hooks:
  rules:
    - point: before_tool_call
      handler: test_tui_smoke:_noop_hook
      matcher: write_*
      name: audit-write
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERQODE_HARNESS", str(harness_path))

    from superqode.harness import load_harness_spec, remember_approval_decision

    spec = load_harness_spec(harness_path)
    remember_approval_decision(
        spec,
        tool_name="bash",
        arguments={"command": "git status"},
        action="allow",
    )
    store = FileHarnessStore(".superqode/sessions")
    store.open_session("session-1", spec)
    run = store.start_run(
        session_id="session-1",
        spec=spec,
        provider="test",
        model="model",
        runtime="builtin",
        prompt="policy test",
    )
    store.append_event(
        run.run_id,
        HarnessEvent(
            type="harness.permission.check",
            run_id=run.run_id,
            data={
                "tool": "bash",
                "arguments": {
                    "keys": ["api_key", "command"],
                    "preview": {"api_key": "[redacted]", "command": "git status"},
                },
            },
        ),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(
            type="harness.hook.error",
            run_id=run.run_id,
            data={"point": "stop", "handler": "bad.module:fn", "error": "missing"},
        ),
    )

    text = render_plain(HarnessPanel()._render_summary())

    assert "policy-workbench" in text
    assert "rules=2" in text
    assert "remembered=1" in text
    assert "allow bash command~git *" in text
    assert "allow remembered bash command~git status" in text
    assert "deny  bash" in text
    assert "hooks=2 (enabled)" in text
    assert "audit-write" in text
    assert "signals" in text
    assert "permission.check  bash keys=api_key,command" in text
    assert "hook.error  stop bad.module:fn" in text
    assert "sk-" not in text


def test_harness_events_command_renders_persisted_timeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness_path = tmp_path / "harness.yaml"
    harness_path.write_text(
        """
name: event-demo
context:
  session_storage: .superqode/sessions
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERQODE_HARNESS", str(harness_path))

    spec = HarnessSpec(name="event-demo")
    store = FileHarnessStore(".superqode/sessions")
    store.open_session("session-1", spec)
    run = store.start_run(
        session_id="session-1",
        spec=spec,
        provider="test",
        model="model",
        runtime="builtin",
        prompt="event test",
        metadata={"workflow": True},
    )
    store.append_event(
        run.run_id,
        HarnessEvent(type="workflow.step.completed", run_id=run.run_id, data={"step_id": "coder", "status": "done"}),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(type="validation.step.completed", run_id=run.run_id, data={"name": "tests", "returncode": 0}),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(
            type="harness.permission.check",
            run_id=run.run_id,
            data={
                "tool": "bash",
                "arguments": {
                    "keys": ["api_key", "command"],
                    "preview": {"api_key": "[redacted]", "command": "git status"},
                },
            },
        ),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(
            type="harness.stop",
            run_id=run.run_id,
            data={"stopped_reason": "complete", "iterations": 2, "tool_calls_made": 1},
        ),
    )

    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd(f"events {run.run_id}", log)

    text = render_plain(log.items[-1])
    assert "Harness Events" in text
    assert run.run_id in text
    assert "workflow.step.completed" in text
    assert "step_id=coder" in text
    assert "validation.step.completed" in text
    assert "harness.permission.check" in text
    assert "tool=bash" in text
    assert "arg_keys=api_key,command" in text
    assert "api_key=[redacted]" in text
    assert "harness.stop" in text
    assert "stopped_reason=complete" in text
    assert f":harness evidence {run.run_id}" in text


def test_harness_replay_and_fork_commands_render_run_lineage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness_path = tmp_path / "harness.yaml"
    harness_path.write_text(
        """
name: replay-demo
context:
  session_storage: .superqode/sessions
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERQODE_HARNESS", str(harness_path))

    spec = HarnessSpec(name="replay-demo")
    store = FileHarnessStore(".superqode/sessions")
    store.open_session("session-1", spec)
    run = store.start_run(
        session_id="session-1",
        spec=spec,
        provider="test",
        model="model",
        runtime="builtin",
        prompt="replay test",
    )
    store.append_event(run.run_id, HarnessEvent(type="run_start", run_id=run.run_id))
    store.append_event(run.run_id, HarnessEvent(type="tool_call", run_id=run.run_id))

    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd(f"replay {run.run_id}", log)
    replay_text = render_plain(log.items[-1])
    assert "Harness Replay" in replay_text
    assert run.run_id in replay_text
    assert "full=False" in replay_text
    assert ":harness fork" in replay_text

    app._harness_cmd(f"fork {run.run_id} 0", log)
    fork_text = render_plain(log.items[-1])
    assert "Harness Fork" in fork_text
    assert run.run_id in fork_text
    assert "Events" in fork_text
    assert ":harness events" in fork_text


def test_tui_palette_exposes_harness_commands():
    app = make_app()

    commands = {command.id: command for command in app._build_palette_commands()}

    assert commands["harness"].shortcut == ":harness"
    assert commands["harness_inspect"].shortcut == ":harness inspect"
    assert commands["harness_doctor"].shortcut == ":harness doctor"
    assert commands["harness_graph"].shortcut == ":harness graph"
    assert commands["harness_runs"].shortcut == ":harness runs"
    assert commands["harness_replay"].shortcut == ":harness replay "
    assert commands["harness_fork"].shortcut == ":harness fork "
    assert commands["harness_events"].shortcut == ":harness events "
    assert commands["harness_evidence"].shortcut == ":harness evidence "


def test_tui_static_commands_include_harness_subcommands():
    from superqode.app.constants import COMMANDS
    from superqode.widgets.slash_complete import DEFAULT_COMMANDS

    assert ":harness inspect" in COMMANDS
    assert ":harness doctor" in COMMANDS
    assert ":harness graph" in COMMANDS
    assert ":harness replay" in COMMANDS
    assert ":harness fork" in COMMANDS
    assert ":harness events" in COMMANDS
    assert ":qe fullstack" not in COMMANDS
    assert ":qe unit_tester" not in COMMANDS
    assert ":qe api_tester" not in COMMANDS
    assert ":connect" in COMMANDS
    assert ":connect acp" in COMMANDS
    assert ":connect byok" in COMMANDS
    assert ":connect local" in COMMANDS
    assert ":exit" in COMMANDS
    assert ":quit" in COMMANDS
    assert ":c" not in COMMANDS
    assert ":q" not in COMMANDS
    slash_values = {command.command for command in DEFAULT_COMMANDS}
    assert ":harness inspect" in slash_values
    assert ":harness doctor" in slash_values
    assert ":harness replay" in slash_values
    assert ":harness fork" in slash_values
    assert ":harness events" in slash_values
    assert ":connect" in slash_values
    assert ":connect acp" in slash_values
    assert ":connect byok" in slash_values
    assert ":connect local" in slash_values
    assert ":exit" in slash_values
    assert ":quit" in slash_values
    assert ":c" not in slash_values
    assert ":q" not in slash_values


def test_slash_complete_prioritizes_connect_and_quit():
    from superqode.widgets.slash_complete import DEFAULT_COMMANDS, filter_slash_commands

    root_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":")]
    connect_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":c")]
    quit_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":q")]

    assert root_values[:6] == [
        ":connect",
        ":connect acp",
        ":connect byok",
        ":connect local",
        ":exit",
        ":quit",
    ]
    assert connect_values[:4] == [
        ":connect",
        ":connect acp",
        ":connect byok",
        ":connect local",
    ]
    assert ":clear" not in connect_values
    assert ":context" not in connect_values
    assert ":copy" not in connect_values
    assert quit_values[0] == ":quit"


def test_skills_command_creates_and_lists_local_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._skills_cmd("add repo-review Repository review workflow", log)
    assert (tmp_path / ".agents" / "skills" / "repo-review" / "SKILL.md").exists()

    app._skills_cmd("", log)
    text = render_plain(log.items[-1])

    assert "repo-review" in text
    assert "Repository review workflow" in text


def test_attach_command_prefills_file_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("print('hi')\n")
    app = make_app()
    log = FakeLog()
    captured = []
    app._set_prompt_prefill = lambda value: captured.append(value)

    app._attach_cmd("src/example.py", log)

    assert captured == ["@src/example.py "]
    assert any("Attached 1 reference" in str(item) for item in log.items)


def test_attach_command_lists_removes_and_clears_refs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "README.md"
    target.write_text("# Project\n")
    app = make_app()
    log = FakeLog()
    captured = []
    app._set_prompt_prefill = lambda value: captured.append(value)
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._attach_cmd("README.md https://example.com/spec", log)
    assert app._attached_refs == ["@README.md", "https://example.com/spec"]

    app._attach_cmd("list", log)
    text = render_plain(log.items[-1])
    assert "@README.md" in text
    assert "https://example.com/spec" in text

    app._attach_cmd("remove 1", log)
    assert app._attached_refs == ["https://example.com/spec"]
    assert captured[-1] == "https://example.com/spec "

    app._attach_cmd("clear", log)
    assert app._attached_refs == []
    assert captured[-1] == ""


def test_skills_doctor_reports_missing_description(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "thin"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: thin\nenabled: true\n---\n\n# Thin\n")
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._skills_cmd("doctor", log)
    text = render_plain(log.items[-1])

    assert "missing description" in text


def test_prompt_completion_suggests_mcp_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".superqode"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        '{"mcpServers":{"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","."]}}}'
    )
    app = make_app()

    assert app._suggest_prompt_completion(":mcp connect fi") == ":mcp connect filesystem"


def test_prompt_completion_suggests_skill_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "repo-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: repo-review\ndescription: Review repository changes\nenabled: true\n---\n\n# Review\n"
    )
    app = make_app()

    assert app._suggest_prompt_completion(":skills info rep") == ":skills info repo-review"


def test_recipes_command_lists_and_doctors_local_recipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recipe_dir = tmp_path / ".superqode" / "recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "review.yaml").write_text(
        "name: review\n"
        "description: Review current change\n"
        "prompt: Review the current git diff.\n"
        "skills: []\n"
    )
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    asyncio.run(app._recipe_cmd("list", log))
    text = render_plain(log.items[-1])
    assert "review" in text
    assert "Review current change" in text

    asyncio.run(app._recipe_cmd("doctor review", log))
    text = render_plain(log.items[-1])
    assert "Recipe looks runnable" in text


def test_recipe_completion_suggests_recipe_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recipe_dir = tmp_path / ".superqode" / "recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "fix-tests.json").write_text(
        '{"name":"fix-tests","description":"Repair failing tests","prompt":"Fix tests."}'
    )
    app = make_app()

    candidates = app._prompt_completion_candidates_for(":recipe run fix")

    assert candidates[0].value == ":recipe run fix-tests"
    assert candidates[0].kind == "recipe"
    assert candidates[0].description == "Repair failing tests"


def test_recipe_run_prefills_prompt_and_stages_refs_when_disconnected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Project\n")
    recipe_dir = tmp_path / ".superqode" / "recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "review.yaml").write_text(
        "name: review\n"
        "description: Review docs\n"
        "prompt: Review attached docs.\n"
        "attachments:\n"
        "  - ../../README.md\n"
        "mcp_resources:\n"
        "  - docs/file:///docs/readme.md\n"
    )
    app = make_app()
    log = FakeLog()
    captured = []
    app._set_prompt_prefill = lambda value: captured.append(value)

    recipe = app._find_recipe("review")
    asyncio.run(app._run_recipe(recipe, "focus on clarity", log))

    assert captured[-1].startswith("Review attached docs.")
    assert "@README.md" in app._attached_refs
    assert "mcp://docs/file:///docs/readme.md" in app._attached_refs
    assert any("Loaded recipe prompt" in str(item) for item in log.items)


def test_byok_provider_selection_enables_model_keyboard_immediately():
    app = make_app()
    log = FakeLog()
    provider_def = SimpleNamespace(name="Anthropic")
    app._awaiting_byok_provider = True
    app._byok_connect_list = [("anthropic", provider_def)]
    def show_provider_models(provider_id, target_log, use_picker=False):
        app._byok_selected_provider = provider_id
        app._byok_model_list = ["claude-sonnet"]

    app._show_provider_models = show_provider_models

    assert app._handle_byok_provider_selection("1", log)

    assert app._awaiting_byok_model is True
    assert app._byok_selected_provider == "anthropic"
    assert app._byok_model_list == ["claude-sonnet"]


def test_byok_highlighted_model_enter_selects_current_model(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._awaiting_byok_model = True
    app._byok_selected_provider = "anthropic"
    app._byok_model_list = ["first-model", "second-model"]
    app._byok_highlighted_model_index = 1
    captured = []
    app.query_one = lambda selector, *args, **kwargs: log if selector == "#log" else None
    app._connect_byok_mode = lambda provider, model, target_log: captured.append((provider, model))

    app.action_select_highlighted_model()

    assert captured == [("anthropic", "second-model")]
    assert app._awaiting_byok_model is False


def test_picker_link_click_selects_byok_model_directly():
    app = make_app()
    log = FakeLog()
    app._awaiting_byok_model = True
    app._byok_selected_provider = "anthropic"
    app._byok_model_list = ["first-model", "second-model"]
    captured = []
    event = SimpleNamespace(
        style=SimpleNamespace(link="superqode://pick/2"),
        stop=lambda: setattr(event, "stopped", True),
        prevent_default=lambda: setattr(event, "prevented", True),
        stopped=False,
        prevented=False,
    )
    app.query_one = lambda selector, *args, **kwargs: log if selector == "#log" else None
    app.set_timer = lambda *args, **kwargs: None
    app._connect_byok_mode = lambda provider, model, target_log: captured.append((provider, model))

    app.on_click(event)

    assert captured == [("anthropic", "second-model")]
    assert event.stopped is True
    assert event.prevented is True
    assert app._awaiting_byok_model is False


def test_acp_highlighted_model_enter_selects_current_agent_model():
    app = make_app()
    app.current_agent = "gemini"
    app._gemini_models = [{"id": "gemini-flash"}, {"id": "gemini-pro"}]
    app._awaiting_model_selection = True
    app._opencode_highlighted_model_index = 1
    captured = []
    app._select_model_by_number = lambda number: captured.append(number)

    app.action_select_highlighted_acp_model()

    assert captured == [2]


def test_workflow_center_renders_active_harness():
    app = make_app()
    log = FakeLog()
    spec = HarnessSpec(
        name="review-flow",
        workflow=WorkflowSpec(mode=WorkflowMode.PARALLEL, parallelism=2),
        agents=(
            AgentSpec(id="api", role="API reviewer"),
            AgentSpec(id="ui", role="UI reviewer"),
        ),
    )
    app._active_harness_spec = lambda: (spec, "superqode.yaml")
    app.current_provider = "anthropic"
    app.current_model = "claude-sonnet"
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._show_workflow_center(log)
    text = render_plain(log.items[-1])

    assert "Workflow Run Center" in text
    assert "review-flow" in text
    assert "parallel" in text
    assert "api" in text
    assert "anthropic/claude-sonnet" in text


def test_workflow_presets_command_lists_builtin_presets():
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._show_workflow_presets(log)
    text = render_plain(log.items[-1])

    assert "Workflow Presets" in text
    assert "parallel-review" in text
    assert "plan-implement-review" in text


def test_workflow_preview_renders_readiness():
    app = make_app()
    log = FakeLog()
    spec = HarnessSpec(
        name="preview-flow",
        workflow=WorkflowSpec(preset="parallel-review"),
    )
    app._active_harness_spec = lambda: (spec, "superqode.yaml")
    app.current_provider = "anthropic"
    app.current_model = "claude-sonnet"
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._show_workflow_preview(log, "fix auth bug")
    text = render_plain(log.items[-1])

    assert "Workflow Preview" in text
    assert "preview-flow" in text
    assert "preset=parallel-review" in text
    assert "security" in text
    assert "anthropic/claude-sonnet" in text
    assert "Readiness" in text
    assert "Run with" in text


def test_workflow_preview_reports_missing_model():
    app = make_app()
    log = FakeLog()
    spec = HarnessSpec(name="blocked-flow", workflow=WorkflowSpec(mode=WorkflowMode.CHAIN))
    app._active_harness_spec = lambda: (spec, "")
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._show_workflow_preview(log, "ship it")
    text = render_plain(log.items[-1])

    assert "Workflow Preview" in text
    assert "not selected" in text
    assert "blocked" in text
    assert "connect BYOK/local" in text


def test_workflow_steps_from_spec_adds_router_step():
    app = make_app()
    spec = HarnessSpec(
        name="router-flow",
        workflow=WorkflowSpec(mode=WorkflowMode.ROUTER),
        agents=(
            AgentSpec(id="frontend", role="Frontend engineer"),
            AgentSpec(id="backend", role="Backend engineer"),
        ),
    )

    steps = app._workflow_steps_from_spec(spec, "Fix the API client")

    assert [step.id for step in steps] == ["router", "frontend", "backend"]
    assert "Fix the API client" in steps[0].prompt
    assert "Frontend engineer" in steps[1].prompt


def test_workflow_timeline_renders_step_states():
    app = make_app()

    text = render_plain(
        app._workflow_timeline_text(
            title="Workflow timeline",
            mode="parallel",
            step_ids=["api", "ui"],
            states={"api": "done", "ui": "running"},
            details={"api": "1 iteration(s)"},
        )
    )

    assert "Workflow timeline" in text
    assert "parallel" in text
    assert "api" in text
    assert "done" in text
    assert "ui" in text
    assert "running" in text


def test_doctor_tui_dashboard_renders_readiness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app.current_provider = "anthropic"
    app.current_model = "claude-sonnet"
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._doctor_cmd("tui", log)
    text = render_plain(log.items[-1])

    assert "TUI Doctor Dashboard" in text
    assert "Provider" in text
    assert "anthropic/claude-sonnet" in text
    assert "Recipes" in text


def test_prompt_completion_suggests_attach_and_prompt_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "prompts" / "review.md"
    target.parent.mkdir()
    target.write_text("Review this change\n")
    app = make_app()

    assert app._suggest_prompt_completion(":attach pro") == ":attach prompts/"
    assert app._suggest_prompt_completion(":prompt prompts/rev") == ":prompt prompts/review.md"


def test_prompt_completion_suggests_provider_and_model():
    app = make_app()

    assert app._suggest_prompt_completion(":connect byok anthrop") == ":connect byok anthropic"
    assert app._suggest_prompt_completion(":model switch anthropic") == ":model switch anthropic/"


def test_prompt_completion_prioritizes_full_connect_and_quit_commands():
    app = make_app()

    root_values = [candidate.value for candidate in app._prompt_completion_candidates_for(":")]
    connect_values = [candidate.value for candidate in app._prompt_completion_candidates_for(":c")]
    quit_values = [candidate.value for candidate in app._prompt_completion_candidates_for(":q")]

    assert root_values[:6] == [
        ":connect",
        ":connect acp",
        ":connect byok",
        ":connect local",
        ":exit",
        ":quit",
    ]
    assert connect_values[:4] == [
        ":connect",
        ":connect acp",
        ":connect byok",
        ":connect local",
    ]
    assert connect_values == [
        ":connect",
        ":connect acp",
        ":connect byok",
        ":connect local",
    ]
    assert quit_values[0] == ":quit"
    assert all(not value.startswith(":qe") for value in quit_values)
    assert SuperQodeApp._should_submit_prompt_without_completion(":c") is False
    assert SuperQodeApp._should_submit_prompt_without_completion(":q") is False
    assert SuperQodeApp._should_submit_prompt_without_completion(":connect") is True


def test_command_suggester_prioritizes_full_connect_and_quit_commands():
    from superqode.app.suggester import CommandSuggester

    suggester = CommandSuggester()

    assert asyncio.run(suggester.get_suggestion(":")) == ":connect"
    assert asyncio.run(suggester.get_suggestion(":c")) == ":connect"
    assert asyncio.run(suggester.get_suggestion(":q")) == ":quit"
    assert asyncio.run(suggester.get_suggestion(":co")) == ":connect"


def test_prompt_completion_candidates_include_descriptions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "repo-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: repo-review\ndescription: Review repository changes\nenabled: true\n---\n\n# Review\n"
    )
    app = make_app()

    candidates = app._prompt_completion_candidates_for(":skills info rep")

    assert candidates[0].label == "repo-review"
    assert candidates[0].description == "Review repository changes"
    assert candidates[0].kind == "skill"


def test_prompt_completion_accepts_visible_candidate():
    app = make_app()
    input_widget = SimpleNamespace(value=":mod", cursor_position=0)
    app._prompt_completion_candidates = app._prompt_completion_candidates_for(":mod")
    app._prompt_completion_index = 0
    app._prompt_completion_visible = True

    assert app._accept_prompt_completion(input_widget)
    assert input_widget.value.startswith(":mode") or input_widget.value.startswith(":model")
    assert input_widget.cursor_position == len(input_widget.value)


def test_mcp_target_config_detects_http_and_stdio():
    app = make_app()

    http_config = app._mcp_server_config_from_target("hf", "https://huggingface.co/mcp")
    stdio_config = app._mcp_server_config_from_target(
        "everything",
        "@modelcontextprotocol/server-everything",
    )

    assert http_config.config.transport == "http"
    assert http_config.config.url == "https://huggingface.co/mcp"
    assert stdio_config.config.transport == "stdio"
    assert stdio_config.config.command == "npx"
    assert stdio_config.config.args == ["@modelcontextprotocol/server-everything"]


def test_mcp_resource_ref_resolution_supports_index_and_server_uri():
    app = make_app()
    resource = SimpleNamespace(
        server_id="docs",
        uri="file:///docs/readme.md",
        name="README",
        description="Project README",
        mime_type="text/markdown",
    )
    manager = SimpleNamespace(list_all_resources=lambda: [resource])

    assert app._resolve_mcp_resource_ref(manager, "1") is resource
    assert app._resolve_mcp_resource_ref(manager, "docs/file:///docs/readme.md") is resource
    assert app._resolve_mcp_resource_ref(manager, "mcp://docs/file:///docs/readme.md") is resource


def test_mcp_attach_resource_stages_prompt_reference():
    app = make_app()
    log = FakeLog()
    captured = []
    app._set_prompt_prefill = lambda value: captured.append(value)
    resource = SimpleNamespace(
        server_id="docs",
        uri="file:///docs/readme.md",
        name="README",
        description="Project README",
        mime_type="text/markdown",
    )
    manager = SimpleNamespace(list_all_resources=lambda: [resource])

    asyncio.run(app._mcp_attach_resource(manager, "1", log))

    assert app._attached_refs == ["mcp://docs/file:///docs/readme.md"]
    assert captured == ["mcp://docs/file:///docs/readme.md "]
    assert any("Attached MCP resource" in str(item) for item in log.items)


def test_prompt_completion_suggests_mcp_resource(monkeypatch):
    from superqode.mcp import integration

    app = make_app()
    resource = SimpleNamespace(
        server_id="docs",
        uri="file:///docs/readme.md",
        name="README",
        description="Project README",
        mime_type="text/markdown",
    )
    manager = SimpleNamespace(list_all_resources=lambda: [resource])
    monkeypatch.setattr(integration, "_mcp_manager", manager)

    candidates = app._prompt_completion_candidates_for(":mcp attach docs/fi")

    assert candidates[0].value == ":mcp attach docs/file:///docs/readme.md"
    assert candidates[0].kind == "resource"
    assert "README" in candidates[0].description


def test_extract_mcp_refs_from_prompt_text():
    text, refs = SuperQodeApp._extract_mcp_refs_from_text(
        "review mcp://docs/file:///docs/readme.md carefully"
    )

    assert text == "review carefully"
    assert refs == ["mcp://docs/file:///docs/readme.md"]


def test_resolve_mcp_attachment_context_reads_text_resource(monkeypatch):
    from superqode.mcp import integration

    app = make_app()
    log = FakeLog()
    app._current_mcp_refs = ["mcp://docs/file:///docs/readme.md"]
    content = SimpleNamespace(
        uri="file:///docs/readme.md",
        mime_type="text/markdown",
        text="# README\nProject notes",
        blob=None,
    )

    class FakeManager:
        async def read_resource(self, server_id, uri):
            assert server_id == "docs"
            assert uri == "file:///docs/readme.md"
            return content

    async def fake_get_mcp_manager():
        return FakeManager()

    monkeypatch.setattr(integration, "get_mcp_manager", fake_get_mcp_manager)

    context = asyncio.run(app._resolve_mcp_attachment_context(log))

    assert '<mcp-resource server="docs" uri="file:///docs/readme.md"' in context
    assert "# README" in context
    assert app._current_mcp_refs == []
    assert any("Including 1 MCP resource" in str(item) for item in log.items)


def test_resolve_mcp_attachment_context_bounds_text(monkeypatch):
    from superqode.mcp import integration

    app = make_app()
    app._current_mcp_refs = ["mcp://docs/file:///large.txt"]
    content = SimpleNamespace(
        uri="file:///large.txt",
        mime_type="text/plain",
        text="x" * 40000,
        blob=None,
    )

    class FakeManager:
        async def read_resource(self, server_id, uri):
            return content

    async def fake_get_mcp_manager():
        return FakeManager()

    monkeypatch.setattr(integration, "get_mcp_manager", fake_get_mcp_manager)

    context = asyncio.run(app._resolve_mcp_attachment_context())

    assert 'truncated="true"' in context
    assert len(context) < 31000


def test_select_command_routes_response_error_prompt_and_transcript():
    app = make_app()
    log = FakeLog()
    log._last_error = "boom"
    app._last_response = "answer"
    app._last_user_message = "question"
    captured = []

    def push_screen(screen, callback=None):
        captured.append((screen._title, screen._content))
        if callback:
            callback(None)

    app.push_screen = push_screen

    app._handle_select(log, "response")
    app._handle_select(log, "error")
    app._handle_select(log, "prompt")
    app._handle_select(log, "all")

    assert captured == [
        ("Response", "answer"),
        ("Error", "boom"),
        ("Prompt", "question"),
        ("Transcript", "full transcript"),
    ]


def test_transcript_command_opens_selectable_transcript():
    app = make_app()
    log = FakeLog()
    captured = []
    app.push_screen = lambda screen, callback=None: captured.append((screen._title, screen._content))

    app._handle_command(":transcript", log)

    assert captured == [("Transcript", "full transcript")]


def test_scroll_actions_target_conversation_log():
    app = make_app()
    calls = []
    log = SimpleNamespace(
        auto_scroll=True,
        scroll_page_up=lambda animate=False: calls.append(("page_up", animate)),
        scroll_page_down=lambda animate=False: calls.append(("page_down", animate)),
        scroll_home=lambda animate=False: calls.append(("home", animate)),
        scroll_end=lambda animate=False: calls.append(("end", animate)),
    )
    app._conversation_log = lambda: log

    app.action_scroll_log_page_up()
    assert log.auto_scroll is False
    app.action_scroll_log_page_down()
    app.action_scroll_log_home()
    app.action_scroll_log_end()

    assert calls == [
        ("page_up", False),
        ("page_down", False),
        ("home", False),
        ("end", False),
    ]
    assert log.auto_scroll is True


def test_busy_message_rejects_second_prompt():
    app = make_app()
    log = FakeLog()
    app.is_busy = True

    app._handle_message("second prompt", log)

    assert any("already running" in str(item) for item in log.items)


def test_plan_command_without_args_does_not_crash():
    app = make_app()
    log = FakeLog()

    app._handle_plan("", log)

    assert any("Plan mode:" in str(item) for item in log.items)
    assert any("Usage: :plan" in str(item) for item in log.items)


def test_agent_question_input_is_handled_while_busy():
    app = make_app()
    log = FakeLog()
    future = concurrent.futures.Future()

    app.is_busy = True
    app._awaiting_agent_question = True
    app._pending_agent_question = Question(
        question="Which implementation should I use?",
        question_type=QuestionType.CHOICE,
        options=["simple", "advanced"],
    )
    app._pending_agent_question_future = future

    handled = app._handle_message("2", log)

    assert handled is None
    assert future.done()
    assert future.result()["value"] == "advanced"
    assert app._awaiting_agent_question is False
    assert any("Continuing" in str(item) for item in log.items)


def test_acp_terminal_output_renders_as_tool_call():
    app = make_app()
    app._call_ui = lambda func, *args: func(*args)
    app._show_thinking_line = lambda text, log: log.add_info(text)
    log = FakeLog()
    terminals = {}
    terminal_counter = [0]

    result, handled = app._handle_terminal_method(
        "terminal/create",
        {"command": "echo", "args": ["hello_from_terminal"]},
        terminals,
        terminal_counter,
        log,
    )
    assert handled is True
    terminal_id = result["terminalId"]
    assert terminals[terminal_id]["pty"] is True

    result, handled = app._handle_terminal_method(
        "terminal/wait_for_exit",
        {"terminalId": terminal_id},
        terminals,
        terminal_counter,
        log,
    )

    assert handled is True
    assert result["exitCode"] == 0
    tool_rows = [item for item in log.items if isinstance(item, dict)]
    assert tool_rows[0]["tool_name"] == "terminal"
    assert tool_rows[0]["status"] == "running"
    assert tool_rows[-1]["status"] == "success"
    assert "hello_from_terminal" in tool_rows[-1]["output"]


def test_acp_terminal_timeout_reports_timeout(monkeypatch):
    monkeypatch.setenv("SUPERQODE_ACP_TERMINAL_PTY", "0")
    app = make_app()
    app._call_ui = lambda func, *args: func(*args)
    app._show_thinking_line = lambda text, log: log.add_info(text)
    log = FakeLog()
    terminals = {}
    terminal_counter = [0]

    result, handled = app._handle_terminal_method(
        "terminal/create",
        {"command": 'python3 -c "import time; time.sleep(2)"'},
        terminals,
        terminal_counter,
        log,
    )
    assert handled is True

    result, handled = app._handle_terminal_method(
        "terminal/wait_for_exit",
        {"terminalId": result["terminalId"], "timeoutMs": 10},
        terminals,
        terminal_counter,
        log,
    )

    assert handled is True
    assert result["exitCode"] == -1
    tool_rows = [item for item in log.items if isinstance(item, dict)]
    assert tool_rows[-1]["status"] == "error"
    assert "Run timed out after 0.01s" in tool_rows[-1]["output"]


def test_agent_question_empty_input_uses_default():
    app = make_app()
    log = FakeLog()
    future = concurrent.futures.Future()

    app._awaiting_agent_question = True
    app._pending_agent_question = Question(
        question="Proceed?",
        question_type=QuestionType.CONFIRM,
        default="Yes",
    )
    app._pending_agent_question_future = future

    assert app._handle_agent_question_input("", log) is True
    assert future.result()["value"] is True


def test_conversation_log_streaming_renders_final_markdown_once():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.start_agent_session("OpenCode", "deepseek/deepseek-v4", "acp", "ask")
    log.add_response_chunk("| Item | Status |\n")
    log.add_response_chunk("| --- | --- |\n")
    log.add_response_chunk("| TUI | clean |\n")
    log.end_agent_session(True)

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "generating response" in rendered
    assert "| --- | --- |" not in rendered
    assert "TUI" in rendered
    assert log.get_last_response().count("| Item | Status |") == 1
    assert "Assistant:" in log.get_all_text()


def test_conversation_log_thinking_icon_is_deterministic():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_thinking("waiting on provider")
    log.add_thinking("waiting on provider")

    rendered = [render_plain(item) for item in writes]
    assert len(rendered) == 1
    assert rendered[0].strip().startswith("💭")


def test_conversation_log_filters_protocol_noise_from_thinking():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_thinking('{"jsonrpc":"2.0","method":"session/update","params":{}}')
    log.add_thinking("reading project files")

    rendered = [render_plain(item) for item in writes]
    assert len(rendered) == 1
    assert "reading project files" in rendered[0]


def test_write_final_response_records_once_and_renders_markdown():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.write_final_response("**Done**\n\n| A | B |\n| --- | --- |\n| 1 | 2 |", agent="OpenCode")
    log.write_final_response("**Done**\n\n| A | B |\n| --- | --- |\n| 1 | 2 |", agent="OpenCode")

    assert log.get_last_response().startswith("**Done**")
    assert log.get_all_text().count("OpenCode:") == 1
    rendered = "\n".join(render_plain(item) for item in writes)
    assert "| --- | --- |" not in rendered
    assert "Done" in rendered


def test_conversation_log_tool_rows_use_action_verbs():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_tool_call(
        "read_file",
        status="success",
        arguments={"path": "src/superqode/app_main.py"},
        output="line 1\nline 2",
        duration=0.2,
    )

    rendered = render_plain(writes[-1])
    assert "Read" in rendered
    assert "src/superqode/app_main.py" in rendered
    assert "0.2s" in rendered


def test_tool_output_modes_minimal_normal_verbose():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.tool_output_mode = "minimal"
    log.add_tool_call("bash", status="success", arguments={"command": "echo hi"}, output="hi")
    minimal = render_plain(writes[-1])
    assert "Run" in minimal
    assert "→" not in minimal

    log.tool_output_mode = "normal"
    log.add_tool_call("bash", status="success", arguments={"command": "echo hi"}, output="hi")
    normal = render_plain(writes[-1])
    assert "1 output line" in normal

    log.tool_output_mode = "verbose"
    log.add_tool_call("bash", status="success", arguments={"command": "echo hi"}, output="hi")
    verbose = render_plain(writes[-1])
    assert "→ hi" in verbose

    log.tool_output_mode = "minimal"
    log.add_tool_call("bash", status="error", arguments={"command": "bad"}, output="boom")
    error = render_plain(writes[-1])
    assert "boom" in error


def test_tool_running_rows_are_hidden_until_verbose():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.tool_output_mode = "normal"
    log.add_tool_call("bash", status="running", arguments={"command": "uv run pytest"})
    assert writes == []

    log.add_tool_call("bash", status="success", arguments={"command": "uv run pytest"}, output="ok")
    assert len(writes) == 1
    assert "Run" in render_plain(writes[-1])

    log.tool_output_mode = "verbose"
    log.add_tool_call("bash", status="running", arguments={"command": "uv run pytest"})
    assert "Run" in render_plain(writes[-1])


def test_active_tool_status_tracks_running_tools_without_log_rows():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)
    log._update_active_tool_status = lambda: None
    log.tool_output_mode = "normal"

    log.add_tool_call("bash", status="running", arguments={"command": "uv run pytest"})
    assert writes == []
    active = render_plain(log._active_tools_renderable())
    assert "running" in active
    assert "Run" in active
    assert "uv run pytest" in active

    # Duplicate running updates from ACP should not duplicate the status strip.
    log.add_tool_call("bash", status="running", arguments={"command": "uv run pytest"})
    assert len(log._active_tool_start_times) == 1

    log.add_tool_call("bash", status="success", arguments={"command": "uv run pytest"}, output="ok")
    assert log._active_tool_start_times == []
    assert render_plain(log._active_tools_renderable()).strip() == ""


def test_tool_diff_is_visible_in_normal_mode():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)
    log.tool_output_mode = "normal"

    diff = "\n".join(
        [
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ]
    )
    log.add_tool_call(
        "apply_patch",
        status="success",
        arguments={"path": "app.py"},
        output="updated",
        diff_text=diff,
    )

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "diff collapsed" not in rendered
    assert "@@ -1 +1 @@" in rendered
    assert "-old" in rendered
    assert "+new" in rendered


def test_pure_tool_result_uses_shared_diff_renderer():
    app = make_app()
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)
    diff = "\n".join(
        [
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ]
    )

    app._show_pure_tool_result(
        "edit_file",
        SimpleNamespace(success=True, output="", metadata={"path": "app.py", "diff_text": diff}),
        log,
    )

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "Edit" in rendered
    assert "app.py" in rendered
    assert "@@ -1 +1 @@" in rendered


def test_permission_needed_for_project_edit_but_not_read(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()

    assert app._tool_needs_permission("edit_file", {"path": "src/app.py"}) is True
    assert app._tool_needs_permission("write_file", {"path": "src/app.py"}) is True
    assert app._tool_needs_permission("apply_patch", {"path": "src/app.py"}) is True
    assert app._tool_needs_permission("read_file", {"path": "src/app.py"}) is False


def test_permission_prompt_is_visible_card_and_sets_pending(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._start_permission_pulse = lambda: None
    app.query_one = lambda *args, **kwargs: SimpleNamespace(placeholder="", focus=lambda: None)

    app._show_permission_prompt("edit_file", {"path": "src/app.py", "old": "a", "new": "b"}, log)

    assert app._permission_pending is True
    assert app._pending_tool_name == "edit_file"
    rendered = render_plain(log.items[-1])
    assert "Permission required" in rendered
    assert "file change" in rendered
    assert "[y]" in rendered
    assert "[n]" in rendered
    assert "[a]" in rendered


def test_permission_input_resets_prompt_state():
    app = make_app()
    app._permission_pending = True
    app._pending_tool_name = "bash"
    app._pending_tool_input = {"command": "uv run pytest"}
    reset = []
    app._reset_input_placeholder = lambda: reset.append(True)
    app.query_one = lambda *args, **kwargs: FakeLog()

    assert app._handle_permission_input("y") is True
    assert app._permission_response == "allow"
    assert app._permission_pending is False
    assert reset == [True]


def test_pending_approvals_render_as_card():
    app = make_app()
    log = FakeLog()
    source = SimpleNamespace(
        get_pending_approvals=lambda: [
            {"index": 0, "tool_name": "bash", "arguments": {"command": "uv run pytest"}}
        ]
    )

    app._announce_pending_approvals(source, log)

    rendered = render_plain(log.items[-1])
    assert "Tool approval needed" in rendered
    assert "bash" in rendered
    assert ":approve [N]" in rendered
    assert ":reject [N]" in rendered


def test_current_git_diff_text_includes_tracked_and_untracked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("new\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("created\n", encoding="utf-8")

    app = make_app()
    diff_text = app._current_git_diff_text()

    assert "tracked.txt" in diff_text
    assert "-old" in diff_text
    assert "+new" in diff_text
    assert "new.txt" in diff_text
    assert "+created" in diff_text


def test_diff_command_opens_selectable_overlay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("new\n", encoding="utf-8")

    app = make_app()
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    assert pushed
    assert pushed[0][0]._title == "Current Diff"
    assert "tracked.txt" in pushed[0][0]._content


def test_acp_render_helpers_keep_completed_row_target_visible():
    from superqode.acp.render import (
        display_title_from_update,
        extract_tool_arguments,
        normalize_acp_tool_status,
    )

    update = {
        "status": "done",
        "name": "read_file",
        "arguments": {"path": "src/superqode/app_main.py"},
    }
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_tool_call(
        display_title_from_update(update),
        "success" if normalize_acp_tool_status(update["status"]) == "completed" else "running",
        arguments=extract_tool_arguments(update),
        output="file contents",
    )

    rendered = render_plain(writes[-1])
    assert "Read" in rendered
    assert "src/superqode/app_main.py" in rendered


@pytest.mark.asyncio
async def test_agent_question_renders_styled_card():
    app = make_app()
    log = FakeLog()
    question = Question(
        question="Which implementation should I use?",
        question_type=QuestionType.CHOICE,
        options=["small patch", "larger cleanup"],
        default="small patch",
    )
    app._call_ui = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    app.query_one = lambda *args, **kwargs: SimpleNamespace(placeholder="", focus=lambda: None)
    app._start_permission_pulse = lambda: None

    task = asyncio.create_task(app._ask_agent_question(question, log))
    await asyncio.sleep(0)
    assert log.items
    text = render_plain(log.items[-1])
    assert "Agent needs your input" in text
    assert "[1]" in text
    assert "small patch" in text
    assert ":cancel" in text
    app._pending_agent_question_future.set_result({"value": "small patch", "custom": False})
    answer = await task
    assert answer.value == "small patch"


def test_retry_refuses_while_busy():
    app = make_app()
    log = FakeLog()
    app.is_busy = True
    app._last_user_message = "previous prompt"

    app._retry_last_message(log)

    assert any("still running" in str(item) for item in log.items)


def test_smart_cancel_resets_local_byok_busy_state():
    app = make_app()
    log = FakeLog()
    pure = FakePureMode()
    app._pure_mode = pure
    app.is_busy = True
    app._stop_thinking = lambda *args, **kwargs: setattr(app, "_stopped_thinking", True)
    app._stop_stream_animation = lambda *args, **kwargs: setattr(app, "is_busy", False)
    app.query_one = lambda *args, **kwargs: log

    app.action_smart_cancel()

    assert pure.cancelled is True
    assert app._cancel_requested is True
    assert app.is_busy is False
    assert any("cancelled" in str(item).lower() for item in log.items)


def test_smart_cancel_prioritizes_active_acp_client_over_stale_byok_session():
    app = make_app()
    log = FakeLog()
    pure = FakePureMode()
    acp_client = FakeACPClient()
    loop_runner = FakeACPLoopRunner()
    app._pure_mode = pure
    app._acp_client = acp_client
    app._acp_loop_runner = loop_runner
    app.is_busy = True
    app._stop_thinking = lambda *args, **kwargs: setattr(app, "_stopped_thinking", True)
    app._stop_stream_animation = lambda *args, **kwargs: setattr(app, "_stopped_stream", True)
    app.query_one = lambda *args, **kwargs: log

    app.action_smart_cancel()

    assert acp_client.cancelled is True
    assert loop_runner.cancel_called is True
    assert pure.cancelled is False
    assert app._cancel_requested is True
    assert any("ACP agent operation" in str(item) for item in log.items)


def test_recommend_command_renders_actionable_picker(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    recommendation = SimpleNamespace(
        provider="ds4",
        model="deepseek-v4-flash",
        setup=SimpleNamespace(configured=True, setup_hint="Ready"),
        labels=["local", "tools", "code"],
        score=125,
        price="free",
        context="1M",
        tool_support="yes",
        reason="Local coding model.",
    )
    monkeypatch.setattr(
        "superqode.providers.recommendations.recommend_models",
        lambda task, limit=8: [recommendation],
    )

    app._recommend_cmd("local", log)

    text = render_plain(log.items[-1])
    assert "Model Recommendations" in text
    assert "ds4/deepseek-v4-flash" in text
    assert "Type a number to connect" in text
    assert app._awaiting_recommendation_selection is True


def test_recommendation_number_connects_local_model():
    app = make_app()
    log = FakeLog()
    connected = []
    app._recommendation_list = [
        SimpleNamespace(provider="ds4", model="deepseek-v4-flash"),
    ]
    app._awaiting_recommendation_selection = True
    app._connect_local_mode = lambda provider, model, target_log: connected.append(
        (provider, model)
    )

    handled = app._handle_recommendation_selection("1", log)

    assert handled is True
    assert connected == [("ds4", "deepseek-v4-flash")]
    assert app._awaiting_recommendation_selection is False


def test_providers_smoke_command_renders_local_health(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app.run_worker = lambda coro: asyncio.run(coro)

    async def fake_smoke_local_provider(provider, model=None, **kwargs):
        assert provider == "ollama"
        return {
            "provider": "ollama",
            "name": "Ollama",
            "host": "http://localhost:11434",
            "registered": True,
            "supported": True,
            "available": True,
            "model": "qwen2.5-coder:7b",
            "models": ["qwen2.5-coder:7b"],
            "running_models": ["qwen2.5-coder:7b"],
            "tool_support": True,
            "tool_result": {"notes": "verified"},
            "completion_ran": False,
            "completion_ok": False,
            "response_preview": "",
        }

    monkeypatch.setattr(
        "superqode.providers.local.smoke.smoke_local_provider",
        fake_smoke_local_provider,
    )

    app._providers_cmd("smoke ollama", log)

    text = render_plain(log.items[-1])
    assert "Local Provider Check" in text
    assert "Ollama (ollama)" in text
    assert "reachable" in text
    assert "qwen2.5-coder:7b" in text
    assert "verified" in text


def test_doctor_live_routes_to_provider_smoke(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app.run_worker = lambda coro: asyncio.run(coro)

    async def fake_smoke_local_provider(provider, model=None, **kwargs):
        assert provider == "ds4"
        return {
            "provider": "ds4",
            "name": "DwarfStar 4",
            "host": "http://127.0.0.1:8000/v1",
            "registered": True,
            "supported": True,
            "available": False,
            "model": "deepseek-v4-flash",
            "models": ["deepseek-v4-flash"],
            "running_models": [],
            "tool_support": True,
            "tool_result": {},
            "completion_ran": False,
            "completion_ok": False,
            "response_preview": "",
        }

    monkeypatch.setattr(
        "superqode.providers.local.smoke.smoke_local_provider",
        fake_smoke_local_provider,
    )

    app._doctor_cmd("ds4 live", log)

    text = render_plain(log.items[-1])
    assert "Local Provider Check" in text
    assert "DwarfStar 4 (ds4)" in text
    assert "not reachable" in text


def test_acp_doctor_command_renders_agent_status(monkeypatch):
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app.run_worker = lambda coro: asyncio.run(coro)

    async def fake_acp_doctor(agent=None, **kwargs):
        assert agent == "opencode"
        return [
            {
                "identity": "opencode.ai",
                "short_name": "opencode",
                "name": "OpenCode",
                "protocol": "acp",
                "type": "coding",
                "installed": False,
                "command": "opencode acp",
                "command_name": "opencode",
                "install_command": "npm install -g opencode",
                "required_env_vars": [],
                "missing_env_vars": [],
                "live": None,
            }
        ]

    monkeypatch.setattr("superqode.acp.doctor.acp_doctor", fake_acp_doctor)

    app._acp_cmd("doctor opencode", log)

    text = render_plain(log.items[-1])
    assert "ACP Agent Doctor" in text
    assert "opencode" in text
    assert "missing" in text
    assert "npm install -g opencode" in text
