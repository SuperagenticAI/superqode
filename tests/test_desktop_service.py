"""Desktop boundary and durable job tests, without external model calls."""

import json
import hashlib
from pathlib import Path
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from superqode.desktop_service.service import DesktopService


@pytest.fixture
def desktop(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "hello.txt").write_text("hello")
    subprocess.run(["git", "-C", str(root), "add", "hello.txt"], check=True)
    service = DesktopService(tmp_path / "state")
    project = service.open_project(str(root))
    yield service, project, root
    service.close()


def wait_job(service, job_id):
    for _ in range(200):
        job = service.dispatch("jobs.get", {"id": job_id})
        if job["status"] not in {"running", "needs_approval"}:
            return job
        time.sleep(0.05)
    pytest.fail("Job did not finish")


def test_scoped_file_reads_reject_escape_and_symlink(desktop, tmp_path):
    service, project, root = desktop
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "escape").symlink_to(outside)
    for name in ("../secret.txt", "escape"):
        with pytest.raises(ValueError, match="outside"):
            service.dispatch("files.read", {"project": project["id"], "path": name})
    (root / ".env").write_text("API_KEY=secret")
    with pytest.raises(ValueError, match="Sensitive"):
        service.dispatch("files.read", {"project": project["id"], "path": ".env"})


def test_approval_cannot_be_reused_or_invented(desktop):
    service, _, _ = desktop
    with pytest.raises(ValueError, match="stale"):
        service.dispatch("jobs.approve", {"id": "missing", "request_id": "invented", "allow": True})


def test_suite_setup_records_skipped_cases_without_model_calls(desktop):
    service, project, _ = desktop
    job = service.dispatch(
        "evaluations.start",
        {
            "project": project["id"],
            "harness": "core",
            "tasks": "decision-routing",
            "provider": "ollama",
            "model": "not-installed",
            "live": False,
            "command_id": "one",
        },
    )
    result = wait_job(service, job["id"])
    assert result["result"]["live"] is False
    assert result["result"]["variants"][0]["skipped"] == 6
    assert all(t["status"] == "skipped" for t in result["result"]["variants"][0]["tasks"])
    # Retrying a durable command does not create a second experiment.
    retry = service.dispatch(
        "evaluations.start",
        {
            "project": project["id"],
            "harness": "core",
            "tasks": "decision-routing",
            "live": False,
            "command_id": "one",
        },
    )
    assert retry["id"] == job["id"]


def test_run_recovery_never_reexecutes_work(tmp_path):
    service = DesktopService(tmp_path)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("run", "project", "task", "task", "running", "{}", None, 1, 1),
    )
    service.db.close()
    restarted = DesktopService(tmp_path)
    assert restarted.dispatch("jobs.list", {})[0]["status"] == "interrupted"
    assert not restarted.processes
    restarted.db.close()


def test_check_records_actual_exit_status(desktop):
    service, project, _ = desktop
    job = service.dispatch("checks.start", {"project": project["id"], "command": "exit 7"})
    result = wait_job(service, job["id"])
    assert result["status"] == "failed"
    assert result["result"]["exit_code"] == 7


def test_catalog_uses_real_backend_and_no_remote_discovery(desktop):
    service, project, _ = desktop
    catalog = service.dispatch("hub.list", {"project": project["id"]})
    assert catalog["count"] > 10
    assert any(row["id"] == "core" for row in catalog["items"])
    assert "api_key" not in json.dumps(service.dispatch("capabilities", {}))


def test_duplicate_active_command_is_not_executed_twice(desktop):
    service, project, _ = desktop
    command = {"project": project["id"], "command": "sleep 20", "command_id": "same-command"}
    first = service.dispatch("checks.start", command)
    second = service.dispatch("checks.start", command)
    assert first == second
    assert len(service.processes) == 1
    service.dispatch("jobs.cancel", first)
    assert service.dispatch("jobs.get", first)["status"] == "cancelled"


def test_changed_candidate_cannot_pass_a_stale_adoption_gate(desktop):
    service, project, root = desktop
    from superqode.harness.templates import no_tool_template
    from superqode.harness.loader import harness_spec_to_dict
    import yaml

    folder = service.root / "runs" / "test-candidate"
    folder.mkdir(parents=True)
    text = yaml.safe_dump(harness_spec_to_dict(no_tool_template()))
    baseline = folder / "baseline.yaml"
    staged = folder / "candidate.yaml"
    baseline.write_text(text)
    staged.write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    result = {
        "accepted": True,
        "baseline_spec_path": str(baseline),
        "staged_spec_path": str(staged),
        "staged_sha256": digest,
    }
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "candidate123456",
            project["id"],
            "optimization",
            "candidate",
            "completed",
            "{}",
            json.dumps(result),
            1,
            1,
        ),
    )
    staged.write_text(text + "\n# changed after validation\n")
    with pytest.raises(ValueError, match="changed"):
        service.dispatch("harnesses.save_candidate", {"id": "candidate123456", "digest": digest})
    staged.write_text(text)
    saved = service.dispatch(
        "harnesses.save_candidate", {"id": "candidate123456", "digest": digest}
    )
    assert Path(saved["path"]).is_relative_to(root)
    assert Path(saved["path"]).read_text() == text
    assert baseline.read_text() == text


def test_unborn_git_repository_has_an_inspectable_diff(desktop):
    service, project, _ = desktop
    status = service.dispatch("git.status", {"project": project["id"]})
    assert "hello.txt" in status["diff"]


@pytest.mark.parametrize("interaction", ["code", "chat"])
def test_actual_harness_stream_and_native_followup(desktop, monkeypatch, interaction):
    """Exercise the real harness stack against an explicitly local model fixture."""
    requests = []
    authorizations = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            authorizations.append(self.headers.get("Authorization"))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (
                    {
                        "id": "fixture",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "gpt-4o-mini",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": "desktop-fixture-response",
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "fixture",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "gpt-4o-mini",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                payload = {
                    "id": "fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "desktop-fixture-response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OPENAI_API_BASE", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "local-desktop-fixture")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    service, project, root = desktop
    import base64

    image = root / "reference.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aU1QAAAAASUVORK5CYII="
        )
    )
    staged_image = service.dispatch("images.stage", {"path": str(image)})
    config = {
        "project": project["id"],
        "harness": "no-tool",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "prompt": "Reply with the fixture response",
        "image_ids": [staged_image["id"]],
        "interaction_mode": interaction,
    }
    (root / "AGENTS.md").write_text("PRIVATE_PROJECT_INSTRUCTION_MUST_NOT_REACH_DIRECT_CHAT")
    ephemeral_key = "desktop-keychain-fixture-secret"
    service.dispatch("providers.credentials.set", {"provider": "openai", "key": ephemeral_key})
    try:
        first = service.dispatch("tasks.start", config)
        result = wait_job(service, first["id"])
        assert result["status"] == "completed", result
        assert any("desktop-fixture-response" in json.dumps(e) for e in result["events"])
        assert authorizations[-1] == "Bearer " + ephemeral_key
        if interaction == "chat":
            assert "PRIVATE_PROJECT_INSTRUCTION_MUST_NOT_REACH_DIRECT_CHAT" not in json.dumps(
                requests
            )
            assert not requests[-1].get("tools")
            assert all(message["role"] != "system" for message in requests[-1]["messages"])

        assert any(
            part.get("type") == "image_url"
            for message in requests[-1]["messages"]
            if isinstance(message.get("content"), list)
            for part in message["content"]
        )
        assert ephemeral_key not in json.dumps(result)
        service.dispatch("providers.credentials.set", {"provider": "openai", "key": None})
        second = service.dispatch(
            "tasks.start",
            {**config, "parent_id": first["id"], "prompt": "What did you just reply?"},
        )
        followup = wait_job(service, second["id"])
        assert followup["status"] == "completed", followup
        assert followup["result"]["session_id"] == result["result"]["session_id"]
        assert authorizations[-1] == "Bearer local-desktop-fixture"
        if interaction == "code":
            compact = service.dispatch(
                "context.compact",
                {
                    "project": project["id"],
                    "source_job": second["id"],
                    "instructions": "Keep the coding decisions",
                },
            )
            compacted = wait_job(service, compact["id"])
            assert compacted["status"] == "completed", compacted
            assert compacted["result"]["success"] is True
            assert compacted["result"]["source_job"] == second["id"]

        for artifact in service.root.rglob("*"):
            if artifact.is_file():
                assert ephemeral_key.encode() not in artifact.read_bytes(), artifact
        assert any(
            "desktop-fixture-response" in json.dumps(message)
            for message in requests[-1]["messages"]
        )
    finally:
        server.shutdown()
        server.server_close()


def test_desktop_credentials_are_ephemeral_and_metadata_is_redacted(desktop, monkeypatch):
    from superqode.desktop_service import connections

    monkeypatch.setattr(connections, "provider_api_key", lambda _: None)
    service, _, _ = desktop
    value = "private-native-desktop-test-key"
    service.dispatch("providers.credentials.set", {"provider": "openai", "key": value})
    rows = service.dispatch("providers.list", {})
    row = next(row for row in rows if row["id"] == "openai")
    assert row["credential_configured"] is True
    assert row["verified"] is False
    assert value not in json.dumps(rows)
    assert value not in json.dumps(service.dispatch("settings.get", {}))
    assert value not in json.dumps(service.dispatch("jobs.list", {}))
    status = service.dispatch("providers.check", {"provider": "openai", "model": "example"})
    assert status["state"] == "needs-test"
    assert status["ready"] is None
    service.dispatch("providers.credentials.set", {"provider": "openai", "key": None})
    assert "openai" not in service.credentials
    assert (
        service.dispatch("providers.check", {"provider": "openai", "model": "example"})["state"]
        == "missing-credential"
    )
    with pytest.raises(ValueError):
        service.dispatch("providers.credentials.set", {"provider": "not-a-provider", "key": value})
    with pytest.raises(ValueError, match="control characters"):
        service.dispatch(
            "providers.credentials.set", {"provider": "openai", "key": value + "\nINJECTED=value"}
        )
    assert not service.credentials


def test_local_readiness_rejects_embedding_models_and_missing_weights(desktop, monkeypatch):
    from superqode.local.inventory import LocalModel

    monkeypatch.setattr(
        "superqode.local.inventory.list_ollama_models",
        lambda: [LocalModel("ollama:local-coder", "ollama")],
    )
    service, _, _ = desktop
    assert (
        service.dispatch("providers.check", {"provider": "ollama", "model": "local-coder"})["ready"]
        is True
    )
    assert (
        service.dispatch("providers.check", {"provider": "ollama", "model": "not-installed"})[
            "ready"
        ]
        is False
    )
    assert (
        service.dispatch("providers.check", {"provider": "ollama", "model": "embed-model"})["state"]
        == "unsupported"
    )
    assert (
        service.dispatch("providers.check", {"provider": "ollama", "model": ""})["state"]
        == "incomplete"
    )


def test_app_key_echo_is_redacted_from_worker_events_and_diagnostics(desktop):
    service, project, _ = desktop
    secret = "private-desktop-fixture-credential"
    service.dispatch("providers.credentials.set", {"provider": "openai", "key": secret})
    started = service.dispatch(
        "checks.start",
        {
            "project": project["id"],
            "command": 'printf "%s\\n" "$OPENAI_API_KEY"; printf "%s\\n" "$OPENAI_API_KEY" >&2',
        },
    )
    result = wait_job(service, started["id"])
    assert result["status"] == "completed"
    assert "[REDACTED]" in json.dumps(result["events"])
    assert secret not in json.dumps(result)
    log = (service.root / (started["id"] + ".log")).read_text()
    assert secret not in log
    artifact = json.loads((service.root / "runs" / started["id"] / "result.json").read_text())
    assert secret not in json.dumps(artifact)
    assert "[REDACTED]" in artifact["output"]


def test_worker_stderr_is_redacted_before_diagnostic_file_write(tmp_path):
    import os
    import sys
    from superqode.desktop_service.service import record_stderr

    secret = "private-stderr-fixture-key"
    process = subprocess.Popen(
        [sys.executable, "-c", "import os,sys;sys.stderr.write(os.environ['FIXTURE_KEY'])"],
        env={**os.environ, "FIXTURE_KEY": secret},
        stderr=subprocess.PIPE,
        text=True,
    )
    output = tmp_path / "diagnostics.log"
    record_stderr(process.stderr, output, (secret,))
    assert process.wait() == 0
    assert output.read_text() == "[REDACTED]"


@pytest.fixture
def desktop_acp_route(desktop, monkeypatch):
    import shlex
    import sys

    route = {
        "id": "acp:desktop-fixture",
        "reference": "acp:desktop-fixture",
        "name": "Desktop ACP fixture",
        "command": shlex.join(
            [sys.executable, str(Path(__file__).parent / "fixtures/desktop_acp_agent.py")]
        ),
        "digest": "fixture-digest",
        "runtime": "ACP",
        "desktop_kind": "acp",
        "available": True,
        "auth": "agent-managed",
    }
    monkeypatch.setattr(
        "superqode.desktop_service.service.resolve_acp_route", lambda root, reference: dict(route)
    )
    return desktop, route


def drive_acp(service, job_id, allow=True, scope="once"):
    for _ in range(200):
        job = service.dispatch("jobs.get", {"id": job_id})
        if job["status"] == "needs_approval":
            request = next(
                event["data"] for event in reversed(job["events"]) if event["type"] == "approval"
            )
            service.dispatch(
                "jobs.approve",
                {"id": job_id, "request_id": request["request_id"], "allow": allow, "scope": scope},
            )
        elif job["status"] not in {"running", "queued"}:
            return job
        time.sleep(0.05)
    pytest.fail("ACP job did not complete")


def test_desktop_acp_edits_code_with_native_permission_and_exact_resume(desktop_acp_route):
    (service, project, root), route = desktop_acp_route
    request = {
        "project": project["id"],
        "harness": route["id"],
        "prompt": "write code",
        "provider": "agent",
        "model": "",
    }
    first = service.dispatch("tasks.start", request)
    result = drive_acp(service, first["id"])
    assert result["status"] == "completed", result
    assert (root / "main.py").read_text() == "print('Hello from desktop ACP')\n"
    assert result["result"]["protocol"] == "ACP"
    assert result["result"]["acp_continuity"] is True
    assert any(event["type"] == "approval" for event in result["events"])
    assert "Updated main.py" in json.dumps(result["events"])
    followup = service.dispatch("tasks.start", {**request, "parent_id": first["id"]})
    resumed = drive_acp(service, followup["id"])
    assert resumed["status"] == "completed", resumed
    assert resumed["result"]["session_id"] == result["result"]["session_id"]
    assert "Resumed ACP session" in json.dumps(resumed["events"])


def test_desktop_acp_denial_and_path_scope(desktop_acp_route, tmp_path):
    (service, project, root), route = desktop_acp_route
    request = {"project": project["id"], "harness": route["id"], "prompt": "write code"}
    denied = drive_acp(service, service.dispatch("tasks.start", request)["id"], allow=False)
    assert denied["status"] == "completed", denied
    assert not (root / "main.py").exists()
    assert "Write denied" in json.dumps(denied["events"])
    escaped = drive_acp(
        service, service.dispatch("tasks.start", {**request, "prompt": "escape"})["id"]
    )
    assert escaped["status"] == "completed", escaped
    assert not (root.parent / "outside.txt").exists()
    assert "Scope blocked" in json.dumps(escaped["events"])
    permanent = drive_acp(
        service, service.dispatch("tasks.start", {**request, "prompt": "permission"})["id"]
    )
    assert permanent["status"] == "completed", permanent
    assert "Permission refused" in json.dumps(permanent["events"])


def test_native_file_edit_guards_revision_and_preserves_executable_mode(desktop):
    service, project, root = desktop
    target = root / "hello.txt"
    target.chmod(0o755)
    opened = service.dispatch("files.read", {"project": project["id"], "path": "hello.txt"})
    saved = service.dispatch(
        "files.write",
        {
            "project": project["id"],
            "path": "hello.txt",
            "digest": opened["digest"],
            "text": "edited in native app\n",
        },
    )
    assert target.read_text() == "edited in native app\n"
    assert target.stat().st_mode & 0o777 == 0o755
    assert saved["digest"] != opened["digest"]
    with pytest.raises(ValueError, match="changed on disk"):
        service.dispatch(
            "files.write",
            {
                "project": project["id"],
                "path": "hello.txt",
                "digest": opened["digest"],
                "text": "stale overwrite",
            },
        )
    assert target.read_text() == "edited in native app\n"
    job = service.dispatch("checks.start", {"project": project["id"], "command": "sleep 20"})
    try:
        with pytest.raises(ValueError, match="active project run"):
            service.dispatch(
                "files.write",
                {
                    "project": project["id"],
                    "path": "hello.txt",
                    "digest": saved["digest"],
                    "text": "racing edit",
                },
            )
    finally:
        service.dispatch("jobs.cancel", job)


def test_new_code_files_are_visible_and_can_be_staged_without_staging_secrets(desktop):
    service, project, root = desktop
    (root / "new-code.py").write_text("print('new code')\n")
    (root / "新しい-code.py").write_text("print('unicode path')\n")
    (root / ".env").write_text("SECRET=not-for-git")
    assert "new-code.py" in service.dispatch("files.list", {"project": project["id"]})
    assert "新しい-code.py" in service.dispatch("files.list", {"project": project["id"]})
    service.dispatch("git.stage_file", {"project": project["id"], "path": "new-code.py"})
    diff = service.dispatch("git.status", {"project": project["id"]})["diff"]
    assert "new-code.py" in diff
    with pytest.raises(ValueError, match="Sensitive"):
        service.dispatch("git.stage_file", {"project": project["id"], "path": ".env"})
    staged = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--cached", "--name-only"], text=True
    )
    assert ".env" not in staged


def test_desktop_acp_terminal_uses_exact_arguments_and_native_approval(desktop_acp_route):
    (service, project, _), route = desktop_acp_route
    job = service.dispatch(
        "tasks.start", {"project": project["id"], "harness": route["id"], "prompt": "terminal"}
    )
    result = drive_acp(service, job["id"])
    assert result["status"] == "completed", result
    assert "ACP terminal with spaces" in json.dumps(result["events"])
    assert any(
        event["type"] == "approval" and event["data"]["tool"]["title"] == "Run command"
        for event in result["events"]
    )


def test_acp_uses_agent_auth_instead_of_app_managed_api_keys(desktop_acp_route, monkeypatch):
    (service, project, _), route = desktop_acp_route
    monkeypatch.setenv("OPENAI_API_KEY", "existing-agent-fixture-key")
    service.dispatch(
        "providers.credentials.set",
        {"provider": "openai", "key": "private-app-key-must-not-reach-agent"},
    )
    result = drive_acp(
        service,
        service.dispatch(
            "tasks.start",
            {"project": project["id"], "harness": route["id"], "prompt": "environment"},
        )["id"],
    )
    assert result["status"] == "completed", result
    assert "Agent auth preserved" in json.dumps(result["events"])


def test_acp_catalog_package_launchers_cannot_enable_implicit_installation(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import shlex
    from superqode.desktop_service.routes import acp_routes

    items = [
        SimpleNamespace(
            id="acp:npx-test",
            kind="acp",
            target={"run_command": {"*": "npx --yes sample-agent"}},
            available=True,
            display_name="NPX fixture",
            description="fixture",
            issue="",
        ),
        SimpleNamespace(
            id="acp:uvx-test",
            kind="acp",
            target={"run_command": {"*": "uvx --online sample-agent"}},
            available=True,
            display_name="UVX fixture",
            description="fixture",
            issue="",
        ),
    ]
    monkeypatch.setattr("superqode.app.harness_picker.harness_picker_items", lambda *a, **kw: items)
    monkeypatch.setattr(
        "superqode.desktop_service.routes.shutil.which", lambda command: "/fixture/" + command
    )
    rows = acp_routes(tmp_path)
    assert "--no-install" in shlex.split(rows[0]["command"])
    assert "--yes" not in shlex.split(rows[0]["command"])
    assert "--offline" in shlex.split(rows[1]["command"])
    assert "--online" not in shlex.split(rows[1]["command"])


def test_large_permission_request_retains_actionable_approval_token(desktop):
    service, project, _ = desktop
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("large-approval", project["id"], "task", "large edit", "needs_approval", "{}", None, 1, 1),
    )
    service.append(
        "large-approval",
        {
            "type": "approval",
            "data": {
                "request_id": "bound-permission-token",
                "tool": {
                    "title": "Write a large source file",
                    "content": "generated code\n" * 10000,
                },
            },
        },
    )
    event = service.dispatch("jobs.get", {"id": "large-approval"})["events"][0]
    assert event["type"] == "approval"
    assert event["data"]["request_id"] == "bound-permission-token"
    assert event["data"]["preview_truncated"] is True
    assert len(json.dumps(event)) < 64_000


def test_acp_native_controls_apply_to_exact_resumed_session(desktop_acp_route):
    (service, project, _), route = desktop_acp_route
    request = {
        "project": project["id"],
        "harness": route["id"],
        "prompt": "controls",
        "command_id": "controls-first",
        "acp_options": {"model": "model-b", "mode": "plan", "config": {"effort": "high"}},
    }
    first = drive_acp(service, service.dispatch("tasks.start", request)["id"])
    assert first["status"] == "completed", first
    output = json.dumps(first["events"])
    assert "model-b" in output and "high" in output
    resumed = drive_acp(
        service,
        service.dispatch(
            "tasks.start",
            {
                **request,
                "parent_id": first["id"],
                "command_id": "controls-resume",
                "acp_options": {"mode": "code"},
            },
        )["id"],
    )
    assert resumed["status"] == "completed", resumed
    assert "Resumed ACP session" in json.dumps(resumed["events"])


def test_native_file_creation_and_unstage_never_overwrite(desktop, tmp_path):
    service, project, root = desktop
    params = {"project": project["id"], "path": "Sources/New.swift"}
    created = service.dispatch("files.create", {**params, "text": "let value = 1\n"})
    assert created["path"] == "Sources/New.swift"
    with pytest.raises(FileExistsError):
        service.dispatch("files.create", {**params, "text": "overwrite"})
    assert (root / params["path"]).read_text() == "let value = 1\n"
    for name in ("../escape.swift", ".git/config", ".env.local", "/tmp/escape.swift"):
        with pytest.raises(ValueError):
            service.dispatch("files.create", {**params, "path": name})
    (root / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        service.dispatch("files.create", {**params, "path": "escape/out.swift"})
    service.dispatch("git.stage_file", params)
    assert "A  Sources/New.swift" in service.dispatch("git.status", params)["status"]
    service.dispatch("git.unstage_file", params)
    assert (root / params["path"]).exists()
    assert "Sources/New.swift" not in subprocess.check_output(
        ["git", "-C", str(root), "ls-files"], text=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    service.dispatch("git.stage_file", params)
    service.dispatch("git.unstage_file", params)
    assert (root / params["path"]).exists()


def test_acp_always_requires_explicit_scope(desktop_acp_route):
    (service, project, _), route = desktop_acp_route
    job = service.dispatch(
        "tasks.start", {"project": project["id"], "harness": route["id"], "prompt": "permission"}
    )
    result = drive_acp(service, job["id"], scope="always")
    assert result["status"] == "completed", result
    assert "Always permission granted" in json.dumps(result["events"])
    assert "unsafe-always" in json.dumps(result["events"])


def _history_row(service, project, identity, parent=None, *, kind="task", updated=1):
    request = {"parent_id": parent, "private_request_field": "not-summary-data"}
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            identity,
            project,
            kind,
            f"Title {identity}",
            "completed",
            json.dumps(request),
            "{}",
            updated,
            updated,
        ),
    )


def test_recent_metadata_keeps_original_conversation_title(desktop):
    service, project, _ = desktop
    for identity, parent, updated in [
        ("root", None, 1),
        ("second", "root", 2),
        ("third", "second", 3),
    ]:
        _history_row(service, project["id"], identity, parent, updated=updated)
    rows = service.dispatch("jobs.list", {})
    assert [row["id"] for row in rows] == ["third", "second", "root"]
    assert {row["conversation_id"] for row in rows} == {"root"}
    assert {row["conversation_title"] for row in rows} == {"Title root"}
    assert "private_request_field" not in json.dumps(rows)
    assert "request" not in rows[0]


def test_recent_metadata_resolves_parent_outside_recent_window(desktop):
    service, project, _ = desktop
    _history_row(service, project["id"], "old-root", updated=0)
    for index in range(101):
        _history_row(service, project["id"], f"other-{index}", updated=index + 1)
    _history_row(service, project["id"], "follow-up", "old-root", updated=200)
    rows = service.dispatch("jobs.list", {})
    assert len(rows) == 100
    assert rows[0]["id"] == "follow-up"
    assert rows[0]["conversation_id"] == "old-root"
    assert rows[0]["conversation_title"] == "Title old-root"


def test_recent_metadata_does_not_merge_foreign_or_missing_parents(desktop):
    service, project, _ = desktop
    _history_row(service, "other-project", "foreign")
    _history_row(service, project["id"], "local", "foreign", updated=2)
    _history_row(service, project["id"], "orphan", "deleted", updated=3)
    rows = {row["id"]: row for row in service.dispatch("jobs.list", {})}
    assert rows["local"]["conversation_id"] == "local"
    assert rows["orphan"]["conversation_id"] == "orphan"


def test_recent_metadata_handles_cyclic_legacy_history(desktop):
    service, project, _ = desktop
    _history_row(service, project["id"], "cycle-a", "cycle-b", updated=1)
    _history_row(service, project["id"], "cycle-b", "cycle-a", updated=2)
    assert len(service.dispatch("jobs.list", {})) == 2


def test_recent_metadata_reuses_lineage_without_rereading_prompts(desktop, monkeypatch):
    service, project, _ = desktop
    _history_row(service, project["id"], "root", updated=1)
    _history_row(service, project["id"], "child", "root", updated=2)
    original = service._all
    reads = []

    def record(query, args=()):
        if "SELECT request" in query:
            reads.append(query)
        return original(query, args)

    monkeypatch.setattr(service, "_all", record)
    first = service.dispatch("jobs.list", {})
    assert reads
    reads.clear()
    assert service.dispatch("jobs.list", {}) == first
    assert not reads


def test_cross_agent_handoff_and_return_resume(desktop_acp_route, monkeypatch):
    """Two scripted ACP connections retain one app conversation and separate bindings."""
    from superqode.desktop_service.conversations import answer

    (service, project, _), route = desktop_acp_route
    monkeypatch.setattr(
        "superqode.desktop_service.service.resolve_acp_route",
        lambda root, reference: {**route, "id": reference, "digest": reference + "-digest"},
    )
    request = {
        "project": project["id"],
        "harness": "acp:first",
        "provider": "agent",
        "model": "",
        "prompt": "Original coding goal",
    }
    first = drive_acp(service, service.dispatch("tasks.start", request)["id"])
    assert first["status"] == "completed", first
    second = drive_acp(
        service,
        service.dispatch(
            "tasks.start",
            {
                **request,
                "harness": "acp:second",
                "parent_id": first["id"],
                "prompt": "Continue in second agent",
                "session_id": "forged",
                "expected_digest": "forged",
                "_handoff_context": "forged",
            },
        )["id"],
    )
    assert second["status"] == "completed", second
    assert "session_id" not in second["request"]
    assert "Original coding goal" in second["request"]["_handoff_context"]
    assert "Handoff received" in answer(service, second["id"])
    assert second["request"]["prompt"] == "Continue in second agent"
    third = drive_acp(
        service,
        service.dispatch(
            "tasks.start",
            {
                **request,
                "parent_id": second["id"],
                "prompt": "Return to first agent",
            },
        )["id"],
    )
    assert third["status"] == "completed", third
    assert third["request"]["session_id"] == first["result"]["session_id"]
    assert third["request"]["_continuity"]["resumed_from"] == first["id"]
    assert "Continue in second agent" in third["request"]["_handoff_context"]
    assert "Resumed ACP session" in answer(service, third["id"])
    transcript = service.dispatch("conversations.get", {"id": third["id"]})
    assert transcript["conversation_id"] == first["id"]
    assert [item["id"] for item in transcript["turns"]] == [first["id"], second["id"]]
    assert len({row["conversation_id"] for row in service.dispatch("jobs.list", {})}) == 1
    # Reopen the durable state without invoking any vendor account.
    from superqode.desktop_service.service import DesktopService

    reopened = DesktopService(service.root)
    try:
        assert reopened.dispatch("conversations.get", {"id": third["id"]}) == transcript
    finally:
        reopened.close()


def test_handoff_bounds_privacy_route_revision_and_failed_session(desktop):
    from superqode.desktop_service.conversations import prepare_continuation, with_handoff

    service, project, root = desktop

    def node(identity, parent, status="completed", digest="old"):
        request = {
            "harness": "acp:one",
            "provider": "agent",
            "model": "",
            "prompt": identity,
            "parent_id": parent,
        }
        result = {
            "session_id": identity + "-thread",
            "acp_continuity": True,
            "harness_digest": digest,
        }
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                identity,
                project["id"],
                "task",
                identity,
                status,
                json.dumps(request),
                json.dumps(result),
                1,
                1,
            ),
        )

    node("first", None)
    node("failed", "first", "failed")
    service.append(
        "first",
        {
            "type": "harness_event",
            "data": {"event": "thinking", "payload": {"text": "PRIVATE_REASONING"}},
        },
    )
    service.append("first", {"type": "approval", "data": {"request_id": "PRIVATE_APPROVAL"}})
    for i in range(520):
        service.append(
            "first",
            {
                "type": "harness_event",
                "data": {"event": "delta", "payload": {"text": str(i) + " "}},
            },
        )
    # A too-large visible answer is omitted whole, never sliced inside code.
    for _ in range(4):
        service.append(
            "failed",
            {
                "type": "harness_event",
                "data": {"event": "delta", "payload": {"text": "x" * 25_000}},
            },
        )
    params = {
        "harness": "acp:one",
        "provider": "agent",
        "model": "",
        "parent_id": "failed",
        "prompt": "CURRENT_REQUEST",
        "_desktop_route": {"digest": "old"},
    }
    prepare_continuation(service, params, project["id"], root)
    assert "session_id" not in params  # Failed session may have unknown side effects.
    assert len(params["_handoff_context"].encode()) < 50_000
    assert "519 " in params["_handoff_context"]  # Reads beyond the first 500 events.
    assert "PRIVATE_" not in params["_handoff_context"]
    assert json.loads(params["_handoff_context"])["metadata"]["omitted_messages"] == 1
    assert params["prompt"] == "CURRENT_REQUEST"
    assert with_handoff(params)["prompt"].endswith("CURRENT_REQUEST")
    revision = {**params, "parent_id": "first", "_desktop_route": {"digest": "new"}}
    prepare_continuation(service, revision, project["id"], root)
    assert "session_id" not in revision
    with pytest.raises(ValueError, match="project"):
        prepare_continuation(service, dict(params), "another-project", root)
    node("busy", "first", "running")
    with pytest.raises(ValueError, match="finished"):
        prepare_continuation(service, {**params, "parent_id": "busy"}, project["id"], root)


def test_conversation_history_pages_keep_complete_messages(desktop):
    service, project, _ = desktop
    for index in range(25):
        _history_row(service, project["id"], str(index), str(index - 1) if index else None)
    page = service.dispatch("conversations.get", {"id": "24"})
    assert len(page["turns"]) == 20
    assert page["earlier"] == "4"
    first = service.dispatch("conversations.get", {"id": "24", "before": page["earlier"]})
    assert [row["id"] for row in first["turns"]] == ["0", "1", "2", "3"]
    assert first["earlier"] == ""


@pytest.mark.parametrize(
    "continuity", ["acp_continuity", "vendor_continuity", "remote_continuity", "native_continuity"]
)
def test_native_binding_is_route_owned_and_digest_checked(desktop, continuity):
    from superqode.desktop_service.conversations import prepare_continuation

    service, project, root = desktop
    request = {"harness": "connection:fixture", "provider": "agent", "model": "", "prompt": "first"}
    result = {
        "session_id": "owned-session",
        continuity: True,
        "harness_digest": "fixture",
        "remote_state": {"context_id": "owned-context"},
    }
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "owned",
            project["id"],
            "task",
            "first",
            "completed",
            json.dumps(request),
            json.dumps(result),
            1,
            1,
        ),
    )
    params = {
        **request,
        "prompt": "next",
        "parent_id": "owned",
        "_desktop_connection": {"digest": "fixture"},
    }
    prepare_continuation(service, params, project["id"], root)
    assert params["session_id"] == "owned-session"
    assert "_handoff_context" not in params
    assert ("_remote_previous" in params) == (continuity == "remote_continuity")
    changed = {
        **request,
        "harness": "connection:other",
        "parent_id": "owned",
        "_desktop_connection": {"digest": "fixture"},
    }
    prepare_continuation(service, changed, project["id"], root)
    assert "session_id" not in changed
    assert "_remote_previous" not in changed
    assert changed["_continuity"]["mode"] == "handoff"
