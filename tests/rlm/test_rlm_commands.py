"""TUI commands for the native RLM harness."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from superqode.app.constants import COMMANDS
from superqode.app.mixins.rlm_commands import RLMCommandMixin
from superqode.pipy.ai import FakeStream, text_response
from superqode.pipy.stream import Model
from superqode.rlm.coding_session import RLMCodingSession, RLMCodingSessionOptions

MODEL = Model(id="fake-rlm", provider="fake", api="fake-api")


class RecordingLog:
    def __init__(self) -> None:
        self.errors = []
        self.infos = []
        self.successes = []
        self.rendered = []

    def add_error(self, message):
        self.errors.append(str(message))

    def add_info(self, message):
        self.infos.append(str(message))

    def add_success(self, message):
        self.successes.append(str(message))

    def write(self, renderable):
        self.rendered.append(renderable)


class App(RLMCommandMixin):
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.workers = []

    def _rlm_is_active(self) -> bool:
        return self.active

    def run_worker(self, coroutine, **_kwargs):
        self.workers.append(coroutine)
        coroutine.close()


async def _session(tmp_path: Path) -> RLMCodingSession:
    return await RLMCodingSession.create(
        RLMCodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=FakeStream([text_response("ok")]),
            session_root=tmp_path / "sessions",
        )
    )


def test_rlm_commands_are_offered_for_completion():
    expected = {
        ":rlm",
        ":rlm help",
        ":rlm session",
        ":rlm policy",
        ":rlm goal",
        ":rlm autonomous",
        ":rlm sandbox",
        ":rlm usage",
        ":rlm agents",
        ":rlm send",
        ":rlm steer",
        ":rlm cancel",
    }

    assert expected <= set(COMMANDS)


def test_bare_rlm_renders_help():
    app = App(active=True)
    log = RecordingLog()

    app._rlm_cmd("", log)

    console = Console(width=100, force_terminal=False)
    with console.capture() as capture:
        console.print(log.rendered[-1])
    rendered = capture.get()
    assert "one persistent Python tool" in rendered
    assert ":rlm agents" in rendered
    assert ":rlm steer" in rendered


def test_rlm_commands_require_the_rlm_harness():
    app = App(active=False)
    log = RecordingLog()

    app._rlm_cmd("agents", log)

    assert any("not the active harness" in message for message in log.errors)
    assert app.workers == []


async def test_session_and_empty_agent_list_are_visible(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "session", "", log)
    await app._rlm_dispatch(session, "agents", "", log)

    assert any(str(session.session_path) in message for message in log.infos)
    assert any("python (serializable state checkpointed)" in message for message in log.infos)
    assert any("detached Python processes" in message for message in log.infos)
    assert any("No recursive child agents" in message for message in log.infos)


async def test_sandbox_status_states_the_boundary_without_overclaiming(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "sandbox", "", log)

    assert any("backend     host" in message for message in log.infos)
    assert any("isolation   none" in message for message in log.infos)
    assert any("not an adversarial model" in message for message in log.infos)


async def test_sandbox_doctor_reports_implemented_profiles(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "sandbox", "doctor", log)

    reported = log.infos + log.successes
    assert any("active      host" in message for message in reported)
    assert any(message.startswith("docker") for message in reported)
    assert any("profiles    host, docker, monty" in message for message in reported)


async def test_sandbox_cannot_be_switched_from_the_command(tmp_path):
    """A setter would be a no-op or a promise this build cannot keep."""
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "sandbox", "docker", log)

    assert any("not set from :rlm sandbox" in message for message in log.errors)
    assert any("runtime.config.sandbox" in message for message in log.infos)


async def test_usage_reports_recursive_spend_and_says_what_it_omits(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "usage", "", log)

    # A fresh session has an executor with nothing spent, so the budget shows.
    assert any("subcalls   0 of 64 calls" in message for message in log.infos)
    assert any("children   none" in message for message in log.infos)
    assert any("context    " in message for message in log.infos)
    # Better to name the gap than to look complete.
    assert any("reported by the harness" in message for message in log.infos)


async def test_usage_applies_the_sessions_context_policy(tmp_path):
    from superqode.rlm.context import ContextPolicy

    (tmp_path / "visible.py").write_text("ok\n", encoding="utf-8")
    (tmp_path / "secret.env").write_text("hidden\n", encoding="utf-8")
    session = await _session(tmp_path)
    session.options.context_policy = ContextPolicy(include=("visible.py",), exclude=("*.env",))
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "usage", "", log)

    assert any("context    1 files" in message for message in log.infos)


async def test_usage_counts_subcalls_once_they_have_run(tmp_path):
    from superqode.pipy.messages import AssistantMessage, TextContent, Usage, UsageCost
    from superqode.pipy.provider_events import AssistantDoneEvent
    from superqode.rlm.coding_session import _EXECUTORS
    from superqode.rlm.subcalls import SubcallExecutor

    def stream_fn(model, context, options):
        async def events():
            yield AssistantDoneEvent(
                reason="stop",
                message=AssistantMessage(
                    content=[TextContent(text="answer")],
                    usage=Usage(input=6, output=4, cost=UsageCost(total=0.002)),
                ),
            )

        return events()

    session = await _session(tmp_path)
    executor = SubcallExecutor(model=MODEL, stream_fn=stream_fn)
    _EXECUTORS[str(session.session_path.resolve())] = executor
    await executor.query("what is this")

    app = App(active=True)
    log = RecordingLog()
    await app._rlm_dispatch(session, "usage", "", log)

    assert any("subcalls   1 of 64 calls" in message for message in log.infos)
    assert any("$0.0020" in message for message in log.infos)


async def test_goal_and_autonomous_commands_persist_policy(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()

    await app._rlm_dispatch(session, "goal", '"Ship the native harness"', log)
    await app._rlm_dispatch(session, "autonomous", '"pytest -q"', log)
    await app._rlm_dispatch(session, "policy", "", log)

    assert session.policy.goal == "Ship the native harness"
    assert session.policy.autonomous is True
    assert session.policy.gates == ("pytest -q",)
    assert any("Ship the native harness" in message for message in log.infos)
    assert any("pytest -q" in message for message in log.infos)


async def test_autonomous_off_clears_gates(tmp_path):
    session = await _session(tmp_path)
    app = App(active=True)
    log = RecordingLog()
    session.update_policy(autonomous=True, gates=("pytest -q",))

    await app._rlm_dispatch(session, "autonomous", "off", log)

    assert session.policy.autonomous is False
    assert session.policy.gates == ()
