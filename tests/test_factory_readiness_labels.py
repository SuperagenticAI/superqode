"""Project readiness runs the application's own checks and labels each finding."""
# ruff: noqa: F401, F811

from click.testing import CliRunner
import json

from test_factory_definition import project, rewrite, git
from superqode.commands.factory import factory
from superqode.factory.operations import readiness


def _checks(root, build="python -c \"print('built')\"", health="exit 3"):
    def change(data):
        data["improvement"]["checks"]["compile"] = {"command": build, "category": "build"}
        data["improvement"]["checks"]["ping"] = {"command": health, "category": "health"}

    rewrite(root, change)


def test_configured_checks_are_labelled_without_running(project):
    _checks(project)
    report = readiness(project)
    rows = {row["id"]: row for row in report["application"]}
    assert rows["compile"]["label"] == "configured"
    assert rows["compile"]["status"] == "not_run"
    assert "--application" in rows["compile"]["action"]
    assert rows["missing-start"]["status"] == "missing"
    assert "category: start" in rows["missing-start"]["action"]
    assert report["application_passed"] is None
    assert "score" not in json.dumps(report)
    assert all(row["label"] in {"configured", "execution_tested"} for row in report["checks"])


def test_application_checks_execute_in_a_temporary_checkout(project):
    _checks(project, build="test -f app.py && echo built > built.txt")
    report = readiness(project, application=True, timeout=30)
    rows = {row["id"]: row for row in report["application"]}
    assert rows["compile"]["label"] == "execution_tested"
    assert rows["compile"]["status"] == "passed", rows["compile"]
    assert rows["ping"]["status"] == "failed"
    assert rows["ping"]["evidence"]["returncode"] == 3
    assert rows["ping"]["action"]
    assert report["application_passed"] is False
    assert report["labels"]["execution_tested"] == 2
    # Nothing is written to the real checkout and the temporary worktree is gone.
    assert not (project / "built.txt").exists()
    assert "readiness-" not in git(project, "worktree", "list")


def test_timeout_is_reported_with_a_fix(project):
    _checks(project, build="sleep 5")
    report = readiness(project, application=True, timeout=1)
    row = next(r for r in report["application"] if r["id"] == "compile")
    assert row["status"] == "failed"
    assert row["evidence"]["timed_out"] is True
    assert "timeout" in row["action"]


def test_cli_check_application_exits_nonzero_on_failure(project):
    _checks(project)
    result = CliRunner().invoke(
        factory,
        ["operations", "check", "--project", str(project), "--application", "--timeout", "30"],
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["application_passed"] is False


def test_verified_acceptance_check_is_quality_evaluated(project, monkeypatch):
    from test_factory_verification import make_completed, simulated_probes  # noqa: F401
    from superqode.factory import verification

    root, store, run = make_completed(project, monkeypatch)

    def probe(argv, *, candidate, scratch, stdin, deadline):
        output = "superqode-verifier-ready\n" if argv[1] == "-c" else "43\n"
        return {"kind": "completed", "backend": "test", "returncode": 0, "stdout": output}

    monkeypatch.setattr(verification, "run_python_probe", probe)
    verification.verify_factory(run, root=root)
    row = next(r for r in readiness(root)["application"] if r["id"] == "regression")
    assert row["label"] == "quality_evaluated"
    assert run in row["detail"]
