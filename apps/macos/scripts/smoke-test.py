"""Launch the real SwiftUI app with an isolated engine and disposable project."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

requests = []
authorizations = []


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        requests.append(body)
        authorizations.append(self.headers.get("Authorization"))
        text = "Native task fixture: the Swift app is streaming the local harness engine."
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for content, finish in [(text, None), (None, "stop")]:
                chunk = {
                    "id": "native-fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content} if content else {},
                            "finish_reason": finish,
                        }
                    ],
                }
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "native-fixture",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "gpt-4o-mini",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": text},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                ).encode()
            )


server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
APP = Path(__file__).resolve().parents[1]
BINARY = (
    Path(os.environ.get("SUPERQODE_SMOKE_APP", str(APP / "release/SuperQode.app")))
    / "Contents/MacOS/SuperQode"
)
ARTIFACTS = Path(os.environ.get("SUPERQODE_SMOKE_ARTIFACTS", str(APP / "artifacts")))
ARTIFACTS.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="superqode-native-") as temporary:
    root = Path(temporary)
    project = root / "project"
    project.mkdir()
    (project / "README.md").write_text("# Native desktop smoke project\n")
    (root / "outside.txt").write_text("outside project boundary")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    report = root / "report.json"
    environment = {
        **os.environ,
        "OPENAI_API_BASE": f"http://127.0.0.1:{server.server_port}/v1",
        "OPENAI_API_KEY": "local-native-test-only",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "SUPERQODE_STATE_DIR": str(root / "state"),
        "SUPERQODE_SMOKE_REPORT": str(report),
    }
    try:
        result = subprocess.run(
            [
                str(BINARY),
                "--smoke-test",
                "--project",
                str(project),
                "--snapshot-dir",
                str(ARTIFACTS),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit(f"Native smoke timed out: {error.stderr}")
    if not report.exists():
        raise SystemExit(
            f"Native application returned {result.returncode} without a report: {result.stderr[-3000:]}"
        )
    evidence = json.loads(report.read_text())
    (ARTIFACTS / "smoke-report.json").write_text(json.dumps(evidence, indent=2))
    evidence["provider_requests"] = len(requests)
    if evidence.get("passed") and (
        len(requests) < 2
        or "Native task fixture" not in json.dumps(requests[-1].get("messages", []))
    ):
        evidence["passed"] = False
        evidence["error"] = "Follow-up did not include prior native session context"
    if evidence.get("passed") and authorizations != ["Bearer native-keychain-smoke-session"] * 2:
        evidence["passed"] = False
        evidence["error"] = "Native session credential did not reach the provider fixture"
    for artifact in (root / "state").rglob("*"):
        if artifact.is_file() and any(
            secret in artifact.read_bytes()
            for secret in (
                b"native-keychain-smoke-initial",
                b"native-keychain-smoke-updated",
                b"native-keychain-smoke-session",
            )
        ):
            evidence["passed"] = False
            evidence["error"] = "Credential persisted in engine state: " + artifact.name
    (ARTIFACTS / "smoke-report.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
    if not evidence.get("passed"):
        raise SystemExit(1)
