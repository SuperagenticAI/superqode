import io
import json
from types import SimpleNamespace

import pytest

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
