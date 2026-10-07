"""Observed route behavior, failure detection and honest unknown coverage."""

import json

import pytest
from click.testing import CliRunner

from superqode.governance import governance_scope
from superqode.harness.certification import (
    run_builtin_certification,
    _FixtureGateway,
    _runtime,
    _bundle,
    BuiltinCertificationReport,
    CertificationCheck,
)
from superqode.main import cli_main
from superqode.providers.gateway.base import GatewayResponse
from superqode.tools.base import ToolResult
from superqode.tools.file_tools import WriteFileTool


async def test_builtin_observations_pass_but_live_provider_remains_unknown():
    report = await run_builtin_certification()
    observed = [check for check in report.checks if check.name != "live-provider-behavior"]
    assert len(observed) == 8
    assert all(check.verdict == "supported" for check in observed), report.to_dict()
    assert report.checks[-1].verdict == "unknown"
    assert not report.complete
    assert not report.has_drift
    assert report.to_dict()["scope"] == "offline-runtime-boundaries"
    assert report.to_dict()["status"] == "incomplete"


async def test_certification_detects_a_tool_that_claims_success_without_writing(monkeypatch):
    async def lost_write(self, args, ctx):
        return ToolResult(True, "claimed success")

    monkeypatch.setattr(WriteFileTool, "execute", lost_write)
    report = await run_builtin_certification()
    file_check = next(check for check in report.checks if check.name == "file-tool-calling")
    assert file_check.verdict == "drift"


@pytest.mark.parametrize("action", ["deny", "ask"])
async def test_nonstreaming_final_response_is_not_saved_when_policy_blocks(tmp_path, action):
    gateway = _FixtureGateway([GatewayResponse(content="PRIVATE_ASSISTANT_MARKER")])
    runtime = _runtime(tmp_path, gateway, storage=True)
    with governance_scope(_bundle(action, phase="response", tool="*")):
        await runtime.run("Explain the fixture.")
    saved = runtime.loop._session_manager.get_messages()
    assert saved and all(message.content != "PRIVATE_ASSISTANT_MARKER" for message in saved)


def test_cli_saves_evidence_without_claiming_complete_certification(tmp_path):
    path = tmp_path / "evidence.json"
    result = CliRunner().invoke(
        cli_main, ["harness", "certify", "builtin", "--json", "--output", str(path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads(path.read_text())
    assert json.loads(result.output)["complete"] is False
    strict = CliRunner().invoke(
        cli_main, ["harness", "certify", "builtin", "--json", "--require-complete"]
    )
    assert strict.exit_code == 2
    assert json.loads(strict.output)["checks"][-1]["verdict"] == "unknown"


def test_cli_fails_on_observed_drift_even_with_unknown_checks(monkeypatch):
    async def failed():
        return BuiltinCertificationReport(
            (
                CertificationCheck("tool", "drift", "denial failed"),
                CertificationCheck("live", "unknown", "not observed"),
            )
        )

    monkeypatch.setattr("superqode.harness.certification.run_builtin_certification", failed)
    result = CliRunner().invoke(
        cli_main, ["harness", "certify", "builtin", "--json", "--require-complete"]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "failed"
