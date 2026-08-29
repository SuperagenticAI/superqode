"""CLI connect a2a: discover a card and optionally send a message."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

pytest.importorskip("a2a", reason="A2A tests require the optional a2a extra")
pytest.importorskip("fastapi", reason="A2A tests require FastAPI")

from superqode.a2a.connection import (
    A2ASettings,
    parse_header_options,
    resolve_settings,
    save_connection,
)
from superqode.commands.connect import connect
from superqode.harness import DirectPythonHarnessAdapter, HarnessProtocolController
from superqode.harness.store import MemoryHarnessStore


def test_resolve_settings_prefers_options_then_env_then_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    save_connection(A2ASettings(url="https://saved.example", token="saved-token"))
    monkeypatch.setenv("SUPERQODE_A2A_URL", "https://env.example")
    monkeypatch.setenv("SUPERQODE_A2A_CLIENT_TOKEN", "env-token")
    chosen = resolve_settings("https://flag.example", "flag-token")
    assert chosen.url == "https://flag.example"
    assert chosen.token == "flag-token"
    from_env = resolve_settings(None, None)
    assert from_env.url == "https://env.example"
    assert from_env.token == "env-token"


def test_connect_a2a_tells_the_user_which_api_key_header_to_pass(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    async def card():
        return JSONResponse(
            {
                "name": "Keyed",
                "version": "1.0",
                "skills": [],
                "url": "http://agent",
                "supportedInterfaces": [
                    {
                        "url": "http://agent",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0",
                    }
                ],
                "securitySchemes": {
                    "apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"}
                },
                "securityRequirements": [{"apiKey": []}],
            }
        )

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    _patch_client(monkeypatch, app)
    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--json", "--no-save", "--no-oauth"],
    )
    assert result.exit_code == 1, result.output
    assert "X-API-Key" in result.output


def test_connect_a2a_logout_clears_stored_tokens(tmp_path, monkeypatch):
    from superqode.a2a.oauth import A2AOAuthStore
    from superqode.mcp.oauth import OAuthTokens

    store = A2AOAuthStore(storage_dir=tmp_path / "oauth", use_keyring=False)
    store.save_tokens("http://agent", OAuthTokens(access_token="tok"))
    monkeypatch.setattr("superqode.a2a.oauth.oauth_storage", lambda: store)
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--logout", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["cleared"] is True
    assert payload["revoked"] is False
    assert store.load_tokens("http://agent") is None


def test_parse_header_options_splits_on_the_first_colon():
    assert parse_header_options(("X-Tenant: acme", "X-Api-Key: secret:still")) == {
        "X-Tenant": "acme",
        "X-Api-Key": "secret:still",
    }


def test_parse_header_line_splits_semicolons():
    from superqode.a2a.connection import format_header_line, parse_header_line

    parsed = parse_header_line("X-Tenant: acme; X-Request-Id: 1")
    assert parsed == {"X-Tenant": "acme", "X-Request-Id": "1"}
    assert parse_header_line("") == {}
    assert format_header_line(parsed) == "X-Tenant: acme; X-Request-Id: 1"


def test_parse_header_options_rejects_a_bare_name():
    with pytest.raises(ValueError, match="NAME:VALUE"):
        parse_header_options(("NoColon",))


def test_save_connection_keeps_extra_headers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    save_connection(
        A2ASettings(url="https://agent.example", token="", headers={"X-Tenant": "acme"})
    )
    saved = resolve_settings(None, None)
    assert saved.headers == {"X-Tenant": "acme"}


def test_save_connection_does_not_copy_an_env_token(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    monkeypatch.setenv("SUPERQODE_A2A_CLIENT_TOKEN", "env-token")
    save_connection(A2ASettings(url="https://agent.example", token="env-token"))
    payload = json.loads((tmp_path / "a2a.json").read_text())
    assert payload["url"] == "https://agent.example"
    assert payload["token"] == ""


def test_connect_a2a_cli_discovers_and_sends(tmp_path: Path, monkeypatch):
    from superqode.a2a.server import A2AServer, A2AServerConfig

    async def handler(message, session):
        del session
        return f"echo:{message.content}"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)],
        store=MemoryHarnessStore(),
    )
    server = A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            url="http://agent",
            working_directory=Path("."),
            task_store_path=None,
            harness_skill_enabled=False,
        ),
    )
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")

    _patch_client(monkeypatch, server.app)

    result = CliRunner().invoke(
        connect,
        [
            "a2a",
            "--url",
            "http://agent",
            "--send",
            "Which coding agents are open source?",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["connected"] is True
    assert payload["binding"] == "JSONRPC"
    assert payload["protocol_version"] == "1.0"
    assert payload["task"]["state"] == "completed"
    assert "Third-party harnesses" in payload["task"]["text"]
    summaries = [event["summary"] for event in payload["inspect"]["events"]]
    assert any("Chose JSONRPC 1.0" in line for line in summaries)
    assert any(line.startswith("GET ") for line in summaries)
    assert any("SendMessage JSONRPC 1.0" in line for line in summaries)
    saved = json.loads((tmp_path / "a2a.json").read_text())
    assert saved["url"] == "http://agent"


def _patch_client(monkeypatch, app, base_url="http://agent"):
    from superqode.a2a.client import A2AClient

    transport = httpx.ASGITransport(app=app)
    real_init = A2AClient.__init__

    def patched_init(
        self,
        agent_url,
        http_client=None,
        timeout=60.0,
        bearer_token=None,
        extra_headers=None,
        client_cert=None,
        client_key=None,
    ):
        if http_client is None:
            http_client = httpx.AsyncClient(transport=transport, base_url=base_url)
        real_init(
            self,
            agent_url,
            http_client=http_client,
            timeout=timeout,
            bearer_token=bearer_token,
            extra_headers=extra_headers,
            client_cert=client_cert,
            client_key=client_key,
        )

    monkeypatch.setattr(A2AClient, "__init__", patched_init)


def test_connect_a2a_inspect_prints_the_wire_log(tmp_path: Path, monkeypatch):
    from superqode.a2a.server import A2AServer, A2AServerConfig

    async def handler(message, session):
        del message, session
        return "ok"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)],
        store=MemoryHarnessStore(),
    )
    server = A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            url="http://agent",
            working_directory=Path("."),
            task_store_path=None,
            harness_skill_enabled=False,
        ),
    )
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    _patch_client(monkeypatch, server.app)

    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--inspect", "--no-save"],
    )
    assert result.exit_code == 0, result.output
    assert "Inspect:" in result.output
    assert "Chose JSONRPC 1.0" in result.output
    assert "skip JSONRPC 0.3" in result.output
    assert "later in preference" in result.output


def test_connect_a2a_inspect_explains_an_unspeakable_card(tmp_path: Path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    async def card():
        return JSONResponse(
            {
                "name": "GrpcOnly",
                "description": "grpc",
                "version": "1.0",
                "skills": [],
                "supportedInterfaces": [
                    {
                        "url": "https://grpc.example",
                        "protocolBinding": "GRPC",
                        "protocolVersion": "1.0",
                    }
                ],
            }
        )

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    _patch_client(monkeypatch, app)

    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--json", "--no-save"],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["connected"] is False
    assert "unsupported binding GRPC" in payload["error"]
    summaries = [event["summary"] for event in payload["inspect"]["events"]]
    assert any(line.startswith("GET ") for line in summaries)
    assert any("No speakable interface" in line for line in summaries)


def test_origin_strips_a_pasted_well_known_path():
    from superqode.widgets.a2a_connect import _origin

    assert _origin("https://agent.example/.well-known/agent-card.json") == "https://agent.example"
    assert _origin("https://agent.example/.well-known/agent.json/") == "https://agent.example"
    assert _origin("https://agent.example/") == "https://agent.example"
    assert _origin("https://agent.example") == "https://agent.example"


def test_the_a2a_connect_screen_paints_every_surface_black():
    from superqode.widgets.a2a_connect import A2AConnectScreen

    css = A2AConnectScreen.CSS
    assert "#050505" not in css
    assert "#333333" not in css
    for selector in (
        "#a2a-url",
        "#a2a-token",
        "#a2a-headers",
        "#a2a-cert",
        "#a2a-oauth",
        "#a2a-options",
        "#a2a-headers-panel",
        "#a2a-tls-panel",
        "#a2a-chat",
        "#a2a-thinking",
        "#a2a-examples",
        "#a2a-inspect",
        "#a2a-actions Button",
        "Footer",
    ):
        assert selector in css
    assert css.count("#000000") >= 10


def test_stream_delta_reads_text_fields():
    from types import SimpleNamespace

    from superqode.widgets.a2a_connect import _stream_context_id, _stream_delta

    assert _stream_delta(SimpleNamespace(data="hello")) == "hello"
    assert _stream_delta(SimpleNamespace(data={"text": "chunk"})) == "chunk"
    assert (
        _stream_delta(
            SimpleNamespace(data={"result": {"artifacts": [{"parts": [{"text": "part"}]}]}})
        )
        == "part"
    )
    assert (
        _stream_delta(
            SimpleNamespace(
                data={
                    "jsonrpc": "2.0",
                    "result": {
                        "kind": "artifact-update",
                        "contextId": "ctx-9",
                        "artifact": {"parts": [{"kind": "text", "text": "streamed"}]},
                    },
                }
            )
        )
        == "streamed"
    )
    assert (
        _stream_delta(
            SimpleNamespace(
                data={
                    "result": {
                        "kind": "status-update",
                        "status": {"message": {"parts": [{"text": "working"}]}},
                    }
                }
            )
        )
        == "working"
    )
    assert (
        _stream_context_id(SimpleNamespace(data={"result": {"contextId": "ctx-9", "artifact": {}}}))
        == "ctx-9"
    )


@pytest.mark.asyncio
async def test_deliver_streams_and_keeps_context_id():
    from types import SimpleNamespace

    from superqode.widgets.a2a_connect import A2AConnectScreen

    class StreamingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str | None]] = []

        async def send_message_streaming(self, message, session_id=None):
            self.calls.append(("stream", message, session_id))
            yield SimpleNamespace(
                type="message",
                data={
                    "result": {
                        "kind": "artifact-update",
                        "contextId": "ctx-1",
                        "artifact": {"parts": [{"text": "hi "}]},
                    }
                },
            )
            yield SimpleNamespace(
                type="message",
                data={
                    "result": {
                        "kind": "artifact-update",
                        "artifact": {"parts": [{"text": "there"}]},
                    }
                },
            )

        async def send_message(self, message, session_id=None):
            self.calls.append(("one", message, session_id))
            raise AssertionError("must not fall back after a live stream")

    screen = A2AConnectScreen(url="", default_url="")
    screen._streaming = True
    screen._context_id = ""
    client = StreamingClient()
    text, task = await screen._deliver(client, "hello")
    assert text == "hi there"
    assert task.context_id == "ctx-1"
    assert client.calls == [("stream", "hello", None)]

    screen._context_id = "ctx-1"
    follow = StreamingClient()
    await screen._deliver(follow, "again")
    assert follow.calls == [("stream", "again", "ctx-1")]


@pytest.mark.asyncio
async def test_deliver_falls_back_when_the_stream_errors():
    from types import SimpleNamespace

    from superqode.widgets.a2a_connect import A2AConnectScreen

    class FallbackClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def send_message_streaming(self, message, session_id=None):
            self.calls.append("stream")
            yield SimpleNamespace(type="error", data="boom")

        async def send_message(self, message, session_id=None):
            self.calls.append("one")
            return SimpleNamespace(
                artifacts=[SimpleNamespace(parts=[SimpleNamespace(text="one-shot")])],
                status=SimpleNamespace(message=""),
                history=[],
                context_id="ctx-2",
            )

    screen = A2AConnectScreen(url="", default_url="")
    screen._streaming = True
    text, task = await screen._deliver(FallbackClient(), "hello")
    assert text == "one-shot"
    assert task.context_id == "ctx-2"


def test_use_saves_in_place_and_chat_keys_are_wired():
    from inspect import getsource

    from superqode.widgets.a2a_connect import A2AConnectScreen, _Row

    assert _Row("echo", "Echo", "repeat", ("say hi",)).examples == ("say hi",)
    use = getsource(A2AConnectScreen._use_connected)
    assert "save_connection" in use
    assert "dismiss" not in use
    assert "Stay here" in use
    source = getsource(A2AConnectScreen)
    assert "action_copy_reply" in source
    assert "action_resend" in source
    assert "action_cancel_or_close" in source
    assert "_note_cold_start" in source
    assert "Host may be cold-starting" in source
    assert "send_message_streaming" in source
    assert "_on_example" in source
    assert 'id="a2a-examples"' in source


def test_a2a_commands_list_saved_connection_once(tmp_path, monkeypatch):
    from superqode.a2a.connection import A2ASettings, save_connection
    from superqode.commands.a2a import A2ACommands

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    save_connection(A2ASettings(url="https://agent.example", name="Pilot"))
    commands = A2ACommands()
    commands.remember_agent("Pilot", "https://agent.example")
    commands.remember_agent("https://agent.example", "https://agent.example")
    agents = commands._agents()
    assert len(agents) == 1
    assert agents[0]["name"] == "Pilot"
    assert commands._resolve_url("Pilot") == "https://agent.example"
    assert commands._resolve_url("https://agent.example") == "https://agent.example"


def test_origin_for_protocol_screen_keeps_flags_on_the_cli():
    from superqode.app.mixins.connect import _origin_for_protocol_screen

    assert _origin_for_protocol_screen([], "--url") == ""
    assert (
        _origin_for_protocol_screen(["https://agent.example"], "--url") == "https://agent.example"
    )
    assert _origin_for_protocol_screen(["--url", "https://agent.example"], "--url") == (
        "https://agent.example"
    )
    assert (
        _origin_for_protocol_screen(
            ["https://agent.example", "--inspect"],
            "--url",
        )
        is None
    )
    assert _origin_for_protocol_screen(["--conformance"], "--url") is None


def test_task_reply_reads_artifacts_then_status():
    from types import SimpleNamespace

    from superqode.widgets.a2a_connect import _task_reply

    task = SimpleNamespace(
        artifacts=[SimpleNamespace(parts=[SimpleNamespace(text="hello from agent")])],
        status=SimpleNamespace(message="ignored"),
        history=[],
    )
    assert _task_reply(task) == "hello from agent"
    empty = SimpleNamespace(artifacts=[], status=SimpleNamespace(message="queued"), history=[])
    assert _task_reply(empty) == "queued"


def test_the_a2a_connect_screen_carries_url_and_token():
    from superqode.widgets.a2a_connect import A2AConnectResult, A2AConnectScreen

    screen = A2AConnectScreen(
        url="https://saved.example",
        default_url="https://superqode.onrender.com",
        token="sqk_live_test",
    )
    assert screen._url == "https://saved.example"
    assert screen._token == "sqk_live_test"

    blank = A2AConnectScreen(url="", default_url="https://superqode.onrender.com")
    assert blank._url == ""
    assert blank._token == ""
    from inspect import getsource

    screen_source = getsource(A2AConnectScreen)
    assert "onrender" not in screen_source
    assert "press Connect for" not in screen_source

    result = A2AConnectResult("https://agent.example", "tok", name="Pilot")
    assert result.url == "https://agent.example"
    assert result.token == "tok"
    assert result.name == "Pilot"
    assert A2AConnectResult("https://agent.example").token == ""
    assert screen._oauth is True
    assert screen._oauth_label() == "OAuth on"
    screen._oauth = False
    assert screen._oauth_label() == "OAuth off"
    assert screen._show_headers is False
    assert screen._show_tls is False


def test_apply_a2a_selection_saves_the_connection(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.widgets.a2a_connect import A2AConnectResult

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")

    app = SuperQodeApp()
    app.set_timer = lambda *a, **k: None
    app._ensure_input_focus = lambda: None
    log = _Log()

    app._apply_a2a_selection(
        A2AConnectResult(
            url="https://agent.example",
            token="tok",
            name="Pilot",
            binding="JSONRPC",
            protocol_version="1.0",
        ),
        log,
    )

    saved = json.loads((tmp_path / "a2a.json").read_text())
    assert saved["url"] == "https://agent.example"
    assert saved["token"] == "tok"
    assert any("Pilot" in str(item) and "JSONRPC" in str(item) for item in log.items)


def test_apply_a2a_selection_saves_headers_and_tls(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp
    from superqode.widgets.a2a_connect import A2AConnectResult

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")

    app = SuperQodeApp()
    app.set_timer = lambda *a, **k: None
    app._ensure_input_focus = lambda: None
    log = _Log()

    app._apply_a2a_selection(
        A2AConnectResult(
            url="https://agent.example",
            token="",
            name="Pilot",
            headers={"X-Tenant": "acme"},
            cert="/tmp/client.pem",
            key="/tmp/client.key",
        ),
        log,
    )

    saved = json.loads((tmp_path / "a2a.json").read_text())
    assert saved["headers"] == {"X-Tenant": "acme"}
    assert saved["cert"] == "/tmp/client.pem"
    assert saved["key"] == "/tmp/client.key"
    assert any("Pilot" in str(item) for item in log.items)


def test_apply_a2a_selection_dismiss_does_not_save(tmp_path, monkeypatch):
    from superqode.app_main import SuperQodeApp

    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    app = SuperQodeApp()
    app.set_timer = lambda *a, **k: None
    focused = []
    app._ensure_input_focus = lambda: focused.append(True)
    app._apply_a2a_selection(None, _Log())
    assert focused == [True]
    assert not (tmp_path / "a2a.json").exists()


class _Log:
    def __init__(self):
        self.items = []

    def add_success(self, text):
        self.items.append(text)

    def add_info(self, text):
        self.items.append(text)

    def add_error(self, text):
        self.items.append(text)
