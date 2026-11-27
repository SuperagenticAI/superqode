"""Protected verification orchestration, fencing and honest artifact evidence."""
# ruff: noqa: F811

import asyncio
import json
import os
import sys
import time

from click.testing import CliRunner
import pytest

from test_factory_definition import project, git, rewrite, admitted  # noqa: F401
from superqode.commands.factory import factory
from superqode.factory import verification as verification
from superqode.factory.probes import parse_probes, run_python_probe, OUTPUT_LIMIT
from superqode.gauge import highest_level
from superqode.sandbox import local_sandbox as sandbox
from superqode.workorders import runner
from superqode.workorders.models import WorkOrderStatus
from superqode.workorders.integration import prepare_integration, merge_integration


@pytest.fixture
def completed(project, monkeypatch):
    return make_completed(project, monkeypatch)


def make_completed(project, monkeypatch, *, tamper=False, peek=None):
    evaluator = project / "protected/probes.json"
    evaluator.parent.mkdir()
    evaluator.write_text(
        json.dumps(
            {
                "format": "superqode.factory-probes/1",
                "cases": [{"id": "answer", "argv": ["python", "app.py"], "stdout": "43\n"}],
            }
        )
    )
    git(project, "add", "protected/probes.json")
    git(project, "commit", "-qm", "Acceptance criteria")
    rewrite(
        project,
        lambda d: (
            d["data_context"]["files"].update(
                probes={"path": "protected/probes.json", "purpose": "evaluator"}
            ),
            d["improvement"]["checks"]["regression"].update(evaluator="probes"),
            d["orchestration"]["stages"][2].update(human_gate=False),
        ),
    )
    plan, store, order = admitted(project)

    async def execute(order, task, *, working_directory, **kwargs):
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print(43)\n")
            if peek is not None:
                peek.append((working_directory / "protected/probes.json").exists())
            if tamper:
                # Simulate a worker trying to weaken the protected evaluator.
                (working_directory / "protected").mkdir(exist_ok=True)
                (working_directory / "protected/probes.json").write_text('{"cases": []}')
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    outcomes = asyncio.run(runner.run_until_idle(store, work_order_id=order.work_order_id))
    assert all(row.status == "succeeded" for row in outcomes)
    return project, store, order.work_order_id


@pytest.fixture
def simulated_probes(monkeypatch):
    calls = []

    def probe(argv, *, candidate, scratch, stdin, deadline):
        calls.append(argv)
        assert not (candidate / "protected/probes.json").exists()
        if argv[1] == "-c":
            output = "superqode-verifier-ready\n"
        else:
            output = "43\n" if (candidate / "app.py").read_text() == "print(43)\n" else "0\n"
        return {
            "kind": "completed",
            "backend": "simulated-for-test",
            "returncode": 0,
            "stdout": output,
            "stderr": "",
        }

    monkeypatch.setattr(verification, "run_python_probe", probe)
    return calls


def test_pinned_evaluators_bind_exact_candidate_and_emit_ship_record(completed, simulated_probes):
    root, store, run_id = completed
    result = verification.verify_factory(run_id, root=root)
    report = result["report"]
    assert report["status"] == "passed"
    assert len(report["results"]) == 1
    assert len(simulated_probes) == 2
    record = result["record"]
    assert record["decision"]["verdict"] == "ship"
    assert record["decision"]["actor"] == "superqode-gauge"
    assert record["assurance"]["evaluator_independent"] is True
    assert record["task_set"]["sealed"] is True
    assert highest_level(record) == "L2"
    assert record["subject"]["code_digest"] == report["code_digest"]
    assert record["subject"]["factory_digest"] == report["binding"]["factory_digest"]
    assert record["subject"]["candidate"]["digest"] == report["binding"]["candidate_digest"]
    assert (
        report["binding"]["factory_digest"]
        == store.get(run_id).metadata["factory"]["snapshot_digest"]
    )
    prepared = prepare_integration(store, run_id)
    assert prepared.artifact_id == report["binding"]["candidate_id"]
    with pytest.raises(ValueError, match="release authorization"):
        merge_integration(store, run_id)


def test_unavailable_os_isolation_records_missing_evidence_and_never_runs_app(
    completed, monkeypatch
):
    root, store, run_id = completed
    calls = []

    def unavailable(argv, **kwargs):
        calls.append(argv)
        return {"kind": "infrastructure_error", "backend": "none", "detail": "Unavailable"}

    monkeypatch.setattr(verification, "run_python_probe", unavailable)
    result = verification.verify_factory(run_id, root=root)
    assert result["report"]["status"] == "held"
    assert result["report"]["missing_evidence"][0]["kind"] == "isolation_unavailable"
    assert len(calls) == 1
    assert not store.get(run_id).metadata["acceptance_checks_passed"]
    with pytest.raises(ValueError, match="passing protected verification"):
        prepare_integration(store, run_id)


def test_weakened_candidate_evaluator_cannot_hide_a_behavioral_failure(
    completed, simulated_probes, monkeypatch
):
    root, store, run_id = completed
    original = verification.run_python_probe

    def wrong_answer(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[1] != "-c":
            result["stdout"] = "0\n"
        return result

    monkeypatch.setattr(verification, "run_python_probe", wrong_answer)
    result = verification.verify_factory(run_id, root=root)
    assert result["report"]["status"] == "held"
    assert result["report"]["results"][0]["status"] == "failed"
    assert not store.get(run_id).metadata["acceptance_checks_passed"]


def test_export_attributes_cannot_silently_omit_candidate_files(project):
    (project / ".gitattributes").write_text("app.py export-ignore\n")
    git(project, "add", ".gitattributes")
    git(project, "commit", "-qm", "Export exclusion")
    tree = git(project, "rev-parse", "HEAD^{tree}")
    destination = project / ".superqode/copy"
    destination.mkdir()
    with pytest.raises(ValueError, match="omitted candidate files"):
        verification._candidate_copy(
            project, tree, destination, project / ".superqode/candidate.tar", set(), 5
        )


def test_export_substitution_cannot_change_verified_candidate_bytes(project):
    (project / ".gitattributes").write_text("app.py export-subst\n")
    (project / "app.py").write_text("print('$Format:%H$')\n")
    git(project, "add", ".gitattributes", "app.py")
    git(project, "commit", "-qm", "Export substitution")
    revision = git(project, "rev-parse", "HEAD")
    destination = project / ".superqode/copy"
    destination.mkdir()
    with pytest.raises(ValueError, match="changed candidate bytes"):
        verification._candidate_copy(
            project, revision, destination, project / ".superqode/candidate.tar", set(), 5
        )


@pytest.mark.skipif(
    os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1", reason="Explicit native OS sandbox check"
)
def test_native_verification_end_to_end(completed):
    root, store, run_id = completed
    result = verification.verify_factory(run_id, root=root, timeout=20)
    assert result["report"]["status"] == "passed", result["report"]
    assert result["report"]["isolation_applied"] is True
    assert result["report"]["sandbox"] in {"seatbelt", "bwrap"}
    assert result["record"]["decision"]["verdict"] == "ship"


def test_legacy_checks_and_fabricated_check_results_cannot_authorize_factory(completed):
    root, store, run_id = completed
    with pytest.raises(ValueError, match="protected verification"):
        store.record_checks(run_id, [{"status": "passed"}])
    with pytest.raises(ValueError, match="exact verified candidate"):
        store.accept(run_id, actor="label-only")
    denied = CliRunner().invoke(factory, ["verify", run_id, "--project", str(root)])
    assert denied.exit_code != 0
    assert "--execute" in denied.output


def test_new_candidate_invalidates_old_verification(completed, simulated_probes):
    root, store, run_id = completed
    result = verification.verify_factory(run_id, root=root)
    candidate = next(
        a
        for a in store.get(run_id).artifacts
        if a.artifact_id == result["report"]["binding"]["candidate_id"]
    )
    store.add_artifact(
        run_id,
        kind="integration_candidate",
        content=candidate.content,
        digest=candidate.digest,
        metadata=candidate.metadata,
    )
    with pytest.raises(ValueError, match="current candidate"):
        store.accept(
            run_id,
            actor="owner",
            expected_candidate_id=candidate.artifact_id,
            expected_candidate_digest=candidate.digest,
        )


def test_cancelled_verification_is_fenced_and_evidence_is_retained(completed, monkeypatch):
    root, store, run_id = completed

    def cancel(argv, **kwargs):
        store.cancel(run_id, actor="owner", reason="Stop")
        return {"kind": "infrastructure_error", "backend": "none", "detail": "Cancelled"}

    monkeypatch.setattr(verification, "run_python_probe", cancel)
    with pytest.raises(ValueError, match="no longer active"):
        verification.verify_factory(run_id, root=root)
    order = store.get(run_id)
    assert order.status == WorkOrderStatus.CANCELLED
    assert any(a.kind == "factory_verification_discarded" for a in order.artifacts)
    assert not order.metadata["acceptance_checks_passed"]


def test_competing_verifier_does_not_publish_another_candidate(
    completed, simulated_probes, monkeypatch
):
    root, store, run_id = completed
    original = verification.run_python_probe

    def competing(argv, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            verification.verify_factory(run_id, root=root)
        return original(argv, **kwargs)

    monkeypatch.setattr(verification, "run_python_probe", competing)
    verification.verify_factory(run_id, root=root)
    assert len([a for a in store.get(run_id).artifacts if a.kind == "integration_candidate"]) == 1


def test_cli_protected_verification_reports_pass_without_release(completed, simulated_probes):
    root, store, run_id = completed
    result = CliRunner().invoke(factory, ["verify", run_id, "--project", str(root), "--execute"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["report"]["status"] == "passed"
    assert store.get(run_id).decision is None


@pytest.mark.parametrize(
    "code,kind",
    [
        ("print('ok')", "completed"),
        ("import time; time.sleep(5)", "timeout"),
        ("print('x'*200000)", "output_limit"),
        ("import os; os.write(1,b'\\xff')", "invalid_utf8"),
    ],
)
def test_probe_process_control_is_bounded(tmp_path, monkeypatch, code, kind):
    # This test exercises pipe/deadline handling with a trusted synthetic script;
    # OS enforcement is tested separately, never bypassed in product code.
    from superqode.factory import probes

    monkeypatch.setattr(
        probes,
        "build_verification_argv",
        lambda argv, **kwargs: sandbox.SandboxPlan(argv, True, "test-process-control"),
    )
    result = run_python_probe(
        ["python", "-c", code],
        candidate=tmp_path,
        scratch=tmp_path,
        stdin="",
        deadline=time.monotonic() + 0.4,
    )
    assert result["kind"] == kind
    assert len(result["stdout"].encode()) <= OUTPUT_LIMIT


def test_probe_environment_does_not_inherit_credentials(tmp_path, monkeypatch):
    from superqode.factory import probes

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-pass")
    monkeypatch.setattr(
        probes,
        "build_verification_argv",
        lambda argv, **kwargs: sandbox.SandboxPlan(argv, True, "test-process-control"),
    )
    result = run_python_probe(
        ["python", "-c", "import os;print(os.environ.get('OPENAI_API_KEY','absent'))"],
        candidate=tmp_path,
        scratch=tmp_path,
        stdin="",
        deadline=time.monotonic() + 2,
    )
    assert result["stdout"] == "absent\n"


@pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("SUPERQODE_VERIFY_NATIVE") != "1",
    reason="Explicit native Linux sandbox check",
)
def test_linux_protected_probe_denies_sockets_after_exec(tmp_path):
    candidate, scratch = tmp_path / "candidate", tmp_path / "scratch"
    candidate.mkdir()
    scratch.mkdir()
    checks = """
import errno, socket
for create in (
    lambda: socket.socket(socket.AF_INET),
    lambda: socket.socket(socket.AF_INET6),
    lambda: socket.socket(socket.AF_UNIX),
    socket.socketpair,
):
    try:
        create()
    except OSError as error:
        assert error.errno == errno.EPERM
    else:
        raise AssertionError('Protected probe created a socket')
"""
    code = (
        checks
        + "\nimport os,sys\n"
        + f"os.execv(sys.executable,[sys.executable,'-S','-c',{checks + chr(10) + 'print("READY")'!r}])"
    )
    result = run_python_probe(
        ["python", "-c", code],
        candidate=candidate,
        scratch=scratch,
        stdin="",
        deadline=time.monotonic() + 5,
    )
    assert result["kind"] == "completed", result
    assert result["returncode"] == 0 and result["stdout"] == "READY\n", result


@pytest.mark.skipif(sys.platform != "linux", reason="Linux network filter")
def test_missing_linux_network_filter_never_runs_candidate(tmp_path, monkeypatch):
    from superqode.factory import probes

    monkeypatch.setattr(
        probes,
        "build_verification_argv",
        lambda argv, **kwargs: sandbox.SandboxPlan(argv, True, "test-process-control"),
    )
    monkeypatch.setattr(
        probes,
        "LINUX_NETWORK_GUARD",
        probes.LINUX_NETWORK_GUARD.replace("libseccomp.so.2", "libseccomp-missing-test.so"),
    )
    result = run_python_probe(
        ["python", "-c", "print('CANDIDATE-RAN')"],
        candidate=tmp_path,
        scratch=tmp_path,
        stdin="",
        deadline=time.monotonic() + 5,
    )
    assert result["returncode"] != 0
    assert result["stdout"] == ""
    assert "libseccomp-missing-test.so" in result["stderr"]


@pytest.mark.parametrize("backend", ["seatbelt", "bwrap", "none"])
def test_protected_sandbox_never_exposes_host_root_or_uses_interactive_fallback(
    tmp_path, monkeypatch, backend
):
    monkeypatch.setattr(sandbox, "_backend_for_platform", lambda: backend)
    candidate, scratch = tmp_path / "candidate", tmp_path / "scratch"
    candidate.mkdir()
    scratch.mkdir()
    plan = sandbox.build_verification_argv(
        [sys.executable, "-S", "app.py"], candidate=candidate, scratch=scratch
    )
    assert plan.applied == (backend != "none")
    if backend == "seatbelt":
        assert "(deny default)" in plan.argv[2]
        assert "(allow default)" not in plan.argv[2]
        assert "(allow process-fork)" not in plan.argv[2]
    elif backend == "bwrap":
        assert "--unshare-all" in plan.argv
        assert not any(
            plan.argv[i : i + 3] == ["--ro-bind", "/", "/"] for i in range(len(plan.argv))
        )
    else:
        assert plan.argv == []


def test_invalid_or_non_python_probes_are_rejected():
    with pytest.raises(ValueError, match="require python"):
        parse_probes(
            json.dumps(
                {
                    "format": "superqode.factory-probes/1",
                    "cases": [{"id": "unsafe", "argv": ["sh", "-c"], "stdout": ""}],
                }
            )
        )


def test_stdout_contains_probe_schema_and_verification(project, monkeypatch):
    parsed = parse_probes(
        json.dumps(
            {
                "format": "superqode.factory-probes/1",
                "cases": [
                    {"id": "contains", "argv": ["python", "app.py"], "stdout_contains": "43"}
                ],
            }
        )
    )
    assert parsed["cases"][0]["stdout_contains"] == "43"
    with pytest.raises(ValueError, match="Invalid protected probes"):
        parse_probes(
            json.dumps(
                {
                    "format": "superqode.factory-probes/1",
                    "cases": [{"id": "empty", "argv": ["python", "app.py"], "stdout_contains": ""}],
                }
            )
        )
    with pytest.raises(ValueError, match="Invalid protected probes"):
        parse_probes(
            json.dumps(
                {
                    "format": "superqode.factory-probes/1",
                    "cases": [{"id": "missing", "argv": ["python", "app.py"]}],
                }
            )
        )

    evaluator = project / "protected/contains.json"
    evaluator.parent.mkdir()
    evaluator.write_text(
        json.dumps(
            {
                "format": "superqode.factory-probes/1",
                "cases": [
                    {"id": "contains-ok", "argv": ["python", "app.py"], "stdout_contains": "43"}
                ],
            }
        )
    )
    git(project, "add", "protected/contains.json")
    git(project, "commit", "-qm", "Contains probe")
    rewrite(
        project,
        lambda d: (
            d["data_context"]["files"].update(
                probes={"path": "protected/contains.json", "purpose": "evaluator"}
            ),
            d["improvement"]["checks"]["regression"].update(evaluator="probes"),
            d["orchestration"]["stages"][2].update(human_gate=False),
        ),
    )
    _, store, order = admitted(project)

    async def execute(order, task, *, working_directory, **kwargs):
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print('result=43')\n")
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    def probe(argv, *, candidate, scratch, stdin, deadline):
        output = "superqode-verifier-ready\n" if argv[1] == "-c" else "result=43\n"
        return {
            "kind": "completed",
            "backend": "simulated-for-test",
            "returncode": 0,
            "stdout": output,
            "stderr": "",
        }

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    monkeypatch.setattr(verification, "run_python_probe", probe)
    outcomes = asyncio.run(runner.run_until_idle(store, work_order_id=order.work_order_id))
    assert all(row.status == "succeeded" for row in outcomes)
    result = verification.verify_factory(order.work_order_id, root=project)
    assert result["report"]["status"] == "passed"
    assert result["record"]["decision"]["verdict"] == "ship"


@pytest.mark.parametrize(
    "command",
    [
        "python self_check.py",
        "python -m unittest",
        "python -m pytest",
        "python -m py_compile app.py",
        "npm test",
    ],
)
def test_scaffolding_does_not_promote_mutable_self_checks(tmp_path, command):
    from superqode.factory.templates import factory_template
    from superqode.factory.verifiers import scaffold_evaluator
    import yaml

    (tmp_path / "app.py").write_text("def total(values): return 999\n")
    (tmp_path / "self_check.py").write_text("assert 1 == 2\n")
    spec = factory_template("fix-and-verify")
    spec["improvement"]["checks"]["regression"]["command"] = command
    raw = yaml.safe_dump(spec, sort_keys=False)
    before = scaffold_evaluator(tmp_path, yaml_text=raw)
    (tmp_path / "self_check.py").write_text("pass\n")
    after = scaffold_evaluator(tmp_path, yaml_text=raw)
    for result in [before, after]:
        assert result["written"] is False
        assert result["already_configured"] is False
        assert result["yaml"] == raw
        assert "self-checks" in result["reason"]
    assert not (tmp_path / ".superqode/evaluators/regression.json").exists()


def test_scaffold_explicit_behavioral_expectations_preserves_existing_files(tmp_path):
    from superqode.factory.templates import factory_template
    from superqode.factory.verifiers import scaffold_evaluator
    import yaml

    raw = yaml.safe_dump(factory_template("fix-and-verify"), sort_keys=False)
    manifest = {
        "format": "superqode.factory-probes/1",
        "cases": [{"id": "total", "argv": ["python", "app.py", "[2,3]"], "stdout": "5\n"}],
    }
    result = scaffold_evaluator(tmp_path, yaml_text=raw, manifest=manifest)
    path = tmp_path / result["path"]
    assert result["written"] is True
    assert json.loads(path.read_text()) == manifest
    updated = yaml.safe_load(result["yaml"])
    assert updated["improvement"]["checks"]["regression"]["evaluator"] == "evaluator-regression"
    original_bytes = path.read_bytes()
    again = scaffold_evaluator(tmp_path, yaml_text=result["yaml"])
    assert again["already_configured"] is True
    with pytest.raises(ValueError, match="already exists"):
        scaffold_evaluator(tmp_path, yaml_text=raw, manifest=manifest)
    assert path.read_bytes() == original_bytes


def test_scaffold_refuses_invalid_manifest_before_creating_file(tmp_path):
    from superqode.factory.templates import factory_template
    from superqode.factory.verifiers import scaffold_evaluator
    import yaml

    with pytest.raises(ValueError, match="Invalid protected probes"):
        scaffold_evaluator(tmp_path, yaml_text=yaml.safe_dump(factory_template()), manifest={})
    assert not (tmp_path / ".superqode/evaluators/regression.json").exists()


def test_scaffold_preserves_unbound_custom_evaluator(tmp_path):
    from superqode.factory.templates import factory_template
    from superqode.factory.verifiers import scaffold_evaluator
    import yaml

    path = tmp_path / ".superqode/evaluators/regression.json"
    path.parent.mkdir(parents=True)
    original = b'{"custom":"existing user file"}\n'
    path.write_bytes(original)
    manifest = {
        "format": "superqode.factory-probes/1",
        "cases": [{"id": "total", "argv": ["python", "app.py"], "stdout": "5\n"}],
    }
    with pytest.raises(ValueError, match="already exists"):
        scaffold_evaluator(
            tmp_path, yaml_text=yaml.safe_dump(factory_template()), manifest=manifest
        )
    assert path.read_bytes() == original


def test_verifier_json_extraction_preserves_prose_support():
    from superqode.factory.verifiers import _extract_json_object

    parsed = _extract_json_object('Here is the manifest:\n```json\n{"checks": {}}\n```\nDone.')
    assert parsed == {"checks": {}}


@pytest.mark.parametrize(
    "call",
    [
        "runpy.run_path('self_check.py', run_name='__main__')",
        "runpy.run_module('unittest', run_name='__main__')",
        "py_compile.compile('app.py', doraise=True)",
    ],
)
def test_previously_generated_self_check_wrappers_are_not_protected_acceptance(call):
    manifest = {
        "format": "superqode.factory-probes/1",
        "cases": [
            {
                "id": "regression-probe",
                "argv": ["python", "-c", call + "; print('SUPERQODE_PROBE_OK')"],
                "stdout_contains": "SUPERQODE_PROBE_OK",
                "returncode": 0,
            }
        ],
    }
    with pytest.raises(ValueError, match="fresh trial"):
        parse_probes(json.dumps(manifest))
