"""Shared Factory contracts for acceptance, intake decisions and observed outcomes."""
# ruff: noqa: F401, F811

import asyncio
from dataclasses import replace
import json
import os
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from test_factory_definition import project, rewrite, admitted
from test_factory_intake import configured, event, SECRET
from test_factory_studio import studio
from test_factory_verification import make_completed, simulated_probes
from superqode.commands.factory import factory
from superqode.factory import evidence, intake, verifiers, verification
from superqode.factory.definition import load_factory
from superqode.factory.maintenance import execution
from superqode.factory.runtime import factory_store


def requirements(root):
    rewrite(
        root,
        lambda d: d["data_context"].update(
            requirements={
                "correct-answer": {
                    "description": "Return the corrected answer",
                    "stages": ["implement", "verify"],
                    "checks": ["regression"],
                }
            }
        ),
    )
    rewrite(root, lambda d: d["improvement"]["checks"]["regression"].update(category="health"))


def checks():
    return {
        "regression": {
            "format": "superqode.factory-probes/1",
            "cases": [{"id": "answer", "argv": ["python", "app.py"], "stdout": "43\n"}],
        }
    }


def test_requirement_unknown_stage_or_nonacceptance_check_is_rejected(project):
    requirements(project)
    rewrite(
        project,
        lambda d: d["data_context"]["requirements"]["correct-answer"].update(stages=["missing"]),
    )
    with pytest.raises(ValueError, match="unknown stage"):
        load_factory(root=project)


def test_trace_requires_actual_check_evidence_and_retains_artifact_links(
    project, monkeypatch, simulated_probes
):
    requirements(project)
    root, store, run = make_completed(project, monkeypatch)
    before = evidence.trace(root, run)
    assert before["covered"] == 0 and before["application_checks"][0]["status"] == "missing"
    result = verification.verify_factory(run, root=root)
    row = result["traceability"]["requirements"][0]
    assert row["status"] == "covered"
    assert row["checks"][0]["category"] == "health"
    assert row["checks"][0]["verification_artifact"]
    assert any(s["artifacts"] for s in row["stages"])
    assert not result["traceability"]["release_authorized"]
    assert any(a.kind == "factory_requirement_trace" for a in store.get(run).artifacts)
    store.add_artifact(run, kind="integration_candidate", content="new candidate", actor="fixture")
    stale = evidence.trace(root, run)
    assert stale["covered"] == 0
    assert stale["application_checks"][0]["status"] == "missing"


def test_verifier_draft_install_requires_exact_review_and_source(project):
    old = (project / ".superqode/factory.yaml").read_bytes()
    proposal = verifiers.draft(project, checks())
    assert (project / ".superqode/factory.yaml").read_bytes() == old
    assert all(not (project / p).exists() for p in proposal["files"])
    with pytest.raises(ValueError, match="confirm"):
        verifiers.install(project, proposal, expected=proposal["digest"])
    changed = {**proposal, "yaml": proposal["yaml"] + "\n"}
    with pytest.raises(ValueError, match="changed"):
        verifiers.install(project, changed, expected=proposal["digest"], confirmed=True)
    with execution(project):
        with pytest.raises(ValueError, match="owns"):
            verifiers.install(project, proposal, expected=proposal["digest"], confirmed=True)
    result = verifiers.install(project, proposal, expected=proposal["digest"], confirmed=True)
    assert result["saved"] and not result["execution_started"]
    assert all((project / p).read_text() == text for p, text in proposal["files"].items())
    with pytest.raises(ValueError, match="changed"):
        verifiers.install(project, proposal, expected=proposal["digest"], confirmed=True)


def test_verifier_generation_uses_route_and_never_executes_or_writes(project):
    class Gateway:
        async def chat_completion(self, **kwargs):
            assert kwargs["tools"] == []
            assert "no sockets" in kwargs["messages"][0].content
            return SimpleNamespace(content=json.dumps({"checks": checks()}), usage=None, cost=None)

    with pytest.raises(ValueError, match="local drafting model"):
        asyncio.run(
            verifiers.generate(
                project,
                description="Check the answer",
                provider="openai",
                model="gpt-5",
                gateway=Gateway(),
            )
        )
    result = asyncio.run(
        verifiers.generate(
            project,
            description="Check the answer",
            provider="ollama",
            model="qwen3-coder",
            gateway=Gateway(),
        )
    )
    assert result["proposal"]["proposal_only"]
    assert all(not (project / p).exists() for p in result["proposal"]["files"])


def test_verifier_rejects_unknown_checks_and_unprotected_commands(project):
    with pytest.raises(ValueError, match="existing final"):
        verifiers.draft(project, {"invented": checks()["regression"]})
    bad = checks()
    bad["regression"]["cases"][0]["argv"] = ["sh", "-c", "true"]
    with pytest.raises(ValueError, match="python"):
        verifiers.draft(project, bad)


def test_ai_reports_unsupported_service_requirements_without_a_fake_pass(project):
    class Gateway:
        async def chat_completion(self, **kwargs):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "checks": {},
                        "assumptions": [],
                        "missing_capabilities": [
                            "External database health requires an explicit service execution contract"
                        ],
                    }
                ),
                usage=None,
                cost=None,
            )

    result = asyncio.run(
        verifiers.generate(
            project,
            description="Verify external database health",
            provider="ollama",
            model="qwen3-coder",
            gateway=Gateway(),
        )
    )
    assert result["proposal"] is None
    assert result["missing_capabilities"]


def test_intake_receipts_explain_filter_duplicate_conflict_and_do_not_store_payloads(configured):
    root = configured
    raw, headers = event()
    with pytest.raises(ValueError, match="authentication"):
        intake.receive(root, "github", raw, {})
    assert not intake.receipts(root)["decisions"]
    result = intake.receive(root, "github", raw, headers)
    intake.receive(root, "github", raw, headers)
    filtered, filtered_headers = event(action="deleted")
    with pytest.raises(ValueError):
        intake.receive(root, "github", filtered, filtered_headers)
    conflict, conflict_headers = event(issue={"title": "sensitive title should never be retained"})
    with pytest.raises(ValueError, match="different payload"):
        intake.receive(root, "github", conflict, conflict_headers)
    value = intake.receipts(root)
    assert {r["status"] for r in value["decisions"]} == {
        "queued",
        "duplicate",
        "filtered",
        "rejected",
    }
    text = json.dumps(value)
    assert SECRET not in text and "sensitive title" not in text and "signature" not in text
    assert any(r["run"] == result["work_order_id"] for r in value["decisions"])


def test_intake_receipts_are_bounded_and_repeated_decisions_coalesce(configured):
    for i in range(260):
        intake._receipt(configured, "monitor", str(i).encode(), "rejected", "stale_event")
    assert len(intake.receipts(configured)["decisions"]) == 256
    intake._receipt(configured, "monitor", b"259", "rejected", "stale_event")
    assert intake.receipts(configured)["decisions"][-1]["count"] == 2


def test_outcomes_preserve_unknown_costs_and_idempotency(project):
    plan, store, order = admitted(project)
    with pytest.raises(ValueError, match="finished"):
        evidence.record_outcome(
            project, order.work_order_id, observation="pilot-1", outcome="met", actor="test"
        )
    store.cancel(order.work_order_id, actor="test", reason="Fixture finished")
    args = dict(observation="pilot-1", outcome="met", human_minutes=12.5, actor="test")
    row = evidence.record_outcome(project, order.work_order_id, **args)
    assert row == evidence.record_outcome(project, order.work_order_id, **args)
    assert row["usage"]["cost_usd"] is None and row["operator_reported"]
    summary = evidence.outcomes(project)
    assert summary["revisions"][0]["human_minutes"] == 12.5
    assert summary["revisions"][0]["cost_usd"] is None
    with pytest.raises(ValueError, match="different outcome"):
        evidence.record_outcome(project, order.work_order_id, **{**args, "outcome": "not_met"})
    with pytest.raises(ValueError, match="count it twice"):
        evidence.record_outcome(project, order.work_order_id, **{**args, "observation": "second"})


def test_outcome_cost_and_human_unknown_are_kept_separate(project):
    _, store, order = admitted(project)
    store.add_artifact(
        order.work_order_id,
        kind="usage",
        metadata={"usage": {"cost_usd": 0.15, "cost_currency": "USD", "total_tokens": 120}},
        actor="fixture",
    )
    store.cancel(order.work_order_id, actor="test", reason="Fixture finished")
    evidence.record_outcome(
        project, order.work_order_id, observation="pilot-1", outcome="not_met", actor="test"
    )
    row = evidence.outcomes(project)["revisions"][0]
    assert row["cost_usd"] == 0.15 and row["total_tokens"] == 120
    assert row["human_minutes"] is None


def test_cli_and_desktop_share_verifier_drafts(studio):
    rpc, root, _ = studio
    proposal = rpc("verifier.draft", checks=checks())
    assert proposal["proposal_only"]
    result = rpc("verifier.install", proposal=proposal, digest=proposal["digest"], confirmed=True)
    assert result["saved"]
    assert rpc("intake.receipts")["decisions"] == []
    cli = CliRunner().invoke(factory, ["intake", "receipts", "--project", str(root)])
    assert cli.exit_code == 0, cli.output


def test_mcp_new_tools_preserve_confirmation_and_execution_boundaries(project):
    from superqode.mcp.factory_server import build_factory_mcp_server

    server = build_factory_mcp_server(project)

    async def check():
        names = {tool.name for tool in await server.list_tools()}
        assert {
            "factory_evidence_trace",
            "factory_outcomes",
            "factory_verifier_draft",
            "factory_intake_receipts",
        } <= names
        with pytest.raises(Exception, match="confirm"):
            await server.call_tool("factory_verifier_install", {"proposal": {}, "digest": "x"})
        with pytest.raises(Exception, match="allow-execution"):
            await server.call_tool(
                "factory_verifier_generate",
                {
                    "description": "Check startup",
                    "provider": "ollama",
                    "model": "qwen3-coder",
                    "confirmed": True,
                },
            )
        assert await server.call_tool("factory_verifier_draft", {"checks": checks()}) is not None

    asyncio.run(check())


def test_desktop_verifier_generation_is_a_confirmed_background_action(studio):
    from superqode.desktop_service.factory_studio import validate_request

    _, root, service = studio
    params = {
        "factory_action": "verifier-generate",
        "description": "Check startup",
        "yaml": (root / ".superqode/factory.yaml").read_text(),
        "provider": "ollama",
        "model": "qwen3-coder",
    }
    with pytest.raises(ValueError, match="confirm"):
        validate_request(root, params, service=service)
    result = validate_request(root, {**params, "confirmed": True}, service=service)
    assert result["factory_action"] == "verifier-generate"
    assert result["factory_providers"] == ["ollama"]


def test_trace_and_observations_reject_foreign_project_orders(project, tmp_path):
    _, store, order = admitted(project)
    foreign = replace(order, repository=str(tmp_path / "another-project"))
    with store._transaction() as conn:
        store._save_tx(conn, foreign)
    with pytest.raises(ValueError, match="different project"):
        evidence.trace(project, order.work_order_id)


def test_checkpoint_preserves_bounded_intake_decisions(configured):
    from superqode.factory import recovery

    raw, headers = event()
    intake.receive(configured, "github", raw, headers)
    expected = (configured / ".superqode/factory-intake/receipts.json").read_bytes()
    package = recovery.create(configured)
    _, entries = recovery.decode(package["path"], package["key_file"], package["sha256"])
    assert entries[".superqode/factory-intake/receipts.json"] == expected


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Actual protected OS probes"
)
@pytest.mark.parametrize("application,passed", [("print(43)\n", True), ("broken syntax\n", False)])
def test_native_generated_verifier_checks_application_startup(
    project, monkeypatch, application, passed
):
    from superqode.workorders import runner

    requirements(project)
    rewrite(
        project,
        lambda d: (
            d["improvement"]["checks"].update(
                build={"category": "build", "command": "python -m compileall ."}
            ),
            d["orchestration"]["acceptance_checks"].append("build"),
        ),
    )
    rewrite(project, lambda d: d["orchestration"]["stages"][2].update(human_gate=False))
    manifests = checks()
    manifests["build"] = {
        "format": "superqode.factory-probes/1",
        "cases": [
            {
                "id": "syntax",
                "argv": [
                    "python",
                    "-c",
                    "import ast; ast.parse(open('app.py').read()); print('READY')",
                ],
                "stdout": "READY\n",
            }
        ],
    }
    proposal = verifiers.draft(project, manifests)
    verifiers.install(project, proposal, expected=proposal["digest"], confirmed=True)
    _, store, order = admitted(project)

    async def execute(order, task, *, working_directory, **kwargs):
        if task.task_id == "implement":
            (working_directory / "app.py").write_text(application)
        return {"content": "Fixture completed", "stopped_reason": "complete", "tool_calls": 0}

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    results = asyncio.run(runner.run_until_idle(store, work_order_id=order.work_order_id))
    assert all(row.status == "succeeded" for row in results), results
    result = verification.verify_factory(order.work_order_id, root=project)
    assert result["report"]["status"] == ("passed" if passed else "held"), result["report"]
    assert result["traceability"]["covered"] == (1 if passed else 0)
    assert {row["category"] for row in result["traceability"]["application_checks"]} == {
        "build",
        "health",
    }
    assert result["record"]["decision"]["verdict"] == "hold"
