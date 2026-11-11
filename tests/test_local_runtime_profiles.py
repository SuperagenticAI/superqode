"""Real desktop workers use selected local profiles without persisting keys."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import local_runtimes


@pytest.fixture
def server():
    requests = []
    token = "private-local-runtime-key"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def auth(self):
            if self.headers.get("Authorization") != "Bearer " + token:
                self.send_response(401)
                self.end_headers()
                return False
            return True

        def do_GET(self):
            if not self.auth():
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"data": [{"id": "fixture", "max_model_len": 8192}]}).encode()
            )

        def do_POST(self):
            if not self.auth():
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"body": body, "authorization": self.headers.get("Authorization")})
            names = {t["function"]["name"] for t in body.get("tools", [])}
            message = {"content": "Hello local model"}
            reason = "stop"
            if "read_probe" in names:
                message = {
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "type": "function",
                            "function": {
                                "name": "read_probe",
                                "arguments": '{"path":"generated-fixture.txt"}',
                            },
                        }
                    ]
                }
                reason = "tool_calls"
            elif names.intersection({"read_file", "read"}) and not any(
                m.get("role") == "tool" for m in body["messages"]
            ):
                read_name = "read_file" if "read_file" in names else "read"
                schema = next(
                    t["function"]["parameters"]
                    for t in body["tools"]
                    if t["function"]["name"] == read_name
                )
                field = "path" if "path" in schema.get("properties", {}) else "file_path"
                message = {
                    "tool_calls": [
                        {
                            "id": "project-read",
                            "type": "function",
                            "function": {
                                "name": read_name,
                                "arguments": json.dumps({field: "README.md"}),
                            },
                        }
                    ]
                }
                reason = "tool_calls"
            payload = {
                "choices": [{"message": message, "finish_reason": reason}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

    runtime = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "url": f"http://127.0.0.1:{runtime.server_port}/v1",
            "requests": requests,
            "key": token,
        }
    finally:
        runtime.shutdown()
        runtime.server_close()
        thread.join(timeout=2)


def save(service, server):
    profile = service.dispatch(
        "local.runtimes.save",
        {
            "id": "my-local",
            "name": "My local server",
            "endpoint": server["url"],
            "context": 4096,
            "remember_key": True,
        },
    )
    service.dispatch("local.runtimes.key", {"id": profile["id"], "key": server["key"]})
    return profile


def wait(service, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = service.dispatch("jobs.get", {"id": identity})
        if result["status"] not in {"running", "queued", "needs_approval", "cancelling"}:
            return result
        time.sleep(0.03)
    pytest.fail("Local worker did not finish")


def test_saved_runtime_probe_chat_and_check_use_the_selected_key(desktop, server, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(service.root))
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-cloud-key")
    monkeypatch.setenv("LOCAL_RUNTIME_API_KEY", "unrelated-shell-key")
    save(service, server)
    models = service.dispatch("local.runtimes.probe", {"id": "my-local"})
    assert models["models"][0]["id"] == "fixture"
    assert not server["requests"], "Discovery must not generate or send project data"
    with pytest.raises(ValueError, match="tool check"):
        service.dispatch(
            "local.runtimes.use",
            {"id": "my-local", "project": project["id"], "model": "fixture", "harness": "core"},
        )
    check = service.dispatch(
        "local.runtimes.test", {"id": "my-local", "project": project["id"], "model": "fixture"}
    )
    completed = wait(service, check["id"])
    assert completed["status"] == "completed", completed
    assert completed["result"]["verification"]["tool_call_success"] is True
    assert not (root / "generated-fixture.txt").exists()
    profile = local_runtimes.read(service, "my-local")
    assert local_runtimes.checked(profile, "fixture")
    before = profile["credential_revision"]
    service.dispatch(
        "local.runtimes.key", {"id": "my-local", "key": server["key"], "restore": True}
    )
    assert local_runtimes.read(service, "my-local")["credential_revision"] == before
    service.dispatch(
        "local.runtimes.use",
        {"id": "my-local", "project": project["id"], "model": "fixture", "harness": "no-tool"},
    )
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": "no-tool",
            "provider": "local-openai",
            "model": "fixture",
            "prompt": "Hello",
            "interaction_mode": "chat",
        },
    )
    result = wait(service, job["id"])
    assert result["status"] == "completed", result
    assert "Hello local model" in json.dumps(result["result"])
    assert len(server["requests"]) == 2
    assert all(row["authorization"] == "Bearer " + server["key"] for row in server["requests"])
    persisted = "\n".join(service.db.iterdump())
    assert server["key"] not in persisted
    assert "unrelated-cloud-key" not in persisted and "unrelated-shell-key" not in persisted


def test_profile_and_key_changes_invalidate_tools_and_old_bindings(desktop, server):
    service, project, _ = desktop
    profile = save(service, server)
    current = local_runtimes.read(service, profile["id"])
    current["checks"] = {
        "fixture": {"tool_call_success": True, "digest": local_runtimes.validation_digest(current)}
    }
    local_runtimes.save(service, current)
    service.dispatch(
        "local.runtimes.use",
        {"id": "my-local", "project": project["id"], "model": "fixture", "harness": "no-tool"},
    )
    service.dispatch("local.runtimes.save", {**profile, "context": 8192})
    assert not local_runtimes.checked(local_runtimes.read(service, "my-local"), "fixture")
    with pytest.raises(ValueError, match="configuration changed"):
        local_runtimes.environment(service, project["id"], "no-tool", "fixture")
    assert not server["requests"]


def test_a_key_is_not_inherited_for_another_keyless_profile(desktop, server, monkeypatch):
    service, project, _ = desktop
    save(service, server)
    spec = service.dispatch("local.runtimes.save", {"id": "keyless", "endpoint": server["url"]})
    service._write(
        "INSERT INTO local_runtime_bindings VALUES(?,?,?,?,?)",
        (
            project["id"],
            "no-tool",
            "fixture",
            spec["id"],
            local_runtimes.digest(local_runtimes.runtimes.validate(spec)),
        ),
    )
    monkeypatch.setenv("LOCAL_RUNTIME_API_KEY", "unrelated-key")
    env = local_runtimes.environment(service, project["id"], "no-tool", "fixture")
    assert env["LOCAL_RUNTIME_API_KEY"] == ""
    assert "private-local-runtime-key" not in json.dumps(env)


def test_core_executes_a_real_read_tool_through_the_external_runtime(desktop, server):
    service, project, root = desktop
    (root / "README.md").write_text("LOCAL_READ_SENTINEL")
    profile = save(service, server)
    check = service.dispatch(
        "local.runtimes.test", {"id": profile["id"], "project": project["id"], "model": "fixture"}
    )
    assert wait(service, check["id"])["status"] == "completed"
    service.dispatch(
        "local.runtimes.use",
        {"id": profile["id"], "project": project["id"], "model": "fixture", "harness": "core"},
    )
    job = service.dispatch(
        "tasks.start",
        {
            "project": project["id"],
            "harness": "core",
            "provider": "local-openai",
            "model": "fixture",
            "prompt": "Read README.md and summarize it",
        },
    )
    result = wait(service, job["id"])
    assert result["status"] == "completed", result
    assert any(
        "LOCAL_READ_SENTINEL" in json.dumps(row["body"]["messages"]) for row in server["requests"]
    ), [[t["function"]["name"] for t in row["body"].get("tools", [])] for row in server["requests"]]
    assert any(row["body"].get("tools") for row in server["requests"][1:])
