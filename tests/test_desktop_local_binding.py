import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_desktop_service import desktop, wait_job  # noqa: F401
from superqode.desktop_service import local_models


def test_selected_local_endpoint_survives_harness_switch_and_no_tool_test(desktop, monkeypatch):
    service, project, _ = desktop
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [
                ({"role": "assistant", "content": "Local endpoint fixture done."}, None),
                ({}, "stop"),
            ]:
                packet = {
                    "id": "local-fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setattr(
        local_models,
        "available",
        lambda engine: {"endpoint": endpoint, "provider": "lmstudio", "models": ["fixture-model"]},
    )
    try:
        service.dispatch(
            "local.models.use",
            {
                "project": project["id"],
                "engine": "lmstudio",
                "harness": "core",
                "model": "fixture-model",
            },
        )
        assert (
            local_models.binding(service, project["id"], "rlm", "lmstudio", "fixture-model")[0][
                "endpoint"
            ]
            == endpoint
        )
        assert not local_models.binding(service, project["id"], "rlm", "openai", "fixture-model")
        for harness in ["core", "no-tool"]:
            started = service.dispatch(
                "tasks.start",
                {
                    "project": project["id"],
                    "harness": harness,
                    "provider": "lmstudio",
                    "model": "fixture-model",
                    "prompt": "Reply briefly.",
                    "command_id": "binding-" + harness,
                },
            )
            completed = wait_job(service, started["id"])
            assert completed["status"] == "completed", completed
        assert len(requests) == 2
        service.dispatch(
            "local.models.clear_binding",
            {"project": project["id"], "provider": "lmstudio", "model": "fixture-model"},
        )
        assert not local_models.binding(service, project["id"], "core", "lmstudio", "fixture-model")
    finally:
        server.shutdown()
        server.server_close()
