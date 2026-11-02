import asyncio
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import textwrap
import threading
import time

import httpx
import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from superqode.desktop_service.acp_catalog import refresh_registry
from superqode.desktop_service.connection_probe import probe_route, terminal_auth_plan
from superqode.desktop_service.ownership import Lease, project_lease_path
from superqode.desktop_service.service import DesktopService


@pytest.fixture
def login_agent(desktop):
    service, project, root = desktop
    script = root / "agent.py"
    script.write_text(
        textwrap.dedent("""
        import json, os, sys
        from pathlib import Path
        marker = Path(".fixture-login")
        if "--login" in sys.argv:
            assert os.environ.get("ACP_INTERACTIVE_LOGIN") == "1"
            marker.write_text("signed in")
            raise SystemExit(0)
        for line in sys.stdin:
            data = json.loads(line)
            method, params = data.get("method"), data.get("params", {})
            if "id" not in data: continue
            if method == "initialize":
                assert data["params"]["protocolVersion"] == 1
                result = {"protocolVersion": 1, "agentInfo": {"name": "login-fixture", "version": "1"}, "agentCapabilities": {"loadSession": True},
                    "authMethods": [{"id": "browser", "name": "Browser login"}, {"id": "terminal", "name": "Terminal login", "type": "terminal", "args": ["--login"], "env": {"ACP_INTERACTIVE_LOGIN": "1"}}]}
            elif method == "authenticate":
                assert params["methodId"] == "browser"
                marker.write_text("signed in")
                result = {}
            elif method in ("session/new", "session/load"):
                if not marker.exists():
                    print(json.dumps({"jsonrpc": "2.0", "id": data["id"], "error": {"code": -32000, "message": "Authentication required"}}), flush=True)
                    continue
                result = {"sessionId": "fixture-session"}
            elif method == "session/prompt":
                calls = Path(".fixture-prompts")
                calls.write_text(calls.read_text() + "prompt\\n" if calls.exists() else "prompt\\n")
                print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "fixture-session", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Fixture complete"}}}}), flush=True)
                result = {"stopReason": "end_turn"}
            else: result = {}
            print(json.dumps({"jsonrpc": "2.0", "id": data["id"], "result": result}), flush=True)
    """)
    )
    route = service.dispatch(
        "connect.acp.custom.save",
        {"project": project["id"], "name": "Fixture agent", "argv": [sys.executable, str(script)]},
    )
    return desktop, route


def wait_action(service, operation):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = service.dispatch("connect.auth.poll", operation)
        if result["state"] != "running":
            return result
        time.sleep(0.02)
    pytest.fail("Setup action did not finish")


def test_custom_agent_probe_and_protocol_sign_in_never_send_prompt(login_agent):
    (service, project, root), route = login_agent
    initial = asyncio.run(probe_route(root, route, lambda _: None))
    assert initial["state"] == "authentication-required"
    assert {m["type"] for m in initial["auth_methods"]} == {"agent", "terminal"}
    action = service.dispatch(
        "connect.auth.start",
        {
            "action": "acp-auth",
            "project": project["id"],
            "reference": route["id"],
            "expected_digest": route["digest"],
            "method": "browser",
        },
    )
    result = wait_action(service, action)
    assert result["state"] == "completed", result
    assert result["result"]["connected"] is True
    assert not (root / ".fixture-prompts").exists()
    assert service.dispatch("jobs.list", {}) == []


def test_terminal_sign_in_plan_preserves_base_argv_and_verifies_after_exit(login_agent):
    (service, project, root), route = login_agent
    plan = asyncio.run(probe_route(root, route, lambda _: None, terminal_method="terminal"))
    assert plan["argv"] == [sys.executable, str(root / "agent.py"), "--login"]
    subprocess.run(plan["argv"], cwd=root, env=plan["env"], check=True)
    assert asyncio.run(probe_route(root, route, lambda _: None))["connected"] is True
    assert not (root / ".fixture-prompts").exists()


def test_signed_in_custom_agent_resumes_after_restart_without_replaying(login_agent):
    (service, project, root), route = login_agent
    asyncio.run(probe_route(root, route, lambda _: None, method_id="browser"))
    request = {"project": project["id"], "harness": route["id"], "prompt": "First fixture task"}
    first = wait_job(service, service.dispatch("tasks.start", request)["id"])
    assert first["status"] == "completed", first
    assert first["result"]["acp_continuity"] is True
    assert (root / ".fixture-prompts").read_text().splitlines() == ["prompt"]
    state = service.root
    service.close()
    restored = DesktopService(state)
    try:
        assert not restored.processes
        assert (root / ".fixture-prompts").read_text().splitlines() == ["prompt"]
        second = wait_job(
            restored,
            restored.dispatch(
                "tasks.start",
                {**request, "parent_id": first["id"], "prompt": "Continue fixture task"},
            )["id"],
        )
        assert second["status"] == "completed", second
        assert second["request"]["_continuity"]["mode"] == "resume"
        assert second["result"]["session_id"] == "fixture-session"
        assert len((root / ".fixture-prompts").read_text().splitlines()) == 2
    finally:
        restored.close()


def test_auth_configuration_drift_and_terminal_environment_are_rejected(login_agent):
    (service, project, _), route = login_agent
    with pytest.raises(ValueError, match="configuration changed"):
        service.dispatch(
            "connect.auth.start",
            {
                "action": "acp-auth",
                "project": project["id"],
                "reference": route["id"],
                "expected_digest": "stale",
                "method": "browser",
            },
        )
    for name in ["PATH", "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "HTTPS_PROXY", "API_KEY"]:
        with pytest.raises(ValueError, match="sensitive environment"):
            terminal_auth_plan(
                route,
                [{"id": "terminal", "type": "terminal", "env": {name: "untrusted"}}],
                "terminal",
            )


def test_custom_configuration_is_scoped_literal_and_revision_checked(desktop):
    service, project, root = desktop
    args = [sys.executable, "--literal; touch SHOULD_NOT_EXIST", "$(echo literal)"]
    route = service.dispatch(
        "connect.acp.custom.save", {"project": project["id"], "name": "Custom", "argv": args}
    )
    assert route["command_argv"] == args
    assert not (root / "SHOULD_NOT_EXIST").exists()
    rows = service.dispatch("routes.list", {"project": project["id"]})
    assert any(r["id"] == route["id"] for r in rows)
    with pytest.raises(ValueError, match="changed"):
        service.dispatch(
            "connect.acp.custom.save",
            {
                "project": project["id"],
                "id": route["id"],
                "name": "Changed",
                "argv": args,
                "expected_digest": "stale",
            },
        )
    other = root.parent / "other"
    other.mkdir()
    foreign = service.open_project(str(other))
    assert not any(
        r["id"] == route["id"] for r in service.dispatch("routes.list", {"project": foreign["id"]})
    )
    service.dispatch(
        "connect.acp.custom.remove",
        {"project": project["id"], "id": route["id"], "expected_digest": route["digest"]},
    )
    assert not any(
        r["id"] == route["id"] for r in service.dispatch("routes.list", {"project": project["id"]})
    )


def test_registry_refresh_is_explicit_atomic_and_offline_readable(desktop, monkeypatch):
    service, project, _ = desktop
    requests = []
    original_client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "agents": [
                    {
                        "id": "new-fixture-agent",
                        "name": "Fixture",
                        "version": "1.0",
                        "_superqode": {"run_command": "sh -c BAD"},
                        "distribution": {"npx": {"package": "fixture-agent@1.0"}},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    assert not requests
    assert service.dispatch("connect.acp.registry.status", {})["count"] == 0
    status = asyncio.run(refresh_registry(service, lambda _: None))
    assert len(requests) == 1
    assert status["count"] == 1
    rows = service.dispatch("routes.list", {"project": project["id"]})
    agent = next(r for r in rows if r["id"] == "acp:new-fixture-agent")
    assert agent["command_argv"] == ["npx", "--no-install", "fixture-agent@1.0"]
    plan = service.dispatch(
        "connect.acp.install.plan", {"project": project["id"], "reference": agent["id"]}
    )
    assert plan["argv"] == ["npm", "install", "-g", "fixture-agent@1.0"]
    before = (service.root / "acp-registry.json").read_bytes()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"agents": []})),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="invalid agent catalog"):
        asyncio.run(refresh_registry(service, lambda _: None))
    assert (service.root / "acp-registry.json").read_bytes() == before
    assert len(requests) == 1


def test_engine_and_orphan_writer_ownership_block_restarts_and_edits(desktop):
    service, project, root = desktop
    with pytest.raises(ValueError, match="still owns"):
        DesktopService(service.root)
    lease = Lease(project_lease_path(service.root, root))
    try:
        assert service.dispatch("execution.recovery", {"project": project["id"]})["blocked"] is True
        with pytest.raises(ValueError, match="still owns"):
            service.dispatch("checks.start", {"project": project["id"], "command": "true"})
        with pytest.raises(ValueError, match="still owns"):
            service.dispatch(
                "files.create", {"project": project["id"], "path": "new.py", "text": ""}
            )
    finally:
        lease.close()


def test_git_mutation_finishes_before_a_new_project_writer_starts(desktop, monkeypatch):
    service, project, _ = desktop
    import superqode.desktop_service.service as engine

    entered, release, started = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def git(*args):
        entered.set()
        assert release.wait(5)
        return ""

    monkeypatch.setattr(engine, "git", git)
    original_start = service.start

    def start():
        try:
            job = original_start(project["id"], "check", {"command": "true"})
            started.set()
            wait_job(service, job["id"])
        except Exception as exc:
            errors.append(exc)

    mutation = threading.Thread(
        target=lambda: service.dispatch("git.stage", {"project": project["id"]})
    )
    writer = threading.Thread(target=start)
    mutation.start()
    try:
        assert entered.wait(5)
        writer.start()
        assert not started.wait(0.1)
    finally:
        release.set()
        mutation.join(10)
        if writer.ident:
            writer.join(10)
    assert not mutation.is_alive() and not writer.is_alive()
    assert started.is_set() and not errors
    assert service.dispatch("execution.recovery", {"project": project["id"]})["blocked"] is False


def test_engine_crash_stops_attached_writer_and_preserves_changes(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "important.txt").write_text("keep these uncommitted changes\n")
    state = tmp_path / "state"
    engine = subprocess.Popen(
        [sys.executable, "-u", "-m", "superqode.desktop_service.service", "--state", str(state)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    sequence = 0

    def call(method, params):
        nonlocal sequence
        sequence += 1
        engine.stdin.write(json.dumps({"id": sequence, "method": method, "params": params}) + "\n")
        engine.stdin.flush()
        response = json.loads(engine.stdout.readline())
        assert "error" not in response, response
        return response["result"]

    worker_pid = None
    restored = None
    try:
        project = call("projects.open", {"path": str(root)})
        heartbeat = root / "heartbeat"
        script = "import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=Path('heartbeat');\nwhile True: p.write_text(str(time.time())); time.sleep(0.05)"
        job = call(
            "checks.start",
            {"project": project["id"], "command": shlex.join([sys.executable, "-c", script])},
        )
        deadline = time.monotonic() + 10
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert heartbeat.exists()
        owner = json.loads(next((state / "writers").glob("*.lock")).read_text())
        worker_pid = owner["pid"]
        engine.kill()
        engine.wait(timeout=5)
        restored = DesktopService(state)
        deadline = time.monotonic() + 10
        while (
            restored.dispatch("execution.recovery", {"project": project["id"]})["blocked"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
        assert not restored.dispatch("execution.recovery", {"project": project["id"]})["blocked"]
        stamp = heartbeat.read_text()
        time.sleep(0.2)
        assert heartbeat.read_text() == stamp
        assert (root / "important.txt").read_text() == "keep these uncommitted changes\n"
        assert restored.dispatch("jobs.get", job)["status"] == "interrupted"
        assert not restored.processes
        assert restored.dispatch("execution.recovery", {"project": project["id"]})["interrupted"]
        restored.dispatch("execution.recovery.acknowledge", {"project": project["id"]})
        assert not restored.dispatch("execution.recovery", {"project": project["id"]})[
            "interrupted"
        ]
    finally:
        if engine.poll() is None:
            engine.kill()
            engine.wait(timeout=5)
        for stream in (engine.stdin, engine.stdout):
            stream.close()
        if worker_pid:
            try:
                os.killpg(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if restored:
            restored.close()


@pytest.mark.asyncio
async def test_unreviewed_install_plan_cannot_execute(desktop, monkeypatch):
    from superqode.desktop_service.acp_catalog import install_agent
    import superqode.desktop_service.acp_catalog as catalog

    service, project, _ = desktop
    called = []
    monkeypatch.setattr(
        catalog,
        "install_plan",
        lambda *args: {"digest": "current", "argv": ["npm", "install", "-g", "fixture"]},
    )

    async def run(*args):
        called.append(args)
        return {"installed": True}

    monkeypatch.setattr("superqode.desktop_service.configuration.run_install_command", run)
    with pytest.raises(ValueError, match="plan changed"):
        await install_agent(service, project["id"], "acp:fixture", "stale", lambda _: None)
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_install_receipt_is_bound_to_reviewed_launch_revision(desktop, monkeypatch, changed):
    import superqode.desktop_service.acp_catalog as catalog

    service, project, _ = desktop
    route = {"id": "acp:fixture", "digest": "reviewed-launch"}
    monkeypatch.setattr(catalog, "extra_routes", lambda *args: [dict(route)])
    monkeypatch.setattr(
        catalog,
        "install_plan",
        lambda *args: {"digest": "reviewed-plan", "argv": ["npm", "install", "-g", "fixture"]},
    )

    async def run(*args):
        if changed:
            route["digest"] = "new-launch"
        return {"installed": True}

    monkeypatch.setattr("superqode.desktop_service.configuration.run_install_command", run)
    await catalog.install_agent(
        service, project["id"], route["id"], "reviewed-plan", lambda _: None
    )
    receipts = service._all("SELECT * FROM acp_install_receipts")
    assert bool(receipts) is not changed
    if receipts:
        assert receipts[0]["digest"] == "reviewed-launch"
