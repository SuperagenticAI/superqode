"""Check and requirement states: passed, failed, blocked and never ran."""
# ruff: noqa: F401, F811

from test_factory_definition import project
from test_factory_research_features import requirements
from test_factory_verification import make_completed, simulated_probes
from superqode.factory import evidence, verification


def test_failure_is_reported_even_when_other_evidence_is_missing(
    project, monkeypatch, simulated_probes
):
    requirements(project)
    root, store, run = make_completed(project, monkeypatch)
    original_probe = verification.run_python_probe
    original_validate = verification.validate_factory_order
    calls = []

    def wrong(argv, **kwargs):
        result = original_probe(argv, **kwargs)
        if argv[1] != "-c":
            result["stdout"] = "0\n"
        return result

    def flaky(order, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("Simulated infrastructure loss after the cases ran")
        return original_validate(order, **kwargs)

    monkeypatch.setattr(verification, "run_python_probe", wrong)
    monkeypatch.setattr(verification, "validate_factory_order", flaky)
    result = verification.verify_factory(run, root=root)
    assert result["report"]["missing_evidence"]
    trace = result["traceability"]
    check = trace["application_checks"][0]
    assert check["status"] == "failed"
    assert check["failed_cases"] == ["answer"]
    assert trace["requirements"][0]["status"] == "failed"
    assert trace["summary"]["checks"]["failed"] == 1
    assert trace["summary"]["requirements"]["failed"] == 1
    assert result["record"]["decision"]["verdict"] == "reject"


def test_unavailable_isolation_blocks_checks_and_requirements(project, monkeypatch):
    requirements(project)
    root, store, run = make_completed(project, monkeypatch)

    def unavailable(argv, **kwargs):
        return {"kind": "infrastructure_error", "backend": "none", "detail": "Unavailable"}

    monkeypatch.setattr(verification, "run_python_probe", unavailable)
    result = verification.verify_factory(run, root=root)
    trace = result["traceability"]
    assert trace["application_checks"][0]["status"] == "blocked"
    assert "isolation_unavailable" in trace["application_checks"][0]["reason"]
    assert trace["requirements"][0]["status"] == "blocked"
    assert trace["summary"]["checks"] == {"passed": 0, "failed": 0, "blocked": 1, "never_ran": 0}
    assert result["record"]["decision"]["verdict"] == "hold"


def test_passing_verification_covers_requirement(project, monkeypatch, simulated_probes):
    requirements(project)
    root, store, run = make_completed(project, monkeypatch)
    assert evidence.trace(root, run)["summary"]["checks"]["never_ran"] == 1
    trace = verification.verify_factory(run, root=root)["traceability"]
    assert trace["summary"]["checks"]["passed"] == 1
    assert trace["summary"]["requirements"] == {
        "covered": 1,
        "failed": 0,
        "blocked": 0,
        "uncovered": 0,
    }
