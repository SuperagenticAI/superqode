"""Opt-in pytest evidence: case outcomes and metadata-only mocked decision calls.

Load with ``-p systemone_evidence --decision-evidence=PATH``. No prompts,
responses, authentication values or provider error bodies are retained.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import threading

import httpx
import pytest

from superqode.systemone.providers import PROVIDERS


def request_metadata(request):
    definitions = {value.endpoint: value for value in PROVIDERS.values()}
    endpoint = str(request.url.copy_with(query=None, fragment=None))
    definition = definitions.get(endpoint)
    if definition is None and request.url.path != "/v1/systemone":
        return None
    try:
        body = json.loads(request.content)
    except (ValueError, UnicodeDecodeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    model = body.get("model")
    known = {model for provider in PROVIDERS.values() for model in provider.models}
    return {
        "provider": definition.id if definition else "typesafe-compatible-fixture",
        "model": model if isinstance(model, str) and model in known else "custom-or-fixture",
        "endpoint": definition.endpoint if definition else "loopback/SystemOne-compatible-fixture",
        "method": request.method,
        "question_count": len(body["questions"])
        if isinstance(body.get("questions"), (dict, list))
        else None,
        "transport": "httpx.MockTransport",
        "authentication": "x-goog-api-key"
        if "x-goog-api-key" in request.headers
        else "bearer"
        if "authorization" in request.headers
        else "none",
    }


def pytest_addoption(parser):
    parser.addoption(
        "--decision-evidence",
        default="",
        help="Write sanitized case and mocked decision API metadata to this JSON file",
    )


class Evidence:
    def __init__(self, output):
        self.output = Path(output)
        self.current = "outside-test-case"
        self.cases = {}
        self.requests = []
        self.lock = threading.Lock()
        self.original = None

    def pytest_sessionstart(self, session):
        self.original = httpx.MockTransport.handle_async_request
        evidence = self

        async def capture(transport, request):
            metadata = request_metadata(request)
            if metadata is None:
                return await evidence.original(transport, request)
            event = {
                **metadata,
                "test_case": evidence.current,
                "http_status": None,
                "error_type": None,
            }
            with evidence.lock:
                evidence.requests.append(event)
            try:
                response = await evidence.original(transport, request)
                event["http_status"] = response.status_code
                return response
            except BaseException as error:
                event["error_type"] = type(error).__name__
                raise

        httpx.MockTransport.handle_async_request = capture

    def pytest_runtest_setup(self, item):
        self.current = item.nodeid

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed or report.skipped:
            case = {
                "id": report.nodeid,
                "status": report.outcome,
                "duration_seconds": round(report.duration, 6),
            }
            if report.skipped and isinstance(report.longrepr, tuple):
                case["reason"] = str(report.longrepr[-1])[:300]
            self.cases[report.nodeid] = case

    def pytest_sessionfinish(self, session, exitstatus):
        if self.original is not None:
            httpx.MockTransport.handle_async_request = self.original
        root = Path(__file__).resolve().parents[1]
        code_paths = sorted(
            set(root.glob("src/superqode/systemone/*.py"))
            | set(root.glob("src/superqode/desktop_service/systemone.py"))
            | set(root.glob("tests/test_systemone*.py"))
            | {Path(__file__).resolve()}
        )
        modified = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"], cwd=root, text=True
        ).splitlines()
        code_paths = sorted(
            set(code_paths)
            | {
                root / path
                for path in modified
                if path.endswith((".py", ".swift")) and (root / path).is_file()
            }
        )
        hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in code_paths
        }
        cases = sorted(self.cases.values(), key=lambda case: case["id"])
        models = []
        for definition in PROVIDERS.values():
            for model in definition.models:
                live = next(
                    (
                        case
                        for case in cases
                        if "test_systemone_provider_live.py::test_live_native_decision_endpoint["
                        + definition.id
                        + "-"
                        + model
                        + "]"
                        in case["id"]
                    ),
                    None,
                )
                models.append(
                    {
                        "provider": definition.id,
                        "model": model,
                        "endpoint": definition.endpoint,
                        "live_validation": live["status"] if live else "not-collected",
                        "live_reason": live.get("reason") if live else None,
                    }
                )
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "os": platform.system(),
                "python": platform.python_version(),
                "execution": "local cloud workspace; GitHub CI was not used",
            },
            "source_base_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "source_files_sha256": hashes,
            "exit_status": int(exitstatus),
            "summary": {
                status: sum(case["status"] == status for case in cases)
                for status in ("passed", "failed", "skipped")
            },
            "decision_models": models,
            "limitations": [
                "Mocked HTTP verifies client contracts, not vendor entitlement or live model quality.",
                "Swift/macOS UI and Keychain need a Mac; they were not executed on this Linux host.",
            ],
            "cases": cases,
            "decision_api_attempts": self.requests,
        }
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def pytest_configure(config):
    if output := config.getoption("--decision-evidence"):
        config.pluginmanager.register(Evidence(output), "systemone-case-evidence")
