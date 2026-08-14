"""DeepSeek Harness backend tests.

Two recorded streams drive these tests, so the translation is checked against
real runtime output without installing the SDK or its runtime wheel:

``fixtures/dsh_bash_tool_notifications.jsonl`` is a verbatim copy of the
success-path snapshot from deepseek-ai/deepseek-harness (MIT), at
``examples/jsonrpc-agent/tests/snapshots/bash-tool/notifications.expected.jsonl``.

``fixtures/dsh_missing_credential_notifications.jsonl`` was captured from a live
run of the bundled runtime with no ``DEEPSEEK_API_KEY`` set, with timestamps
normalized. The upstream snapshot has no failing turn, which is why the failure
path needed its own recording.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.harness import RuntimeSpec, get_harness_template
from superqode.harness.backends import (
    DSHHarnessBackend,
    DSHSettings,
    HarnessBackendRequest,
    create_harness_backend,
    known_harness_backend_names,
)
from superqode.harness.backends.dsh import from_dsh_notification

FIXTURE = Path(__file__).parent / "fixtures" / "dsh_bash_tool_notifications.jsonl"
SESSION_ID = "dsh-test-session"
MESSAGE_ID = "msg-1"


def wire_session_id() -> str:
    """The process-scoped id the runtime actually sees on the wire."""
    from superqode.harness.backends.dsh import _runtime_session_id

    return _runtime_session_id(SESSION_ID)


def _recorded_notifications(session_id: str | None = None) -> list[SimpleNamespace]:
    """Load the recorded stream with snapshot placeholders bound to one session."""
    session_id = session_id or wire_session_id()
    notifications: list[SimpleNamespace] = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line.replace("{{sessionId}}", session_id))
        notifications.append(SimpleNamespace(method=raw["method"], payload=raw.get("params") or {}))
    # The recorded receipt carries the session id; bind it to our prompt instead.
    for notification in notifications:
        event = notification.payload.get("event") or {}
        if event.get("type") != "agent/inbox/spliced":
            continue
        for message in (event.get("data") or {}).get("inserted") or []:
            message["id"] = MESSAGE_ID
    return notifications


class FakeSubscription:
    def __init__(self, notifications):
        self._queue: queue.Queue = queue.Queue()
        for notification in notifications:
            self._queue.put(notification)
        self.closed = False

    def next(self):
        return self._queue.get(timeout=5)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, notifications):
        self._notifications = notifications
        self.subscriptions: list[FakeSubscription] = []
        self.prompts: list[tuple[str, list]] = []

    def subscribe_session_notifications(self, session_id):
        subscription = FakeSubscription(self._notifications)
        self.subscriptions.append(subscription)
        return subscription

    def session_prompt(self, session_id, content_blocks, *, notification_subscription=None):
        self.prompts.append((session_id, content_blocks))
        return MESSAGE_ID


class FakeHarness:
    """Stands in for deepseek_harness.DeepSeekHarness."""

    def __init__(self, notifications=None, *, fail_on_start: str = ""):
        self.client = FakeClient(notifications if notifications is not None else [])
        self.started = False
        self.closed = False
        self.start_calls = 0
        self._fail_on_start = fail_on_start

    def start(self):
        self.start_calls += 1
        if self._fail_on_start:
            raise RuntimeError(self._fail_on_start)
        self.started = True

    def close(self):
        self.closed = True


def _request(tmp_path: Path, **runtime_config) -> HarnessBackendRequest:
    spec = replace(
        get_harness_template("coding"),
        runtime=RuntimeSpec(
            backend="deepseek-harness", config={"deepseek_harness": runtime_config}
        ),
    )
    return HarnessBackendRequest(
        spec=spec,
        prompt="Run this exact command with your bash tool",
        provider="deepseek-official",
        model="deepseek-v4-flash",
        working_directory=tmp_path,
        session_id=SESSION_ID,
    )


def _backend(harness: FakeHarness) -> DSHHarnessBackend:
    return DSHHarnessBackend(harness_factory=lambda _request, _settings: harness)


@pytest.fixture(autouse=True)
def _no_leaked_runtimes():
    """Runtimes are cached per session across runs, so isolate every test."""
    from superqode.harness.backends.dsh import close_dsh_runtimes

    close_dsh_runtimes()
    yield
    close_dsh_runtimes()


def test_dsh_backend_is_registered() -> None:
    assert "deepseek-harness" in known_harness_backend_names()
    assert isinstance(create_harness_backend("deepseek-harness"), DSHHarnessBackend)


def test_preset_is_resolvable_by_name_and_aliases() -> None:
    from superqode.harness.catalog import resolve_harness

    for reference in ("dsh", "deepseek", "deepseek-harness"):
        entry = resolve_harness(reference)
        assert entry.id == "deepseek-harness"
        assert entry.runtime == "deepseek-harness"
        assert entry.source == "optional:deepseek-harness"


def test_preset_needs_no_cordis_file() -> None:
    spec = get_harness_template("deepseek-harness")

    # The SDK injects DeepSeek's bundled composition when none is configured,
    # so shipping one of our own would fork upstream's plugin graph.
    assert "cordis" not in spec.runtime.config["deepseek_harness"]
    assert (
        spec.runtime.config["deepseek_harness"]["env"]["DSH_PERMISSION_MODE"] == "workspace-write"
    )


def test_preset_does_not_claim_a_superqode_model_route() -> None:
    spec = get_harness_template("deepseek-harness")

    assert spec.model_policy.primary is None
    assert spec.model_policy.config["dsh_uses_own_provider_catalog"] is True
    assert "approvals" in spec.metadata["selection_warning"].lower()


def test_preset_defaults_resolve_without_any_user_configuration(tmp_path: Path) -> None:
    request = replace(
        HarnessBackendRequest(
            spec=get_harness_template("deepseek-harness"),
            prompt="hello",
            provider="",
            model="",
            working_directory=tmp_path,
        ),
    )

    settings = DSHSettings.from_request(request)

    assert settings.provider == "deepseek-official"
    assert settings.cordis is None
    assert settings.env == {"DSH_PERMISSION_MODE": "workspace-write"}


def test_capabilities_report_the_permission_boundary() -> None:
    capabilities = DSHHarnessBackend.capabilities

    assert capabilities.supports_shell is True
    # DeepSeek executes tools itself, so SuperQode cannot gate a call first.
    assert capabilities.supports_approvals is False
    assert capabilities.supports_no_tool is False
    assert capabilities.event_detail == "rich"


def test_settings_resolve_paths_against_the_working_directory(tmp_path: Path) -> None:
    settings = DSHSettings.from_request(
        _request(tmp_path, cordis="cordis.yml", session_root="sessions")
    )

    assert settings.cordis == str((tmp_path / "cordis.yml").resolve())
    assert settings.session_root == str((tmp_path / "sessions").resolve())


def test_settings_default_session_root_stays_inside_superqode(tmp_path: Path) -> None:
    settings = DSHSettings.from_request(_request(tmp_path))

    assert settings.session_root == str(
        (tmp_path / ".superqode" / "deepseek-harness" / "sessions").resolve()
    )
    assert settings.cordis is None


def test_connected_superqode_route_is_not_forwarded_as_a_provider_name(
    tmp_path: Path,
) -> None:
    # A runtime whose composition only registers deepseek-official rejects
    # 'ollama' as a route name, so the name must not be forwarded.
    request = replace(
        _request(tmp_path, provider="deepseek-official", model="deepseek-v4-flash"),
        provider="ollama",
        model="qwen3-coder",
    )

    settings = DSHSettings.from_request(request)

    assert settings.provider == "deepseek-official"


def test_a_connected_local_route_is_bridged_onto_the_deepseek_endpoint(
    tmp_path: Path,
) -> None:
    # Connecting to Ollama and switching to this harness must use Ollama, not
    # fail asking for a DeepSeek key.
    request = replace(_request(tmp_path), provider="ollama", model="qwen3.5:9b")

    settings = DSHSettings.from_request(request)

    assert settings.provider == "deepseek-official"
    assert settings.model == "qwen3.5:9b"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.api_key
    assert settings.bridged_from == "ollama/qwen3.5:9b"


def test_an_explicit_endpoint_is_never_overridden_by_bridging(tmp_path: Path) -> None:
    request = replace(
        _request(tmp_path, base_url="https://api.deepseek.com", model="deepseek-v4-flash"),
        provider="ollama",
        model="qwen3.5:9b",
    )

    settings = DSHSettings.from_request(request)

    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-flash"
    assert settings.bridged_from is None


def test_a_provider_with_its_own_wire_format_is_not_bridged(tmp_path: Path) -> None:
    # Anthropic does not speak the OpenAI wire format, so pointing DeepSeek's
    # adapter at it would swap one confusing failure for another.
    request = replace(_request(tmp_path), provider="anthropic", model="claude-sonnet-4")

    settings = DSHSettings.from_request(request)

    assert settings.bridged_from is None
    assert settings.base_url is None


def test_route_forwarding_is_opt_in(tmp_path: Path) -> None:
    request = replace(
        _request(tmp_path, use_superqode_route=True),
        provider="pi-ai",
        model="some-model",
    )

    settings = DSHSettings.from_request(request)

    assert settings.provider == "pi-ai"
    assert settings.model == "some-model"


def test_provider_defaults_when_nothing_is_configured(tmp_path: Path) -> None:
    request = replace(_request(tmp_path), provider="", model="")

    settings = DSHSettings.from_request(request)

    assert settings.provider == "deepseek-official"
    assert settings.model == "deepseek-v4-flash"


def test_rejects_non_positive_timeouts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        DSHSettings.from_request(_request(tmp_path, prompt_timeout=0))


@pytest.mark.asyncio
async def test_run_translates_the_recorded_deepseek_stream(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_notifications())

    result = await _backend(harness).run(_request(tmp_path))

    assert result.backend == "deepseek-harness"
    assert result.runtime == "dsh_jsonrpc"
    assert result.response.error is None
    assert result.response.stopped_reason == "complete"
    assert result.response.content == "dsh-sdk-proof-7391"
    assert result.response.tool_calls_made == 1
    assert result.response.iterations == 1
    assert harness.started is True
    # The runtime stays alive so the next turn can reuse the session.
    assert harness.closed is False


@pytest.mark.asyncio
async def test_run_sums_committed_usage_without_double_counting(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_notifications())

    result = await _backend(harness).run(_request(tmp_path))

    # The recording commits two steps: 123+233 in, 89+24 out. The streamed usage
    # chunks repeat those totals and must not be added again.
    assert result.response.input_tokens == 356
    assert result.response.output_tokens == 113
    assert result.response.total_tokens == 469
    assert result.metadata["dsh_usage"]["reasoning_tokens"] == 32


@pytest.mark.asyncio
async def test_stream_emits_tool_call_and_result_in_order(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_notifications())

    events = [event async for event in _backend(harness).stream(_request(tmp_path))]

    types = [event.type for event in events]
    assert types.index("tool_call") < types.index("tool_result")

    call = next(event for event in events if event.type == "tool_call")
    assert call.data["name"] == "bash"
    assert json.loads(call.data["arguments"])["command"] == "echo dsh-sdk-proof-7391"

    tool_result = next(event for event in events if event.type == "tool_result")
    assert tool_result.data["result"] == "dsh-sdk-proof-7391\n"
    assert tool_result.data["is_error"] is False
    assert tool_result.data["tool_call_id"] == call.data["tool_call_id"]


@pytest.mark.asyncio
async def test_stream_separates_reasoning_from_answer_text(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_notifications())

    events = [event async for event in _backend(harness).stream(_request(tmp_path))]

    thinking = "".join(event.data["text"] for event in events if event.type == "thinking_delta")
    answer = "".join(event.data["text"] for event in events if event.type == "model_delta")
    assert "run a specific bash command" in thinking
    assert answer == "dsh-sdk-proof-7391"
    assert "dsh-sdk-proof" not in thinking


@pytest.mark.asyncio
async def test_stream_stops_at_idle_and_closes_the_subscription(tmp_path: Path) -> None:
    notifications = _recorded_notifications()
    trailing = SimpleNamespace(
        method="session.event",
        payload={
            "sessionId": wire_session_id(),
            "event": {"type": "turn/start", "data": {"turn": 9}},
        },
    )
    harness = FakeHarness([*notifications, trailing])

    events = [event async for event in _backend(harness).stream(_request(tmp_path))]

    assert events[-1].type == "end"
    assert all(event.data.get("turn") != 9 for event in events)
    assert harness.client.subscriptions[0].closed is True


@pytest.mark.asyncio
async def test_traffic_before_the_inbox_receipt_is_not_attributed_to_the_run(
    tmp_path: Path,
) -> None:
    earlier = SimpleNamespace(
        method="session.event",
        payload={
            "sessionId": wire_session_id(),
            "event": {
                "type": "assistant/chunk",
                "data": {"chunk": {"type": "text-delta", "text": "stale"}},
            },
        },
    )
    harness = FakeHarness([earlier, *_recorded_notifications()])

    result = await _backend(harness).run(_request(tmp_path))

    assert "stale" not in result.response.content


@pytest.mark.asyncio
async def test_startup_failure_is_reported_and_the_process_is_not_leaked(
    tmp_path: Path,
) -> None:
    # start() spawns before it handshakes, so a failure can otherwise strand a
    # live subprocess that never entered the reuse cache.
    harness = FakeHarness(fail_on_start="runtime binary missing")

    result = await _backend(harness).run(_request(tmp_path))

    assert result.response.stopped_reason == "error"
    assert "runtime binary missing" in str(result.response.error)
    assert harness.closed is True


@pytest.mark.asyncio
async def test_prompt_timeout_reports_an_error_instead_of_hanging(tmp_path: Path) -> None:
    class Hung(FakeSubscription):
        """A runtime that accepted the prompt but never reaches idle."""

        def next(self):
            # The real subscription blocks on queue.get(); bound the wait so a
            # stray worker thread cannot outlive the test session.
            threading.Event().wait(1.5)
            raise queue.Empty

    harness = FakeHarness(_recorded_notifications())
    harness.client.subscribe_session_notifications = lambda _session: Hung([])

    result = await _backend(harness).run(_request(tmp_path, prompt_timeout=0.25))

    assert result.response.stopped_reason == "error"
    assert "without reaching idle" in str(result.response.error)


@pytest.mark.asyncio
async def test_transport_failure_without_a_message_still_names_the_cause(
    tmp_path: Path,
) -> None:
    class Broken(FakeSubscription):
        def next(self):
            raise queue.Empty  # stringifies to ""

    harness = FakeHarness(_recorded_notifications())
    harness.client.subscribe_session_notifications = lambda _session: Broken([])

    result = await _backend(harness).run(_request(tmp_path))

    assert result.response.stopped_reason == "error"
    assert result.response.error == "Empty"


CREDENTIAL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "dsh_missing_credential_notifications.jsonl"
)


def _recorded_failure(session_id: str | None = None) -> list[SimpleNamespace]:
    """Load the real missing-credential stream captured from the DeepSeek runtime."""
    session_id = session_id or wire_session_id()
    notifications = []
    for line in CREDENTIAL_FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line.replace("{{sessionId}}", session_id))
        notifications.append(SimpleNamespace(method=raw["method"], payload=raw["params"]))
    for notification in notifications:
        event = notification.payload.get("event") or {}
        if event.get("type") != "agent/inbox/spliced":
            continue
        for message in (event.get("data") or {}).get("inserted") or []:
            message["id"] = MESSAGE_ID
    return notifications


@pytest.mark.asyncio
async def test_failed_turn_reports_the_reason_the_runtime_gave(tmp_path: Path) -> None:
    # Recorded from a live run with no DEEPSEEK_API_KEY. The runtime reports the
    # cause on turn/end rather than as an error notification, so dropping it
    # left the user with a failed run and no explanation.
    harness = FakeHarness(_recorded_failure())

    result = await _backend(harness).run(_request(tmp_path))

    assert result.response.stopped_reason == "error"
    assert "no API key for provider route" in str(result.response.error)


@pytest.mark.asyncio
async def test_a_failure_is_reported_once_not_twice(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_failure())

    events = [event async for event in _backend(harness).stream(_request(tmp_path))]

    # The runtime states the failure twice (streamed finish chunk, then
    # turn/end). Only one of them may reach the UI as an error.
    assert [event.type for event in events].count("error") == 0
    detail = next(event for event in events if event.type == "model_failure")
    assert detail.data["error_code"] == "MISSING_CREDENTIAL"
    closing = next(event for event in events if event.type == "turn_complete")
    assert "no API key" in closing.data["error"]


@pytest.mark.asyncio
async def test_a_failed_turn_never_reports_an_empty_reason(tmp_path: Path) -> None:
    silent = SimpleNamespace(
        method="session.event",
        payload={
            "sessionId": wire_session_id(),
            "event": {"type": "turn/end", "data": {"turn": 1, "reason": {"kind": "error"}}},
        },
    )
    idle = SimpleNamespace(
        method="session.status", payload={"sessionId": wire_session_id(), "status": "idle"}
    )
    receipt = _recorded_failure()[0]
    harness = FakeHarness([receipt, silent, idle])

    result = await _backend(harness).run(_request(tmp_path))

    assert result.response.stopped_reason == "error"
    assert result.response.error


@pytest.mark.asyncio
async def test_a_second_turn_reuses_the_runtime_for_the_same_session(tmp_path: Path) -> None:
    # DeepSeek rejects a second prompt sent from a fresh process under an
    # existing session id, so every conversation past its first message failed.
    harness = FakeHarness(_recorded_notifications())
    backend = _backend(harness)

    await backend.run(_request(tmp_path))
    harness.client._notifications = _recorded_notifications()
    await backend.run(_request(tmp_path))

    assert harness.start_calls == 1
    assert harness.closed is False
    assert len(harness.client.prompts) == 2


def test_the_wire_session_id_is_scoped_to_this_process() -> None:
    # SuperQode session ids are durable across restarts, but DeepSeek rejects an
    # id whose persisted log predates the live session, so a resumed session
    # must not reuse the previous run's wire id.
    from superqode.harness.backends.dsh import _runtime_session_id

    wire = _runtime_session_id(SESSION_ID)

    assert wire != SESSION_ID
    assert wire.startswith(f"{SESSION_ID}-")


@pytest.mark.asyncio
async def test_emitted_events_carry_the_superqode_session_id(tmp_path: Path) -> None:
    harness = FakeHarness(_recorded_notifications())

    events = [event async for event in _backend(harness).stream(_request(tmp_path))]

    # The wire id is an implementation detail; the UI correlates on ours.
    assert {event.session_id for event in events} == {SESSION_ID}
    assert harness.client.prompts[0][0] == wire_session_id()


def test_unknown_notifications_are_preserved_for_forward_compatibility() -> None:
    event = from_dsh_notification("session.future", {"sessionId": "s1", "shape": {"a": 1}})

    assert event.type == "dsh_event"
    assert event.session_id == "s1"
    assert event.data["dsh_notification"]["params"]["shape"] == {"a": 1}


def test_turn_end_reason_maps_onto_the_superqode_vocabulary() -> None:
    def reason(kind: str) -> str:
        event = from_dsh_notification(
            "session.event",
            {
                "sessionId": "s1",
                "event": {"type": "turn/end", "data": {"turn": 1, "reason": {"kind": kind}}},
            },
        )
        return event.data["reason"]

    assert reason("completed") == "completed"
    assert reason("max-tokens") == "max-tokens"


def test_subagent_notifications_carry_their_ancestry() -> None:
    event = from_dsh_notification(
        "subagent.started",
        {"parentSessionId": "root", "childSessionId": "child"},
    )

    assert event.type == "subagent"
    assert event.data["phase"] == "started"
    assert event.data["parent_session_id"] == "root"
    assert event.data["child_session_id"] == "child"
