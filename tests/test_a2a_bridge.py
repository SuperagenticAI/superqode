from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

pytest.importorskip("a2a", reason="A2A tests require the optional a2a extra")
pytest.importorskip("fastapi", reason="A2A tests require FastAPI")

from fastapi.testclient import TestClient

from superqode.a2a.client import A2AClient
from superqode.a2a.server import A2AServer, A2AServerConfig
from superqode.a2a.types import TaskStatusValue
from superqode.commands.serve import serve
from superqode.harness import DirectPythonHarnessAdapter, HarnessProtocolController
from superqode.harness.store import MemoryHarnessStore


def _server(
    tmp_path: Path,
    *,
    token: str | None = None,
    url: str = "http://127.0.0.1:8000",
) -> tuple[A2AServer, list[str]]:
    session_ids: list[str] = []

    async def handler(message, session):
        session_ids.append(session.session_id)
        return f"echo:{message.content}"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)],
        store=MemoryHarnessStore(),
    )
    return (
        A2AServer(
            controller,
            A2AServerConfig(
                provider="test",
                model="test",
                url=url,
                working_directory=Path("."),
                task_store_path=tmp_path / "tasks.sqlite3",
                bearer_token=token,
            ),
        ),
        session_ids,
    )


def _request(message: str, *, context_id: str | None = None) -> dict:
    payload = {
        "message": {
            "messageId": f"message-{message}",
            "role": "ROLE_USER",
            "parts": [{"text": message}],
        },
        "configuration": {"acceptedOutputModes": ["text/plain"]},
    }
    if context_id:
        payload["message"]["contextId"] = context_id
    return payload


def test_a2a_card_task_lifecycle_and_context_session_reuse(tmp_path: Path):
    server, session_ids = _server(tmp_path)
    client = TestClient(server.app)

    card_response = client.get("/.well-known/agent-card.json")
    assert card_response.status_code == 200
    card = card_response.json()
    assert card == json.loads(server.agent_card_json())
    assert card["supportedInterfaces"] == [
        {
            "url": "http://127.0.0.1:8000",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        }
    ]
    assert client.post("/message:send", json=_request("no-version")).status_code == 400

    first = client.post(
        "/message:send",
        headers={"A2A-Version": "1.0"},
        json=_request("first"),
    )
    assert first.status_code == 200
    first_task = first.json()["task"]
    assert first_task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert first_task["artifacts"][0]["parts"][0]["text"] == "echo:first"

    fetched = client.get(f"/tasks/{first_task['id']}", headers={"A2A-Version": "1.0"})
    assert fetched.status_code == 200
    assert fetched.json()["id"] == first_task["id"]

    with client.stream(
        "GET",
        f"/tasks/{first_task['id']}:subscribe",
        headers={"A2A-Version": "1.0"},
    ) as subscribed:
        subscription_body = "\n".join(subscribed.iter_lines())
    assert subscribed.status_code == 400
    assert "terminal state" in subscription_body

    second = client.post(
        "/message:send",
        headers={"A2A-Version": "1.0"},
        json=_request("second", context_id=first_task["contextId"]),
    )
    assert second.status_code == 200
    assert session_ids[0] == session_ids[1]
    assert session_ids[0] == f"a2a-{first_task['contextId']}"


def test_a2a_bearer_auth_protects_operations_but_not_discovery(tmp_path: Path):
    server, _ = _server(tmp_path, token="secret")
    client = TestClient(server.app)

    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json()["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"
    assert (
        client.post(
            "/message:send",
            headers={"A2A-Version": "1.0"},
            json=_request("blocked"),
        ).status_code
        == 401
    )
    allowed = client.post(
        "/message:send",
        headers={"A2A-Version": "1.0", "Authorization": "Bearer secret"},
        json=_request("allowed"),
    )
    assert allowed.status_code == 200


def test_a2a_streams_harness_deltas_as_artifact_updates(tmp_path: Path):
    async def handler(message, session):
        del message, session

        async def chunks():
            yield "one"
            yield "-two"

        return chunks()

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("stream", handler)],
        store=MemoryHarnessStore(),
    )
    server = A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            working_directory=Path("."),
            task_store_path=tmp_path / "stream-tasks.sqlite3",
        ),
    )
    client = TestClient(server.app)

    with client.stream(
        "POST",
        "/message:stream",
        headers={"A2A-Version": "1.0"},
        json=_request("stream"),
    ) as response:
        body = "\n".join(response.iter_lines())

    assert response.status_code == 200
    assert "one" in body
    assert "-two" in body
    assert "artifactUpdate" in body
    assert "TASK_STATE_COMPLETED" in body


@pytest.mark.asyncio
async def test_superqode_client_uses_a2a_1_0_shapes(tmp_path: Path):
    server, _ = _server(tmp_path)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as http_client:
        client = A2AClient("http://agent", http_client=http_client)
        card = await client.get_agent_card()
        task = await client.send_message("from-client")

    assert card.url == "http://127.0.0.1:8000"
    assert card.skills[0].id == "superqode-harness"
    assert task.status.state == TaskStatusValue.COMPLETED
    assert task.artifacts[0].parts[0].text == "echo:from-client"


@pytest.mark.asyncio
async def test_client_routes_operations_to_the_discovered_path(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    server, _ = _server(tmp_path, url="http://agent/superqode/a2a")
    outer = FastAPI()

    @outer.get("/.well-known/agent-card.json")
    async def public_card():
        return JSONResponse(content=json.loads(server.agent_card_json()))

    outer.mount("/superqode/a2a", server.app)
    transport = httpx.ASGITransport(app=outer)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as http_client:
        client = A2AClient("http://agent", http_client=http_client)
        task = await client.send_message("path-aware")
        fetched = await client.get_task(task.task_id)

    assert task.status.state == TaskStatusValue.COMPLETED
    assert fetched.task_id == task.task_id
    assert fetched.artifacts[0].parts[0].text == "echo:path-aware"


@pytest.mark.asyncio
async def test_client_strips_whitespace_from_interface_url(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    server, _ = _server(tmp_path, url="http://agent/superqode/a2a")
    outer = FastAPI()

    @outer.get("/.well-known/agent-card.json")
    async def public_card():
        payload = json.loads(server.agent_card_json())
        # Mimic a hand-edited static card with accidental leading whitespace.
        payload["supportedInterfaces"][0]["url"] = "  http://agent/superqode/a2a  "
        return JSONResponse(content=payload)

    outer.mount("/superqode/a2a", server.app)
    transport = httpx.ASGITransport(app=outer)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as http_client:
        client = A2AClient("http://agent", http_client=http_client)
        card = await client.get_agent_card()
        task = await client.send_message("trim-url")

    assert card.url == "http://agent/superqode/a2a"
    assert task.status.state == TaskStatusValue.COMPLETED
    assert task.artifacts[0].parts[0].text == "echo:trim-url"


@pytest.mark.asyncio
async def test_a2a_can_list_and_cancel_a_running_task(tmp_path: Path):
    started = asyncio.Event()

    async def handler(message, session):
        del message, session
        started.set()
        await asyncio.sleep(30)
        return "too late"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("cancel", handler)],
        store=MemoryHarnessStore(),
    )
    server = A2AServer(
        controller,
        A2AServerConfig(
            provider="test",
            model="test",
            task_store_path=tmp_path / "cancel-tasks.sqlite3",
        ),
    )
    transport = httpx.ASGITransport(app=server.app)
    headers = {"A2A-Version": "1.0"}
    async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
        send = asyncio.create_task(
            client.post("/message:send", headers=headers, json=_request("wait"))
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            for _ in range(40):
                listed = await client.get("/tasks", headers=headers)
                if listed.json()["tasks"]:
                    break
                await asyncio.sleep(0.05)
            task_id = listed.json()["tasks"][0]["id"]
            subscribed = asyncio.create_task(
                client.get(f"/tasks/{task_id}:subscribe", headers=headers)
            )
            await asyncio.sleep(0)
            canceled = await client.post(f"/tasks/{task_id}:cancel", headers=headers, json={})
            sent = await asyncio.wait_for(send, timeout=2)
            subscription = await asyncio.wait_for(subscribed, timeout=2)
        finally:
            if not send.done():
                send.cancel()

    assert listed.status_code == 200
    assert canceled.status_code == 200
    assert canceled.json()["status"]["state"] == "TASK_STATE_CANCELED"
    assert sent.status_code == 200
    assert subscription.status_code == 200
    assert "TASK_STATE_CANCELED" in subscription.text


def test_a2a_task_records_survive_server_restart(tmp_path: Path):
    task_store = tmp_path / "durable-tasks.sqlite3"
    first_server, _ = _server_with_task_store(task_store)
    with TestClient(first_server.app) as client:
        response = client.post(
            "/message:send",
            headers={"A2A-Version": "1.0"},
            json=_request("durable"),
        )
        task_id = response.json()["task"]["id"]

    second_server, _ = _server_with_task_store(task_store)
    with TestClient(second_server.app) as client:
        restored = client.get(f"/tasks/{task_id}", headers={"A2A-Version": "1.0"})

    assert restored.status_code == 200
    assert restored.json()["id"] == task_id
    assert restored.json()["status"]["state"] == "TASK_STATE_COMPLETED"


def _server_with_task_store(path: Path) -> tuple[A2AServer, list[str]]:
    session_ids: list[str] = []

    async def handler(message, session):
        session_ids.append(session.session_id)
        return f"echo:{message.content}"

    controller = HarnessProtocolController(
        [DirectPythonHarnessAdapter("test", handler)],
        store=MemoryHarnessStore(),
    )
    return (
        A2AServer(
            controller,
            A2AServerConfig(
                provider="test",
                model="test",
                working_directory=Path("."),
                task_store_path=path,
            ),
        ),
        session_ids,
    )


def test_exported_agent_card_matches_checked_in_publication(tmp_path: Path):
    exported = tmp_path / "agent-card.json"
    result = CliRunner().invoke(
        serve,
        [
            "a2a",
            "--public-url",
            "https://super-agentic.ai/superqode/a2a",
            "--token",
            "preview-only-value",
            "--harness-store",
            str(tmp_path / "harness.sqlite3"),
            "--task-store",
            str(tmp_path / "tasks.sqlite3"),
            "--export-agent-card",
            str(exported),
        ],
    )

    expected = Path(__file__).parents[1] / "examples" / "a2a" / "agent-card.json"
    assert result.exit_code == 0, result.output
    assert json.loads(exported.read_text()) == json.loads(expected.read_text())


def test_independent_node_typescript_client_interoperates(tmp_path: Path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")

    version = subprocess.run([node, "--version"], check=False, capture_output=True, text=True)
    major = 0
    if version.returncode == 0 and version.stdout.startswith("v"):
        try:
            major = int(version.stdout[1:].split(".", 1)[0])
        except ValueError:
            major = 0
    if major < 22:
        pytest.skip("Node 22+ is required for --experimental-strip-types")

    import uvicorn

    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("Loopback sockets are unavailable in this sandbox")
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server, _ = _server(tmp_path, token="interop-secret", url=base_url)
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()

    try:
        for _ in range(50):
            try:
                if httpx.get(f"{base_url}/health", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            pytest.fail("Local A2A interoperability server did not start")

        script = (
            Path(__file__).parents[1]
            / "examples"
            / "qm-deployment-layer"
            / "interop"
            / "a2a-client.mts"
        )
        completed = subprocess.run(
            [
                node,
                "--experimental-strip-types",
                str(script),
                base_url,
                "interop-secret",
                "from-typescript",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["agent"] == "SuperQode"
    assert result["state"] == "TASK_STATE_COMPLETED"
    assert result["fetchedState"] == "TASK_STATE_COMPLETED"
    assert result["artifactText"] == "echo:from-typescript"


def test_a2a_cli_refuses_unauthorized_remote_binding():
    result = CliRunner().invoke(serve, ["a2a", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "Use --allow-remote" in result.output

    result = CliRunner().invoke(serve, ["a2a", "--host", "0.0.0.0", "--allow-remote"])
    assert result.exit_code == 1
    assert "requires --token" in result.output
