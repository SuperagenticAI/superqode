"""exo cluster discovery, model start and reviewed handoffs.

The fixtures follow exo's own wire format (exo-explore/exo main): ``GET /state``
serializes ``State`` with camelCase aliases and tags union members by class name,
``GET /v1/models`` lists the whole model catalogue, and ``?status=downloaded``
narrows it to completed downloads.
"""

import json
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import handoffs, local_runtimes
from superqode.local import runtimes

GB = 1024**3


def card(model, size):
    return {"modelId": model, "storageSize": {"inBytes": size}, "nLayers": 32}


def shard(model, size):
    return {"PipelineShardMetadata": {"modelCard": card(model, size), "startLayer": 0}}


def exo_state(*, downloads=True):
    state = {
        "instances": {
            "inst-1": {
                "MlxRingInstance": {
                    "instanceId": "inst-1",
                    "shardAssignments": {
                        "modelId": "mlx-community/Qwen3-30B-A3B-4bit",
                        "runnerToShard": {},
                        "nodeToRunner": {"node-a": "runner-1"},
                    },
                    "hostsByNode": {},
                    "ephemeralPort": 5000,
                }
            }
        },
        "topology": {"nodes": ["node-a", "node-b"], "connections": {}},
        "nodeIdentities": {
            "node-a": {"friendlyName": "Studio", "chipId": "Apple M3 Ultra"},
            "node-b": {"friendlyName": "Unknown", "chipId": "Unknown"},
            "node-gone": {"friendlyName": "Old laptop", "chipId": "Apple M1"},
        },
        "nodeMemory": {
            "node-a": {
                "ramTotal": {"inBytes": 192 * GB},
                "ramAvailable": {"inBytes": 120 * GB},
                "swapTotal": {"inBytes": 0},
                "swapAvailable": {"inBytes": 0},
            },
            "node-b": {
                "ramTotal": {"inBytes": 64 * GB},
                "ramAvailable": {"inBytes": 40 * GB},
                "swapTotal": {"inBytes": 0},
                "swapAvailable": {"inBytes": 0},
            },
        },
    }
    if downloads:
        state["downloads"] = {
            "node-a": [
                {
                    "DownloadCompleted": {
                        "nodeId": "node-a",
                        "shardMetadata": shard("mlx-community/Qwen3-30B-A3B-4bit", 17 * GB),
                        "total": {"inBytes": 17 * GB},
                    }
                },
                {
                    "DownloadCompleted": {
                        "nodeId": "node-a",
                        "shardMetadata": shard("mlx-community/Llama-3.2-3B-Instruct-4bit", 2 * GB),
                        "total": {"inBytes": 2 * GB},
                    }
                },
                {
                    "DownloadFailed": {
                        "nodeId": "node-a",
                        "shardMetadata": shard("mlx-community/broken", GB),
                        "errorMessage": "disk full",
                    }
                },
                {
                    "DownloadCompleted": {
                        "nodeId": "node-a",
                        "shardMetadata": shard("black-forest-labs/FLUX.1-schnell", 30 * GB),
                        "total": {"inBytes": 30 * GB},
                    }
                },
            ],
            "node-b": [
                {
                    "DownloadOngoing": {
                        "nodeId": "node-b",
                        "shardMetadata": shard("mlx-community/gpt-oss-20b-MXFP4-Q8", 12 * GB),
                        "downloadProgress": {
                            "total": {"inBytes": 12 * GB},
                            "downloaded": {"inBytes": 3 * GB},
                            "downloadedThisSession": {"inBytes": 3 * GB},
                            "completedFiles": 1,
                            "totalFiles": 4,
                            "speed": 1.0,
                            "etaMs": 1,
                            "files": {},
                        },
                    }
                },
                {
                    "DownloadCompleted": {
                        "nodeId": "node-b",
                        "shardMetadata": shard("mlx-community/Llama-3.2-3B-Instruct-4bit", 2 * GB),
                        "total": {"inBytes": 2 * GB},
                    }
                },
            ],
        }
    return state


CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "mlx-community/Qwen3-30B-A3B-4bit",
            "context_length": 40960,
            "storage_size_megabytes": 17408,
            "tasks": ["TextGeneration"],
        },
        {
            "id": "mlx-community/Llama-3.2-3B-Instruct-4bit",
            "context_length": 131072,
            "storage_size_megabytes": 2048,
            "tasks": ["TextGeneration"],
        },
        {
            "id": "mlx-community/gpt-oss-20b-MXFP4-Q8",
            "context_length": 131072,
            "storage_size_megabytes": 12288,
            "tasks": ["TextGeneration"],
        },
        {"id": "black-forest-labs/FLUX.1-schnell", "tasks": ["TextToImage"]},
        {
            "id": "mlx-community/DeepSeek-V3.1-8bit",
            "context_length": 163840,
            "storage_size_megabytes": 700000,
            "tasks": ["TextGeneration"],
        },
    ],
}


def exo_transport(state=None, *, downloaded=None, calls=None):
    def answer(request):
        if calls is not None:
            calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/state":
            if state is None:
                return httpx.Response(503)
            return httpx.Response(200, json=state)
        assert request.url.path == "/v1/models"
        if request.url.params.get("status") == "downloaded":
            ids = set(downloaded or [])
            return httpx.Response(
                200, json={"data": [row for row in CATALOG["data"] if row["id"] in ids]}
            )
        return httpx.Response(200, json=CATALOG)

    return httpx.MockTransport(answer)


def exo_spec(context=32768):
    data = {**asdict(runtimes.TEMPLATES[0]), "context": context}
    return runtimes.validate(data)


@pytest.mark.asyncio
async def test_exo_cluster_reads_nodes_memory_running_and_downloads_from_state():
    cluster = await runtimes.exo_cluster(exo_spec(), transport=exo_transport(exo_state()))
    assert cluster["node_count"] == 2, "Topology lists the connected nodes"
    assert [(n["name"], n["chip"]) for n in cluster["nodes"]] == [
        ("node-b", ""),
        ("Studio", "Apple M3 Ultra"),
    ]
    studio = cluster["nodes"][1]
    assert studio["ram_total_bytes"] == 192 * GB
    assert studio["ram_available_bytes"] == 120 * GB
    assert cluster["installed_memory_bytes"] == 256 * GB
    assert cluster["available_memory_bytes"] == 160 * GB
    assert cluster["deployed_models"] == ["mlx-community/Qwen3-30B-A3B-4bit"]
    downloads = cluster["downloads"]
    assert downloads["mlx-community/Llama-3.2-3B-Instruct-4bit"]["status"] == "downloaded"
    assert downloads["mlx-community/Llama-3.2-3B-Instruct-4bit"]["nodes"] == ["Studio", "node-b"]
    ongoing = downloads["mlx-community/gpt-oss-20b-MXFP4-Q8"]
    assert ongoing["status"] == "downloading"
    assert ongoing["progress"] == pytest.approx(0.25)
    assert "mlx-community/broken" not in downloads


@pytest.mark.asyncio
async def test_exo_catalog_lists_downloaded_and_running_models_but_offers_only_running():
    spec = exo_spec()
    catalog = await runtimes.model_catalog(spec, transport=exo_transport(exo_state()))
    rows = {row["id"]: row for row in catalog["exo_models"]}
    assert [row["id"] for row in catalog["exo_models"]] == [
        "mlx-community/Qwen3-30B-A3B-4bit",
        "mlx-community/Llama-3.2-3B-Instruct-4bit",
        "mlx-community/gpt-oss-20b-MXFP4-Q8",
    ]
    assert rows["mlx-community/Qwen3-30B-A3B-4bit"]["status"] == "running"
    assert rows["mlx-community/Llama-3.2-3B-Instruct-4bit"]["status"] == "downloaded"
    assert rows["mlx-community/Llama-3.2-3B-Instruct-4bit"]["size_bytes"] == 2 * GB
    assert rows["mlx-community/Llama-3.2-3B-Instruct-4bit"]["context"] == 32768
    assert rows["mlx-community/gpt-oss-20b-MXFP4-Q8"]["status"] == "downloading"
    assert "mlx-community/DeepSeek-V3.1-8bit" not in rows, "Catalogue-only models stay hidden"
    assert "black-forest-labs/FLUX.1-schnell" not in rows, "Image models are not chat models"
    assert [row["id"] for row in catalog["models"]] == ["mlx-community/Qwen3-30B-A3B-4bit"]
    assert [
        row["id"] for row in await runtimes.models(spec, transport=exo_transport(exo_state()))
    ] == ["mlx-community/Qwen3-30B-A3B-4bit"]


@pytest.mark.asyncio
async def test_exo_catalog_uses_downloaded_filter_when_state_has_no_downloads():
    calls = []
    transport = exo_transport(
        exo_state(downloads=False),
        downloaded=["mlx-community/Llama-3.2-3B-Instruct-4bit"],
        calls=calls,
    )
    catalog = await runtimes.model_catalog(exo_spec(), transport=transport)
    assert ("GET", "/v1/models", {"status": "downloaded"}) in calls
    assert [(r["id"], r["status"]) for r in catalog["exo_models"]] == [
        ("mlx-community/Qwen3-30B-A3B-4bit", "running"),
        ("mlx-community/Llama-3.2-3B-Instruct-4bit", "downloaded"),
    ]
    assert catalog["exo_models"][1]["size_bytes"] == 2048 * 1024 * 1024


@pytest.mark.asyncio
async def test_exo_catalog_never_dumps_the_whole_catalogue_when_state_fails():
    spec = exo_spec()
    catalog = await runtimes.model_catalog(spec, transport=exo_transport(None))
    assert catalog["models"] == [] and catalog["exo_models"] == []
    assert catalog["cluster"] is None
    assert "cluster state is unavailable" in catalog["cluster_error"]
    with pytest.raises(ValueError, match="cluster state is unavailable"):
        await runtimes.models(spec, transport=exo_transport(None))


def start_transport(previews, *, ready=True, place_status=200, calls=None):
    def answer(request):
        calls.append((request.method, request.url.path, dict(request.url.params), request.content))
        if request.url.path == "/instance/previews":
            return httpx.Response(200, json={"previews": previews})
        if request.url.path == "/place_instance":
            if place_status != 200:
                return httpx.Response(place_status, json={"detail": "Not enough memory"})
            return httpx.Response(200, json={"message": "Command received.", "command_id": "c"})
        if request.url.path == "/instance/await":
            message = (
                {"type": "ready", "instance": {}}
                if ready
                else {"type": "timeout", "message": "No instance found"}
            )
            body = ": keepalive\n\ndata: " + json.dumps(message) + "\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        raise AssertionError(request.url.path)

    return httpx.MockTransport(answer)


PREVIEWS = [
    {
        "model_id": "m",
        "sharding": "Tensor",
        "instance_meta": "MlxJaccl",
        "instance": None,
        "memory_delta_by_node": None,
        "error": "Requires RDMA",
    },
    {
        "model_id": "m",
        "sharding": "Pipeline",
        "instance_meta": "MlxRing",
        "instance": {"MlxRingInstance": {}},
        "memory_delta_by_node": {"node-a": 1, "node-b": 2},
        "error": None,
    },
]


@pytest.mark.asyncio
async def test_exo_start_places_the_first_fitting_preview_and_waits_until_ready():
    calls = []
    notes = []
    started = await runtimes.exo_start(
        exo_spec(),
        "m",
        "key",
        transport=start_transport(PREVIEWS, calls=calls),
        timeout=120,
        progress=notes.append,
    )
    assert started == {"model": "m", "nodes": 2}
    assert [call[1] for call in calls] == [
        "/instance/previews",
        "/place_instance",
        "/instance/await",
    ]
    assert calls[0][2] == {"model_id": "m"}
    assert json.loads(calls[1][3]) == {
        "model_id": "m",
        "sharding": "Pipeline",
        "instance_meta": "MlxRing",
        "min_nodes": 2,
    }
    assert calls[2][2] == {"model_id": "m", "timeout_seconds": "120"}
    assert notes[-1] == "Waiting for exo to load the model"


@pytest.mark.asyncio
async def test_exo_start_reports_placement_refusals_and_timeouts():
    with pytest.raises(ValueError, match="Requires RDMA"):
        await runtimes.exo_start(exo_spec(), "m", transport=start_transport(PREVIEWS[:1], calls=[]))
    with pytest.raises(ValueError, match="Not enough memory"):
        await runtimes.exo_start(
            exo_spec(), "m", transport=start_transport(PREVIEWS, place_status=400, calls=[])
        )
    with pytest.raises(ValueError, match="still loading"):
        await runtimes.exo_start(
            exo_spec(), "m", transport=start_transport(PREVIEWS, ready=False, calls=[])
        )
    with pytest.raises(ValueError, match="300 seconds"):
        await runtimes.exo_start(exo_spec(), "m", timeout=301)


@pytest.fixture
def exo_server():
    requests = []
    running = {"mlx-community/Qwen3-30B-A3B-4bit"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, payload, content="application/json"):
            body = payload if isinstance(payload, str) else json.dumps(payload)
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body.encode())))
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            url = urlsplit(self.path)
            requests.append(("GET", url.path, parse_qs(url.query)))
            if url.path == "/state":
                state = exo_state()
                for model in running - {"mlx-community/Qwen3-30B-A3B-4bit"}:
                    state["instances"]["inst-2"] = {
                        "MlxRingInstance": {"shardAssignments": {"modelId": model}}
                    }
                return self.reply(state)
            if url.path == "/v1/models":
                return self.reply(CATALOG)
            if url.path == "/instance/previews":
                return self.reply({"previews": PREVIEWS})
            if url.path == "/instance/await":
                return self.reply(
                    'data: {"type": "ready", "instance": {}}\n\n', "text/event-stream"
                )
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            url = urlsplit(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(("POST", url.path, body))
            running.add(body["model_id"])
            self.reply({"message": "Command received."})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_port}/v1", "requests": requests}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def save_exo(service, url):
    return service.dispatch(
        "local.runtimes.save",
        {
            "id": "exo-home",
            "name": "exo cluster",
            "template": "exo",
            "endpoint": url,
            "context": 16384,
        },
    )


def wait(service, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = service.dispatch("jobs.get", {"id": identity})
        if result["status"] not in {"running", "queued", "needs_approval", "cancelling"}:
            return result
        time.sleep(0.03)
    pytest.fail("exo start job did not finish")


def test_probe_and_start_a_downloaded_exo_model_as_a_job(desktop, exo_server, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(service.root))
    save_exo(service, exo_server["url"])
    probe = service.dispatch("local.runtimes.probe", {"id": "exo-home"})
    assert [r["id"] for r in probe["models"]] == ["mlx-community/Qwen3-30B-A3B-4bit"]
    assert {r["status"] for r in probe["exo_models"]} == {"running", "downloaded", "downloading"}
    assert [n["name"] for n in probe["cluster"]["nodes"]] == ["node-b", "Studio"]
    with pytest.raises(ValueError, match="already running"):
        service.dispatch(
            "local.runtimes.exo.start",
            {
                "id": "exo-home",
                "project": project["id"],
                "model": "mlx-community/Qwen3-30B-A3B-4bit",
            },
        )
    with pytest.raises(ValueError, match="finished downloading"):
        service.dispatch(
            "local.runtimes.exo.start",
            {
                "id": "exo-home",
                "project": project["id"],
                "model": "mlx-community/gpt-oss-20b-MXFP4-Q8",
            },
        )
    with pytest.raises(ValueError, match="finished downloading"):
        service.dispatch(
            "local.runtimes.exo.start",
            {
                "id": "exo-home",
                "project": project["id"],
                "model": "mlx-community/DeepSeek-V3.1-8bit",
            },
        )
    job = service.dispatch(
        "local.runtimes.exo.start",
        {
            "id": "exo-home",
            "project": project["id"],
            "model": "mlx-community/Llama-3.2-3B-Instruct-4bit",
        },
    )
    finished = wait(service, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["title"] == "Start exo model"
    assert finished["result"]["exo_started"]["nodes"] == 2
    placed = [r for r in exo_server["requests"] if r[0] == "POST"]
    assert placed == [
        (
            "POST",
            "/place_instance",
            {
                "model_id": "mlx-community/Llama-3.2-3B-Instruct-4bit",
                "sharding": "Pipeline",
                "instance_meta": "MlxRing",
                "min_nodes": 2,
            },
        )
    ]
    assert local_runtimes.read(service, "exo-home")["last_operation_job"] == job["id"]
    again = service.dispatch("local.runtimes.probe", {"id": "exo-home"})
    assert "mlx-community/Llama-3.2-3B-Instruct-4bit" in [r["id"] for r in again["models"]]


def add_job(service, project, job, *, status="completed", kind="task", request=None):
    request = {
        "prompt": "Fix add in calc.py",
        "harness": "silicon-demo",
        "provider": "apple-foundation",
        "interaction_mode": "code",
        **(request or {}),
    }
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (job, project, kind, "Fix add", status, json.dumps(request), None, 1, 1),
    )


HARNESSES = [
    {"id": "core", "name": "Core", "selectable": True, "backend": "builtin"},
    {"id": "silicon", "name": "Silicon Harness", "selectable": True, "backend": "builtin"},
    {"id": "silicon-demo", "name": "silicon-demo", "selectable": True, "backend": "builtin"},
]


def test_handoff_source_rules_and_harness_choice(desktop, monkeypatch):
    service, project, _ = desktop
    pid = project["id"]
    from superqode.desktop_service import local_models

    monkeypatch.setattr(local_models, "harnesses", lambda *_: HARNESSES)
    assert "Select a finished" in handoffs.source(service, pid, "")["reason"]
    add_job(service, pid, "live", status="running")
    assert "Wait for this turn" in handoffs.source(service, pid, "live")["reason"]
    service._write("UPDATE jobs SET status='completed' WHERE id='live'")
    add_job(service, pid, "chat", request={"interaction_mode": "chat"})
    assert "chat turn" in handoffs.source(service, pid, "chat")["reason"]
    add_job(service, pid, "check", kind="check")
    assert "coding turn" in handoffs.source(service, pid, "check")["reason"]
    add_job(service, "elsewhere", "other")
    assert "another project" in handoffs.source(service, pid, "other")["reason"]
    add_job(service, pid, "demo")
    kept = handoffs.source(service, pid, "demo")
    assert kept["ready"] and kept["harness"] == "silicon-demo" and kept["kept_harness"]
    add_job(service, pid, "acp", request={"harness": "acp:claude"})
    fallback = handoffs.source(service, pid, "acp")
    assert fallback["harness"] == "core" and not fallback["kept_harness"]
    add_job(service, pid, "busy", status="queued")
    assert "Finish the current run" in handoffs.source(service, pid, "demo")["reason"]


def test_handoff_targets_preview_and_start_through_exo(desktop, exo_server, monkeypatch):
    service, project, root = desktop
    pid = project["id"]
    from superqode.desktop_service import local_models

    monkeypatch.setattr(local_models, "harnesses", lambda *_: HARNESSES)
    add_job(service, pid, "demo")
    targets = service.dispatch("handoff.targets", {"project": pid, "job": "demo"})
    assert targets == {"source": targets["source"], "targets": []}
    assert targets["source"]["ready"] and targets["source"]["harness"] == "silicon-demo"
    save_exo(service, exo_server["url"])
    row = service.dispatch("handoff.targets", {"project": pid, "job": "demo"})["targets"][0]
    host = urlsplit(exo_server["url"]).netloc
    assert row["id"] == "exo:exo-home" and row["kind"] == "exo"
    assert row["title"] == f"exo cluster ({host})"
    assert not row["available"] and "tool check" in row["reason"]
    profile = local_runtimes.read(service, "exo-home")
    model = "mlx-community/Qwen3-30B-A3B-4bit"
    profile["checks"] = {
        model: {"digest": local_runtimes.validation_digest(profile), "tool_call_success": True}
    }
    local_runtimes.save(service, profile)
    row = service.dispatch("handoff.targets", {"project": pid, "job": "demo"})["targets"][0]
    assert row["available"] and row["reason"] == ""
    assert [m["id"] for m in row["models"]] == [model]
    with pytest.raises(ValueError, match="handoff target"):
        service.dispatch("handoff.preview", {"project": pid, "job": "demo", "target": "cloud:x"})
    preview = service.dispatch(
        "handoff.preview", {"project": pid, "job": "demo", "target": "exo:exo-home"}
    )
    assert preview["model"] == model and preview["harness"] == "silicon-demo"
    assert preview["destination"] == "On your network"
    assert "Objective: Fix add in calc.py" in preview["prompt"]
    submitted = []
    monkeypatch.setattr(
        service, "start", lambda project, kind, args: submitted.append((kind, args)) or {"id": "n"}
    )
    params = {
        "project": pid,
        "job": "demo",
        "target": "exo:exo-home",
        "model": model,
        "prompt": "Reviewed text",
        "command_id": "1",
    }
    with pytest.raises(ValueError, match="Review the handoff again"):
        service.dispatch("handoff.start", {**params, "digest": "stale"})
    with pytest.raises(ValueError, match="tool check"):
        service.dispatch(
            "handoff.start",
            {
                **params,
                "digest": preview["digest"],
                "model": "mlx-community/Llama-3.2-3B-Instruct-4bit",
            },
        )
    assert not submitted
    assert service.dispatch("handoff.start", {**params, "digest": preview["digest"]}) == {"id": "n"}
    kind, args = submitted[0]
    assert kind == "task"
    assert args["harness"] == "silicon-demo" and args["provider"] == "local-openai"
    assert args["model"] == model and args["prompt"] == "Reviewed text"
    assert args["permission_mode"] == "ask" and args["interaction_mode"] == "code"
    bound = service._all(
        "SELECT harness FROM local_runtime_bindings WHERE project=? AND runtime='exo-home'", (pid,)
    )
    assert {r["harness"] for r in bound} == {"silicon-demo", "no-tool"}


def test_handoff_targets_report_an_unreachable_exo(desktop, monkeypatch):
    service, project, _ = desktop
    save_exo(service, "http://127.0.0.1:9/v1")
    rows = service.dispatch("handoff.targets", {"project": project["id"], "job": ""})
    assert not rows["source"]["ready"]
    target = rows["targets"][0]
    assert not target["available"] and target["reason"]
    assert target["models"] == []
