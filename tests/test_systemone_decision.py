"""Decision flavor and systemone harness backend. Stub only."""

from __future__ import annotations

import json
from pathlib import Path

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.registry import create_harness_backend, inspect_harness_backend
from superqode.harness.loader import harness_spec_from_dict, load_harness_spec
from superqode.harness.spec import HarnessFlavor


def test_decision_flavor_round_trips():
    spec = harness_spec_from_dict(
        {
            "name": "tool-gate",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "stub", "pack": "tool_gate"},
        }
    )
    assert spec.flavor is HarnessFlavor.DECISION
    assert spec.is_decision is True
    assert spec.is_coding is False
    inspection = inspect_harness_backend("systemone", spec)
    assert inspection.ok
    assert inspection.capabilities.supports_decision is True


def test_builtin_backend_rejects_decision_flavor():
    spec = harness_spec_from_dict(
        {
            "name": "tool-gate",
            "flavor": "decision",
            "runtime": {"backend": "builtin"},
            "systemone": {"enabled": True},
        }
    )
    inspection = inspect_harness_backend("builtin", spec)
    assert inspection.ok is False
    assert any(issue.code == "decision_unsupported" for issue in inspection.issues)


def test_example_decision_spec_loads():
    path = Path("examples/harnesses/systemone-tool-gate.yaml")
    spec = load_harness_spec(path)
    assert spec.flavor is HarnessFlavor.DECISION
    assert spec.runtime.backend == "systemone"
    assert spec.systemone.pack == "tool_gate"
    assert spec.systemone.client == "live"


async def test_live_backend_without_key_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    spec = harness_spec_from_dict(
        {
            "name": "tool-gate",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "live", "pack": "tool_gate"},
        }
    )
    backend = create_harness_backend("systemone")
    request = HarnessBackendRequest(
        spec=spec,
        prompt='{"tool":"bash","arguments":{"command":"pytest"}}',
        provider="none",
        model="none",
        working_directory=tmp_path,
    )
    import pytest

    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        await backend.run(request)


async def test_systemone_backend_evaluates_stub_state(tmp_path):
    spec = harness_spec_from_dict(
        {
            "name": "tool-gate",
            "flavor": "decision",
            "runtime": {"backend": "systemone"},
            "systemone": {"enabled": True, "client": "stub", "pack": "tool_gate"},
        }
    )
    backend = create_harness_backend("systemone")
    request = HarnessBackendRequest(
        spec=spec,
        prompt=json.dumps(
            {
                "tool": "bash",
                "arguments": {"command": "pytest"},
                "task": "run tests",
            }
        ),
        provider="none",
        model="none",
        working_directory=tmp_path,
    )
    result = await backend.run(request)
    payload = json.loads(result.response.content)
    assert payload["action"] in {"allow", "deny", "ask"}
    assert payload["metadata"]["pack"].startswith("tool_gate@")
