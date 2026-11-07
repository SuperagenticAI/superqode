"""Private companion trust boundaries, using no VPN, credentials or models."""

import json
from types import SimpleNamespace

import httpx
import pytest

from test_desktop_service import desktop  # noqa: F401
from test_desktop_session_identity import add_run
from superqode.desktop_service import remote_network
from superqode.desktop_service.remote_access import digest
from superqode.desktop_service.remote_http import application, RemoteServer, MAX_BODY

ORIGIN = "https://home.example-tailnet.ts.net"
PRINCIPAL = "owner@example.test"


@pytest.fixture
def companion(desktop):
    service, project, root = desktop
    access = service.companion
    profile = access.handle(
        "remote.profiles.save",
        {
            "project": project["id"],
            "name": "Home model",
            "harness": "core",
            "provider": "ollama",
            "model": "fixture",
            "local_only": False,
        },
    )
    access.config.update(enabled=True, private_url=ORIGIN)
    access.server = SimpleNamespace(running=True, stop=lambda: None)
    yield service, project, root, profile, access


def pair(access, profile, permissions=None):
    params = {"profiles": [profile["id"]]}
    if permissions is not None:
        params["permissions"] = permissions
    invitation = access.handle("remote.pairing.create", params)
    pending = access.request_pairing(invitation["code"], "My phone", PRINCIPAL)
    access.handle("remote.pairing.approve", {"id": pending["id"]})
    claimed = access.claim_pairing(pending["id"], pending["claim"], PRINCIPAL)
    return claimed["token"], access.authenticate(claimed["token"], PRINCIPAL)


def test_one_project_share_keeps_later_harness_changes(companion):
    service, project, _, profile, access = companion
    assert profile["id"] == "project:" + project["id"]
    assert "core" in profile["allowed_harnesses"]
    updated = access.handle(
        "remote.profiles.save",
        {
            "project": project["id"],
            "name": "Home model",
            "harness": "core",
            "provider": "ollama",
            "model": "changed",
            "local_only": False,
            "source": "mac",
        },
    )
    assert updated["id"] == profile["id"]
    assert updated["model"] == "changed"
    assert updated["revision"] == 2
    assert len(access.config["profiles"]) == 1
    _, device = pair(access, updated)
    switched = access.rpc(
        device,
        "project.connection",
        {"project": project["id"], "harness": "core", "provider": "ollama", "model": "from-phone"},
        "switch-harness",
    )
    # A built-in harness keeps the model chosen on the Mac, not one sent by the phone.
    assert switched["model"] == "changed"
    assert access.profiles(device)[0]["model"] == "changed"


def test_phone_harness_switch_is_limited_to_the_mac_allow_list(companion):
    _, project, _, profile, access = companion
    _, device = pair(access, profile)
    narrowed = access.handle(
        "remote.profiles.save",
        {
            "project": project["id"],
            "name": "Home model",
            "harness": "core",
            "provider": "ollama",
            "model": "fixture",
            "local_only": False,
            "allowed_harnesses": [],
        },
    )
    assert narrowed["allowed_harnesses"] == ["core"]
    choices = access.rpc(device, "project.connections", {"project": project["id"]})
    assert {choice["id"] for choice in choices} <= {"core"}
    with pytest.raises(PermissionError, match="Allow this harness"):
        access.rpc(
            device,
            "project.connection",
            {"project": project["id"], "harness": "no-tool", "provider": "", "model": ""},
            "switch-to-no-tool",
        )
    with pytest.raises(ValueError, match="Choose the harnesses"):
        access.handle(
            "remote.profiles.save",
            {**narrowed, "allowed_harnesses": "core"},
        )


def test_new_shares_reach_only_the_phones_chosen_on_the_mac(desktop):
    service, project, _ = desktop
    access = service.companion
    access.config.update(enabled=True, private_url=ORIGIN)
    access.server = SimpleNamespace(running=True, stop=lambda: None)
    share = {
        "project": project["id"],
        "name": "Home model",
        "harness": "core",
        "provider": "ollama",
        "model": "fixture",
        "local_only": False,
    }
    with pytest.raises(ValueError, match="Share a project"):
        access.handle("remote.pairing.create", {"profiles": []})
    with pytest.raises(ValueError, match="Choose the Mac connections"):
        access.handle("remote.pairing.create", {"profiles": ["missing"]})
    profile = access.handle("remote.profiles.save", share)
    _, device = pair(access, profile)
    assert [item["id"] for item in access.rpc(device, "projects.list", {})] == [project["id"]]
    access.handle("remote.profiles.remove", {"id": profile["id"]})
    again = access.handle("remote.profiles.save", share)
    assert again["id"] == profile["id"]
    # Sharing the project again does not hand it back to an earlier phone.
    assert access.rpc(device, "projects.list", {}) == []
    listed = access.handle("remote.status", {})["devices"][0]
    assert listed["profiles"] == []
    access.handle(
        "remote.devices.grant", {"id": device["id"], "profile": again["id"], "allow": True}
    )
    assert [item["id"] for item in access.rpc(device, "projects.list", {})] == [project["id"]]
    access.handle(
        "remote.devices.grant", {"id": device["id"], "profile": again["id"], "allow": False}
    )
    assert access.rpc(device, "projects.list", {}) == []
    with pytest.raises(ValueError, match="Share this project"):
        access.handle("remote.devices.grant", {"id": device["id"], "profile": "x", "allow": True})


def test_pairing_requires_invitation_local_approval_and_correct_claim(companion):
    _, _, _, profile, access = companion
    with pytest.raises(PermissionError):
        access.request_pairing("invented", "Attacker", PRINCIPAL)
    invitation = access.handle("remote.pairing.create", {"profiles": [profile["id"]]})
    pending = access.request_pairing(invitation["code"], "Phone", PRINCIPAL)
    assert access.claim_pairing(pending["id"], pending["claim"], PRINCIPAL)["state"] == "pending"
    with pytest.raises(PermissionError):
        access.claim_pairing(pending["id"], "invented", PRINCIPAL)
    with pytest.raises(PermissionError):
        access.claim_pairing(pending["id"], pending["claim"], "other@example.test")
    with pytest.raises(PermissionError):
        access.request_pairing(invitation["code"], "Another phone", PRINCIPAL)
    access.handle("remote.pairing.deny", {"id": pending["id"]})
    assert "token" not in access.claim_pairing(pending["id"], pending["claim"], PRINCIPAL)


def test_device_token_is_hashed_bound_to_network_identity_and_revocable(companion):
    service, _, _, profile, access = companion
    token, device = pair(access, profile)
    assert device["token_hash"] == digest(token)
    assert token not in json.dumps(service._all("SELECT * FROM companion_devices"))
    assert token not in json.dumps(access.status())
    with pytest.raises(PermissionError):
        access.authenticate(token, "someone-else@example.test")
    access.handle("remote.devices.revoke", {"id": device["id"]})
    with pytest.raises(PermissionError):
        access.authenticate(token, PRINCIPAL)
    with pytest.raises(PermissionError):
        access.rpc(device, "projects.list", {})


def test_pairing_expiry_and_device_expiry_fail_closed(companion, monkeypatch):
    service, _, _, profile, access = companion
    token, device = pair(access, profile)
    service._write("UPDATE companion_devices SET expires=0 WHERE id=?", (device["id"],))
    with pytest.raises(PermissionError):
        access.authenticate(token, PRINCIPAL)
    invitation = access.handle("remote.pairing.create", {"profiles": [profile["id"]]})
    access.invitations[digest(invitation["code"])]["expires"] = 0
    with pytest.raises(PermissionError):
        access.request_pairing(invitation["code"], "Phone", PRINCIPAL)


def test_project_and_parent_authorization_precedes_dispatch(companion, tmp_path):
    service, project, _, profile, access = companion
    _, device = pair(access, profile)
    other = service.open_project(str(tmp_path / "other")) if (tmp_path / "other").is_dir() else None
    if other is None:
        (tmp_path / "other").mkdir()
        other = service.open_project(str(tmp_path / "other"))
    add_run(service, project, "local-run")
    add_run(service, other, "foreign-run")
    assert [p["id"] for p in access.rpc(device, "projects.list", {})] == [project["id"]]
    assert "foreign-run" not in {j["id"] for j in access.rpc(device, "jobs.list", {})}
    for method, params in [
        ("jobs.get", {"id": "foreign-run"}),
        ("jobs.cancel", {"id": "foreign-run"}),
        ("files.read", {"project": other["id"], "path": "secret"}),
        ("tasks.start", {"profile": profile["id"], "prompt": "test", "parent_id": "foreign-run"}),
    ]:
        with pytest.raises(PermissionError):
            access.rpc(device, method, params, "test")


def test_internal_admin_and_parameter_injection_are_refused(companion):
    _, _, _, profile, access = companion
    _, device = pair(access, profile)
    for method in (
        "engine.shutdown",
        "projects.open",
        "remote.pairing.approve",
        "settings.set",
        "tools.start",
        "providers.credentials.set",
        "files.write",
    ):
        with pytest.raises(PermissionError):
            access.rpc(device, method, {})
    with pytest.raises(ValueError, match="Unsupported"):
        access.rpc(
            device,
            "tasks.start",
            {"profile": profile["id"], "prompt": "test", "permission_mode": "full"},
            "inject",
        )


def test_permission_and_removed_profile_are_enforced(companion):
    _, _, _, profile, access = companion
    _, device = pair(access, profile, ["read"])
    with pytest.raises(PermissionError):
        access.rpc(device, "tasks.start", {"profile": profile["id"], "prompt": "test"}, "read-only")
    access.handle("remote.profiles.remove", {"id": profile["id"]})
    assert access.rpc(device, "projects.list", {}) == []


def test_a_later_shared_project_can_start_a_task(companion, monkeypatch, tmp_path):
    service, _, _, first, access = companion
    folder = tmp_path / "second"
    folder.mkdir()
    other = service.open_project(str(folder))
    second = access.handle(
        "remote.profiles.save",
        {
            "project": other["id"],
            "name": "Second",
            "harness": "core",
            "provider": "ollama",
            "model": "fixture",
            "local_only": False,
        },
    )
    _, device = pair(access, first)
    access.handle(
        "remote.devices.grant", {"id": device["id"], "profile": second["id"], "allow": True}
    )
    device = service._all("SELECT * FROM companion_devices WHERE id=?", (device["id"],))[0]
    assert [p["id"] for p in access.profiles(device)] == [first["id"], second["id"]]
    recorded = []

    def start(project, kind, params):
        recorded.append(project)
        return {"id": "second-run"}

    monkeypatch.setattr(service, "start", start)
    result = access.rpc(
        device,
        "tasks.start",
        {"profile": second["id"], "prompt": "fixture only"},
        "second-project",
    )
    assert result["id"] == "second-run"
    assert recorded == [other["id"]]


def test_idempotency_prevents_duplicate_launch_and_rejects_changed_request(companion, monkeypatch):
    service, _, _, profile, access = companion
    _, device = pair(access, profile)
    recorded = []

    def start(project, kind, params):
        recorded.append(params)
        return {"id": "new-run"}

    monkeypatch.setattr(service, "start", start)
    params = {"profile": profile["id"], "prompt": "fixture only"}
    assert access.rpc(device, "tasks.start", params, "stable") == {"id": "new-run"}
    assert access.rpc(device, "tasks.start", params, "stable") == {"id": "new-run"}
    assert len(recorded) == 1
    assert recorded[0]["permission_mode"] == "ask"
    assert recorded[0]["remote_origin"]["device"] == device["id"]
    with pytest.raises(ValueError, match="already used"):
        access.rpc(device, "tasks.start", {**params, "prompt": "different"}, "stable")


def test_uncertain_mutation_is_not_replayed(companion, monkeypatch):
    service, _, _, profile, access = companion
    _, device = pair(access, profile)
    calls = []

    def fail(*args):
        calls.append(args)
        raise RuntimeError("simulated process loss")

    monkeypatch.setattr(service, "start", fail)
    params = {"profile": profile["id"], "prompt": "fixture only"}
    with pytest.raises(RuntimeError):
        access.rpc(device, "tasks.start", params, "uncertain")
    with pytest.raises(ValueError, match="uncertain outcome"):
        access.rpc(device, "tasks.start", params, "uncertain")
    assert len(calls) == 1


def test_local_only_requires_verified_endpoint_and_never_uses_cloud_optimizer(companion):
    service, project, _, profile, access = companion
    raw = {**profile, "local_only": True}
    with pytest.raises(ValueError, match="verified loopback"):
        access.validate_profile(raw)
    service._write(
        "INSERT INTO local_model_bindings VALUES(?,?,?,?,?)",
        (project["id"], "core", "ollama", "fixture", "http://127.0.0.1:11434/v1"),
    )
    local = access.handle("remote.profiles.save", raw)
    _, device = pair(access, local, ["read", "optimize"])
    assert not access.rpc(device, "companion.catalog", {})["profiles"][0]["optimization"]
    with pytest.raises(ValueError, match="Local-only optimization"):
        access.rpc(
            device,
            "optimizations.start",
            {
                "profile": local["id"],
                "tasks": "decision-routing",
                "tasks_hash": "fixture",
                "live": True,
            },
            "no-cloud",
        )
    service._write("UPDATE local_model_bindings SET endpoint='https://external.example/v1'")
    with pytest.raises(ValueError, match="verified loopback"):
        access.validate_profile(raw)


@pytest.mark.asyncio
async def test_http_pair_claim_rpc_and_revocation_round_trip(companion):
    _, _, _, profile, access = companion
    invitation = access.handle("remote.pairing.create", {"profiles": [profile["id"]]})
    headers = {"Tailscale-User-Login": PRINCIPAL}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(access)), base_url=ORIGIN, headers=headers
    ) as client:
        pending = (
            await client.post("/v1/pair", json={"code": invitation["code"], "name": "Phone"})
        ).json()["result"]
        assert "token" not in pending
        access.handle("remote.pairing.approve", {"id": pending["id"]})
        claimed = (
            await client.post(
                "/v1/pair/claim", json={"id": pending["id"], "claim": pending["claim"]}
            )
        ).json()["result"]
        auth = {"Authorization": "Bearer " + claimed["token"]}
        response = await client.post("/v1/rpc", headers=auth, json={"method": "companion.catalog"})
        assert response.status_code == 200
        assert response.json()["result"]["profiles"][0]["id"] == profile["id"]
        assert response.headers["cache-control"] == "no-store"
        access.handle("remote.devices.revoke", {"id": claimed["device"]})
        assert (
            await client.post("/v1/rpc", headers=auth, json={"method": "projects.list"})
        ).status_code == 403


@pytest.mark.asyncio
async def test_http_rejects_funnel_foreign_origin_bad_host_and_oversized_body(companion):
    _, _, _, _, access = companion
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(access)), base_url=ORIGIN
    ) as client:
        assert (await client.post("/v1/rpc", json={"method": "projects.list"})).status_code == 403
        for headers in [{"Origin": "https://attacker.example"}, {"Host": "127.0.0.1"}]:
            response = await client.post(
                "/v1/rpc", json={}, headers={"Tailscale-User-Login": PRINCIPAL, **headers}
            )
            assert response.status_code == 403
        response = await client.post(
            "/v1/rpc",
            content=b"x" * (MAX_BODY + 1),
            headers={"Tailscale-User-Login": PRINCIPAL, "Content-Type": "application/json"},
        )
        assert response.status_code == 413


def test_private_network_check_refuses_funnel_and_wrong_proxy(monkeypatch):
    monkeypatch.setattr(remote_network, "tailscale_binary", lambda: "/fixture/tailscale")
    serving = {"AllowFunnel": {"home.example-tailnet.ts.net:443": True}}

    def command(binary, *args):
        if args[0] == "status":
            return {"BackendState": "Running", "Self": {"DNSName": "home.example-tailnet.ts.net."}}
        return serving

    monkeypatch.setattr(remote_network, "command", command)
    assert not remote_network.inspect()["ready"]
    serving.clear()
    assert not remote_network.inspect()["ready"]
    serving["Web"] = {
        "home.example-tailnet.ts.net:47832": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:47831"}}
        }
    }
    assert remote_network.inspect()["ready"]


def test_actual_listener_is_loopback_only_and_stops_without_stopping_engine(companion):
    service, _, _, profile, access = companion
    token, _ = pair(access, profile)
    server = RemoteServer(access, 0)
    server.start()
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/v1/rpc",
                headers={
                    "Host": "home.example-tailnet.ts.net",
                    "Tailscale-User-Login": PRINCIPAL,
                    "Authorization": "Bearer " + token,
                },
                json={"method": "projects.list"},
            )
        assert response.status_code == 200
    finally:
        server.stop()
    assert not server.running
    assert service.dispatch("projects.list", {})


def test_private_setup_never_overwrites_existing_services_or_enables_funnel(monkeypatch):
    monkeypatch.setattr(remote_network, "tailscale_binary", lambda: "/fixture/tailscale")
    monkeypatch.setattr(
        remote_network, "inspect", lambda port: {"ready": False, "private_url": ORIGIN}
    )
    config = {
        "Web": {"home.example-tailnet.ts.net:47832": {"Handlers": {"/": {"Proxy": "http://other"}}}}
    }
    monkeypatch.setattr(remote_network, "command", lambda *args: config)
    executed = []
    monkeypatch.setattr(
        remote_network.subprocess,
        "run",
        lambda argv, **kwargs: executed.append(argv) or SimpleNamespace(returncode=0),
    )
    with pytest.raises(ValueError, match="left unchanged"):
        remote_network.setup()
    assert not executed
    config.clear()
    config["Web"] = {
        "home.example-tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://other-app"}}}
    }
    remote_network.setup()
    assert executed == [
        ["/fixture/tailscale", "serve", "--bg", "--https=47832", "http://127.0.0.1:47831"]
    ]


def test_connect_starts_tailscale_without_asking_for_a_shell_command(monkeypatch):
    monkeypatch.setattr(remote_network, "tailscale_binary", lambda: "/fixture/tailscale")
    monkeypatch.setattr(remote_network, "tailscale_app", lambda: None)
    monkeypatch.setattr(remote_network.time, "sleep", lambda _seconds: None)
    state = {"backend": "Stopped", "served": False}

    def command(binary, *args):
        if args[0] == "status":
            return {
                "BackendState": state["backend"],
                "Self": {"DNSName": "home.example-tailnet.ts.net."},
            }
        web = {}
        if state["served"]:
            web["home.example-tailnet.ts.net:47832"] = {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:47831"}}
            }
        return {"AllowFunnel": {}, "Web": web}

    def run(argv, **kwargs):
        if "up" in argv:
            state["backend"] = "Running"
        if "--bg" in argv:
            state["served"] = True
            assert "--funnel" not in argv
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(remote_network, "command", command)
    monkeypatch.setattr(remote_network.subprocess, "run", run)
    checked = remote_network.inspect()
    assert checked["command"] == ""
    assert checked["ready"] is False
    assert "tailscale serve" not in checked["issue"]
    connected = remote_network.connect()
    assert connected["ready"] is True
    assert connected["command"] == ""
    assert state["served"] is True


def test_approval_snapshot_is_current_even_after_event_pagination(companion):
    service, project, _, profile, access = companion
    _, device = pair(access, profile)
    add_run(service, project, "approval-job")
    for identity in ("old", "current"):
        service._write(
            "INSERT INTO events(job,payload) VALUES(?,?)",
            (
                "approval-job",
                json.dumps(
                    {
                        "type": "approval",
                        "data": {"request_id": identity, "tool": {"name": identity}},
                    }
                ),
            ),
        )
    service.pending["approval-job"] = "current"
    result = access.rpc(device, "jobs.get", {"id": "approval-job", "after": 10000})
    assert result["events"] == []
    assert result["pending_approval"]["request_id"] == "current"
    with pytest.raises(ValueError, match="stale"):
        access.rpc(
            device,
            "jobs.approve",
            {"id": "approval-job", "request_id": "old", "allow": True},
            "old-approval",
        )
    assert service.pending["approval-job"] == "current"


def test_local_suite_cannot_add_unverified_grader_or_variant(companion, monkeypatch):
    import superqode.harness.eval as evaluation

    service, project, _, profile, access = companion
    service._write(
        "INSERT INTO local_model_bindings VALUES(?,?,?,?,?)",
        (project["id"], "core", "ollama", "fixture", "http://127.0.0.1:11434/v1"),
    )
    local = access.handle("remote.profiles.save", {**profile, "local_only": True})
    _, device = pair(access, local)
    monkeypatch.setattr(
        evaluation,
        "load_eval_tasks",
        lambda path: {"variants": [{"spec": "cloud-harness"}], "tasks": []},
    )
    with pytest.raises(ValueError, match="local routes are not verified"):
        access.rpc(device, "evals.inspect", {"profile": local["id"], "tasks": "decision-routing"})


def test_device_grant_persists_across_engine_restart_without_storing_bearer(companion):
    from superqode.desktop_service.service import DesktopService

    service, _, _, profile, access = companion
    token, original = pair(access, profile)
    access.config["enabled"] = False
    access._save()
    root = service.root
    service.close()
    restored = DesktopService(root)
    try:
        device = restored.companion.authenticate(token, PRINCIPAL)
        assert device["id"] == original["id"]
        assert (
            restored.companion.rpc(device, "companion.catalog", {})["profiles"][0]["id"]
            == profile["id"]
        )
        assert token not in json.dumps(restored._all("SELECT * FROM companion_devices"))
    finally:
        restored.close()


def test_remote_thread_library_can_rename_pin_and_archive_with_project_scope(companion):
    service, project, _, profile, access = companion
    _, device = pair(access, profile)
    add_run(service, project, "organized-run")
    access.rpc(
        device,
        "threads.update",
        {
            "project": project["id"],
            "id": "organized-run",
            "title": "Release review",
            "pinned": True,
        },
        "organize-1",
    )
    page = access.rpc(
        device, "threads.list", {"project": project["id"], "query": "Release", "view": "pinned"}
    )
    assert page["items"][0]["conversation_title"] == "Release review"
    access.rpc(
        device,
        "threads.update",
        {"project": project["id"], "id": "organized-run", "archived": True},
        "organize-2",
    )
    assert (
        access.rpc(device, "threads.list", {"project": project["id"], "view": "active"})["items"]
        == []
    )
    assert access.rpc(device, "threads.list", {"project": project["id"], "view": "archived"})[
        "items"
    ]
    _, read_only = pair(access, profile, ["read"])
    with pytest.raises(PermissionError):
        access.rpc(
            read_only,
            "threads.update",
            {"project": project["id"], "id": "organized-run", "archived": False},
            "read-only",
        )


def test_request_reconciliation_never_replays_and_is_bound_to_device(companion, monkeypatch):
    service, project, _, profile, access = companion
    _, device = pair(access, profile)
    assert access.rpc(device, "companion.request_status", {"key": "pending"}) == {
        "state": "not_recorded"
    }
    service._write(
        "INSERT INTO companion_commands VALUES(?,?,?,NULL,?)",
        (device["id"], "pending", "digest", 1),
    )
    assert access.rpc(device, "companion.request_status", {"key": "pending"}) == {
        "state": "uncertain"
    }
    add_run(service, project, "accepted-run")
    service._write(
        "UPDATE jobs SET request=? WHERE id=?",
        (json.dumps({"command_id": f"companion:{device['id']}:pending"}), "accepted-run"),
    )
    assert access.rpc(device, "companion.request_status", {"key": "pending"}) == {
        "state": "accepted",
        "result": {"id": "accepted-run"},
    }
    service._write(
        "UPDATE companion_commands SET result=? WHERE device=? AND key=?",
        (json.dumps({"id": "accepted-run"}), device["id"], "pending"),
    )
    assert (
        access.rpc(device, "companion.request_status", {"key": "pending"})["state"] == "completed"
    )
    _, other_device = pair(access, profile)
    assert (
        access.rpc(other_device, "companion.request_status", {"key": "pending"})["state"]
        == "not_recorded"
    )
    access.handle("remote.profiles.remove", {"id": profile["id"]})
    with pytest.raises(PermissionError):
        access.rpc(device, "companion.request_status", {"key": "pending"})


def test_direct_chat_capability_rejects_agent_managed_routes_before_reserving(companion):
    service, _, _, profile, access = companion
    _, device = pair(access, profile)
    assert access.rpc(device, "companion.catalog", {})["profiles"][0]["chat"] is True
    access.handle("remote.profiles.save", {**profile, "provider": "agent"})
    assert access.rpc(device, "companion.catalog", {})["profiles"][0]["chat"] is False
    with pytest.raises(ValueError, match="Direct Chat requires"):
        access.rpc(
            device,
            "tasks.start",
            {"profile": profile["id"], "prompt": "Hello", "interaction_mode": "chat"},
            "unsupported-chat",
        )
    assert (
        service._all(
            "SELECT key FROM companion_commands WHERE device=? AND key=?",
            (device["id"], "unsupported-chat"),
        )
        == []
    )


def _add_route(monkeypatch, route):
    from superqode.desktop_service import connect_workflow

    original = connect_workflow.desktop_routes

    def extra(root):
        return [*original(root), route]

    monkeypatch.setattr(connect_workflow, "desktop_routes", extra)


def test_phone_sees_the_same_harnesses_as_the_mac(companion, monkeypatch):
    service, project, _, profile, access = companion
    _add_route(
        monkeypatch,
        {
            "id": "acp:phone-fixture",
            "name": "Phone fixture agent",
            "desktop_kind": "acp",
            "agent_id": "phone-fixture",
            "available": True,
        },
    )
    builtins = [
        row["id"]
        for row in service.dispatch("harnesses.list", {"project": project["id"]})
        if row.get("available")
        and row.get("runtime") == "builtin"
        and row["id"]
        in {
            "core",
            "pipy",
            "codegem",
            "systemone",
            "no-tool",
        }
    ]
    access.config["profiles"][0]["allowed_harnesses"] = list(
        dict.fromkeys([profile["harness"], *builtins])
    )
    _, device = pair(access, profile)
    choices = access.rpc(device, "project.connections", {"project": project["id"]})
    assert "acp:phone-fixture" in {choice["id"] for choice in choices}
    assert "core" in {choice["id"] for choice in choices}
    assert "acp:phone-fixture" in access.config["profiles"][0]["allowed_harnesses"]
    access.handle(
        "remote.profiles.save",
        {**profile, "allowed_harnesses": ["core"], "local_only": False},
    )
    narrowed = access.rpc(device, "project.connections", {"project": project["id"]})
    assert {choice["id"] for choice in narrowed} <= {"core"}


def test_phone_lists_connect_rows_that_still_need_setup(companion, monkeypatch):
    """An automatic installed-only list grows to the full Connect catalog."""
    _, project, _, profile, access = companion
    hidden = {
        "command": "do-not-send",
        "install": {"command": "curl hidden"},
        "extra_env": {"TOKEN": "secret"},
    }
    _add_route(
        monkeypatch,
        {
            "id": "acp:not-ready",
            "name": "Not ready agent",
            "desktop_kind": "acp",
            "agent_id": "not-ready",
            "available": False,
            "description": "An ACP agent that is not set up on this Mac",
            **hidden,
        },
    )
    _add_route(
        monkeypatch,
        {
            "id": "connection:not-ready-plan",
            "name": "Not ready plan",
            "desktop_kind": "connection",
            "subscription_vendor": "example",
            "available": False,
            **hidden,
        },
    )
    stored = access.config["profiles"][0]
    stored.pop("allowed_mode", None)
    # The list this Mac actually saved: a handful of installed names, not an
    # explicit toggle of the whole Connect catalog.
    stored["allowed_harnesses"] = ["core", "connection:antigravity", "acp:opencode", "grok"]
    assert "acp:not-ready" not in stored["allowed_harnesses"]
    _, device = pair(access, profile)
    choices = access.rpc(device, "project.connections", {"project": project["id"]})
    by_id = {choice["id"]: choice for choice in choices}
    assert by_id["acp:not-ready"]["group"] == "acp"
    assert by_id["acp:not-ready"]["available"] is False
    assert by_id["connection:not-ready-plan"]["group"] == "subscription"
    assert by_id["connection:not-ready-plan"]["available"] is False
    for choice in (by_id["acp:not-ready"], by_id["connection:not-ready-plan"]):
        assert "command" not in choice
        assert "install" not in choice
        assert "extra_env" not in choice
        assert "TOKEN" not in json.dumps(choice)
    assert "acp:not-ready" in stored["allowed_harnesses"]
    assert stored["allowed_mode"] == "all"
    with pytest.raises(ValueError, match="Set up this harness"):
        access.rpc(
            device,
            "project.connection",
            {
                "project": project["id"],
                "harness": "acp:not-ready",
                "provider": "agent",
                "model": "",
            },
            "use-not-ready",
        )
    access.handle(
        "remote.profiles.save",
        {**profile, "allowed_harnesses": ["core"], "local_only": False},
    )
    narrowed = access.rpc(device, "project.connections", {"project": project["id"]})
    assert {choice["id"] for choice in narrowed} <= {"core"}


def test_superqode_harness_uses_a_model_connected_on_the_mac(companion, monkeypatch):
    service, project, _, profile, access = companion
    monkeypatch.setattr("superqode.local.inventory.list_ollama_models", lambda: [])
    _add_route(
        monkeypatch,
        {
            "id": "connection:antigravity",
            "name": "Antigravity CLI",
            "desktop_kind": "connection",
            "runtime": "antigravity-cli",
            "subscription_vendor": "antigravity",
            "available": True,
        },
    )
    shared = access.handle(
        "remote.profiles.save",
        {
            "project": project["id"],
            "name": profile["name"],
            "harness": "connection:antigravity",
            "provider": "agent",
            "model": "",
            "local_only": False,
        },
    )
    _, device = pair(access, shared)
    with pytest.raises(ValueError, match="Choose a model"):
        access.rpc(
            device,
            "project.connection",
            {"project": project["id"], "harness": "core", "provider": "agent", "model": ""},
            "needs-model",
        )
    with pytest.raises(ValueError, match="Choose a model"):
        access.rpc(
            device,
            "project.connection",
            {
                "project": project["id"],
                "harness": "core",
                "provider": "openai",
                "model": "phone-invented-model",
            },
            "invented-model",
        )
    service.dispatch("settings.set", {"key": "provider", "value": "ollama"})
    service.dispatch("settings.set", {"key": "model", "value": "fixture"})
    listed = access.rpc(device, "project.models", {"project": project["id"]})
    assert any(row["provider"] == "ollama" and row["model"] == "fixture" for row in listed)
    assert all("key" not in row and "credential" not in row for row in listed)
    switched = access.rpc(
        device,
        "project.connection",
        {"project": project["id"], "harness": "core", "provider": "ollama", "model": "fixture"},
        "use-connected-model",
    )
    assert switched["harness"] == "core"
    assert switched["provider"] == "ollama"
    assert switched["model"] == "fixture"


def test_phone_connection_list_follows_the_mac_connect_ladder():
    from superqode.desktop_service.remote_access import connection_choice, order_connection_choices

    rows = [
        connection_choice(
            {
                "id": "acp:opencode",
                "name": "OpenCode",
                "desktop_kind": "acp",
                "agent_id": "opencode",
                "available": True,
                "command": "opencode acp",
                "description": "Local ACP agent",
            },
            "routes.list",
        ),
        connection_choice(
            {
                "id": "connection:antigravity",
                "name": "Antigravity CLI",
                "desktop_kind": "connection",
                "runtime": "antigravity-cli",
                "subscription_vendor": "antigravity",
                "available": True,
                "command": "agy",
                "extra_env": {"TOKEN": "secret"},
            },
            "routes.list",
        ),
        connection_choice(
            {
                "id": "acp:cursor",
                "name": "Cursor",
                "desktop_kind": "acp",
                "subscription_vendor": "cursor",
                "agent_id": "cursor",
                "available": True,
            },
            "routes.list",
        ),
        connection_choice(
            {
                "id": "attach:qwen",
                "name": "Qwen Code",
                "desktop_kind": "attached",
                "available": True,
                "description": "Connect with your API key or a local model",
            },
            "routes.list",
        ),
        connection_choice(
            {
                "id": "core",
                "name": "SuperQode Core",
                "runtime": "builtin",
                "available": True,
                "description": "SuperQode harness",
            },
            "harnesses.list",
        ),
        connection_choice(
            {
                "id": "remote:abc",
                "name": "Remote agent",
                "kind": "a2a",
                "available": True,
            },
            "routes.list",
        ),
    ]
    ordered = order_connection_choices(rows)
    assert [row["group"] for row in ordered] == [
        "subscription",
        "subscription",
        "model",
        "harness",
        "acp",
        "protocol",
    ]
    assert [row["name"] for row in ordered[:2]] == ["Antigravity CLI", "Cursor"]
    antigravity = ordered[0]
    assert antigravity["icon_key"] == "antigravity"
    assert antigravity["desktop_kind"] == "connection"
    assert set(antigravity) == {
        "id",
        "name",
        "provider",
        "model",
        "group",
        "desktop_kind",
        "icon_key",
        "description",
        "available",
    }
    assert "command" not in antigravity
    assert "extra_env" not in antigravity
    assert ordered[3]["group"] == "harness"
    assert ordered[3]["icon_key"] == "superqode"
    assert ordered[4]["group"] == "acp"
    assert ordered[4]["icon_key"] == "opencode"
    assert ordered[5]["group"] == "protocol"
