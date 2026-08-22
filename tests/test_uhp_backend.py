"""UHP HarnessSpec backend: TUI/kernel wrapper around the protocol adapter."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.registry import create_harness_backend
from superqode.harness.backends.uhp import UHPHarnessBackend
from superqode.harness.catalog import resolve_harness
from superqode.harness.templates import uhp_template
from superqode.harness.uhp_adapter import UHPHarnessProtocolAdapter
from superqode.harness.uhp_client import UHPClient

BASE_URL = "https://uhp.test"


def _sse(events):
    chunks = []
    for index, event in enumerate(events):
        payload = {"sequence_number": index, **event}
        chunks.append(f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n")
    return "".join(chunks)


def _response_payload(**overrides):
    payload = {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "model": "gpt-5",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        "metadata": {"session_id": "sess_1"},
    }
    payload.update(overrides)
    return payload


def _client(handler):
    return UHPClient(
        BASE_URL,
        api_key="key-123",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _backend(
    handler, tmp_path: Path, session_id: str = "session-1"
) -> tuple[UHPHarnessBackend, HarnessBackendRequest]:
    adapter = UHPHarnessProtocolAdapter(BASE_URL, harness_id="chrn_codex", client=_client(handler))
    backend = UHPHarnessBackend(adapter=adapter)
    request = HarnessBackendRequest(
        spec=uhp_template(),
        prompt="review this repository",
        provider="",
        model="",
        working_directory=tmp_path,
        session_id=session_id,
    )
    return backend, request


@pytest.mark.asyncio
async def test_backend_translates_protocol_events_for_the_tui(tmp_path: Path):
    body = _sse(
        [
            {
                "type": "response.output_text.delta",
                "delta": "done",
            },
            {
                "type": "response.completed",
                "response": _response_payload(id="resp_1"),
            },
        ]
    )

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    backend, request = _backend(handler, tmp_path)
    events = [event async for event in backend.stream(request)]
    await backend.adapter.aclose()

    assert [event.type for event in events] == [
        "model_request",
        "model_delta",
        "turn_complete",
        "message.created",
    ]
    assert events[1].data["text"] == "done"


@pytest.mark.asyncio
async def test_first_turn_does_not_require_resume(tmp_path: Path):
    """Tau resumes every turn. UHP has nothing to resume until the first response."""
    sent = []

    def handler(request):
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                text=_sse(
                    [{"type": "response.completed", "response": _response_payload(id="resp_1")}]
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    backend, request = _backend(handler, tmp_path)
    result = await backend.run(request)
    await backend.adapter.aclose()

    assert result.response.error is None
    assert "previous_response_id" not in sent[0]


@pytest.mark.asyncio
async def test_backend_persists_ids_so_the_next_turn_resumes(tmp_path: Path):
    sent = []

    def handler(request):
        if request.method == "POST":
            sent.append(json.loads(request.content))
            index = len(sent)
            return httpx.Response(
                200,
                text=_sse(
                    [
                        {
                            "type": "response.completed",
                            "response": _response_payload(id=f"resp_{index}"),
                        }
                    ]
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    first, request = _backend(handler, tmp_path, session_id="demo")
    await first.run(request)
    await first.adapter.aclose()

    restarted, request = _backend(handler, tmp_path, session_id="demo")
    await restarted.run(request)
    await restarted.adapter.aclose()

    assert "previous_response_id" not in sent[0]
    assert sent[1]["previous_response_id"] == "resp_1"
    state_path = tmp_path / ".superqode" / "uhp" / "sessions" / "demo.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["uhp_previous_response_id"] == "resp_2"
    assert payload["uhp_session_id"] == "sess_1"


def test_uhp_is_a_catalog_and_registry_backend(tmp_path: Path):
    entry = resolve_harness("uhp", root=tmp_path)
    backend = create_harness_backend("uhp")

    assert entry.id == "uhp"
    assert entry.runtime == "uhp"
    assert entry.source == "optional:uhp"
    assert entry.spec.metadata["policy_owner"] == "server"
    assert backend.name == "uhp"
    assert uhp_template().runtime.backend == "uhp"


def test_uhp_aliases_resolve(tmp_path: Path):
    assert resolve_harness("unified-harness-protocol", root=tmp_path).id == "uhp"
    assert resolve_harness("harness-router", root=tmp_path).id == "uhp"


def test_availability_tracks_configuration_not_an_installed_package(tmp_path, monkeypatch):
    """The route must not look ready before a server and harness are chosen."""
    from superqode.harness.backends.uhp import uhp_backend_status
    from superqode.providers import uhp as uhp_settings
    from superqode.providers.uhp import (
        API_KEY_ENV,
        BASE_URL_ENV,
        HARNESS_ENV,
        UHPSettings,
        save_connection,
    )

    monkeypatch.setattr(uhp_settings.Path, "home", staticmethod(lambda: tmp_path))
    for name in (BASE_URL_ENV, API_KEY_ENV, HARNESS_ENV):
        monkeypatch.delenv(name, raising=False)

    ready, issue = uhp_backend_status()
    assert ready is False and "connect uhp" in issue

    save_connection(UHPSettings(base_url=BASE_URL))
    ready, issue = uhp_backend_status()
    assert ready is False and "--harness" in issue

    save_connection(UHPSettings(base_url=BASE_URL, harness_id="chrn_codex"))
    assert uhp_backend_status() == (True, "")


@pytest.mark.asyncio
async def test_two_sessions_do_not_share_a_conversation(tmp_path: Path):
    """Threading is per session; leaking it would cross two users' work."""
    sent = []

    def handler(request):
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                text=_sse(
                    [{"type": "response.completed", "response": _response_payload(id="resp_1")}]
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    first, first_request = _backend(handler, tmp_path, session_id="one")
    await first.run(first_request)
    second, second_request = _backend(handler, tmp_path, session_id="two")
    await second.run(second_request)

    assert "previous_response_id" not in sent[0]
    assert "previous_response_id" not in sent[1]


def test_switching_to_a_server_owned_harness_skips_the_local_model_step(monkeypatch, tmp_path):
    """Collecting a local model for a remote harness gathers an unused setting."""
    from superqode.harness.templates import uhp_template

    spec = uhp_template()
    assert spec.metadata["policy_owner"] == "server"
    # No local model policy, which is exactly why the switch flow used to
    # fall through to its "ask for a model" branch.
    assert not spec.model_policy.primary
    assert spec.agents[0].tools == ()


def test_server_owned_harnesses_are_identifiable_from_the_spec():
    """The TUI keys its model prompt and tools line off this one field."""
    from superqode.harness.templates import core_template, uhp_template

    assert str(uhp_template().metadata.get("policy_owner")) == "server"
    assert core_template().metadata.get("policy_owner") is None


def test_switching_to_a_server_owned_harness_connects_the_session(tmp_path, monkeypatch):
    """Skipping the model step must not leave the session unable to send.

    The model prompt is also what connected the session, so removing it once
    left `:harness switch uhp` active but every message refused with
    "Not connected".
    """
    from superqode.app_main import SuperQodeApp
    from superqode.providers import uhp as uhp_settings
    from superqode.providers.uhp import UHPSettings, save_connection
    from superqode.pure_mode import PureMode

    monkeypatch.setattr(uhp_settings.Path, "home", staticmethod(lambda: tmp_path))
    save_connection(UHPSettings(base_url=BASE_URL, harness_id="chrn_codex"))

    class Log:
        def __init__(self):
            self.items = []

        def clear(self):
            pass

        def write(self, content):
            self.items.append(str(content))

        def add_info(self, message):
            self.items.append(str(message))

        def add_error(self, message):
            self.items.append(str(message))

        def add_success(self, message):
            self.items.append(str(message))

        def add_meta(self, message, **kwargs):
            self.items.append(str(message))

        def scroll_end(self, **kwargs):
            pass

    app = SuperQodeApp()
    app.set_timer = lambda *a, **k: None
    app._ensure_input_focus = lambda: None
    app._record_ex_command = lambda *a: None
    app._pure_mode = PureMode()

    assert app._pure_mode.session.connected is False
    app._harness_cmd("switch uhp", Log())

    assert app._pure_mode.session.connected is True
    assert app._pure_mode.session.provider == "uhp"


def test_the_connect_screen_paints_every_surface_black():
    """Textual gives Input, OptionList and Button their own grey panels."""
    from superqode.widgets.uhp_connect import UHPConnectScreen

    css = UHPConnectScreen.CSS
    assert "#050505" not in css
    assert "#333333" not in css
    for selector in ("#uhp-url", "#uhp-list", "#uhp-actions Button", "Footer"):
        assert selector in css
    assert css.count("#000000") >= 10
