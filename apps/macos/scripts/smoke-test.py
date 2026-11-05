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


def fail_smoke(message):
    annotation = str(message)[-4000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error title=Native app smoke failed::" + annotation, flush=True)
    raise SystemExit(message)


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        requests.append(body)
        authorizations.append(self.headers.get("Authorization"))
        text = "Native task fixture: the Swift app is streaming the local harness engine."
        self.send_response(200)
        if self.path.endswith("/responses"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for index, packet in enumerate(
                [
                    {
                        "type": "response.output_text.delta",
                        "item_id": "message",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": text,
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "native-fixture",
                            "object": "response",
                            "status": "completed",
                            "output": [],
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                        },
                    },
                ]
            ):
                packet["sequence_number"] = index
                self.wfile.write(
                    ("event: " + packet["type"] + "\ndata: " + json.dumps(packet) + "\n\n").encode()
                )
            return
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
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Native Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Initial native fixture",
        ],
        check=True,
    )
    report = root / "report.json"
    environment = {
        **os.environ,
        "OPENAI_API_BASE": f"http://127.0.0.1:{server.server_port}/v1",
        "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "OPENAI_API_KEY": "local-native-test-only",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SUPERQODE_STATE_DIR": str(root / "state"),
        "SUPERQODE_SMOKE_REPORT": str(report),
    }
    # Exercise actual boot without --project, with an existing recent and a
    # saved editor destination. No clicks or provider requests are allowed.
    # Seed with the packaged interpreter and engine, not the runner's Python.
    runtime = BINARY.parent.parent / "Resources/runtime"
    previous = json.loads(
        subprocess.check_output(
            [
                str(runtime / "python/bin/python3"),
                "-B",
                "-c",
                "import json,sys; from superqode.desktop_service.service import DesktopService; "
                "fixture=DesktopService(sys.argv[1]); "
                "print(json.dumps(fixture.open_project(sys.argv[2]))); fixture.close()",
                str(root / "state"),
                str(project),
            ],
            env={**environment, "PYTHONPATH": str(runtime / "backend")},
            text=True,
        )
    )
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    destination = {
        "projectID": previous["id"],
        "projectPath": str(project),
        "conversationID": "",
        "jobID": "",
        "section": "Files",
        "filePath": "README.md",
        "inspectorVisible": False,
        "checkpointID": "",
        "checkpointPath": "",
        "showWelcome": False,
    }
    (recovery / "workspace-v1.json").write_text(
        json.dumps(
            {
                "version": 1,
                "lastDestination": destination,
                "destinations": {},
                "projectDestinations": {previous["id"]: destination},
                "composers": {},
                "editors": {},
                "transcripts": {},
                "migratedProjects": [],
            }
        )
    )
    welcome_report = root / "welcome-report.json"
    try:
        welcome_result = subprocess.run(
            [str(BINARY), "--smoke-test", "--welcome-only", "--snapshot-dir", str(ARTIFACTS)],
            env={
                **environment,
                "SUPERQODE_SMOKE_REPORT": str(welcome_report),
                "SUPERQODE_SMOKE_RECOVERY_DIRECTORY": str(recovery),
            },
            capture_output=True,
            text=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        fail_smoke("Welcome startup smoke timed out")
    if not welcome_report.exists():
        fail_smoke(f"Welcome startup returned no report: {welcome_result.stderr[-2000:]}")
    welcome_evidence = json.loads(welcome_report.read_text())
    (ARTIFACTS / "welcome-startup-report.json").write_text(json.dumps(welcome_evidence, indent=2))
    if welcome_result.returncode or not welcome_evidence.get("passed") or requests:
        fail_smoke(f"Welcome startup navigated or made provider requests: {welcome_evidence}")
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
        fail_smoke(f"Native smoke timed out: {error.stderr}")
    (ARTIFACTS / "native-app-stderr.log").write_text(result.stderr)
    if not report.exists():
        fail_smoke(
            f"Native application returned {result.returncode} without a report: {result.stderr[-3000:]}"
        )
    evidence = json.loads(report.read_text())
    evidence["welcome_startup"] = welcome_evidence["welcome_startup"]
    (ARTIFACTS / "smoke-report.json").write_text(json.dumps(evidence, indent=2))
    evidence["provider_requests"] = len(requests)
    if evidence.get("passed") and (
        len(requests) < 2
        or "Native task fixture"
        not in json.dumps(requests[-1].get("messages", requests[-1].get("input", [])))
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
        fail_smoke(evidence.get("error", "Native smoke reported failure without an explanation"))
    signature = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(BINARY.parent.parent.parent)],
        capture_output=True,
        text=True,
    )
    if signature.returncode:
        fail_smoke("Smoke run changed the signed app: " + signature.stderr[-3000:])
