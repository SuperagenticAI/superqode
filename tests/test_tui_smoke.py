from rich.console import Console
from types import SimpleNamespace
import asyncio
import concurrent.futures

from superqode.app_main import SuperQodeApp, render_welcome
from superqode.tools.question_tool import Question, QuestionType


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

    def add_error(self, text):
        self.items.append(text)

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


def test_busy_message_rejects_second_prompt():
    app = make_app()
    log = FakeLog()
    app.is_busy = True

    app._handle_message("second prompt", log)

    assert any("already running" in str(item) for item in log.items)


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
