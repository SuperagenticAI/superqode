from rich.console import Console
from pathlib import Path
from types import SimpleNamespace
import asyncio
import concurrent.futures
import json
import platform
import subprocess
import sys

import pytest

from superqode.app_main import SelectionAwareInput, SuperQodeApp, render_welcome
from superqode.app.widgets import ConversationLog, HintsBar, StreamingThinkingIndicator
from superqode.harness import (
    AgentSpec,
    FileHarnessStore,
    HarnessEvent,
    HarnessSpec,
    WorkflowMode,
    WorkflowSpec,
    load_harness_spec,
)
from superqode.tools.question_tool import Question, QuestionType
from superqode.providers.models import ModelCapability, ModelInfo, set_live_models
from superqode.providers.models_dev import ProviderInfo, get_models_dev
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

    def scroll_to(self, **kwargs):
        self.scroll_to_kwargs = kwargs

    def add_info(self, text):
        self.items.append(text)

    def add_success(self, text):
        self.items.append(text)

    def add_error(self, text):
        self.items.append(text)

    def add_warning(self, text):
        self.items.append(text)

    def add_system(self, text):
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
        metadata=None,
    ):
        self.items.append(
            {
                "tool_name": tool_name,
                "status": status,
                "file_path": file_path,
                "command": command,
                "output": output,
                "arguments": arguments or {},
                "metadata": metadata or {},
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


def test_tui_init_creates_local_first_config_and_harness(monkeypatch, tmp_path):
    app = make_app()
    log = FakeLog()
    monkeypatch.chdir(tmp_path)

    app._init_config("", log)

    config = Path("superqode.yaml").read_text(encoding="utf-8")
    harness = Path(".superqode/harnesses/coding.yaml").read_text(encoding="utf-8")
    rendered = "\n".join(str(item) for item in log.items)

    assert "provider: ollama" in config
    assert "model: qwen3:8b" in config
    assert "primary: ollama/qwen3:8b" in harness
    assert "provider: ollama" in harness
    assert "gpt-4o-mini" not in config
    assert "gpt-4o-mini" not in harness
    assert "Created local-first harness" in rendered


class FakeACPClient:
    def __init__(self):
        self.cancelled = False
        self._process = None

    async def cancel(self):
        self.cancelled = True
        return True


def render_plain(renderable) -> str:
    # soft_wrap=True maps to no_wrap + overflow=ignore so long command lines and
    # helper phrases are not mid-word wrapped in export_text (width-sensitive
    # substring asserts in this file would otherwise flake on narrow terminals).
    console = Console(record=True, width=140, force_terminal=True)
    console.print(renderable, soft_wrap=True)
    return console.export_text()


def make_app() -> SuperQodeApp:
    app = SuperQodeApp()
    app.set_timer = lambda *args, **kwargs: None
    app._ensure_input_focus = lambda: None
    return app


def test_byok_picker_includes_models_dev_provider_and_full_model_lookup(monkeypatch):
    import superqode.providers.models as model_db

    app = make_app()
    log = FakeLog()
    client = get_models_dev()
    saved_providers = dict(client._providers)
    saved_models = dict(client._models)
    saved_live_models = model_db._live_models
    saved_use_live_data = model_db._use_live_data
    saved_autoload_attempted = model_db._live_autoload_attempted
    muse = ModelInfo(
        id="muse-spark-1.1",
        name="Muse Spark 1.1",
        provider="meta",
        input_price=1.25,
        output_price=4.25,
        context_window=1_000_000,
        capabilities=[
            ModelCapability.TOOLS,
            ModelCapability.REASONING,
            ModelCapability.VISION,
            ModelCapability.LONG_CONTEXT,
        ],
    )
    try:
        client._providers = {
            "meta": ProviderInfo(
                id="meta",
                name="Meta",
                env_vars=["META_MODEL_API_KEY"],
                api_url="https://api.meta.ai/v1",
            )
        }
        client._models = {"meta": {muse.id: muse}}
        monkeypatch.setattr(client, "ensure_cache_loaded", lambda: True)
        set_live_models({"meta": {muse.id: muse}})

        app._show_connect_picker(log)
        assert any(provider_id == "meta" for provider_id, _ in app._byok_connect_list)
        assert "meta" in {
            candidate.value for candidate in app._byok_provider_completion_candidates()
        }

        app._just_showed_byok_picker = False
        app._show_provider_models("meta", log)
        assert app._byok_model_list == ["muse-spark-1.1"]
        assert "muse-spark-1.1" in render_plain(log.items[-1])

        selected = {}
        app._byok_selected_provider = "openai"
        app._awaiting_byok_model = True
        app._byok_model_list = ["gpt-5.6"]
        app._byok_all_model_list = ["gpt-5.6", "gpt-5.6-sol"]
        app._connect_byok_mode = lambda provider, model, _log: selected.update(
            provider=provider, model=model
        )

        assert app._handle_byok_model_selection("gpt-5.6-sol", log) is True
        assert selected == {"provider": "openai", "model": "gpt-5.6-sol"}
    finally:
        client._providers = saved_providers
        client._models = saved_models
        model_db._live_models = saved_live_models
        model_db._use_live_data = saved_use_live_data
        model_db._live_autoload_attempted = saved_autoload_attempted


def test_streaming_indicator_uses_single_slow_rotating_phrase(monkeypatch):
    import superqode.app.widgets as widgets

    monkeypatch.setattr(widgets, "monotonic", lambda: 0)
    indicator = StreamingThinkingIndicator()
    indicator.is_active = True

    text = render_plain(indicator.render())

    assert "◌ 🧠 Thinking deeply" in text
    assert text.count("Thinking deeply") == 1

    monkeypatch.setattr(widgets, "monotonic", lambda: 128)
    text = render_plain(indicator.render())

    assert "🍕 Serving hot code" in text
    assert text.count("Serving hot code") == 1


def test_streaming_indicator_status_shows_alongside_rotating_phrase(monkeypatch):
    import superqode.app.widgets as widgets

    monkeypatch.setattr(widgets, "monotonic", lambda: 128)
    indicator = StreamingThinkingIndicator()
    indicator.is_active = True
    indicator.status = "Working… (step 2)"

    text = render_plain(indicator.render())

    # The whimsical phrase keeps cycling in every mode; the concrete live
    # status appears beside it rather than replacing it.
    assert "Working… (step 2)" in text
    assert "Serving hot code" in text


def test_streaming_indicator_skips_generic_thinking_status(monkeypatch):
    import superqode.app.widgets as widgets

    monkeypatch.setattr(widgets, "monotonic", lambda: 128)
    indicator = StreamingThinkingIndicator()
    indicator.is_active = True
    indicator.status = "💭 Thinking…"

    text = render_plain(indicator.render())

    # A generic "thinking" status is redundant with the phrase, so it's hidden.
    assert "🍕 Serving hot code" in text
    assert "💭 Thinking…" not in text


def test_welcome_positions_superqode_as_harness_engineering_frameworks():
    welcome = render_welcome([])

    text = render_plain(welcome)

    assert "Harness Engineering frameworks for Coding Agents" in text
    assert ":connect" in text
    assert ":mode" in text
    assert ":help" in text
    assert ":init" not in text
    assert "Explore the possibilities of SuperQode" in text
    assert "Optimized for Local and Open Models" in text
    assert "Build and Optimize Your Harness" in text
    assert "Connect Anything" in text
    assert "Local · ACP · MCP · A2A · BYOK · SDKs" in text
    assert "Local/open models · Harnesses · ACP/MCP/A2A · BYOK/SDKs" not in text
    assert "Agentic Code Needs Super Quality Engineering" not in text


def test_hints_bar_surfaces_mode_switcher():
    text = render_plain(HintsBar().render())

    assert ":connect" in text
    assert ":init" not in text
    assert ":mode" in text
    assert ":harness" in text
    assert ":memory" in text


def test_lmstudio_app_only_prompt_does_not_arm_enter_start(monkeypatch):
    import superqode.local.servers as servers
    from superqode.local.servers import LocalReadiness

    class _Manager:
        def precheck(self, engine):
            assert engine == "lmstudio"
            return LocalReadiness(
                engine="lmstudio",
                installed=True,
                running=False,
                base_url="http://127.0.0.1:1234/v1",
                state="stopped",
                start_hint="Open LM Studio and start the Local Server on port 1234",
                needs_model=False,
                startable=False,
                cli_available=False,
            )

    monkeypatch.setattr(servers, "get_manager", lambda: _Manager())

    app = SuperQodeApp.__new__(SuperQodeApp)
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = FakeLog()

    handled = asyncio.run(SuperQodeApp._render_local_server_state(app, "lmstudio", log))
    text = "\n".join(render_plain(item) for item in log.items)

    assert handled is True
    assert getattr(app, "_awaiting_local_server_start", None) is None
    assert "First open LM Studio" in text
    assert 'open -a "LM Studio"' in text
    assert "lms server start -p 1234" in text
    assert "npx lmstudio install-cli" in text
    assert pinned


def test_lmstudio_cli_but_app_closed_prompt_asks_user_to_open_app_first(monkeypatch):
    import superqode.local.servers as servers
    from superqode.local.servers import LocalReadiness

    class _Manager:
        def precheck(self, engine):
            assert engine == "lmstudio"
            return LocalReadiness(
                engine="lmstudio",
                installed=True,
                running=False,
                base_url="http://127.0.0.1:1234/v1",
                state="stopped",
                start_hint=":local serve lmstudio",
                needs_model=False,
                startable=False,
                cli_available=True,
            )

    monkeypatch.setattr(servers, "get_manager", lambda: _Manager())

    app = SuperQodeApp.__new__(SuperQodeApp)
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = FakeLog()

    handled = asyncio.run(SuperQodeApp._render_local_server_state(app, "lmstudio", log))
    text = "\n".join(render_plain(item) for item in log.items)

    assert handled is True
    assert getattr(app, "_awaiting_local_server_start", None) is None
    assert "First open LM Studio" in text
    assert 'open -a "LM Studio"' in text
    assert "lms server start -p 1234" in text
    assert "Need SuperQode to run that command? Press Enter" not in text
    assert "npx lmstudio install-cli" not in text
    assert pinned


def test_lmstudio_open_with_cli_offers_enter_start(monkeypatch):
    import superqode.local.servers as servers
    from superqode.local.servers import LocalReadiness

    class _Manager:
        def precheck(self, engine):
            assert engine == "lmstudio"
            return LocalReadiness(
                engine="lmstudio",
                installed=True,
                running=False,
                base_url="http://127.0.0.1:1234/v1",
                state="stopped",
                start_hint=":local serve lmstudio",
                needs_model=False,
                startable=True,
                app_running=True,
                cli_available=True,
            )

    monkeypatch.setattr(servers, "get_manager", lambda: _Manager())

    app = SuperQodeApp.__new__(SuperQodeApp)
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = FakeLog()

    handled = asyncio.run(SuperQodeApp._render_local_server_state(app, "lmstudio", log))
    text = "\n".join(render_plain(item) for item in log.items)

    assert handled is True
    assert app._awaiting_local_server_start == "lmstudio"
    assert "LM Studio is open and the lms CLI is available" in text
    assert "Need SuperQode to run that command? Press Enter" in text
    assert "lms server start -p 1234" in text
    assert 'open -a "LM Studio"' not in text
    assert pinned


def test_startable_local_server_prompt_is_manual_first(monkeypatch):
    import superqode.local.servers as servers
    from superqode.local.servers import LocalReadiness

    class _Manager:
        def precheck(self, engine):
            assert engine == "ollama"
            return LocalReadiness(
                engine="ollama",
                installed=True,
                running=False,
                base_url="http://127.0.0.1:11434/v1",
                state="stopped",
                start_hint=":local serve ollama",
                needs_model=False,
                startable=True,
            )

    monkeypatch.setattr(servers, "get_manager", lambda: _Manager())

    app = SuperQodeApp.__new__(SuperQodeApp)
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = FakeLog()

    handled = asyncio.run(SuperQodeApp._render_local_server_state(app, "ollama", log))
    text = "\n".join(render_plain(item) for item in log.items)

    assert handled is True
    assert app._awaiting_local_server_start == "ollama"
    assert "Recommended: start it yourself" in text
    assert "OLLAMA_HOST=127.0.0.1:11434 ollama serve" in text
    assert ":local serve ollama" in text
    assert "Edit the model, port, or context if your setup needs it." in text
    assert "Need SuperQode to start a managed server? Press Enter" in text
    assert "to start it now" not in text
    assert pinned
    assert "Start ollama yourself" in pinned[-1][0]


def test_missing_mlx_prompt_shows_environment_and_exact_command(monkeypatch):
    import superqode.local.servers as servers
    import superqode.providers.env_introspect as env_introspect
    from superqode.local.servers import LocalReadiness

    class _Manager:
        def precheck(self, engine):
            assert engine == "mlx"
            return LocalReadiness(
                engine="mlx",
                installed=False,
                running=False,
                base_url="http://127.0.0.1:8080/v1",
                state="missing",
                start_hint=":local serve mlx",
                needs_model=False,
                startable=False,
            )

    monkeypatch.setattr(servers, "get_manager", lambda: _Manager())
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        env_introspect,
        "environment_info",
        lambda: SimpleNamespace(
            label="SuperQode dev checkout",
            python="/tmp/superqode/.venv/bin/python",
            target="the SuperQode checkout at /tmp/superqode",
        ),
    )
    monkeypatch.setattr(
        servers,
        "mlx_install_command",
        lambda python=None: (
            "uv pip install --python /tmp/superqode/.venv/bin/python 'mlx-lm>=0.31.0,<0.32.0'"
        ),
    )

    app = SuperQodeApp.__new__(SuperQodeApp)
    pinned = []
    app._pin_local_prompt_to_input = lambda placeholder, log, **kwargs: pinned.append(
        (placeholder, kwargs)
    )
    log = FakeLog()

    handled = asyncio.run(SuperQodeApp._render_local_server_state(app, "mlx", log))
    text = "\n".join(render_plain(item) for item in log.items)

    assert handled is True
    assert app._awaiting_local_dep_install == "mlx"
    assert "SuperQode is running from: SuperQode dev checkout" in text
    assert "This will modify: the SuperQode checkout at /tmp/superqode" in text
    assert "Exact command:" in text
    assert "uv pip install --python /tmp/superqode/.venv/bin/python" in text
    assert "Press Enter to run that exact command" in text
    assert pinned


def test_runtime_missing_message_includes_environment_context(monkeypatch):
    import superqode.providers.env_introspect as env_introspect

    monkeypatch.setattr(
        env_introspect,
        "environment_info",
        lambda: SimpleNamespace(
            label="project virtual environment",
            python="/tmp/project/.venv/bin/python",
            target="the current project environment at /tmp/project",
        ),
    )

    message = SuperQodeApp._runtime_install_message("pydanticai", 'uv add "superqode[pydanticai]"')

    assert "Runtime 'pydanticai' is not installed." in message
    assert "SuperQode is running from: project virtual environment" in message
    assert "This command modifies: the current project environment at /tmp/project" in message
    assert 'Run: uv add "superqode[pydanticai]"' in message


def test_opencode_acp_model_normalization_preserves_provider_ids():
    assert (
        SuperQodeApp._normalize_acp_model_id("opencode", "deepseek/deepseek-v4-pro")
        == "deepseek/deepseek-v4-pro"
    )
    assert SuperQodeApp._normalize_acp_model_id("opencode", "big-pickle") == "opencode/big-pickle"
    assert SuperQodeApp._normalize_acp_model_id("opencode", "opencode/auto") is None


def test_grok_acp_model_normalization_strips_ui_prefixes():
    # UI placeholders mean "use the signed-in account's default".
    assert SuperQodeApp._normalize_acp_model_id("grok", "grok/default") is None
    assert SuperQodeApp._normalize_acp_model_id("grok", "auto") is None
    # Grok Build expects bare xAI ids; provider-style prefixes are stripped.
    assert SuperQodeApp._normalize_acp_model_id("grok", "xai/grok-4.5") == "grok-4.5"
    assert SuperQodeApp._normalize_acp_model_id("grok", "grok/grok-build-0.1") == "grok-build-0.1"
    # The CLI's own default alias and bare ids pass through unchanged.
    assert SuperQodeApp._normalize_acp_model_id("grok", "grok-build") == "grok-build"
    assert SuperQodeApp._normalize_acp_model_id("grok", "grok-4.5") == "grok-4.5"


def test_prompt_height_wraps_and_caps_long_text():
    # Prompt starts at a 3-line minimum and grows up to an 8-line cap.
    assert SelectionAwareInput._height_for_text("", 40) == 3
    assert SelectionAwareInput._height_for_text("short prompt", 40) == 3
    assert SelectionAwareInput._height_for_text("x" * 90, 40) == 3
    assert SelectionAwareInput._height_for_text("x" * 400, 40) == 8
    assert SelectionAwareInput._height_for_text("x" * 1000, 40) == 8
    assert SelectionAwareInput._height_for_text("line 1\nline 2", 40) == 3


def test_prompt_default_placeholder_mentions_dictation():
    assert "dictation" in SelectionAwareInput.DEFAULT_PLACEHOLDER.lower()


def test_connect_local_picker_lists_ds4():
    app = make_app()
    log = FakeLog()

    app._show_local_provider_picker(log)

    text = render_plain(log.items[-1])
    assert "Local Model Lab" in text
    assert ":chat on" in text
    assert "no repo context or tools" in text
    assert ":build" in text
    assert "repo-aware coding harness" in text
    assert ":plan on" in text
    assert ":local doctor" in text
    assert ":local optimize" in text
    assert "DwarfStar 4" in text
    assert "ds4" in text
    assert "recommended" in text


def test_prompt_mode_label_tracks_chat_build_and_plan(monkeypatch):
    app = make_app()
    log = FakeLog()

    class FakeLabel:
        def __init__(self):
            self.value = ""

        def update(self, value):
            self.value = value

    class FakePrompt:
        placeholder = SelectionAwareInput.DEFAULT_PLACEHOLDER

    class FakeStatus:
        plan_state = ""
        interaction_mode = ""

    label = FakeLabel()
    prompt = FakePrompt()
    status = FakeStatus()

    def query_one(selector, *args, **kwargs):
        if selector == "#prompt-symbol":
            return label
        if selector == "#prompt-input":
            return prompt
        if selector == "#status-bar":
            return status
        raise LookupError(selector)

    monkeypatch.setattr(app, "query_one", query_one)
    app.current_mode = "local"
    app._pure_mode = SimpleNamespace(
        session=SimpleNamespace(provider="ollama", model="qwen", connected=True)
    )

    app._chat_cmd("on", log)
    assert label.value == "<>"
    assert status.interaction_mode == "chat"
    assert "No repo context or tools" in prompt.placeholder

    app._build_cmd("", log)
    assert label.value == "<>"
    assert status.interaction_mode == "build"
    assert prompt.placeholder == SelectionAwareInput.DEFAULT_PLACEHOLDER
    assert app._chat_mode is False
    assert app._plan_mode_enabled is False

    app._handle_plan("on", log)
    assert label.value == "<>"
    assert status.interaction_mode == "plan"
    assert "Plan first" in prompt.placeholder
    assert status.plan_state == "ON"


def test_prompt_border_title_uses_code_not_build(monkeypatch):
    app = make_app()

    class FakeInputBox:
        border_title = ""

    input_box = FakeInputBox()
    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, *args, **kwargs: (
            input_box if selector == "#input-box" else (_ for _ in ()).throw(LookupError(selector))
        ),
    )

    app._set_prompt_border_title()

    assert input_box.border_title == "✎ Code"


def test_mode_picker_switches_with_keyboard(monkeypatch):
    app = make_app()
    log = FakeLog()

    class FakeSymbol:
        def update(self, value):
            self.value = value

    class FakePrompt:
        placeholder = SelectionAwareInput.DEFAULT_PLACEHOLDER

    class FakeStatus:
        plan_state = ""
        interaction_mode = ""

    symbol = FakeSymbol()
    prompt = FakePrompt()
    status = FakeStatus()

    def query_one(selector, *args, **kwargs):
        if selector == "#log":
            return log
        if selector == "#prompt-symbol":
            return symbol
        if selector == "#prompt-input":
            return prompt
        if selector == "#status-bar":
            return status
        raise LookupError(selector)

    monkeypatch.setattr(app, "query_one", query_one)
    app.set_timer = lambda *args, **kwargs: None

    app._mode_cmd("", log)
    text = render_plain(log.items[-1])
    assert "Mode Switcher" in text
    assert "CHAT" in text
    assert "BUILD" in text
    assert "PLAN" in text

    app.action_navigate_mode_down()
    app.action_navigate_mode_down()
    app.action_select_highlighted_mode()

    assert app._awaiting_mode_selection is False
    assert app._plan_mode_enabled is True
    assert app._chat_mode is False
    assert status.interaction_mode == "plan"


def test_connection_summary_renders_compact_local_card():
    app = make_app()
    log = FakeLog()

    app._show_connection_summary(
        log,
        mode="local",
        provider="ollama",
        provider_name="Ollama",
        model="gemma4:12b-mlx",
        host="http://localhost:11434",
    )

    text = render_plain(log.items[-1])
    assert "Local Model Connected" in text
    assert "Method" in text
    assert "Local" in text
    assert "Ollama" in text
    assert "gemma4:12b-mlx" in text
    assert "http://localhost:11434" in text
    assert "ollama serve" not in text
    assert "ollama pull" not in text


def test_colorful_status_bar_shows_local_provider_and_full_model():
    from superqode.app.widgets import ColorfulStatusBar

    bar = ColorfulStatusBar()
    bar.update_byok_status("ollama", "gemma4:12b-mlx")
    bar.interaction_mode = "chat"

    plain = bar.render().plain
    assert "ollama" in plain
    assert "gemma4:12b-mlx" in plain
    assert "CHAT" in plain


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
checks:
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
        HarnessEvent(
            type="workflow.step.completed",
            run_id=run.run_id,
            data={"step_id": "coder", "status": "done"},
        ),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(
            type="checks.step.completed",
            run_id=run.run_id,
            data={"name": "tests", "returncode": 0},
        ),
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
    assert "checks.step.completed" in text
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
    assert commands["harness_wizard"].shortcut == ":harness wizard "
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
    assert ":harness wizard" in COMMANDS
    assert ":harness init" in COMMANDS
    assert ":harness wizard" in {command.command for command in DEFAULT_COMMANDS}
    assert ":qe fullstack" not in COMMANDS
    assert ":qe unit_tester" not in COMMANDS
    assert ":qe api_tester" not in COMMANDS
    assert ":connect" in COMMANDS
    assert ":connect acp" in COMMANDS
    assert ":connect byok" in COMMANDS
    assert ":connect local" in COMMANDS
    assert ":connect grok" in COMMANDS
    assert ":chat" in COMMANDS
    assert ":build" in COMMANDS
    assert ":mode" in COMMANDS
    assert ":mode chat" in COMMANDS
    assert ":mode build" in COMMANDS
    assert ":mode plan" in COMMANDS
    assert ":exit" in COMMANDS
    assert ":quit" in COMMANDS
    assert ":vim" in COMMANDS
    assert ":set vim" in COMMANDS
    assert ":w" in COMMANDS
    assert ":e" in COMMANDS
    assert ":ls" in COMMANDS

    assert ":grep" in COMMANDS
    assert ":diff files" in COMMANDS
    assert ":timeline" in COMMANDS
    assert ":tree" in COMMANDS
    assert ":sidebar" in COMMANDS
    assert ":sodebar" in COMMANDS
    assert ":sessions" in COMMANDS
    assert ":sessions resume" in COMMANDS
    assert ":resume" in COMMANDS
    assert ":share" in COMMANDS
    assert ":share create" in COMMANDS
    assert ":share import" in COMMANDS
    assert ":trust" in COMMANDS
    assert ":trust yes" in COMMANDS
    assert ":plugins" in COMMANDS
    assert ":plugins doctor" in COMMANDS
    assert ":plugins add" in COMMANDS
    assert ":skills optimize" in COMMANDS
    assert ":skillopt export" in COMMANDS
    assert ":skillopt check" in COMMANDS
    assert ":harness optimize" in COMMANDS
    assert ":harness optimize-inspect" in COMMANDS
    assert ":harness optimize-ledger" in COMMANDS
    assert ":local optimize" in COMMANDS
    assert ":memory" in COMMANDS
    assert ":memory providers" in COMMANDS
    assert ":memory remember" in COMMANDS
    assert ":permissions" in COMMANDS
    assert ":policy" in COMMANDS
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
    assert ":connect grok" in slash_values
    assert ":chat" in slash_values
    assert ":build" in slash_values
    assert ":mode" in slash_values
    assert ":mode chat" in slash_values
    assert ":mode build" in slash_values
    assert ":mode plan" in slash_values
    assert ":skills optimize" in slash_values
    assert ":skillopt export" in slash_values
    assert ":skillopt check" in slash_values
    assert ":harness optimize" in slash_values
    assert ":harness optimize-inspect" in slash_values
    assert ":harness optimize-ledger" in slash_values
    assert ":local optimize" in slash_values
    assert ":connect byok" in slash_values
    assert ":connect local" in slash_values
    assert ":exit" in slash_values
    assert ":quit" in slash_values
    assert ":vim" in slash_values
    assert ":set vim" in slash_values
    assert ":w" in slash_values
    assert ":e" in slash_values
    assert ":ls" in slash_values
    assert ":grep" in slash_values
    assert ":diff" in slash_values
    assert ":diff files" in slash_values
    assert ":timeline" in slash_values
    assert ":tree" in slash_values
    assert ":sidebar" in slash_values
    assert ":sodebar" in slash_values
    assert ":sessions" in slash_values
    assert ":sessions resume" in slash_values
    assert ":resume" in slash_values
    assert "/tree" in slash_values
    assert ":share" in slash_values
    assert ":share create" in slash_values
    assert ":share import" in slash_values
    assert ":trust" in slash_values
    assert ":trust yes" in slash_values
    assert ":plugins" in slash_values
    assert ":plugins doctor" in slash_values
    assert ":plugins add" in slash_values
    assert ":memory" in slash_values
    assert ":memory providers" in slash_values
    assert ":memory remember" in slash_values
    assert ":permissions" in slash_values
    assert ":policy" in slash_values
    assert ":c" not in slash_values
    assert ":q" not in slash_values


def test_tui_static_commands_cover_cli_surface_except_tui_launcher():
    import click

    from superqode.app.constants import COMMANDS
    from superqode.main import cli_main

    def walk(command, prefix=()):
        rows = []
        if isinstance(command, click.Group):
            for name, subcommand in command.commands.items():
                path = prefix + (name,)
                rows.append(path)
                rows.extend(walk(subcommand, path))
        return rows

    tui_commands = {tuple(command[1:].split()) for command in COMMANDS if command.startswith(":")}
    missing = [
        " ".join(path) for path in walk(cli_main) if path != ("tui",) and path not in tui_commands
    ]

    assert missing == []


def test_tui_harness_wizard_writes_and_loads_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd(
        "wizard demo --starter coding --provider ollama --model qwen3-coder --output demo.yaml --load",
        log,
    )

    spec_path = tmp_path / "demo.yaml"
    assert spec_path.exists()
    spec = load_harness_spec(spec_path)
    assert spec.name == "demo"
    assert spec.model_policy.primary == "ollama/qwen3-coder"
    assert spec.metadata["built_with"] == "harness wizard"

    rendered = "\n".join(
        render_plain(item) if not isinstance(item, str) else item for item in log.items
    )
    assert "Harness Wizard" in rendered
    assert "Harness: Demo loaded" in rendered
    assert app._pure_mode is not None
    assert app._pure_mode.harness_enabled


def test_tui_harness_wizard_guided_steps_write_and_load_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    assert app._awaiting_harness_wizard is True
    assert "Harness name" in render_plain(log.items[-1])

    app._handle_harness_wizard_input("guided", log)
    assert "Choose starting point" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("1", log)
    assert "Provider" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("ollama", log)
    assert "Model" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("qwen3-coder", log)
    assert "Tools" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("3", log)
    assert "Permissions" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("1", log)
    assert "Tool-call format" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("", log)
    assert "Workflow" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("", log)
    assert "Output file" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("guided.yaml", log)
    assert "Load this harness now" in render_plain(log.items[-1])
    app._handle_harness_wizard_input("", log)

    spec = load_harness_spec(tmp_path / "guided.yaml")
    assert spec.name == "guided"
    assert spec.model_policy.primary == "ollama/qwen3-coder"
    assert spec.execution_policy.allow_write is True
    assert spec.execution_policy.allow_shell is False
    assert app._awaiting_harness_wizard is False
    assert app._pure_mode is not None
    assert app._pure_mode.harness_enabled


def test_tui_harness_wizard_enter_defaults_create_runnable_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    for _ in range(10):
        app._handle_harness_wizard_input("", log)

    spec = load_harness_spec(tmp_path / "harness.yaml")
    assert spec.name == "my-harness"
    assert spec.metadata["template"] == "qwen-coding"
    assert spec.model_policy.primary == "ollama/qwen3-coder"
    assert spec.model_policy.pack == "qwen-coder"
    assert app._awaiting_harness_wizard is False
    assert app._pure_mode is not None
    assert app._pure_mode.harness_enabled


def test_tui_harness_wizard_final_yes_loads_and_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    for _ in range(9):
        app._handle_harness_wizard_input("", log)
    assert "Load this harness now" in render_plain(log.items[-1])

    app._handle_harness_wizard_input("yes", log)

    assert app._awaiting_harness_wizard is False
    assert app._harness_wizard_state is None
    assert app._pure_mode is not None
    status = app._pure_mode.get_status()["harness"]
    assert status["enabled"] is True
    assert status["name"] == "my-harness"
    assert status["path"].endswith("harness.yaml")
    rendered = "\n".join(
        render_plain(item) if not isinstance(item, str) else item for item in log.items
    )
    assert "Harness: My-harness loaded" in rendered


def test_tui_harness_wizard_yes_on_output_step_loads_default_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    for _ in range(8):
        app._handle_harness_wizard_input("", log)
    assert "Output file" in render_plain(log.items[-1])

    app._handle_harness_wizard_input("yes", log)

    assert (tmp_path / "harness.yaml").exists()
    assert not (tmp_path / "yes").exists()
    assert app._awaiting_harness_wizard is False
    assert app._harness_wizard_state is None
    assert app._pure_mode is not None
    status = app._pure_mode.get_status()["harness"]
    assert status["enabled"] is True
    assert status["path"].endswith("harness.yaml")


def test_tui_harness_wizard_defaults_use_next_available_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "harness.yaml").write_text("existing: true\n")
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    for _ in range(10):
        app._handle_harness_wizard_input("", log)

    assert (tmp_path / "harness-2.yaml").exists()
    assert (tmp_path / "harness.yaml").read_text() == "existing: true\n"
    assert app._awaiting_harness_wizard is False
    status = app._pure_mode.get_status()["harness"]
    assert status["enabled"] is True
    assert status["path"].endswith("harness-2.yaml")


def test_tui_help_surfaces_developer_workflows():
    app = make_app()
    log = FakeLog()

    app._show_help(log)

    text = render_plain(log.items[-1])
    assert "Developer Workflows" in text
    assert ":share create" in text
    assert ":share export" in text
    assert ":share list" in text
    assert ":share revoke" in text
    assert ":trust doctor" in text
    assert ":trust yes|no" in text
    assert ":plugins doctor" in text
    assert ":memory remember" in text
    assert ":memory search specmem" in text
    assert ":codex status" in text
    assert ":claude status" in text
    assert ":antigravity status" in text
    assert "Optional Vim Mode" in text


def test_vim_mode_toggle_and_set_aliases(monkeypatch):
    monkeypatch.delenv("SUPERQODE_VIM_MODE", raising=False)
    app = make_app()
    log = FakeLog()

    assert app._vim_enabled() is False

    app._handle_command(":vim on", log)
    assert app._vim_enabled() is True
    assert any("Vim mode enabled" in str(item) for item in log.items)

    app._handle_command(":set novim", log)
    assert app._vim_enabled() is False

    app._handle_command(":set vim", log)
    assert app._vim_enabled() is True


def test_vim_aliases_route_to_existing_handlers(monkeypatch):
    app = make_app()
    log = FakeLog()
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(app, "_handle_export", lambda args, _log: calls.append(("export", args)))
    monkeypatch.setattr(app, "_handle_view", lambda args, _log: calls.append(("view", args)))
    monkeypatch.setattr(app, "_handle_search", lambda args, _log: calls.append(("search", args)))
    monkeypatch.setattr(app, "_show_sessions", lambda _log: calls.append(("sessions", "")))

    app._handle_command(":w out/transcript", log)
    app._handle_command(":e src/superqode/app_main.py", log)
    app._handle_command(":grep TODO", log)
    app._handle_command(":ls", log)

    assert calls == [
        ("export", "out/transcript"),
        ("view", "src/superqode/app_main.py"),
        ("search", "TODO"),
        ("sessions", ""),
    ]


def test_sidebar_commands_toggle_sidebar(monkeypatch):
    app = make_app()
    log = FakeLog()
    calls = []

    monkeypatch.setattr(app, "action_toggle_sidebar", lambda: calls.append("sidebar"))

    app._handle_command(":sidebar", log)
    app._handle_command(":sodebar", log)

    assert calls == ["sidebar", "sidebar"]


def test_export_writes_markdown_and_json_transcripts(tmp_path, monkeypatch):
    app = make_app()
    app.current_runtime = "codex-sdk"
    app.current_provider = "openai"
    app.current_model = "gpt-5.5"
    log = FakeLog()
    log._messages = [
        ("user", "summarize this repo", ""),
        ("agent", "Here is the summary.", "codex"),
    ]
    monkeypatch.chdir(tmp_path)

    app._handle_export("markdown exports/session", log)
    app._handle_export("json exports/session", log)

    md_path = tmp_path / "exports" / "session.md"
    json_path = tmp_path / "exports" / "session.json"
    assert md_path.exists()
    assert json_path.exists()
    markdown = md_path.read_text(encoding="utf-8")
    exported_json = json_path.read_text(encoding="utf-8")
    assert "# SuperQode Transcript" in markdown
    assert "**Runtime:** codex-sdk" in markdown
    assert "summarize this repo" in markdown
    assert '"format": "superqode-transcript-v1"' in exported_json
    assert '"model": "gpt-5.5"' in exported_json
    assert '"content": "Here is the summary."' in exported_json


def test_export_infers_format_from_suffix(tmp_path, monkeypatch):
    app = make_app()
    log = FakeLog()
    log._messages = [("user", "hello", "")]
    monkeypatch.chdir(tmp_path)

    app._handle_export(str(tmp_path / "transcript.json"), log)

    exported = (tmp_path / "transcript.json").read_text(encoding="utf-8")
    assert '"format": "superqode-transcript-v1"' in exported
    assert '"content": "hello"' in exported


def test_session_tree_renders_forks(tmp_path, monkeypatch):
    from superqode.agent.session_manager import SessionManager

    monkeypatch.chdir(tmp_path)
    manager = SessionManager(storage_dir=".superqode/sessions")
    parent_id = manager.start_session("root-session", provider="openai", model="gpt-5")
    manager.add_user_message("start")
    child_id = manager.fork_current_session("child-session")
    child_meta = manager.get_session_info(child_id)
    assert child_meta is not None
    child_meta.title = "Forked idea"
    manager.store._save_metadata(child_meta)

    app = make_app()
    log = FakeLog()
    app._show_session_tree(log)

    text = render_plain(log.items[-1])
    assert "Session Tree" in text
    assert parent_id[:8] in text
    assert child_id[:8] in text
    assert "Forked idea" in text
    assert "+-" in text


def test_sessions_resume_opens_keyboard_picker_and_selects(tmp_path, monkeypatch):
    from superqode.agent.session_manager import SessionManager

    monkeypatch.chdir(tmp_path)
    manager = SessionManager(storage_dir=".superqode/sessions")
    manager.start_session("first-session", provider="ollama", model="qwen")
    manager.start_session("second-session", provider="openai", model="gpt")

    app = make_app()
    log = FakeLog()
    resumed = []

    class FakePureMode:
        def __init__(self):
            self.current = ""

        def resume_session(self, session_id):
            self.current = session_id
            resumed.append(session_id)
            return [{"role": "user", "content": "hello from saved session"}]

        def get_current_session_id(self):
            return self.current

    pure = FakePureMode()
    monkeypatch.setattr(app, "_ensure_pure_mode", lambda: pure)
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: log)

    app._handle_command(":sessions resume", log)

    assert app._awaiting_session_resume is True
    rendered = render_plain(log.items[-1])
    assert "Resume Session" in rendered
    assert ":sessions resume <id>" in rendered

    app.action_navigate_session_resume_down()
    expected_id = app._session_resume_list[app._session_resume_highlighted_index].session_id
    app.action_select_highlighted_session_resume()

    assert resumed == [expected_id]
    assert app._awaiting_session_resume is False
    assert any("Resumed session" in str(item) for item in log.items)


def test_share_create_import_list_and_revoke(tmp_path, monkeypatch):
    from superqode.agent.session_manager import SessionManager

    monkeypatch.chdir(tmp_path)
    manager = SessionManager(storage_dir=".superqode/sessions")
    manager.start_session("abc123", provider="test", model="m")
    manager.add_user_message("hello")

    app = make_app()
    log = FakeLog()

    app._handle_share("create abc123", log)
    artifacts = list((tmp_path / ".superqode" / "shares").glob("*.superqode-share.json"))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.exists()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["format"] == "superqode-share-v1"
    assert payload["source_session_id"] == "abc123"

    app._handle_share(f"import {artifact} imported-session", log)
    imported = manager.get_session_info("imported-session")
    assert imported is not None
    assert imported.parent_session_id == "abc123"
    manager.start_session("imported-session")
    assert manager.get_messages()[0].content == "hello"

    app._handle_share("list", log)
    assert artifact.name in render_plain(log.items[-1])

    app._handle_share(f"revoke {artifact}", log)
    assert not artifact.exists()
    assert manager.get_session_info("abc123") is not None


def test_share_export_markdown_and_json(tmp_path, monkeypatch):
    from superqode.agent.session_manager import SessionManager

    monkeypatch.chdir(tmp_path)
    manager = SessionManager(storage_dir=".superqode/sessions")
    manager.start_session("abc123", provider="test", model="m")
    manager.add_user_message("hello")

    app = make_app()
    log = FakeLog()
    md_path = tmp_path / "session-share.md"
    json_path = tmp_path / "session-share.json"

    app._handle_share(f"export abc123 {md_path} --markdown", log)
    app._handle_share(f"export abc123 {json_path} --json", log)

    assert "# SuperQode Session abc123" in md_path.read_text(encoding="utf-8")
    assert '"session_id": "abc123"' in json_path.read_text(encoding="utf-8")


def test_plugins_tui_add_disable_enable_and_doctor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    source = tmp_path / "demo-plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "commands": [{"name": "demo"}],
            }
        ),
        encoding="utf-8",
    )
    app = make_app()
    log = FakeLog()
    app._handle_trust("yes", log)

    app._plugins_cmd(f"add {source}", log)
    assert (tmp_path / ".superqode" / "plugins" / "demo" / "plugin.json").exists()

    app._plugins_cmd("", log)
    text = render_plain(log.items[-1])
    assert "demo" in text
    assert "enabled" in text

    app._plugins_cmd("disable demo", log)
    app._plugins_cmd("", log)
    assert "disabled" in render_plain(log.items[-1])

    app._plugins_cmd("enable demo", log)
    app._plugins_cmd("doctor", log)
    doctor = render_plain(log.items[-1])
    assert "Plugin Doctor" in doctor
    assert "1/1 manifests valid" in doctor


def test_plugins_tui_doctor_reports_broken_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin_dir = tmp_path / ".superqode" / "plugins" / "broken"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"id": "broken", "name": "Broken", "commands": [{"path": "missing.py"}]}),
        encoding="utf-8",
    )
    app = make_app()
    log = FakeLog()

    app._plugins_cmd("doctor", log)

    text = render_plain(log.items[-1])
    assert "FAIL broken" in text
    assert "missing.py" in text


def test_trust_tui_status_and_toggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    (tmp_path / ".superqode" / "plugins").mkdir(parents=True)
    app = make_app()
    log = FakeLog()

    app._handle_trust("", log)
    text = render_plain(log.items[-1])
    assert "Project Trust" in text
    assert "untrusted" in text
    assert ".superqode/plugins" in text

    app._handle_trust("yes", log)
    app._handle_trust("status", log)
    assert "trusted" in render_plain(log.items[-1])

    app._handle_trust("no", log)
    app._handle_trust("status", log)
    assert "untrusted" in render_plain(log.items[-1])


def test_plugins_add_requires_trusted_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    source = tmp_path / "demo-plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo Plugin"}),
        encoding="utf-8",
    )
    app = make_app()
    log = FakeLog()

    app._plugins_cmd(f"add {source}", log)

    assert not (tmp_path / ".superqode" / "plugins" / "demo" / "plugin.json").exists()
    assert any("untrusted" in str(item).lower() for item in log.items)


def test_memory_tui_remember_search_and_providers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    app = make_app()
    log = FakeLog()

    app._memory_cmd("remember Use pnpm in this repo; do not use npm.", log)
    assert any("Remembered" in str(item) for item in log.items)

    app._memory_cmd("search pnpm", log)
    text = render_plain(log.items[-1])
    assert "Memory Search" in text
    assert "Use pnpm" in text

    app._memory_cmd("providers", log)
    providers = render_plain(log.items[-1])
    assert "local" in providers
    assert "specmem" in providers


def test_memory_tui_searches_specmem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    specmem = tmp_path / ".specmem"
    specmem.mkdir()
    (specmem / "agent_context.md").write_text(
        "Checkout flow requires payment smoke tests.",
        encoding="utf-8",
    )
    app = make_app()
    log = FakeLog()

    app._memory_cmd("search specmem checkout payment", log)

    text = render_plain(log.items[-1])
    assert "specmem" in text
    assert "Checkout flow" in text


def test_vim_repeat_replays_last_ex_command(monkeypatch):
    app = make_app()
    log = FakeLog()
    calls: list[str] = []

    monkeypatch.setattr(app, "_show_harness_status", lambda _log: calls.append("status"))

    app._handle_command(":status", log)
    app._repeat_last_ex_command(log)

    assert calls == ["status", "status"]
    assert app._last_ex_command == ":status"


def test_vim_command_history_lists_colon_commands():
    app = make_app()
    log = FakeLog()

    app._history_manager.append_sync(":connect local")
    app._history_manager.append_sync("plain prompt")
    app._history_manager.append_sync(":status")

    app._vim_command_history(log)
    text = render_plain(log.items[-1])

    assert "q: Command History" in text
    assert ":connect local" in text
    assert ":status" in text
    assert "plain prompt" not in text


def test_vim_search_finds_and_navigates_conversation_messages(monkeypatch):
    app = make_app()
    log = FakeLog()
    feedback: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_kwargs: feedback.append(message))
    log._messages = [
        ("user", "first question", ""),
        ("agent", "alpha answer\nwith details", "Agent"),
        ("error", "beta failure", ""),
        ("agent", "alpha follow-up", "Agent"),
    ]

    app._vim_search(log, "alpha")
    assert app._vim_search_matches == [1, 3]
    assert app._vim_search_index == 0
    assert log.scroll_to_kwargs["animate"] is False
    assert "Match 1/2" in feedback[-1]

    app._vim_search_next(log)
    assert app._vim_search_index == 1
    assert "Match 2/2" in feedback[-1]

    app._vim_search_next(log, reverse=True)
    assert app._vim_search_index == 0
    assert "Match 1/2" in feedback[-1]


def test_vim_search_input_parser_preserves_known_slash_commands(monkeypatch):
    app = make_app()
    app._vim_experience_enabled = True
    log = FakeLog()
    searches: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        app,
        "_vim_search",
        lambda _log, query, *, reverse=False: searches.append((query, reverse)),
    )

    assert app._try_vim_search_input("/connect local", log) is False
    assert searches == []

    assert app._try_vim_search_input("/traceback", log) is True
    assert searches == [("traceback", False)]

    assert app._try_vim_search_input("?traceback", log) is True
    assert searches[-1] == ("traceback", True)


def test_vim_search_input_parser_navigates_existing_search(monkeypatch):
    app = make_app()
    log = FakeLog()
    calls: list[bool] = []
    monkeypatch.setattr(
        app,
        "_vim_search_next",
        lambda _log, *, reverse=False: calls.append(reverse),
    )

    assert app._try_vim_search_input("n", log) is True
    assert app._try_vim_search_input("N", log) is True
    assert calls == [False, True]


def test_conversation_log_search_highlight_styles_matching_spans():
    from rich.segment import Segment
    from rich.style import Style
    from textual.strip import Strip

    strip = Strip([Segment("alpha beta alpha", Style())], 16)

    highlighted = ConversationLog._highlight_query_in_strip(strip, "alpha")
    highlighted_segments = [
        segment
        for segment in highlighted
        if segment.style
        and segment.style.bgcolor
        and segment.style.bgcolor.get_truecolor().hex == "#facc15"
    ]

    assert "".join(segment.text for segment in highlighted_segments) == "alphaalpha"


def test_slash_complete_prioritizes_connect_and_quit():
    from superqode.widgets.slash_complete import DEFAULT_COMMANDS, filter_slash_commands

    root_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":")]
    connect_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":c")]
    quit_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":q")]

    assert root_values[:8] == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect grok",
        ":connect byok",
        ":connect local",
        ":exit",
        ":quit",
    ]
    assert connect_values[:6] == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect grok",
        ":connect byok",
        ":connect local",
    ]
    assert ":clear" not in connect_values
    assert ":context" not in connect_values
    assert ":copy" not in connect_values
    assert quit_values[0] == ":quit"


def test_mention_completion_suggests_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    app = make_app()

    # Typing "@" at the end of a prose prompt opens the file picker.
    candidates = app._prompt_completion_candidates_for("explain @")
    labels = {c.label for c in candidates}
    assert "@main.py" in labels
    assert "@src/" in labels

    # The candidate value preserves the leading prose and inserts the reference.
    main_candidate = next(c for c in candidates if c.label == "@main.py")
    assert main_candidate.value == "explain @main.py"
    assert main_candidate.kind == "file"

    # Drilling into a directory lists its contents.
    nested = app._prompt_completion_candidates_for("explain @src/")
    assert any(c.value == "explain @src/app.py" for c in nested)


def test_mention_completion_ignores_emails_and_plain_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = make_app()

    # No "@" -> not a mention, and not a command either.
    assert app._mention_completion_candidates("just some text") is None
    # An email address must not trigger the file picker (no whitespace before @).
    assert app._mention_completion_candidates("ping me at foo@bar.com") is None
    # A trailing space closes the active mention.
    assert app._mention_completion_candidates("see @src/ here") is None


def test_slash_complete_prioritizes_diff_review_commands():
    from superqode.widgets.slash_complete import DEFAULT_COMMANDS, filter_slash_commands

    diff_values = [command.command for command in filter_slash_commands(DEFAULT_COMMANDS, ":d")]

    assert diff_values[:4] == [
        ":diff",
        ":diff files",
        ":diff unified",
        ":diff split",
    ]


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

    # Collapse whitespace so the assertion is robust to terminal line wrapping.
    assert "missing description" in " ".join(text.split())


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

    assert root_values[:8] == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect grok",
        ":connect byok",
        ":connect local",
        ":exit",
        ":quit",
    ]
    assert connect_values[:6] == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect grok",
        ":connect byok",
        ":connect local",
    ]
    assert connect_values == [
        ":connect",
        ":connect acp",
        ":connect antigravity",
        ":connect grok",
        ":connect byok",
        ":connect local",
    ]
    assert quit_values[0] == ":quit"
    assert all(not value.startswith(":qe") for value in quit_values)
    assert SuperQodeApp._should_submit_prompt_without_completion(":c") is False
    assert SuperQodeApp._should_submit_prompt_without_completion(":q") is False
    assert SuperQodeApp._should_submit_prompt_without_completion(":connect") is True
    assert SuperQodeApp._should_submit_prompt_without_completion(":connect acp") is True
    assert SuperQodeApp._should_submit_prompt_without_completion(":connect byok") is True
    assert SuperQodeApp._should_submit_prompt_without_completion(":connect local") is True


def test_connect_completion_enter_accepts_selected_subcommand():
    app = make_app()

    app._prompt_completion_candidates = app._prompt_completion_candidates_for(":connect")
    assert [candidate.value for candidate in app._prompt_completion_candidates[:2]] == [
        ":connect",
        ":connect acp",
    ]

    app._prompt_completion_index = 0
    assert app._prompt_completion_enter_action(":connect") == "submit"

    app._prompt_completion_index = 1
    assert app._prompt_completion_enter_action(":connect") == "accept"


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


def test_prompt_completion_candidates_include_skill_optimize_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / ".agents" / "skills" / "repo-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: repo-review\ndescription: Review repository changes\nenabled: true\n---\n\n# Review\n"
    )
    app = make_app()

    candidates = app._prompt_completion_candidates_for(":skills optimize rep")

    assert candidates[0].label == "repo-review"
    assert candidates[0].kind == "skill"


def test_tui_optimize_commands_delegate_to_cli(monkeypatch):
    app = make_app()
    log = FakeLog()
    calls: list[tuple[list[str], str]] = []

    async def fake_cli(command_parts, _log, label):
        calls.append((command_parts, label))

    monkeypatch.setattr(app, "_superqode_cli_cmd", fake_cli)
    app.run_worker = lambda coro: asyncio.run(coro)

    app._harness_cmd("optimize --spec harness.yaml --tasks eval-tasks.yaml --export-only", log)
    app._harness_cmd(
        "improve --spec harness.yaml --tasks eval-tasks.yaml --from-failures failures.json --export-only",
        log,
    )
    app._harness_cmd("optimize-inspect .superqode/metaharness/run", log)
    app._harness_cmd("optimize-ledger .superqode/metaharness/run", log)
    app._local_cmd("optimize --endpoint http://127.0.0.1:11434/v1 --model qwen", log)
    app._skillopt_cmd("check --baseline base.md --candidate candidate.md", log)

    assert calls == [
        (
            [
                "harness",
                "optimize",
                "--spec",
                "harness.yaml",
                "--tasks",
                "eval-tasks.yaml",
                "--export-only",
            ],
            "Harness optimization",
        ),
        (
            [
                "harness",
                "improve",
                "--spec",
                "harness.yaml",
                "--tasks",
                "eval-tasks.yaml",
                "--from-failures",
                "failures.json",
                "--export-only",
            ],
            "Harness self-improvement",
        ),
        (
            ["harness", "optimize-inspect", ".superqode/metaharness/run"],
            "Harness optimization",
        ),
        (
            ["harness", "optimize-ledger", ".superqode/metaharness/run"],
            "Harness optimization",
        ),
        (
            ["local", "optimize", "--endpoint", "http://127.0.0.1:11434/v1", "--model", "qwen"],
            "Local optimization",
        ),
        (
            ["skillopt", "check", "--baseline", "base.md", "--candidate", "candidate.md"],
            "SkillOpt command",
        ),
    ]


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
    app.push_screen = lambda screen, callback=None: captured.append(
        (screen._title, screen._content)
    )

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


def test_busy_message_queues_second_prompt():
    app = make_app()
    log = FakeLog()
    app.is_busy = True

    app._handle_message("second prompt", log)

    # Type-ahead: the prompt is queued to send once the agent is free.
    assert app._typeahead_queue == ["second prompt"]


def test_plan_command_without_args_does_not_crash():
    app = make_app()
    log = FakeLog()

    app._handle_plan("", log)

    assert any("Plan mode:" in str(item) for item in log.items)
    assert any("Usage: :plan" in str(item) for item in log.items)


def test_live_todos_sync_into_plan_command_state():
    app = make_app()
    log = FakeLog()

    app._sync_plan_manager_from_todos(
        [
            {
                "id": "inspect",
                "content": "Inspect files",
                "status": "completed",
                "priority": "high",
            },
            {
                "id": "patch",
                "content": "Patch code",
                "status": "in_progress",
                "priority": "medium",
            },
        ]
    )

    app._handle_plan("", log)

    text = "\n".join(
        render_plain(item) if not isinstance(item, str) else item for item in log.items
    )
    assert "Progress: 1/2 (50%)" in text
    assert "Inspect files" in text
    assert "Patch code" in text


def test_plan_review_renders_pending_request_even_without_todos():
    app = make_app()
    log = FakeLog()
    app._pending_plan_request = "fix the parser"
    app._pending_plan_status = "pending"

    app._handle_plan("", log)

    text = "\n".join(
        render_plain(item) if not isinstance(item, str) else item for item in log.items
    )
    assert "Plan Review" in text
    assert "fix the parser" in text
    assert "No structured TODOs were emitted yet" in text
    assert ":plan approve" in text
    assert ":plan edit" in text
    assert ":plan reject" in text


def test_plan_edit_replaces_pending_request_and_renders_review():
    app = make_app()
    log = FakeLog()
    app._pending_plan_request = "old request"
    app._pending_plan_status = "approved"

    app._handle_plan("edit new request", log)

    assert app._pending_plan_request == "new request"
    assert app._pending_plan_status == "pending"
    text = "\n".join(
        render_plain(item) if not isinstance(item, str) else item for item in log.items
    )
    assert "new request" in text
    assert "pending" in text


def test_plan_approve_and_reject_aliases():
    app = make_app()
    log = FakeLog()
    handled = []
    app._handle_message = lambda message, target_log: handled.append((message, target_log))

    app._pending_plan_request = "fix the bug"
    app._handle_plan("approve", log)

    assert app._force_execute_once is True
    assert app._pending_plan_status == "approved"
    assert handled == [("fix the bug", log)]

    app._pending_plan_request = "discard me"
    app._force_plan_once = True
    app._force_execute_once = True
    app._handle_plan("reject", log)

    assert app._pending_plan_request == ""
    assert app._pending_plan_status == "rejected"
    assert app._force_plan_once is False
    assert app._force_execute_once is False
    assert any("Plan cleared" in str(item) for item in log.items)


def test_plan_mode_permission_bridge_denies_runtime_approvals():
    app = make_app()
    log = FakeLog()
    pure = SimpleNamespace(on_permission_request=None)
    app._active_plan_mode_for_current_message = True
    app._call_ui = lambda func, *args: func(*args)

    app._install_pure_permission_bridge(pure, log)

    assert pure.on_permission_request("bash", {"command": "touch bad"}) is False
    assert any("Plan mode blocked runtime approval for bash" in str(item) for item in log.items)


def test_colorful_status_bar_shows_plan_badge():
    from superqode.app.widgets import ColorfulStatusBar

    bar = ColorfulStatusBar()
    bar.plan_state = "pending"

    plain = bar.render().plain
    assert "PLAN pending" in plain


def test_plan_status_badge_reflects_app_state(monkeypatch):
    from superqode.app.widgets import ColorfulStatusBar

    app = make_app()
    bar = ColorfulStatusBar()
    monkeypatch.setattr(app, "query_one", lambda *_args, **_kwargs: bar)

    app._plan_mode_enabled = True
    app._refresh_plan_status_badge()
    assert bar.plan_state == "ON"

    app._pending_plan_request = "fix the parser"
    app._pending_plan_status = "pending"
    app._refresh_plan_status_badge()
    assert bar.plan_state == "pending"

    app._pending_plan_status = "approved"
    app._plan_mode_enabled = False
    app._refresh_plan_status_badge()
    assert bar.plan_state == ""


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
    # Full tool rows are the verbose-mode rendering; calm mode folds them into
    # a tidy summary line, so opt into verbose for these structural assertions.
    app.thinking_verbosity = "verbose"
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
    app.thinking_verbosity = "verbose"  # assert full tool rows, not calm summary
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
    assert "generating response" not in rendered
    assert "| --- | --- |" not in rendered
    assert "TUI" in rendered
    assert log.get_last_response().count("| Item | Status |") == 1
    assert "Assistant:" in log.get_all_text()


def test_conversation_log_clearly_separates_question_and_answer():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_user("How does chat mode differ from build mode?")
    log.reset_response_stream("ollama/qwen")
    log.add_response_chunk("Chat skips repo context.\n\n")
    log.write_final_response("Chat skips repo context.\n\nBuild uses tools.", agent="ollama/qwen")

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "YOU" in rendered
    assert "How does chat mode differ from build mode?" in rendered
    assert "AGENT" in rendered
    assert "ollama/qwen" in rendered
    assert rendered.count("Chat skips repo context.") == 1
    assert "Build uses tools." in rendered


def test_final_response_does_not_duplicate_fully_streamed_answer():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.reset_response_stream("Assistant")
    log.add_response_chunk("Already shown.\n\n")
    log.write_final_response("Already shown.\n\n", agent="Assistant")

    rendered = "\n".join(render_plain(item) for item in writes)
    assert rendered.count("Already shown.") == 1
    assert rendered.count("AGENT") == 1


def test_streaming_renders_completed_paragraphs_live():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.start_agent_session("OpenCode", "deepseek/deepseek-v4", "acp", "ask")
    # First paragraph completes (blank line) -> should render before the turn ends.
    log.add_response_chunk("Here is the **plan**.\n\n")
    rendered_mid = "\n".join(render_plain(item) for item in writes)
    assert "Here is the plan." in rendered_mid

    # Second paragraph still being typed -> held back until it stabilizes.
    log.add_response_chunk("Now the second")
    rendered_partial = "\n".join(render_plain(item) for item in writes)
    assert "Now the second" not in rendered_partial

    log.add_response_chunk(" part is done.")
    log.end_agent_session(True)
    rendered_final = "\n".join(render_plain(item) for item in writes)
    assert "Now the second part is done." in rendered_final
    # The first paragraph must not be rendered twice.
    assert rendered_final.count("Here is the plan.") == 1


def test_chat_stream_reset_prevents_previous_reply_in_latest_response():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.reset_response_stream()
    log.add_response_chunk("first reply")
    log.write_final_response("first reply", agent="ollama/qwen")

    log.reset_response_stream()
    log.add_response_chunk("second reply")
    log.write_final_response("second reply", agent="ollama/qwen")

    rendered_items = [render_plain(item) for item in writes]
    second_reply_items = [text for text in rendered_items if "second reply" in text]

    assert second_reply_items
    assert all("first reply" not in text for text in second_reply_items)
    assert log.get_last_response() == "second reply"


def test_chat_worker_resets_stream_between_turns(monkeypatch):
    from types import SimpleNamespace
    from superqode.providers.gateway.base import StreamChunk
    import superqode.providers.gateway.litellm_gateway as gateway_mod

    replies = [["first reply"], ["second reply"]]

    class FakeGateway:
        async def stream_completion(self, **kwargs):
            for piece in replies.pop(0):
                yield StreamChunk(content=piece)

    app = make_app()
    app._pure_mode = SimpleNamespace(
        session=SimpleNamespace(provider="ollama", model="qwen", connected=True)
    )
    app._chat_history = []
    app._cancel_requested = False
    app.call_from_thread = lambda func, *args: func(*args)
    app._start_thinking = lambda *args, **kwargs: None
    app._stop_thinking = lambda *args, **kwargs: None
    app._write_chat_stats = lambda *args, **kwargs: None
    monkeypatch.setattr(gateway_mod, "LiteLLMGateway", FakeGateway)

    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    asyncio.run(app._send_chat_message("one", log))
    asyncio.run(app._send_chat_message("two", log))

    rendered_items = [render_plain(item) for item in writes]
    second_reply_items = [text for text in rendered_items if "second reply" in text]

    assert second_reply_items
    assert all("first reply" not in text for text in second_reply_items)
    assert app._chat_history[-1].content == "second reply"


def test_streaming_holds_unterminated_code_fence():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.start_agent_session("OpenCode", "deepseek/deepseek-v4", "acp", "ask")
    log.add_response_chunk("intro line\n\n```python\nx = 1\n\n")
    rendered = "\n".join(render_plain(item) for item in writes)
    # Intro paragraph flushes, but the open code fence is not rendered yet.
    assert "intro line" in rendered
    assert "x = 1" not in rendered

    log.add_response_chunk("y = 2\n```\n\n")
    log.end_agent_session(True)
    rendered_final = "\n".join(render_plain(item) for item in writes)
    assert "x = 1" in rendered_final
    assert "y = 2" in rendered_final


def test_perform_rewind_trims_transcript_and_truncates_history(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from superqode.agent.session_manager import SessionManager

    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("rwapp01", provider="ollama", model="qwen")
    manager.add_user_message("q1")
    manager.add_assistant_message("a1")
    manager.add_user_message("q2")
    manager.add_assistant_message("a2")

    app = make_app()
    app._pure_mode = SimpleNamespace(_session_manager=manager)

    log = ConversationLog()
    log.write = lambda *a, **k: None
    infos = []
    log.add_info = lambda text: infos.append(text)
    log._messages = [
        ("user", "q1", ""),
        ("agent", "a1", "A"),
        ("user", "q2", ""),
        ("agent", "a2", "A"),
    ]

    app._perform_rewind(2, log)

    # Transcript record is trimmed to before the 2nd user message.
    assert log._messages == [("user", "q1", ""), ("agent", "a1", "A")]
    # Stored agent history is truncated too.
    assert [(m.role, m.content) for m in manager.get_messages()] == [
        ("user", "q1"),
        ("assistant", "a1"),
    ]
    assert any("Rewound to message 2" in t for t in infos)


def test_render_compare_results_shows_labels_answers_and_errors():
    from superqode.agent.parallel_compare import CompareResult, CompareSpec

    app = make_app()
    log = ConversationLog()
    writes = []
    log.write = lambda content, *a, **k: writes.append(content)

    results = [
        CompareResult(spec=CompareSpec("openai", "gpt-4o"), text="**Answer A**", elapsed=1.2),
        CompareResult(spec=CompareSpec("anthropic", "claude"), error="boom", elapsed=0.3),
    ]
    app._render_compare_results(results, log)

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "openai/gpt-4o" in rendered
    assert "Answer A" in rendered
    assert "anthropic/claude" in rendered
    assert "boom" in rendered


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


def test_failed_tool_renders_failure_card_with_command_context():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_tool_call(
        "bash",
        status="error",
        arguments={"command": "uv run pytest"},
        output="line one\nline two\nFAILED tests/test_example.py",
        duration=2.4,
        metadata={"command": "uv run pytest", "cwd": "/repo", "exit_code": 1},
    )

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "Tool failed: Run" in rendered
    assert "exit 1" in rendered
    assert "uv run pytest" in rendered
    assert "/repo" in rendered
    assert "FAILED tests/test_example.py" in rendered


def test_failed_tool_timeout_card_shows_timeout():
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    log.add_tool_call(
        "bash",
        status="error",
        arguments={"command": "npm test"},
        output="Command timed out after 300 seconds",
        metadata={"command": "npm test", "timed_out": True, "timeout": 300},
    )

    rendered = "\n".join(render_plain(item) for item in writes)
    assert "timeout 300s" in rendered
    assert "npm test" in rendered


def test_tool_runs_index_and_detail_capture_output_metadata_and_diff():
    log = ConversationLog()
    log.write = lambda content, *args, **kwargs: None
    diff = "\n".join(["--- a/app.py", "+++ b/app.py", "@@ -1 +1 @@", "-old", "+new"])

    log.add_tool_call(
        "bash",
        status="error",
        arguments={"command": "uv run pytest"},
        output="FAILED tests/test_app.py",
        duration=1.25,
        metadata={"command": "uv run pytest", "cwd": "/repo", "exit_code": 1},
    )
    log.add_tool_call(
        "apply_patch",
        status="success",
        arguments={"path": "app.py"},
        output="updated",
        diff_text=diff,
        metadata={"path": "app.py"},
    )

    index = log.format_tool_runs_index()
    assert "Recent tool runs (2)" in index
    assert "Run" in index
    assert "Apply Patch" in index

    detail = log.format_tool_run_detail(1)
    assert "SuperQode Tool Run" in detail
    assert "Tool:     bash" in detail
    assert "Command:  uv run pytest" in detail
    assert "Cwd:      /repo" in detail
    assert "Exit:     1" in detail
    assert "FAILED tests/test_app.py" in detail

    patch_detail = log.format_tool_run_detail(2)
    assert "Diff" in patch_detail
    assert "+new" in patch_detail


def test_tools_recent_and_tool_number_commands():
    app = make_app()
    log = ConversationLog()
    writes = []
    pushed = []
    log.write = lambda content, *args, **kwargs: writes.append(content)
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None
    log.add_tool_call(
        "bash",
        status="success",
        arguments={"command": "echo hi"},
        output="hi",
    )

    app._show_tools("recent", log)
    assert "Recent tool runs" in render_plain(writes[-1])

    app._show_tools("1", log)
    assert pushed
    assert pushed[0][0]._title == "Tool Run #1"
    assert "SuperQode Tool Run" in pushed[0][0]._content
    assert "echo hi" in pushed[0][0]._content


def test_session_timeline_includes_messages_and_tool_runs():
    log = ConversationLog()
    log.write = lambda content, *args, **kwargs: None

    log.add_user("please fix the test")
    log.add_info("connected to opencode")
    log.add_tool_call(
        "bash",
        status="error",
        arguments={"command": "uv run pytest"},
        output="FAILED tests/test_app.py",
        metadata={"command": "uv run pytest", "exit_code": 1},
    )
    log.write_final_response("Changed the failing test.", agent="Assistant")

    timeline = log.format_session_timeline()

    assert "SuperQode Session Timeline" in timeline
    assert "Messages:" in timeline
    assert "Tool runs: 1" in timeline
    assert "User: please fix the test" in timeline
    assert "Info: connected to opencode" in timeline
    assert "error   Run" in timeline
    assert "uv run pytest" in timeline
    assert "Assistant: Changed the failing test." in timeline
    assert ":tools <number>" in timeline


def test_timeline_command_opens_session_timeline():
    app = make_app()
    log = ConversationLog()
    log.write = lambda content, *args, **kwargs: None
    log.add_user("hello")
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_command(":timeline", log)

    assert pushed
    assert pushed[0][0]._title == "Session Timeline"
    assert "SuperQode Session Timeline" in pushed[0][0]._content
    assert "User: hello" in pushed[0][0]._content


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
    # The shared diff renderer is the verbose-mode path; calm mode shows a tidy
    # one-liner instead, so opt into verbose for this assertion.
    app.thinking_verbosity = "verbose"
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


def test_pure_tool_result_calm_mode_is_one_tidy_line():
    app = make_app()
    app.thinking_verbosity = "normal"  # calm (default)
    log = ConversationLog()
    writes = []
    log.write = lambda content, *args, **kwargs: writes.append(content)

    app._show_pure_tool_result(
        "edit_file",
        SimpleNamespace(success=True, output="", metadata={"path": "app.py", "diff_text": "x"}),
        log,
    )

    rendered = "\n".join(render_plain(item) for item in writes)
    # Tidy summary line, no raw diff content.
    assert "edit" in rendered
    assert "app.py" in rendered
    assert "@@" not in rendered
    assert app._calm_actions == 1


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
    assert "Risk:" in rendered
    assert "medium" in rendered
    assert "[y]" in rendered
    assert "[n]" in rendered
    assert "[a]" in rendered


def test_permission_risk_marks_destructive_commands_critical():
    app = make_app()

    label, _style = app._permission_risk("bash", {"command": "sudo rm -rf /tmp/example"})

    assert label == "critical"


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


def test_permissions_command_shows_mode_pending_and_learned_rules():
    from superqode.approval import ApprovalManager, ApprovalRequest

    app = make_app()
    app.approval_mode = "ask"
    app._permission_pending = True
    app._pending_tool_name = "bash"
    app._approval_manager = ApprovalManager(Console())
    app._approval_manager.always_approve.add("README.md")
    app._approval_manager.always_reject.add("secrets.env")
    app._approval_manager.add_request(
        ApprovalRequest(
            id="req-1",
            title="Edit app.py",
            description="Agent wants to edit app.py",
            file_path="app.py",
            old_content="old\n",
            new_content="new\n",
        )
    )
    log = FakeLog()

    app._handle_permissions(log)

    rendered = render_plain(log.items[-1])
    assert "Permission Policy" in rendered
    assert "Mode" in rendered
    assert "ask" in rendered
    assert "Pending" in rendered
    assert "bash" in rendered
    assert "1 pending" in rendered
    assert "Edit app.py" in rendered
    assert "README.md" in rendered
    assert "secrets.env" in rendered
    assert ":mode auto|ask|deny" in rendered


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

    assert "SuperQode Diff Review" in diff_text
    assert "Files:" in diff_text
    assert "[Working tree] tracked.txt" in diff_text
    assert "[Untracked] new.txt" in diff_text
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
    assert pushed[0][0]._title == "Diff Review"
    assert "SuperQode Diff Review" in pushed[0][0]._content
    assert "Files:" in pushed[0][0]._content
    assert "tracked.txt" in pushed[0][0]._content


def test_diff_files_command_lists_changed_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("new\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("created\n", encoding="utf-8")

    app = make_app()
    log = FakeLog()

    app._handle_diff("files", log)

    rendered = render_plain(log.items[-1])
    assert "Changed files (" in rendered
    assert "[Working tree] tracked.txt" in rendered
    assert "[Staged] tracked.txt" in rendered
    assert "[Untracked] new.txt" in rendered
    assert "Use :diff <path> to open one file." in rendered


def test_diff_command_filters_to_matching_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("old a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old b\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "b.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("new a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new b\n", encoding="utf-8")

    app = make_app()
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("a.txt", log)

    assert pushed
    content = pushed[0][0]._content
    assert "[Working tree] a.txt" in content
    assert "diff --git a/a.txt b/a.txt" in content
    assert "diff --git a/b.txt b/b.txt" not in content


def test_diff_review_overlay_supports_file_navigation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("old a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old b\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "b.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("new a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new b\n", encoding="utf-8")

    app = make_app()
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    screen = pushed[0][0]
    assert len(screen._entries) >= 2
    assert screen._index == -1
    screen.action_next_file()
    assert screen._index == 0
    assert "File 1/" in screen._current_text
    assert "a.txt" in screen._current_text
    screen.action_next_file()
    assert screen._index == 1
    assert "b.txt" in screen._current_text
    screen.action_show_all()
    assert screen._index == -1
    assert "SuperQode Diff Review" in screen._current_text
    assert "Files:" in screen._current_text


def test_diff_review_overlay_can_approve_pending_file_change(tmp_path, monkeypatch):
    from superqode.approval import ApprovalManager, ApprovalRequest

    monkeypatch.chdir(tmp_path)
    app = make_app()
    app._approval_manager = ApprovalManager(Console())
    app._approval_manager.add_request(
        ApprovalRequest(
            id="req-1",
            title="Update app.py",
            description="Agent wants to edit app.py",
            file_path="app.py",
            old_content="old\n",
            new_content="new\n",
        )
    )
    writes = []
    app._file_manager = SimpleNamespace(write=lambda path, content: writes.append((path, content)))
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    screen = pushed[0][0]
    assert screen._entries[0]["approval_id"] == "req-1"
    screen.action_next_file()
    assert "app.py" in screen._current_text
    screen.action_approve_current()

    assert writes == [("app.py", "new\n")]
    assert app._approval_manager.get_pending() == []
    assert screen._entries == []


def test_diff_review_overlay_can_reject_pending_file_change(tmp_path, monkeypatch):
    from superqode.approval import ApprovalManager, ApprovalRequest

    monkeypatch.chdir(tmp_path)
    app = make_app()
    app._approval_manager = ApprovalManager(Console())
    app._approval_manager.add_request(
        ApprovalRequest(
            id="req-2",
            title="Update app.py",
            description="Agent wants to edit app.py",
            file_path="app.py",
            old_content="old\n",
            new_content="new\n",
        )
    )
    writes = []
    app._file_manager = SimpleNamespace(write=lambda path, content: writes.append((path, content)))
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    screen = pushed[0][0]
    screen.action_next_file()
    screen.action_reject_current()

    assert writes == []
    assert app._approval_manager.get_pending() == []
    assert screen._entries == []


def test_diff_review_overlay_can_copy_current_file_patch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("old a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old b\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "b.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("new a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new b\n", encoding="utf-8")

    app = make_app()
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    copied = []
    screen = pushed[0][0]
    screen._copy_to_clipboard = lambda text: copied.append(text)
    screen.action_next_file()
    screen.action_copy_current_patch()

    assert copied
    assert "diff --git a/a.txt b/a.txt" in copied[-1]
    assert "diff --git a/b.txt b/b.txt" not in copied[-1]


def test_diff_review_overlay_can_open_current_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("old a\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], check=True, capture_output=True, text=True)
    (tmp_path / "a.txt").write_text("new a\n", encoding="utf-8")

    app = make_app()
    opened = []
    app._open_diff_entry_file = lambda entry: opened.append(entry["path"]) or "Opened"
    log = FakeLog()
    pushed = []
    app.push_screen = lambda screen, callback=None: pushed.append((screen, callback))
    app.set_timer = lambda *_args, **_kwargs: None

    app._handle_diff("", log)

    screen = pushed[0][0]
    screen.action_next_file()
    screen.action_open_current_file()

    assert opened == ["a.txt"]


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
    pure.session = SimpleNamespace(provider="ollama", model="qwen3.6:35b-mlx")
    app._pure_mode = pure
    app.is_busy = True
    torn_down = []
    app._teardown_local_model_runtime = lambda provider, model: torn_down.append((provider, model))
    app._stop_thinking = lambda *args, **kwargs: setattr(app, "_stopped_thinking", True)
    app._stop_stream_animation = lambda *args, **kwargs: setattr(app, "is_busy", False)
    app.query_one = lambda *args, **kwargs: log

    app.action_smart_cancel()

    assert pure.cancelled is True
    assert app._cancel_requested is True
    assert app.is_busy is False
    assert torn_down == [("ollama", "qwen3.6:35b-mlx")]
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


def test_cleanup_on_exit_cancels_and_tears_down_local_runtime():
    app = make_app()
    pure = FakePureMode()
    pure.session = SimpleNamespace(provider="ollama", model="qwen3.6:35b-mlx")
    app._pure_mode = pure
    torn_down = []
    app._teardown_local_model_runtime = lambda provider, model: torn_down.append((provider, model))

    app._cleanup_on_exit()

    assert pure.cancelled is True
    assert app._cancel_requested is True
    assert torn_down == [("ollama", "qwen3.6:35b-mlx")]


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


def test_local_picker_labels_gemma4_as_tool_capable():
    from superqode.providers.local import LocalModel

    app = make_app()
    log = FakeLog()
    app._local_selected_provider = "ollama"
    app._local_model_list = ["gemma4:31b-mlx-bf16", "gemma2:9b-it", "gemma:latest"]
    app._local_cached_models = [
        LocalModel(id="gemma4:31b-mlx-bf16", name="Gemma 4 31B"),
        LocalModel(id="gemma2:9b-it", name="Gemma 2 9B"),
        LocalModel(id="gemma:latest", name="Gemma Base"),
    ]

    app._redraw_local_provider_models(log)

    text = render_plain(log.items[-1])
    assert "Gemma 4 31B" in text
    assert "Good tool support" in text
    assert "Gemma 2 9B" in text
    assert "No tool support" in text
    gemma_base_section = text.split("Gemma Base", 1)[1]
    assert "No tool support" not in gemma_base_section


def test_local_model_navigation_scrolls_to_highlighted_row(monkeypatch):
    from superqode.providers.local import LocalModel

    app = make_app()
    log = FakeLog()
    models = [LocalModel(id=f"model-{idx}", name=f"Model {idx}") for idx in range(1, 11)]
    app._awaiting_local_model = True
    app._local_selected_provider = "ollama"
    app._local_model_list = [model.id for model in models]
    app._local_cached_models = models
    app._local_highlighted_model_index = 4

    scroll_calls = []
    app.query_one = lambda *args, **kwargs: log
    app._scroll_to_highlighted_local_model = lambda target_log, idx: scroll_calls.append(
        (target_log, idx)
    )

    app.action_navigate_local_model_down()

    assert app._local_highlighted_model_index == 5
    assert scroll_calls == [(log, 5)]


def test_local_model_scroll_calculation_uses_multiline_rows():
    app = make_app()
    calls = []
    log = SimpleNamespace(
        auto_scroll=True,
        size=SimpleNamespace(height=10),
        scroll_to=lambda **kwargs: calls.append(kwargs),
    )

    app._scroll_to_highlighted_local_model(log, 9)

    assert calls
    assert calls[-1]["y"] >= 40
    assert calls[-1]["animate"] is False


def test_picker_scroll_reveals_selected_row_and_supporting_content():
    calls = []
    log = SimpleNamespace(
        auto_scroll=True,
        lines=[
            SimpleNamespace(text="header"),
            SimpleNamespace(text="▶ [7] Advanced runtime  ← SELECTED"),
            SimpleNamespace(text="description"),
            SimpleNamespace(text="ready"),
            SimpleNamespace(text="instructions"),
        ],
        size=SimpleNamespace(height=8),
        scrollable_content_region=SimpleNamespace(height=8),
        scroll_to_region=lambda region, **kwargs: calls.append((region, kwargs)),
    )

    assert SuperQodeApp._scroll_to_rendered_selected_block(log) is True
    assert calls
    region, kwargs = calls[-1]
    assert region.y == 1
    assert region.height == 5
    assert kwargs["animate"] is False


def test_connect_selection_replaces_picker_before_rendering_result():
    from superqode.providers.connection_profiles import list_connection_profiles

    app = make_app()
    log = FakeLog()
    log.write("long picker content")
    profiles = list_connection_profiles()
    app._awaiting_connect_type = True
    app._byok_highlighted_connect_type_index = len(profiles) - 1
    app.query_one = lambda *args, **kwargs: log
    observed = []

    def dispatch(profile, target_log):
        observed.append((profile.id, list(target_log.items)))
        target_log.write("selected result")

    app._dispatch_connection_profile = dispatch
    app.action_select_highlighted_connect_type()

    assert observed == [(profiles[-1].id, [])]
    assert log.items == ["selected result"]
    assert log.scrolled_home is True


def test_tui_local_smoke_command_renders_mvp_readiness(monkeypatch):
    from superqode.local.smoke import SmokeCheck, SmokeReport

    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app.run_worker = lambda coro: asyncio.run(coro)

    def fake_run_smoke(**kwargs):
        assert kwargs["repo_path"] == "."
        return SmokeReport(
            status="ready",
            engine="ollama",
            endpoint="http://localhost:11434/v1",
            model="qwen3-coder",
            ttft_s=0.4,
            decode_tps=50.0,
            checks=[SmokeCheck("server", True, "reachable")],
        )

    monkeypatch.setattr("superqode.local.smoke.run_smoke", fake_run_smoke)

    app._local_cmd("smoke", log)

    text = render_plain(log.items[-1])
    assert "SuperQode local smoke" in text
    assert "qwen3-coder" in text
    assert "Local coding harness ready" in text


def test_tui_local_init_writes_harness(monkeypatch, tmp_path):
    from superqode.local.doctor import DoctorReport
    from superqode.local.engines import EngineStatus
    from superqode.local.hardware import HardwareProfile
    from superqode.local.matrix import ModelCandidate, StackRecommendation
    from superqode.local.smoke import SmokeCheck, SmokeReport

    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)
    app.run_worker = lambda coro: asyncio.run(coro)

    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="huggingface-cli download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=True)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
    )
    smoke = SmokeReport(
        status="ready",
        engine="mlx-lm",
        endpoint="http://localhost:8080/v1",
        model="THUDM/GLM-4.5-Air",
        checks=[SmokeCheck("server", True, "reachable")],
    )
    monkeypatch.setattr("superqode.local.doctor.run_doctor", lambda *a, **k: report)
    monkeypatch.setattr("superqode.local.smoke.run_smoke", lambda **kwargs: smoke)
    target = tmp_path / "superqode.local.yaml"

    app._local_cmd(f"init --repo {tmp_path} --output {target}", log)

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "primary: mlx/THUDM/GLM-4.5-Air" in text
    rendered = render_plain(log.items[-1])
    assert "Local Coding Init" in rendered
    assert "Wrote local harness" in rendered


def test_tui_local_init_pack_override(monkeypatch, tmp_path):
    from superqode.local.doctor import DoctorReport
    from superqode.local.engines import EngineStatus
    from superqode.local.hardware import HardwareProfile
    from superqode.local.matrix import ModelCandidate, StackRecommendation

    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)

    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=True)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
    )
    monkeypatch.setattr("superqode.local.doctor.run_doctor", lambda *a, **k: report)
    target = tmp_path / "superqode.local.yaml"

    app._local_cmd(
        f"init --repo {tmp_path} --output {target} --pack minimax-m1 --skip-smoke",
        log,
    )

    text = target.read_text(encoding="utf-8")
    assert "pack: minimax-m1" in text
    assert "model_pack_source: user" in text
    assert "Model pack" in render_plain(log.items[-1])


def test_tui_local_migrate_renders_plan(tmp_path):
    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)
    (tmp_path / "AGENTS.md").write_text("Use local tools.\n", encoding="utf-8")

    app._local_cmd(f"migrate --repo {tmp_path} --model MiniMaxAI/MiniMax-M1", log)

    rendered = render_plain(log.items[-1])
    assert "SuperQode local migration plan" in rendered
    assert "pack: minimax" in rendered
    assert "local init --repo" in rendered


def test_tui_local_pack_init_dry_run(monkeypatch, tmp_path):
    from superqode.local import packs

    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)
    monkeypatch.setattr(packs, "USER_PACKS_DIR", tmp_path)

    app._local_cmd("pack init --model MiniMaxAI/MiniMax-M1 --dry-run", log)

    rendered = render_plain(log.items[-1])
    assert "SuperQode model pack draft" in rendered
    assert "minimax-m1" in rendered
    assert "Dry run only" in rendered
    assert not (tmp_path / "minimax-m1.yaml").exists()


def test_tui_local_airplane_dispatches_cli():
    app = make_app()
    log = FakeLog()
    calls = []

    async def fake_cli(command_parts, target_log, label):
        calls.append((command_parts, target_log, label))

    app._superqode_cli_cmd = fake_cli
    app.run_worker = lambda coro: asyncio.run(coro)

    app._local_cmd("airplane prepare --repo . --model ollama/qwen3:8b --force", log)

    assert calls == [
        (
            [
                "local",
                "airplane",
                "prepare",
                "--repo",
                ".",
                "--model",
                "ollama/qwen3:8b",
                "--force",
            ],
            log,
            "Airplane Mode",
        )
    ]


def test_tui_local_airplane_requires_subcommand():
    app = make_app()
    log = FakeLog()

    app._local_cmd("airplane", log)

    rendered = "\n".join(str(item) for item in log.items)
    assert ":local airplane <doctor|prepare|index|smoke|models|health>" in rendered


def test_tui_local_warmup_sends_tiny_generation(monkeypatch):
    from superqode.providers.gateway.base import GatewayResponse
    import superqode.providers.gateway.litellm_gateway as gateway_mod

    app = make_app()
    log = FakeLog()
    calls = []

    class FakeGateway:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return GatewayResponse(content="ok")

    monkeypatch.setattr(gateway_mod, "LiteLLMGateway", FakeGateway)

    asyncio.run(app._warmup_local_generation("ollama", "qwen3:8b", log))

    assert calls
    assert calls[0]["provider"] == "ollama"
    assert calls[0]["model"] == "qwen3:8b"
    assert calls[0]["max_tokens"] == 4
    rendered = "\n".join(str(item) for item in log.items)
    assert "Local model warm" in rendered


def test_tui_local_build(monkeypatch, tmp_path):
    from superqode.local import build as build_mod
    from superqode.local.doctor import DoctorReport
    from superqode.local.engines import EngineStatus
    from superqode.local.hardware import HardwareProfile
    from superqode.local.matrix import ModelCandidate, StackRecommendation

    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)
    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=True)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
    )
    monkeypatch.setattr(build_mod, "run_doctor", lambda *a, **k: report)

    app._local_cmd(
        f"build --repo {tmp_path} --model MiniMaxAI/MiniMax-M1 --pack minimax-m1 --force",
        log,
    )

    rendered = render_plain(log.items[-1])
    assert "SuperQode local harness builder" in rendered
    assert "Final live checks" in rendered
    assert (tmp_path / "superqode.local.yaml").exists()


def test_tui_local_setup_renders_tui_first_guide(monkeypatch, tmp_path):
    from superqode.local import setup as setup_mod
    from superqode.local.doctor import DoctorReport
    from superqode.local.engines import EngineStatus
    from superqode.local.guardrails import LocalGuardrails
    from superqode.local.hardware import HardwareProfile
    from superqode.local.matrix import ModelCandidate, StackRecommendation
    from superqode.local.repo import RepoProfile
    from superqode.local.setup import LocalSetupGuide

    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)
    candidate = ModelCandidate(
        name="GLM-4.5-Air",
        match=["glm-4.5-air"],
        pull="hf download THUDM/GLM-4.5-Air",
        pack="glm",
        source="models.dev/labs/zhipuai",
    )
    report = DoctorReport(
        hardware=HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=64),
        engines={"mlx-lm": EngineStatus(engine="mlx-lm", installed=True, running=False)},
        inventory=[],
        recommendation=StackRecommendation(
            tier_id="apple_64",
            description="test",
            engine="mlx-lm",
            engine_ranked=["mlx-lm"],
            models=[candidate],
        ),
        repo=RepoProfile(
            root=str(tmp_path),
            estimated_tokens=42000,
            recommended_context_tokens=65536,
            recommended_model_size="medium",
        ),
        guardrails=LocalGuardrails(
            hardware_tier="apple_64",
            max_worker_concurrency=2,
            recommended_context_cap=65536,
            memory_headroom_gb=12,
            battery_mode="normal",
        ),
    )
    guide = LocalSetupGuide(query="glm", repo=str(tmp_path), report=report, hits=[])
    monkeypatch.setattr(setup_mod, "build_local_setup_guide", lambda *a, **k: guide)

    app._local_cmd(f"setup glm --repo {tmp_path}", log)

    rendered = render_plain(log.items[-1])
    assert "SuperQode Local Model Setup" in rendered
    assert "TUI  : :local serve mlx" in rendered
    assert "TUI  : :local build" in rendered
    assert "Do not rely on anyone else's harness as-is" in rendered


def test_tui_local_no_model_hints_avoid_llama(monkeypatch):
    app = make_app()
    log = FakeLog()
    app.run_worker = lambda coro: asyncio.run(coro)

    class Discovery:
        async def scan_all(self):
            return {}

    monkeypatch.setattr("superqode.providers.local.get_discovery_service", lambda: Discovery())

    app._local_cmd("models", log)

    text = render_plain(log.items[-1])
    assert "qwen3.6:35b-a3b" in text
    assert "llama3" not in text.lower()
    assert "codellama" not in text.lower()


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


def test_colorful_status_bar_shows_full_runtime_and_model():
    """Regression: the *mounted* status bar (ColorfulStatusBar) must render the
    active runtime + model in full — earlier code updated an unmounted widget and
    the byok_model path shortened 'gpt-5.5' to 'gpt'."""
    from superqode.app.widgets import ColorfulStatusBar

    bar = ColorfulStatusBar()
    bar.active_runtime = "codex-sdk"
    bar.active_model = "gpt-5.5"
    bar.interaction_mode = "plan"
    plain = bar.render().plain
    assert "codex-sdk" in plain
    assert "gpt-5.5" in plain  # full, not shortened to "gpt"
    assert "PLAN" in plain


def test_colorful_status_bar_no_badge_when_unset():
    from superqode.app.widgets import ColorfulStatusBar

    bar = ColorfulStatusBar()
    assert "🔧" not in bar.render().plain


def test_wizard_lets_typed_commands_through_to_dispatcher(tmp_path, monkeypatch):
    """:quit (and any typed command) must never be swallowed by the wizard."""
    monkeypatch.chdir(tmp_path)
    app = make_app()
    log = FakeLog()
    app._show_command_output = lambda target_log, content, clear_log=True: target_log.write(content)

    app._harness_cmd("wizard", log)
    assert app._awaiting_harness_wizard is True

    # Typed commands fall through (False = dispatcher handles them, so
    # ":quit" quits the app from any wizard step).
    assert app._handle_harness_wizard_input(":quit", log) is False
    assert app._handle_harness_wizard_input("/exit", log) is False
    assert app._handle_harness_wizard_input(":connect byok", log) is False
    assert app._awaiting_harness_wizard is True  # wizard still pending

    # The wizard's own control words keep working.
    assert app._handle_harness_wizard_input(":cancel", log) is True
    assert app._awaiting_harness_wizard is False


def test_agent_question_lets_quit_through_to_dispatcher():
    """:quit must quit even while an agent question is pending."""

    class _PendingFuture:
        def done(self):
            return False

    app = make_app()
    log = FakeLog()
    app._awaiting_agent_question = True
    app._pending_agent_question = object()
    app._pending_agent_question_future = _PendingFuture()

    for quit_cmd in (":quit", "/quit", ":exit", "/exit", ":q"):
        assert app._handle_agent_question_input(quit_cmd, log) is False
    # The pending question is untouched — app teardown resolves it.
    assert app._awaiting_agent_question is True


def test_codex_config_error_hint_explains_unknown_variant():
    """The user's exact failure: a config value the app-server doesn't know."""

    class _Recorder:
        def __init__(self):
            self.infos = []

        def add_info(self, msg):
            self.infos.append(msg)

    log = _Recorder()
    exc = Exception(
        "JSON-RPC error -32600: failed to load configuration: "
        "/Users/shashi/.codex/config.toml:2:26: unknown variant `ultra`, "
        "expected one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`"
    )
    SuperQodeApp._codex_config_error_hint(log, exc)

    joined = " ".join(log.infos)
    assert "config.toml:2:26" in joined
    assert "`ultra` is newer than it supports" in joined
    assert "xhigh" in joined  # accepted values are listed for the user
    assert "per-process effort override" in joined
    assert SuperQodeApp._codex_error_hint(str(exc)) == joined

    # Unrelated errors add no noise.
    quiet = _Recorder()
    SuperQodeApp._codex_config_error_hint(quiet, Exception("connection refused"))
    assert quiet.infos == []


def test_codex_active_model_comes_from_the_live_thread_not_catalog_default():
    app = make_app()
    app._pure_mode = SimpleNamespace(
        _runtime=SimpleNamespace(active_model="gpt-5.6-terra"),
    )
    log = FakeLog()

    asyncio.run(app._resolve_codex_active_model(log))

    assert any("Active Codex model: gpt-5.6-terra" in str(item) for item in log.items)


def test_codex_subcommands_autocomplete_on_both_surfaces():
    """All Codex controls are reachable in the live prompt and legacy overlay."""
    from superqode.app.constants import COMMANDS
    from superqode.widgets.slash_complete import DEFAULT_COMMANDS

    app = make_app()
    app._codex_models = [
        {
            "id": "gpt-5.6-terra",
            "name": "GPT-5.6 Terra",
            "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        },
        {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "efforts": ["xhigh"]},
    ]

    codex_cmds = [c for c in COMMANDS if c.startswith(":codex")]
    assert ":codex effort" in codex_cmds
    assert ":codex model" in codex_cmds

    slash_values = {c.command for c in DEFAULT_COMMANDS}
    missing = [c for c in codex_cmds if c not in slash_values]
    assert missing == []

    # The live TUI uses _prompt_completion_candidates_for(), not DEFAULT_COMMANDS.
    subcommands = [
        candidate.value for candidate in app._prompt_completion_candidates_for(":codex ")
    ]
    assert set(codex_cmds) - {":codex"} <= set(subcommands)

    efforts = [
        candidate.value for candidate in app._prompt_completion_candidates_for(":codex effort ")
    ]
    assert efforts == [
        ":codex effort default",
        ":codex effort none",
        ":codex effort minimal",
        ":codex effort low",
        ":codex effort medium",
        ":codex effort high",
        ":codex effort xhigh",
        ":codex effort max",
        ":codex effort ultra",
    ]
    assert app._suggest_prompt_completion(":codex effort h") == ":codex effort high"

    models = [
        candidate.value for candidate in app._prompt_completion_candidates_for(":codex model gpt")
    ]
    assert models == [":codex model gpt-5.6-terra", ":codex model gpt-5.6-sol"]

    # The panel displays a compact page, but keeps every Codex subcommand
    # keyboard-reachable through up/down navigation.
    candidates = app._prompt_completion_candidates_for(":codex ")
    app._show_prompt_completion_panel(candidates)
    assert len(app._prompt_completion_candidates) == len(candidates) > 8


def test_connect_bare_model_resolves_provider(monkeypatch):
    """':connect gpt-5.6-sol' style input resolves the hosting provider."""
    from superqode.providers import models as model_db
    from superqode.providers.models import ModelInfo

    monkeypatch.setattr(model_db, "_use_live_data", True)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)
    monkeypatch.setattr(
        model_db,
        "_live_models",
        {
            "acme": {"gpt-9-flash": ModelInfo("gpt-9-flash", "GPT 9 Flash", "acme")},
            "beta": {"dual-model": ModelInfo("dual-model", "Dual", "beta")},
            "gamma": {"dual-model": ModelInfo("dual-model", "Dual", "gamma")},
        },
    )

    class _Log:
        def __init__(self):
            self.infos = []

        def add_info(self, msg):
            self.infos.append(msg)

    class _Stub:
        def __init__(self):
            self.connected = []
            self.shown = []

        def _connect_byok_mode(self, provider, model, log):
            self.connected.append((provider, model))

        def _show_provider_models(self, provider, log, use_picker=False):
            self.shown.append(provider)

    # Unique model id → auto-resolve and connect.
    stub, log = _Stub(), _Log()
    SuperQodeApp._connect_byok_cmd(stub, "gpt-9-flash", log)
    assert stub.connected == [("acme", "gpt-9-flash")]

    # Ambiguous id → list the candidates, never guess.
    stub, log = _Stub(), _Log()
    SuperQodeApp._connect_byok_cmd(stub, "dual-model", log)
    assert stub.connected == []
    joined = " ".join(log.infos)
    assert ":connect beta/dual-model" in joined
    assert ":connect gamma/dual-model" in joined

    # Unknown token → existing provider-models fallback.
    stub, log = _Stub(), _Log()
    SuperQodeApp._connect_byok_cmd(stub, "no-such-thing", log)
    assert stub.connected == []
    assert stub.shown == ["no-such-thing"]


def test_connect_bare_model_prefers_curated_provider_over_gateways(monkeypatch):
    """Gateways mirror popular models; first-party curated providers win."""
    from superqode.providers import models as model_db
    from superqode.providers.models import ModelInfo

    monkeypatch.setattr(model_db, "_use_live_data", True)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)
    monkeypatch.setattr(
        model_db,
        "_live_models",
        {
            # meta is a curated registry provider; fauxgateway is models.dev-only.
            "meta": {"solo-x": ModelInfo("solo-x", "Solo X", "meta")},
            "fauxgateway": {"solo-x": ModelInfo("solo-x", "Solo X", "fauxgateway")},
        },
    )

    class _Log:
        def add_info(self, msg):
            pass

    class _Stub:
        def __init__(self):
            self.connected = []

        def _connect_byok_mode(self, provider, model, log):
            self.connected.append((provider, model))

        def _show_provider_models(self, provider, log, use_picker=False):
            raise AssertionError("should resolve, not fall back")

    stub = _Stub()
    SuperQodeApp._connect_byok_cmd(stub, "solo-x", _Log())
    assert stub.connected == [("meta", "solo-x")]


def test_calm_tool_done_shows_bash_command():
    """A finished bash tool must show what ran, not a bare 'run' line.

    Regression: the calm-mode result line rebuilt args from result metadata
    but forwarded only "path", so read results showed their file while bash
    results showed nothing (observed on the Grok subscription harness, but
    provider-independent).
    """
    from types import SimpleNamespace

    class _Stub:
        def __init__(self):
            self.done = []

        def _is_calm_output(self):
            return True

        def _calm_tool_done(self, name, args, log, ok=True):
            self.done.append((name, args, ok))

    stub = _Stub()
    result = SimpleNamespace(
        success=True,
        output="3 passed",
        metadata={"command": "pytest -q", "exit_code": 0, "cwd": "/repo"},
    )
    SuperQodeApp._show_pure_tool_result(stub, "bash", result, log=None)
    assert stub.done == [("bash", {"command": "pytest -q"}, True)]

    # Read results keep their path target.
    stub = _Stub()
    result = SimpleNamespace(success=True, output="...", metadata={"path": "src/app.py"})
    SuperQodeApp._show_pure_tool_result(stub, "read", result, log=None)
    assert stub.done == [("read", {"path": "src/app.py"}, True)]


def test_calm_verb_target_renders_command_for_bash():
    """End-to-end mapping: bash + command metadata renders as 'run <command>'."""

    class _Stub:
        def query_one(self, *_a, **_k):
            raise RuntimeError("no widget in unit test")

    verb, target = SuperQodeApp._calm_verb_target(_Stub(), "bash", {"command": "pytest -q"})
    assert verb == "bash" or verb == "run"  # widget formatter unavailable → fallback verb
    assert target == "pytest -q"


def test_harness_display_name_capitalizes_for_labels():
    from superqode.app_main import _harness_display_name

    assert _harness_display_name("core") == "Core"
    assert _harness_display_name("workbench") == "Workbench"
    assert _harness_display_name("no-tool") == "No-tool"
    assert _harness_display_name("") == "-"
    assert _harness_display_name(None) == "-"


def test_grok_connect_without_cli_shows_install_steps(monkeypatch):
    """Missing product must produce install guidance, not `grok login` advice."""
    import superqode.app_main as am

    monkeypatch.setattr(am.shutil, "which", lambda name: None)

    class _Log:
        def __init__(self):
            self.lines = []

        def add_error(self, msg):
            self.lines.append(msg)

        def add_info(self, msg):
            self.lines.append(msg)

    class _Stub:
        pass

    log = _Log()
    assert am.SuperQodeApp._import_grok_token(_Stub(), log) is False
    joined = " ".join(log.lines)
    assert "not installed" in joined
    assert "https://x.ai/cli/install.sh" in joined
    assert ":connect byok xai grok-4.5" in joined


def test_codex_connect_without_cli_shows_install_steps(tmp_path, monkeypatch):
    """:connect codex without the Codex CLI must explain how to install it."""
    import superqode.app_main as am
    import superqode.runtime as rt
    from superqode.runtime import RuntimeInfo

    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.codex/auth.json
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setattr(am.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        rt,
        "list_runtimes",
        lambda: [
            RuntimeInfo(
                name="codex-sdk",
                description="Codex SDK runtime",
                installed=True,
                install_hint=None,
                implemented=True,
            )
        ],
    )

    class _Log:
        def __init__(self):
            self.lines = []

        def add_error(self, msg):
            self.lines.append(msg)

        def add_info(self, msg):
            self.lines.append(msg)

    class _Stub:
        pass

    log = _Log()
    am.SuperQodeApp._runtime_cmd(_Stub(), "codex-sdk", log)
    joined = " ".join(log.lines)
    assert "npm i -g @openai/codex" in joined
    assert "codex login" in joined
    assert ":connect byok openai" in joined


def test_calm_mode_skips_partial_tool_output_chunks():
    """Streamed output chunks must not commit a finished-tool line each.

    Regression: the Codex runtime streams command output in flushes; each
    flush arrived as a success ToolResult with no metadata, printing a stack
    of bare "run" lines in calm mode.
    """
    from types import SimpleNamespace

    class _Stub:
        def __init__(self):
            self.done = []

        def _is_calm_output(self):
            return True

        def _calm_tool_done(self, name, args, log, ok=True):
            self.done.append((name, args, ok))

    stub = _Stub()
    for chunk in ("collecting tests\n", "3 passed\n"):
        partial = SimpleNamespace(success=True, output=chunk, metadata={"partial": True})
        SuperQodeApp._show_pure_tool_result(stub, "bash", partial, log=None)
    assert stub.done == []

    final = SimpleNamespace(
        success=True,
        output="3 passed",
        metadata={"command": "pytest -q", "exit_code": 0, "status": "completed"},
    )
    SuperQodeApp._show_pure_tool_result(stub, "bash", final, log=None)
    assert stub.done == [("bash", {"command": "pytest -q"}, True)]


def test_agent_session_label_names_what_actually_runs():
    """Codex sessions must not be labelled with SuperQode's native harness."""
    from types import SimpleNamespace

    app = SuperQodeApp.__new__(SuperQodeApp)

    # Self-contained runtime: the agent owns the loop, regardless of the
    # native harness setting.
    app._pure_mode = SimpleNamespace(
        runtime_name="codex-sdk",
        get_status=lambda: {"harness": {"name": "core"}},
    )
    assert app._agent_session_label("openai") == "Runtime: Codex (agent-owned harness)"

    # Native loop with a named harness.
    app._pure_mode = SimpleNamespace(
        runtime_name="builtin",
        get_status=lambda: {"harness": {"name": "core"}},
    )
    assert app._agent_session_label("xai") == "Harness: Core"

    # Native loop without a harness name falls back to the provider.
    app._pure_mode = SimpleNamespace(runtime_name="", get_status=lambda: {"harness": {}})
    assert app._agent_session_label("openai") == "BYOK openai"
