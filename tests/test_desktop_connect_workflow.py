"""Connection ladder parity and credential-safe native execution contracts."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superqode.desktop_service.service import DesktopService
from superqode.desktop_service.connect_workflow import (
    connection_menu,
    profile_route,
    validate_origin,
)


@pytest.fixture
def desktop(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    service = DesktopService(tmp_path / "state")
    opened = service.open_project(str(project))
    yield service, opened, project
    service.close()


def test_native_menu_uses_terminal_profiles_and_order(desktop):
    from superqode.providers.connection_profiles import list_connection_profiles

    service, project, root = desktop
    for menu in [
        "root",
        "agents",
        "vendors",
        "harness",
        "models",
        "plan",
        "protocols",
        "open-harnesses",
        "closed-harnesses",
        "by-language",
    ]:
        native = service.dispatch("connect.menu", {"project": project["id"], "menu": menu})
        assert [r["id"] for r in native["rows"]] == [p.id for p in list_connection_profiles(menu)]
    vendors = connection_menu(root, "vendors")["rows"]
    assert {r["id"] for r in vendors} >= {"codex", "copilot", "gemini-cli", "grok"}
    codex = next(r for r in vendors if r["id"] == "codex")
    assert codex["route"]["subscription_vendor"] == "codex"
    assert codex["route"]["runtime"] == "codex-cli"
    assert (
        next(r for r in connection_menu(root, "open-harnesses")["rows"] if r["id"] == "deepagents")[
            "harness_ref"
        ]
        == "deepagents"
    )


def test_model_subscription_guidance_is_not_an_agent_connection(desktop):
    _, _, root = desktop
    plans = connection_menu(root, "plan")["rows"]
    assert plans and all(r["connector"] == "plan-guidance" and "route" not in r for r in plans)
    with pytest.raises(ValueError):
        profile_route(root, plans[0]["id"])


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/foo",
        "https://name:secret@example.org",
        "https://example.org?key=secret",
        "http://example.org",
    ],
)
def test_credentials_cannot_be_sent_to_plaintext_or_embedded_urls(url):
    with pytest.raises(ValueError):
        validate_origin(url, True)


def test_subscription_runtime_keeps_vendor_model_and_strips_api_billing(monkeypatch, tmp_path):
    from superqode.desktop_service.connection_worker import run_connection

    captured = {}
    events = []

    class Runtime:
        async def run_harness_events(self, prompt):
            captured["key_present"] = "OPENAI_API_KEY" in os.environ
            yield SimpleNamespace(type="model_delta", data={"text": "fixture reply"})

        async def aclose(self):
            captured["closed"] = True

    def factory(name, **kwargs):
        captured.update(name=name, **kwargs)
        return Runtime()

    monkeypatch.setattr("superqode.runtime.registry.create_runtime", factory)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-bill-api")
    request = {
        "_desktop_connection": {
            "id": "connection:codex",
            "kind": "runtime",
            "runtime": "codex-cli",
            "subscription_vendor": "codex",
            "digest": "fixture-digest",
        },
        "cwd": str(tmp_path),
        "state_root": str(tmp_path),
        "prompt": "change code",
        "model": "",
    }
    asyncio.run(
        run_connection(request, tmp_path, lambda kind, data: events.append((kind, data)), [])
    )
    assert captured["name"] == "codex-cli" and captured["config"].model == ""
    assert captured["billing_requested"] == "subscription"
    assert not captured["key_present"] and captured["closed"]
    assert callable(captured["approval_callback"])
    assert events[0][0] == "billing"
    assert "OPENAI_API_KEY" in events[0][1]["ignored_api_key_variables"]


@pytest.fixture
def protocol_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            received.append((self.path, self.headers.get("Authorization")))
            if self.path == "/v1/harnesses":
                self.reply(
                    {
                        "data": [
                            {"id": "coding", "name": "Fixture coding"},
                            {"id": "review", "name": "Fixture review"},
                        ]
                    }
                )
            else:
                self.reply(
                    {
                        "name": "Fixture agent",
                        "description": "Local contract fixture",
                        "url": f"http://127.0.0.1:{self.server.server_port}/rpc",
                        "version": "1",
                        "protocolVersion": "0.3.0",
                        "capabilities": {},
                        "skills": [
                            {
                                "id": "code",
                                "name": "Coding",
                                "description": "Writes code",
                                "tags": ["code"],
                            }
                        ],
                    }
                )

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), body))
            text = "fixture-secret-token: code written"
            if self.path == "/v1/responses":
                response = {
                    "id": "response1",
                    "status": "completed",
                    "session_id": "remote-session",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": text}]}
                    ],
                }
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event, data in [
                    (
                        "response.created",
                        {"response": {"id": "response1", "status": "in_progress"}},
                    ),
                    ("response.output_text.delta", {"delta": text}),
                    ("response.completed", {"response": response}),
                ]:
                    self.wfile.write(
                        (
                            "event: "
                            + event
                            + "\ndata: "
                            + json.dumps({"type": event, **data})
                            + "\n\n"
                        ).encode()
                    )
                    self.wfile.flush()
            else:
                self.reply(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "kind": "task",
                            "id": "task1",
                            "contextId": "context1",
                            "status": {"state": "completed"},
                            "artifacts": [
                                {"artifactId": "answer", "parts": [{"kind": "text", "text": text}]}
                            ],
                        },
                    }
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("protocol", ["a2a", "uhp"])
def test_protocol_discovery_selection_and_real_worker_task(desktop, protocol_server, protocol):
    service, project, _ = desktop
    url, received = protocol_server
    discovery = service.dispatch(
        "connect.protocol",
        {
            "project": project["id"],
            "protocol": protocol,
            "url": url,
            "token": "fixture-secret-token",
        },
    )
    assert discovery["items"]
    route = service.dispatch(
        "connect.protocol.select",
        {"project": project["id"], "connection": discovery["connection"], "harness": "coding"},
    )
    if protocol == "uhp":
        other = service.dispatch(
            "connect.protocol.select",
            {"project": project["id"], "connection": discovery["connection"], "harness": "review"},
        )
        assert other["id"] != route["id"]
        assert service.remote_connections[route["id"]]["route"]["remote_harness"] == "coding"
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": route["id"],
            "prompt": "Write code",
            "command_id": protocol,
        },
    )
    for _ in range(200):
        result = service.dispatch("jobs.get", {"id": job["id"]})
        if result["status"] not in {"running", "needs_approval"}:
            break
        time.sleep(0.05)
    assert result["status"] == "completed", result
    assert all(row[1] == "Bearer fixture-secret-token" for row in received)
    text = json.dumps(result)
    assert "fixture-secret-token" not in text
    assert "[REDACTED]: code written" in text
    assert not result["result"]["native_continuity"]
    assert "fixture-secret-token" not in (service.root / "desktop.sqlite").read_bytes().decode(
        errors="ignore"
    )
    if protocol == "uhp":
        assert received[-1][2]["metadata"]["harness_id"] == "coding"
    assert result["result"]["remote_continuity"]
    followup = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": route["id"],
            "prompt": "Continue",
            "command_id": "resume-" + protocol,
            "parent_id": job["id"],
        },
    )
    for _ in range(200):
        follow = service.dispatch("jobs.get", {"id": followup["id"]})
        if follow["status"] not in {"running", "needs_approval"}:
            break
        time.sleep(0.05)
    assert follow["status"] == "completed", follow
    if protocol == "uhp":
        assert received[-1][2]["previous_response_id"] == "response1"
    else:
        assert received[-1][2]["params"]["message"]["contextId"] == "context1"
    service.remote_connections.clear()
    with pytest.raises(ValueError, match="Reconnect"):
        service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": route["id"],
                "prompt": "again",
                "command_id": "missing",
            },
        )


def test_acp_model_attachment_uses_catalog_credentials_and_provider_limits(desktop):
    from superqode.desktop_service.connect_workflow import attachment_route, attachment_environment

    _, _, root = desktop
    route = attachment_route(root, "qwen-code-key")
    assert route["subscription_vendor"] is None
    assert route["byok_providers"] == ("alibaba",)
    with pytest.raises(ValueError, match="does not declare support"):
        attachment_environment(route, "openai", {"openai": "wrong-provider-key"})
    env = attachment_environment(route, "alibaba", {"alibaba": "fixture-model-key"})
    assert env["QWEN_API_KEY"] == "fixture-model-key"
    assert env["DASHSCOPE_API_KEY"] == "fixture-model-key"
    assert "fixture-model-key" not in json.dumps(route)


def test_runtime_routes_remain_discoverable_without_saved_tokens(desktop):
    service, project, _ = desktop
    routes = service.dispatch("routes.list", {"project": project["id"]})
    assert any(r["id"] == "connection:codex" for r in routes)
    assert any(r["id"] == "connection:copilot" for r in routes)
    assert any(r["id"] == "attach:opencode-key" for r in routes)


def test_native_harness_builder_validates_and_never_overwrites(desktop, tmp_path):
    service, project, root = desktop
    draft = service.dispatch("connect.harness.draft", {"project": project["id"], "harness": "core"})
    saved = service.dispatch(
        "connect.harness.save",
        {"project": project["id"], "name": "my-native-harness", "yaml": draft["yaml"]},
    )
    assert Path(saved["path"]).is_relative_to(root)
    rows = service.dispatch("harnesses.list", {"project": project["id"]})
    assert any(row["id"] == "my-native-harness" for row in rows)
    for name, text in [
        ("../escape", draft["yaml"]),
        ("my-native-harness", draft["yaml"]),
        ("broken", "not-a-field: true"),
        ("inherits-secret", "inherits: /tmp/secret.yaml"),
    ]:
        with pytest.raises(ValueError):
            service.dispatch(
                "connect.harness.save", {"project": project["id"], "name": name, "yaml": text}
            )
    outside = tmp_path / "outside"
    outside.mkdir()
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    (other_project / ".superqode").symlink_to(outside, target_is_directory=True)
    other = service.open_project(str(other_project))
    with pytest.raises(ValueError, match="outside"):
        service.dispatch(
            "connect.harness.save",
            {"project": other["id"], "name": "escaping", "yaml": draft["yaml"]},
        )
    assert not list(outside.iterdir())


@pytest.mark.parametrize("allow", [True, False])
def test_subscription_cli_real_worker_and_native_approval(desktop, monkeypatch, tmp_path, allow):
    import sys
    from test_runtime_codex_cli import SERVER

    service, project, _ = desktop
    trace = tmp_path / "subscription-trace.json"
    executable = tmp_path / "fixture vendor agent"
    script = "#!" + sys.executable + "\nimport sys, os, json\n"
    script += "if 'generate-json-schema' in sys.argv: sys.exit(1)\n"
    script += "if '--version' in sys.argv: print('codex 0.160.0'); sys.exit(0)\n"
    # Store only a boolean presence check, never the environment credential itself.
    script += "assert 'OPENAI_API_KEY' not in os.environ\n"
    body = SERVER.replace(
        'assert msg["result"]["decision"] in ("accept", "decline")',
        'assert msg["result"]["decision"] in ("accept", "decline")\n            open('
        + repr(str(trace))
        + ', "w").write(json.dumps(msg["result"]))',
    )
    executable.write_text(script + body)
    executable.chmod(0o700)
    monkeypatch.setenv("SUPERQODE_CODEX_BIN", str(executable))
    monkeypatch.delenv("SUPERQODE_CODEX_SERVER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key-must-not-reach-subscription")
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": "connection:codex",
            "model": "",
            "prompt": "approval",
            "command_id": "subscription-" + str(allow),
            "_desktop_connection": {"kind": "invented"},
        },
    )
    approved = False
    for _ in range(300):
        record = service.dispatch("jobs.get", {"id": job["id"]})
        if record["status"] == "needs_approval" and not approved:
            permission = next(e for e in reversed(record["events"]) if e["type"] == "approval")
            service.dispatch(
                "jobs.approve",
                {"id": job["id"], "request_id": permission["data"]["request_id"], "allow": allow},
            )
            approved = True
        if record["status"] not in {"running", "needs_approval"}:
            break
        time.sleep(0.05)
    assert record["status"] == "completed", record
    assert approved
    assert json.loads(trace.read_text())["decision"] == ("accept" if allow else "decline")
    assert record["request"]["_desktop_connection"]["runtime"] == "codex-cli"
    assert record["request"]["provider"] == "agent"
    assert "fixture-key-must-not-reach-subscription" not in json.dumps(record)
    assert record["result"]["vendor_continuity"] is True
    followup = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": "connection:codex",
            "model": "",
            "prompt": "continue",
            "parent_id": job["id"],
        },
    )
    for _ in range(200):
        resumed = service.dispatch("jobs.get", {"id": followup["id"]})
        if resumed["status"] not in {"running", "needs_approval"}:
            break
        time.sleep(0.05)
    assert resumed["status"] == "completed", resumed
    assert resumed["result"]["session_id"] == record["result"]["session_id"]
