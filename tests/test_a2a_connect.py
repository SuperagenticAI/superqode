"""CLI connect a2a: discover a card and optionally send a message."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

pytest.importorskip("a2a", reason="A2A tests require the optional a2a extra")
pytest.importorskip("fastapi", reason="A2A tests require FastAPI")

from superqode.a2a.connection import A2ASettings, resolve_settings, save_connection
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

    def patched_init(self, agent_url, http_client=None, timeout=60.0, bearer_token=None):
        if http_client is None:
            http_client = httpx.AsyncClient(transport=transport, base_url=base_url)
        real_init(
            self,
            agent_url,
            http_client=http_client,
            timeout=timeout,
            bearer_token=bearer_token,
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
        "#a2a-list",
        "#a2a-inspect",
        "#a2a-actions Button",
        "Footer",
    ):
        assert selector in css
    assert css.count("#000000") >= 10


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
    assert blank._url == "https://superqode.onrender.com"
    assert blank._token == ""

    result = A2AConnectResult("https://agent.example", "tok", name="Pilot")
    assert result.url == "https://agent.example"
    assert result.token == "tok"
    assert result.name == "Pilot"
    assert A2AConnectResult("https://agent.example").token == ""


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
