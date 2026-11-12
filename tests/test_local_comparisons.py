"""Actual desktop model/harness comparisons with independent repository grades."""

import json
import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import local_comparisons


@pytest.fixture
def models():
    requests = []
    token = "private-comparison-key"
    controls = {"change_revision": False, "changed": False}
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer " + token
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "data": [
                            {
                                "id": model,
                                "revision": hashlib.sha256(
                                    (model + str(controls["changed"])).encode()
                                ).hexdigest(),
                            }
                            for model in ("good", "bad", "error", "wait")
                        ]
                    }
                ).encode()
            )

        def do_POST(self):
            assert self.headers.get("Authorization") == "Bearer " + token
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if controls["change_revision"]:
                controls["changed"] = True
            if body["model"] == "wait":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"starting"}}]}\n\n')
                self.wfile.flush()
                release.wait(30)
                return
            if body["model"] == "error":
                self.send_response(400)
                self.end_headers()
                return
            functions = {t["function"]["name"]: t["function"] for t in body.get("tools", [])}
            name = next((n for n in ("write", "write_file") if n in functions), None)
            message = {"content": "Done"}
            reason = "stop"
            if name and not any(m.get("role") == "tool" for m in body["messages"]):
                code = "def clamp(v,lo,hi):\n if lo>hi: raise ValueError()\n return max(lo,min(v,hi))\ndef unique_names(values):\n out=[]; seen=set()\n for s in values:\n  s=s.strip()\n  if s and s.casefold() not in seen:\n   out.append(s); seen.add(s.casefold())\n return out\n"
                if body["model"] == "bad":
                    code = "def clamp(*a): return 0\ndef unique_names(*a): return []\n"
                fields = functions[name]["parameters"]["properties"]
                path_field = "path" if "path" in fields else "file_path"
                message = {
                    "tool_calls": [
                        {
                            "id": "write-case",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    {path_field: "sq_local_trial.py", "content": code}
                                ),
                            },
                        }
                    ]
                }
                reason = "tool_calls"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [{"message": message, "finish_reason": reason}],
                        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "endpoint": f"http://127.0.0.1:{server.server_port}/v1",
            "key": token,
            "requests": requests,
            "controls": controls,
        }
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.fixture
def configured(desktop, models, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(service.root))
    monkeypatch.setattr(
        "superqode.desktop_service.local_models.available",
        lambda *_: {"models": [], "endpoint": "http://127.0.0.1:9/v1"},
    )
    service.dispatch(
        "local.runtimes.save",
        {"id": "comparison", "endpoint": models["endpoint"], "context": 4096, "tools": True},
    )
    service.dispatch("local.runtimes.key", {"id": "comparison", "key": models["key"]})
    catalog = service.dispatch("local.comparisons.catalog", {"project": project["id"]})
    routes = {r["model"]: r["id"] for r in catalog["routes"]}
    params = {
        "project": project["id"],
        "selections": [
            {"route": routes["good"], "harness": "core"},
            {"route": routes["bad"], "harness": "core"},
        ],
        "context": 4096,
        "warmup": False,
    }
    return service, project, root, params


def wait(service, identity):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        value = service.dispatch("jobs.get", {"id": identity})
        if value["status"] not in {"running", "queued", "needs_approval", "cancelling"}:
            return value
        time.sleep(0.03)
    pytest.fail("Comparison worker did not finish")


def test_review_then_real_worker_grades_models_independently_without_changing_project(
    configured, models
):
    service, project, root, params = configured
    (root / "README.md").write_text("PRESERVE_ME")
    plan = service.dispatch("local.comparisons.prepare", params)
    assert not models["requests"], "Review must not send prompts or execute model-written code"
    assert "suite_content" not in plan and all("harness_yaml" not in r for r in plan["routes"])
    start = {
        "project": project["id"],
        "plan": plan["id"],
        "expected_digest": plan["digest"],
        "execute": True,
        "command_id": "compare-real",
    }
    job = service.dispatch("local.comparisons.start", start)
    assert service.dispatch("local.comparisons.start", start)["id"] == job["id"]
    completed = wait(service, job["id"])
    assert completed["status"] == "completed", completed
    result = completed["result"]
    assert [v["passed"] for v in result["variants"]] == [2, 0], result
    assert result["comparison"]["candidates"][0]["counts"]["regression"] == 2
    assert all(
        t["workspace"]["snapshot_sha256"] == result["workspace"]["snapshot_sha256"]
        for v in result["variants"]
        for t in v["tasks"]
    )
    assert all(v["model_requests"] for v in result["variants"])
    assert all(v["local_configuration"]["identity_verified"] for v in result["variants"])
    assert all(b["max_tokens"] <= 1024 for b in models["requests"])
    assert not (root / "sq_local_trial.py").exists()
    assert (root / "README.md").read_text() == "PRESERVE_ME"
    history = service.dispatch("local.comparisons.history", {"project": project["id"]})
    assert history[0]["id"] == job["id"] and "result" not in history[0]
    assert models["key"] not in "\n".join(service.db.iterdump())
    assert models["key"] not in (service.root / (job["id"] + ".log")).read_text()


def test_stale_review_and_credentials_refuse_start_before_generation(configured, models):
    service, project, _, params = configured
    plan = service.dispatch("local.comparisons.prepare", params)
    request = {
        "project": project["id"],
        "plan": plan["id"],
        "expected_digest": "stale",
        "execute": True,
    }
    with pytest.raises(ValueError, match="digest"):
        service.dispatch("local.comparisons.start", request)
    request["expected_digest"] = plan["digest"]
    service.dispatch("local.runtimes.key", {"id": "comparison", "key": "changed"})
    with pytest.raises(ValueError, match="credentials changed"):
        service.dispatch("local.comparisons.start", request)
    assert not models["requests"]


def test_shared_context_and_identical_candidates_are_rejected(configured):
    service, _, _, params = configured
    with pytest.raises(ValueError, match="configured cap"):
        service.dispatch("local.comparisons.prepare", {**params, "context": 8192})
    with pytest.raises(ValueError, match="different"):
        service.dispatch(
            "local.comparisons.prepare", {**params, "selections": [params["selections"][0]] * 2}
        )


def test_immutable_identity_distinguishes_artifact_changes_from_residency_metadata():
    digest = "a" * 64
    assert not local_comparisons.identity_changed(
        {"digest": digest, "size": 4}, {"digest": digest, "size": 8}
    )
    assert local_comparisons.identity_changed({"digest": digest}, {"digest": "b" * 64})
    assert local_comparisons.identity_changed({"quantization": "Q4"}, {"quantization": "Q8"})
    assert not local_comparisons.identity_changed(None, {"digest": digest})
    assert local_comparisons.immutable_identity({"revision": "main"}) is None


def test_review_budget_does_not_mutate_the_source_harness_definition(configured, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from superqode.harness.catalog import resolve_harness

    service, _, _, params = configured
    available = local_comparisons.catalog(service, params["project"])
    base = resolve_harness("core").spec
    original = deepcopy(base.model_policy.config)
    monkeypatch.setattr(local_comparisons, "catalog", lambda *_: available)
    monkeypatch.setattr(
        "superqode.harness.catalog.resolve_harness",
        lambda *a, **k: SimpleNamespace(spec=base, digest="source-digest"),
    )
    service.dispatch("local.comparisons.prepare", params)
    assert base.model_policy.config == original, (
        "Review must not change a shared harness's iteration budget"
    )


@pytest.mark.parametrize("nested", [False, True])
def test_explicit_rlm_child_routes_cannot_escape_the_selected_model_comparison(
    configured, monkeypatch, nested
):
    from dataclasses import replace
    from types import SimpleNamespace
    from superqode.harness.catalog import resolve_harness

    service, _, _, params = configured
    available = local_comparisons.catalog(service, params["project"])
    base = resolve_harness("core").spec
    child = {"sub_provider": "google", "sub_model": "cloud-model"}
    runtime = replace(base.runtime, backend="rlm", config={"rlm_code": child} if nested else child)
    monkeypatch.setattr(local_comparisons, "catalog", lambda *_: available)
    monkeypatch.setattr(
        "superqode.harness.catalog.resolve_harness",
        lambda *a, **k: SimpleNamespace(spec=replace(base, runtime=runtime), digest="test"),
    )
    with pytest.raises(ValueError, match="child model routes"):
        service.dispatch("local.comparisons.prepare", params)


def test_error_candidate_is_recorded_without_losing_baseline_results(configured):
    service, project, _, params = configured
    route = next(
        r
        for r in service.dispatch("local.comparisons.catalog", {"project": project["id"]})["routes"]
        if r["model"] == "error"
    )
    params["selections"][1]["route"] = route["id"]
    plan = service.dispatch("local.comparisons.prepare", params)
    job = service.dispatch(
        "local.comparisons.start",
        {
            "project": project["id"],
            "plan": plan["id"],
            "expected_digest": plan["digest"],
            "execute": True,
        },
    )
    completed = wait(service, job["id"])
    assert completed["status"] == "completed", completed
    assert completed["result"]["variants"][0]["passed"] == 2
    assert completed["result"]["variants"][1]["errors"] == 2


def test_revision_change_disables_adoption_comparison(configured, models):
    service, project, _, params = configured
    plan = service.dispatch("local.comparisons.prepare", params)
    models["controls"]["change_revision"] = True
    job = service.dispatch(
        "local.comparisons.start",
        {
            "project": project["id"],
            "plan": plan["id"],
            "expected_digest": plan["digest"],
            "execute": True,
        },
    )
    completed = wait(service, job["id"])
    assert completed["status"] == "completed", completed
    assert completed["result"]["comparison"]["available"] is False
    assert "artifact changed" in completed["result"]["comparison"]["message"]


def test_stop_cancels_a_model_wait_in_the_supervised_comparison_job(configured, models):
    service, project, _, params = configured
    route = next(
        r
        for r in service.dispatch("local.comparisons.catalog", {"project": project["id"]})["routes"]
        if r["model"] == "wait"
    )
    params["selections"][0]["route"] = route["id"]
    plan = service.dispatch("local.comparisons.prepare", params)
    job = service.dispatch(
        "local.comparisons.start",
        {
            "project": project["id"],
            "plan": plan["id"],
            "expected_digest": plan["digest"],
            "execute": True,
        },
    )
    deadline = time.monotonic() + 8
    while not any(r["model"] == "wait" for r in models["requests"]) and time.monotonic() < deadline:
        time.sleep(0.03)
    assert any(r["model"] == "wait" for r in models["requests"])
    service.dispatch("jobs.cancel", {"id": job["id"]})
    assert wait(service, job["id"])["status"] == "cancelled"
