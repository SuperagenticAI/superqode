"""A2A client checks against a card: fetch, shape, binding, one task."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

pytest.importorskip("a2a", reason="A2A tests require the optional a2a extra")
pytest.importorskip("fastapi", reason="A2A tests require FastAPI")

from superqode.a2a.conformance import (
    DEFAULT_PROBE,
    render_a2a_conformance,
    run_a2a_conformance,
)
from superqode.a2a.connection import A2ASettings, normalize_url
from superqode.commands.connect import connect
from superqode.harness import DirectPythonHarnessAdapter, HarnessProtocolController
from superqode.harness.store import MemoryHarnessStore


def _server(tmp_path: Path):
    from superqode.a2a.server import A2AServer, A2AServerConfig

    async def handler(message, session):
        del session
        return f"echo:{message.content}"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)],
        store=MemoryHarnessStore(),
    )
    return A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            url="http://agent",
            working_directory=Path("."),
            task_store_path=tmp_path / "tasks.sqlite3",
            harness_skill_enabled=False,
        ),
    )


def _client(app, base_url="http://agent"):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=base_url)


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


def _names(report):
    return [check.name for check in report.checks]


@pytest.mark.asyncio
async def test_conformance_passes_a_local_agent(tmp_path: Path):
    server = _server(tmp_path)
    async with _client(server.app) as http:
        report = await run_a2a_conformance(
            A2ASettings(url="http://agent"),
            http_client=http,
        )
    assert report.passed
    assert _names(report) == ["card-fetch", "card-shape", "binding", "send"]
    assert all(not check.skipped for check in report.checks)
    assert report.binding == "JSONRPC"
    assert report.protocol_version == "1.0"
    send = report.checks[-1]
    assert "completed" in send.detail
    kinds = [event["kind"] for event in report.inspect["events"]]
    assert "choice" in kinds
    assert "request" in kinds


@pytest.mark.asyncio
async def test_conformance_skips_send_when_the_card_is_unspeakable():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    async def card():
        return JSONResponse(
            {
                "name": "GrpcOnly",
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

    async with _client(app) as http:
        report = await run_a2a_conformance(
            A2ASettings(url="http://agent"),
            http_client=http,
        )
    assert report.passed is False
    by_name = {check.name: check for check in report.checks}
    assert by_name["card-fetch"].passed is True
    assert by_name["binding"].passed is False
    assert "unsupported binding GRPC" in by_name["binding"].detail
    assert by_name["send"].skipped is True
    rendered = render_a2a_conformance(report)
    assert "A2A client checks: FAIL" in rendered
    assert "[FAIL] binding" in rendered
    assert "[skip] send" in rendered


@pytest.mark.asyncio
async def test_conformance_fails_when_there_is_no_card():
    from fastapi import FastAPI

    async with _client(FastAPI()) as http:
        report = await run_a2a_conformance(
            A2ASettings(url="http://agent"),
            http_client=http,
        )
    assert report.passed is False
    by_name = {check.name: check for check in report.checks}
    assert by_name["card-fetch"].passed is False
    assert "404" in by_name["card-fetch"].detail
    assert by_name["card-shape"].skipped is True
    assert by_name["binding"].skipped is True
    assert by_name["send"].skipped is True


@pytest.mark.asyncio
async def test_conformance_can_skip_send(tmp_path: Path):
    server = _server(tmp_path)
    async with _client(server.app) as http:
        report = await run_a2a_conformance(
            A2ASettings(url="http://agent"),
            send=False,
            http_client=http,
        )
    assert report.passed
    by_name = {check.name: check for check in report.checks}
    assert by_name["send"].skipped is True
    assert by_name["send"].detail == "not requested"


def test_connect_a2a_conformance_cli(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    _patch_client(monkeypatch, _server(tmp_path).app)

    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--conformance", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert payload["binding"] == "JSONRPC"
    assert [check["name"] for check in payload["checks"]] == [
        "card-fetch",
        "card-shape",
        "binding",
        "send",
    ]
    assert not (tmp_path / "a2a.json").exists()


def test_connect_a2a_conformance_no_send_skips_the_task(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("superqode.a2a.connection.connection_path", lambda: tmp_path / "a2a.json")
    _patch_client(monkeypatch, _server(tmp_path).app)

    result = CliRunner().invoke(
        connect,
        ["a2a", "--url", "http://agent", "--conformance", "--no-send", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    send = next(check for check in payload["checks"] if check["name"] == "send")
    assert send["skipped"] is True


def test_connect_a2a_conformance_cli_fails_unspeakable(tmp_path: Path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/.well-known/agent-card.json")
    async def card():
        return JSONResponse(
            {
                "name": "GrpcOnly",
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
        ["a2a", "--url", "http://agent", "--conformance"],
    )
    assert result.exit_code == 1, result.output
    assert "A2A client checks: FAIL" in result.output
    assert "unsupported binding GRPC" in result.output
    assert "Inspect:" in result.output


def test_normalize_url_strips_a_pasted_card_path():
    assert normalize_url("https://agent.example/.well-known/agent-card.json") == (
        "https://agent.example"
    )
    assert DEFAULT_PROBE == "ping"


def test_the_check_button_is_on_the_connect_screen():
    import inspect

    from superqode.widgets.a2a_connect import A2AConnectScreen

    source = inspect.getsource(A2AConnectScreen.compose)
    assert 'id="a2a-check"' in source
    assert 'id="a2a-logout"' in source
    assert 'id="a2a-oauth"' in source
    assert 'id="a2a-headers-btn"' in source
    assert 'id="a2a-tls-btn"' in source
    assert 'id="a2a-inspect-btn"' in source
    assert 'id="a2a-headers"' in source
    assert 'id="a2a-cert"' in source
    assert 'id="a2a-examples"' in source
    from superqode.widgets.a2a_connect import _HINT

    assert "anonymous" in _HINT
