"""Private companion trust boundaries, using no VPN, credentials or models."""

import json
from types import SimpleNamespace

import httpx
import pytest

from test_desktop_service import desktop  # noqa: F401
from test_desktop_session_identity import add_run
from superqode.desktop_service import remote_network
from superqode.desktop_service.remote_access import digest
from superqode.desktop_service.remote_http import application, RemoteServer

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
            content=b"x" * 65537,
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
        "home.example-tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:47831"}}}
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
