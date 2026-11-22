"""Factory Studio uses the engine without model calls or implicit activation."""
# ruff: noqa: F811

import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import pytest
import yaml

from test_factory_definition import project  # noqa: F401
from superqode.desktop_service.service import DesktopService
from superqode.desktop_service.factory_studio import validate_request


@pytest.fixture
def studio(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop-state")
    identity = service.open_project(str(project))["id"]

    def rpc(method, **params):
        return service.dispatch("factory." + method, {"project": identity, **params})

    yield rpc, project, service
    service.close()


def test_validate_save_history_and_trial_are_explicit_and_retry_safe(studio):
    rpc, root, service = studio
    draft = rpc("open", template="fix-and-verify")
    original = (root / ".superqode/factory.yaml").read_text()
    review = rpc("inspect", yaml=draft["yaml"])
    assert len(review["layers"]) == 7
    assert (root / ".superqode/factory.yaml").read_text() == original
    assert any("protected evaluator" in w for w in review["warnings"])
    with pytest.raises(ValueError, match="Save the reviewed"):
        rpc(
            "trial",
            **{k: review[k] for k in ("review", "digest")},
            confirmed=True,
            goal="Fix",
            request_id="trial",
        )
    rpc(
        "save",
        **{k: review[k] for k in ("review", "digest", "expected_file_digest")},
        reason="Native draft",
    )
    history = rpc("list")["revisions"]
    assert len(history) == 2 and all(r["intact"] for r in history)
    review = rpc("inspect", yaml=draft["yaml"])
    args = {k: review[k] for k in ("review", "digest")}
    trial = rpc("trial", **args, confirmed=True, goal="Fix", request_id="trial")
    retry = rpc("trial", **args, confirmed=True, goal="Fix", request_id="trial")
    assert trial == retry and trial["execution_started"] is False
    run = trial["work_order"]["work_order_id"]
    inspected = rpc("run.inspect", run=run)
    assert inspected["work_order"]["status"] == "queued"
    assert not service.processes


def test_save_rejects_disk_drift_and_dependency_drift(studio):
    rpc, root, _ = studio
    data = yaml.safe_load(rpc("open")["yaml"])
    (root / "context.txt").write_text("context")
    data["data_context"]["files"]["context"] = {"path": "context.txt", "purpose": "context"}
    text = yaml.safe_dump(data, sort_keys=False)
    (root / ".superqode/factory.yaml").write_text(text)
    review = rpc("inspect", yaml=text)
    (root / ".superqode/factory.yaml").write_text(text + "\n")
    with pytest.raises(ValueError, match="changed; reload"):
        rpc(
            "save",
            **{k: review[k] for k in ("review", "digest", "expected_file_digest")},
            reason="stale",
        )
    (root / ".superqode/factory.yaml").write_text(text)
    # The fixture references this context document in its immutable snapshot.
    data = yaml.safe_load(text)
    context = next(v["path"] for v in data["data_context"]["files"].values())
    (root / context).write_text("changed")
    with pytest.raises(ValueError, match="components changed"):
        rpc(
            "save",
            **{k: review[k] for k in ("review", "digest", "expected_file_digest")},
            reason="stale",
        )


def test_templates_preserve_legacy_routes(studio):
    rpc, root, _ = studio
    routes = {"default_route": "special", "routes": {"special": {"model": "ollama/qwen3:8b"}}}
    (root / ".superqode/factory.yaml").write_text(yaml.safe_dump(routes))
    draft = yaml.safe_load(rpc("open", template="continuous-outcomes")["yaml"])
    assert draft["routes"] == routes["routes"] and draft["default_route"] == "special"


def test_inspection_exposes_inherited_models_without_changing_the_binding(studio):
    from superqode.harness.templates import core_template
    from superqode.harness.loader import harness_spec_to_dict

    rpc, root, _ = studio
    original = (root / ".superqode/factory.yaml").read_bytes()
    data = yaml.safe_load(rpc("open", template="fix-and-verify")["yaml"])
    data["inference"]["harnesses"]["coder"].pop("model")
    unselected = rpc("inspect", yaml=yaml.safe_dump(data))
    assert unselected["binding_models"]["coder"] == ""
    harness = harness_spec_to_dict(core_template())
    harness["model_policy"]["primary"] = "ollama/inherited-test-model"
    component = root / ".superqode/components/inherited.yaml"
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(yaml.safe_dump(harness))
    data["inference"]["harnesses"]["coder"] = {"path": ".superqode/components/inherited.yaml"}
    reviewed = rpc("inspect", yaml=yaml.safe_dump(data))
    assert reviewed["binding_models"]["coder"] == "ollama/inherited-test-model"
    assert "model" not in reviewed["bindings"]["coder"]
    assert (root / ".superqode/factory.yaml").read_bytes() == original


def test_generation_request_strips_runtime_overrides(studio):
    rpc, root, _ = studio
    text = rpc("open")["yaml"]
    safe = validate_request(
        root,
        dict(
            factory_action="generate",
            confirmed=True,
            yaml=text,
            description="Make a careful factory",
            provider="ollama",
            model="qwen3:8b",
            harness="evil",
            cwd="/",
            _desktop_api_key="secret",
            factory_providers=["evil"],
        ),
    )
    assert safe["factory_providers"] == ["ollama"]
    assert "harness" not in safe and "cwd" not in safe and "_desktop_api_key" not in safe
    with pytest.raises(ValueError, match="confirm"):
        validate_request(root, {"factory_action": "generate"})


def test_probe_supervisor_stops_when_controller_pipe_is_lost(tmp_path):
    from superqode.factory import probe_supervisor

    counter = tmp_path / "counter"
    code = "import pathlib,time; p=pathlib.Path('counter'); i=0\nwhile True:\n i+=1; p.write_text(str(i)); time.sleep(.03)"
    process = subprocess.Popen(
        [sys.executable, "-S", probe_supervisor.__file__],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        request = {
            "argv": [sys.executable, "-S", "-c", code],
            "cwd": str(tmp_path),
            "env": {},
            "stdin": "",
            "timeout": 30,
            "backend": "test-lifetime-only",
        }
        process.stdin.write(json.dumps(request).encode() + b"\n")
        process.stdin.flush()
        for _ in range(100):
            if counter.exists():
                break
            time.sleep(0.02)
        assert counter.exists()
        process.stdin.close()
        assert process.wait(timeout=3) == -signal.SIGKILL
        time.sleep(0.1)
        value = counter.read_text()
        time.sleep(0.15)
        assert counter.read_text() == value
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def test_generation_is_a_bounded_tool_free_proposal_and_preserves_authority(studio):
    from superqode.providers.gateway import GatewayResponse
    from superqode.factory.generation import generate_factory

    rpc, _, _ = studio
    original = rpc("open")["yaml"]
    calls = []

    class Gateway:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return GatewayResponse(
                content=json.dumps(
                    {
                        "yaml": original,
                        "assumptions": ["Fixture"],
                        "missing_capabilities": ["Add probes"],
                    }
                )
            )

    result = asyncio.run(
        generate_factory(
            description="Build a careful factory",
            yaml_text=original,
            provider="ollama",
            model="qwen3:8b",
            gateway=Gateway(),
        )
    )
    assert result["proposal_only"] and result["cost"] is None
    assert calls[0]["tools"] == [] and calls[0]["max_tokens"] == 6000
    assert len(calls[0]["messages"]) == 2
    assert rpc("open")["yaml"] == original

    # An authority change cannot be smuggled into an otherwise valid proposal.
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    public = base64.b64encode(
        key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ).decode()
    pinned = rpc("edit", yaml=original, controls={"public_key": public})["yaml"]
    with pytest.raises(ValueError, match="cannot change.*release authority"):
        asyncio.run(
            generate_factory(
                description="Build",
                yaml_text=pinned,
                provider="ollama",
                model="qwen3:8b",
                gateway=Gateway(),
            )
        )
    with pytest.raises(ValueError, match="private route"):
        asyncio.run(
            generate_factory(
                description="Build",
                yaml_text=original,
                provider="openai",
                model="gpt-4o",
                gateway=Gateway(),
            )
        )


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1",
    reason="Explicit native desktop job sandbox check",
)
def test_native_studio_verification_and_signed_delivery(project, tmp_path, monkeypatch):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from test_factory_definition import rewrite  # noqa: F401
    from test_factory_verification import make_completed  # noqa: F401
    from test_factory_release import signed  # noqa: F401

    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).decode()
    rewrite(
        project,
        lambda d: d["governance"].update(
            release_authority={
                "method": "p256-signature",
                "keys": {"fixture": {"public_key": public}},
                "challenge_ttl_seconds": 120,
            }
        ),
    )
    root, store, run = make_completed(project, monkeypatch)
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop-state")
    identity = service.open_project(str(root))["id"]

    def rpc(method, **params):
        return service.dispatch("factory." + method, {"project": identity, **params})

    def action(name, **params):
        job = rpc("action.start", factory_action=name, confirmed=True, run=run, **params)
        for _ in range(400):
            result = service.dispatch("jobs.get", {"id": job["id"]})
            if result["status"] not in {"queued", "running", "cancelling", "needs_approval"}:
                assert result["status"] == "completed", result
                return result["result"]
            time.sleep(0.05)
        pytest.fail("Factory desktop job did not finish")

    try:
        result = action("verify")
        assert result["verification_status"] == "passed", result
        assert result["record"]["decision"]["verdict"] == "hold"
        challenge = rpc("release.challenge", run=run, key_id="fixture")
        rpc("release.authorize", run=run, proof=signed(challenge, key))
        inspected = rpc("run.inspect", run=run)
        assert inspected["evidence"]
        assert (
            action(
                "apply",
                candidate_id=inspected["candidate_id"],
                candidate_digest=inspected["candidate_digest"],
            )["factory_state"]
            == "merged"
        )
        assert (root / "app.py").read_text() == "print(43)\n"
    finally:
        service.close()
