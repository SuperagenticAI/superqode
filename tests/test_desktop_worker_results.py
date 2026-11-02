import io
import json
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from test_desktop_service import desktop


@pytest.mark.parametrize("payload", [None, [], "not a result"])
def test_zero_exit_without_result_object_does_not_claim_completion(desktop, payload):
    service, project, _ = desktop
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "empty-worker",
            project["id"],
            "check",
            "missing result",
            "running",
            "{}",
            None,
            1,
            1,
        ),
    )
    stdout = "" if payload is None else json.dumps({"type": "result", "data": payload}) + "\n"
    process = SimpleNamespace(stdout=io.StringIO(stdout), stdin=io.StringIO(), wait=lambda: 0)
    service._watch("empty-worker", process)
    result = service.dispatch("jobs.get", {"id": "empty-worker"})
    assert result["status"] == "failed"
    assert "terminal result" in result["result"]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events",
    [
        [],
        [("model_delta", {"text": "partial"})],
        [("turn_complete", {"status": "error", "error": "login failed"}), ("model_result", {})],
        [("turn_complete", {"status": "cancelled"})],
    ],
)
async def test_vendor_stream_failure_cannot_be_reported_completed(tmp_path, monkeypatch, events):
    from superqode.desktop_service.connection_worker import run_connection
    from superqode.harness.events import HarnessEvent

    async def stream(_):
        for name, data in events:
            yield HarnessEvent(type=name, data=data)

    close = AsyncMock()
    runtime = SimpleNamespace(run_harness_events=stream, aclose=close)
    monkeypatch.setattr("superqode.runtime.registry.create_runtime", lambda *a, **k: runtime)
    monkeypatch.setattr(
        "superqode.desktop_service.controls.inbox", lambda _: SimpleNamespace(bind=lambda _: None)
    )
    emitted = []
    with pytest.raises(RuntimeError):
        await run_connection(
            {
                "_desktop_connection": {
                    "kind": "runtime",
                    "id": "fixture",
                    "runtime": "copilot-sdk",
                },
                "cwd": str(tmp_path),
                "state_root": str(tmp_path),
                "prompt": "fixture",
            },
            tmp_path,
            lambda name, data: emitted.append((name, data)),
            (),
        )
    assert not any(name == "result" for name, _ in emitted)
    close.assert_awaited_once()
