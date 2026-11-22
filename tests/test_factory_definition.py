"""Factory composition contracts: compatibility, pinned inputs and dry compilation."""

import json
from dataclasses import replace
from pathlib import Path
import subprocess

from click.testing import CliRunner
import pytest
import yaml

from superqode.commands.factory import factory
from superqode.factory import (
    FactorySnapshot,
    compile_factory,
    load_factory,
    materialize_snapshot,
    resolve_factory,
)
from superqode.factory.definition import read_mapping
from superqode.session.factory import SoftwareFactory
from superqode.workorders.models import WorkOrder, WorkOrderStatus
from superqode.workorders.store import WorkOrderStore


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/factory/fix-and-verify.yaml"


def git(root, *args):
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "core.hooksPath=.git/disabled-hooks",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Factory Test")
    git(root, "config", "user.email", "factory@example.invalid")
    (root / ".gitignore").write_text(".superqode/\n")
    (root / "app.py").write_text("answer = 42\n")
    git(root, "add", ".gitignore", "app.py")
    git(root, "commit", "-qm", "Application baseline")
    (root / ".superqode").mkdir()
    (root / ".superqode/factory.yaml").write_text(EXAMPLE.read_text())
    return root


def rewrite(root, change):
    path = root / ".superqode/factory.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def resolved(root):
    return resolve_factory(load_factory(root=root))


def test_legacy_policy_remains_unchanged_and_is_not_compilable(project):
    path = project / ".superqode/factory.yaml"
    text = "default_route: cheap\nroutes:\n  cheap:\n    prefer: [local/test]\n"
    path.write_text(text)
    definition = load_factory(root=project)
    assert definition.legacy
    factory_obj = SoftwareFactory(project / ".superqode/sessions")
    assert factory_obj.policy()["default_route"] == "cheap"
    assert factory_obj.resolve_route("cheap")["config"]["prefer"] == ["local/test"]
    with pytest.raises(ValueError, match="Routing-only"):
        resolve_factory(definition)
    assert path.read_text() == text


def test_versioned_definition_preserves_existing_route_consumers(project):
    policy = SoftwareFactory(project / ".superqode/sessions").policy()
    assert policy["default_route"] == "no-subscription"
    assert policy["routes"]["no-subscription"]["allow_cloud"] is False
    assert "orchestration" not in policy
    assert "apiVersion" not in policy


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d.update(apiVersion="superqode.dev/v99"), "apiVersion"),
        (
            lambda d: d["orchestration"]["stages"][1].update(depends_on=["missing"]),
            "unknown dependency",
        ),
        (lambda d: d["orchestration"]["stages"][0].update(depends_on=["verify"]), "cycle"),
        (lambda d: d["orchestration"]["stages"][1].update(id="investigate"), "unique"),
        (lambda d: d["orchestration"]["stages"][0].update(harness="missing"), "unknown harness"),
        (lambda d: d["orchestration"].update(acceptance_checks=["missing"]), "unknown acceptance"),
        (lambda d: d["orchestration"]["stages"][0].update(transitions=[]), "Additional properties"),
        (lambda d: d["compute"].update(runner="remote"), "compute.runner"),
        (lambda d: d["governance"]["budget"].update(max_workers=0), "max_workers"),
        (
            lambda d: d["improvement"]["optimization"].update(automatic_experiments=True),
            "automatic_experiments",
        ),
        (
            lambda d: d["orchestration"]["stages"][0].update(permissions={"allow_network": True}),
            "widens",
        ),
        (
            lambda d: d["improvement"]["checks"]["regression"].update(files=["missing"]),
            "unknown declared file",
        ),
    ],
)
def test_invalid_or_unsupported_contracts_fail_before_execution(project, change, message):
    rewrite(project, change)
    with pytest.raises(ValueError, match=message):
        resolved(project)


@pytest.mark.parametrize(
    "text",
    [
        "routes: {}\nroutes: {}\n",
        "data: &data {recursive: *data}\n",
        "numeric: .nan\n",
        "date: 2026-11-21\n",
    ],
)
def test_ambiguous_or_non_json_yaml_is_rejected(text):
    with pytest.raises(ValueError):
        read_mapping(text)


def test_snapshot_is_stable_immutable_and_reopens_without_original_files(project):
    snapshot = resolved(project)
    assert resolved(project).digest == snapshot.digest
    copy = snapshot.payload
    copy["definition"]["metadata"]["name"] = "changed"
    assert snapshot.payload["definition"]["metadata"]["name"] == "fix-and-verify"
    (project / ".superqode/factory.yaml").unlink()
    reopened = FactorySnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
    assert reopened == snapshot
    tampered = snapshot.to_dict()
    tampered["definition"]["metadata"]["name"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        FactorySnapshot.from_dict(tampered)


def test_snapshot_pins_inherited_harness_evaluator_and_context(project):
    directory = project / ".superqode/components"
    directory.mkdir()
    base = directory / "base.yaml"
    base.write_text("inherits: core\ndescription: first\n")
    (directory / "coder.yaml").write_text("inherits: base.yaml\nname: customer-coder\n")
    evaluator = directory / "check.py"
    evaluator.write_text("assert 1 + 1 == 2\n")
    (project / "AGENTS.md").write_text("Keep changes small.\n")
    rewrite(
        project,
        lambda d: (
            d["inference"]["harnesses"]["coder"].update(path=".superqode/components/coder.yaml"),
            d["inference"]["harnesses"]["coder"].pop("template"),
            d["data_context"]["files"].update(
                check={
                    "path": ".superqode/components/check.py",
                    "purpose": "evaluator",
                }
            ),
            d["improvement"]["checks"]["regression"].update(files=["check"]),
        ),
    )
    first = resolved(project)
    assert first.payload["harnesses"]["coder"]["description"] == "first"
    assert "AGENTS.md" in first.payload["sources"]
    base.write_text("inherits: core\ndescription: improved\n")
    second = resolved(project)
    assert second.digest != first.digest
    evaluator.write_text("assert 1 + 1 == 2, 'checked'\n")
    assert resolved(project).digest != second.digest


@pytest.mark.parametrize("path", ["../outside.yaml", "/outside.yaml", ".git/config"])
def test_declared_files_cannot_escape_project_or_read_git_state(project, path):
    rewrite(
        project,
        lambda d: d["data_context"]["files"].update(
            unsafe={"path": path, "purpose": "context"},
        ),
    )
    with pytest.raises(ValueError, match="inside the project"):
        resolved(project)


def test_symlinked_components_and_external_inheritance_are_rejected(project):
    external = project.parent / "outside.yaml"
    external.write_text("name: outside\n")
    link = project / ".superqode/link.yaml"
    link.symlink_to(external)
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"].update(
            coder={"path": ".superqode/link.yaml"},
        ),
    )
    with pytest.raises(ValueError, match="symbolic links"):
        resolved(project)
    link.unlink()
    link.write_text(f"inherits: {external}\n")
    with pytest.raises(ValueError, match="inside the project"):
        resolved(project)


def test_compile_produces_draft_with_pinned_harnesses_and_no_admission(project):
    plan = compile_factory(resolved(project), root=project, goal="Fix the export freeze")
    order = plan.work_order
    assert order.status == WorkOrderStatus.DRAFT
    assert order.tasks[1].dependencies == ("investigate",)
    assert order.tasks[2].dependencies == ("implement",)
    assert order.acceptance_tests == ("python -m pytest -q",)
    assert order.budget.max_workers == 1
    assert order.metadata["factory"]["repository_commit"] == git(project, "rev-parse", "HEAD")
    assert WorkOrder.from_dict(order.to_dict()) == order
    assert not (project / ".superqode/workorders").exists()
    assert not plan.snapshot_directory.exists()
    assert plan.harnesses["implement"]["execution_policy"]["allow_write"]
    assert not plan.harnesses["verify"]["execution_policy"]["allow_write"]
    assert not plan.harnesses["investigate"]["execution_policy"]["allow_write"]
    assert all(not h["execution_policy"]["allow_network"] for h in plan.harnesses.values())
    # The existing store accepts the compiled contract, still as a draft.
    store = WorkOrderStore(project / ".superqode/test-store.sqlite3")
    assert store.create(order).status == WorkOrderStatus.DRAFT


def test_stage_permissions_can_only_narrow_and_never_widen_harness(project):
    rewrite(
        project,
        lambda d: (
            d["governance"]["permissions"].update(allow_network=True),
            d["orchestration"]["stages"][1].update(permissions={"allow_shell": False}),
        ),
    )
    plan = compile_factory(resolved(project), root=project, goal="Fix")
    assert not plan.harnesses["implement"]["execution_policy"]["allow_shell"]
    # The underlying core harness denies network even though the factory allows it.
    assert not plan.harnesses["implement"]["execution_policy"]["allow_network"]


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_compile_rejects_unpinned_application_state(project, kind):
    (project / ("app.py" if kind == "tracked" else "new.py")).write_text("changed = True\n")
    with pytest.raises(ValueError, match="Commit or isolate"):
        compile_factory(resolved(project), root=project, goal="Fix")


def test_compile_rejects_unsupported_runtime_contracts(project):
    component = project / ".superqode/coder.yaml"
    component.write_text(
        "inherits: core\nhooks:\n  rules:\n    - point: before_tool_call\n      handler: example:hook\n"
    )
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"].update(
            coder={"path": ".superqode/coder.yaml", "model": "local/test"},
        ),
    )
    with pytest.raises(ValueError, match="adapter contracts"):
        compile_factory(resolved(project), root=project, goal="Fix")


def test_compile_enforces_private_route_for_primary_and_fallback_models(project):
    rewrite(project, lambda d: d["inference"]["harnesses"]["coder"].update(model="openai/example"))
    with pytest.raises(ValueError, match="disallows non-local inference"):
        compile_factory(resolved(project), root=project, goal="Fix")
    component = project / ".superqode/coder.yaml"
    component.write_text(
        "inherits: core\nmodel_policy:\n  primary: ollama/test\n  fallbacks: [openai/example]\n"
    )
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"].update(
            coder={"path": ".superqode/coder.yaml"},
        ),
    )
    with pytest.raises(ValueError, match="disallows non-local inference"):
        compile_factory(resolved(project), root=project, goal="Fix")


def test_materialization_detects_extra_context_files(project):
    plan = compile_factory(resolved(project), root=project, goal="Fix")
    target = materialize_snapshot(plan)
    (target / "sources/extra-instructions.md").write_text("Unexpected instructions")
    with pytest.raises(ValueError, match="unexpected files"):
        materialize_snapshot(plan)


def test_materialization_refuses_a_symlinked_destination(project):
    plan = compile_factory(resolved(project), root=project, goal="Fix")
    destination = project / ".superqode/factory"
    elsewhere = project / ".superqode/elsewhere"
    elsewhere.mkdir()
    destination.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        materialize_snapshot(plan)


def test_snapshot_import_rejects_external_context_even_with_matching_digest(project):
    from superqode.factory.snapshot import canonical, digest

    value = resolved(project).to_dict()
    value.pop("digest")
    value["harnesses"]["coder"]["context"]["skills_dir"] = "/external/skills"
    value["digest"] = digest(canonical(value))
    with pytest.raises(ValueError, match="inside the project"):
        FactorySnapshot.from_dict(value)


def test_harness_inheritance_cycles_are_rejected(project):
    (project / ".superqode/coder.yaml").write_text("inherits: coder.yaml\n")
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"].update(
            coder={"path": ".superqode/coder.yaml", "model": "local/test"},
        ),
    )
    with pytest.raises(ValueError, match="inheritance cycle"):
        resolved(project)


def test_materialization_is_explicit_idempotent_and_detects_tampering(project):
    plan = compile_factory(resolved(project), root=project, goal="Fix")
    target = materialize_snapshot(plan)
    assert target == materialize_snapshot(plan)
    assert (
        FactorySnapshot.from_dict(json.loads((target / "snapshot.json").read_text()))
        == plan.snapshot
    )
    assert all(Path(task.harness).is_file() for task in plan.work_order.tasks)
    assert not (project / ".superqode/workorders").exists()
    (target / "harnesses/implement.yaml").write_text("tampered: true\n")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        materialize_snapshot(plan)


def test_cli_validation_resolution_and_compilation_are_read_only_by_default(project):
    runner = CliRunner()
    args = ["--project", str(project)]
    validation = runner.invoke(factory, ["validate", *args, "--json"])
    assert validation.exit_code == 0, validation.output
    assert json.loads(validation.output)["valid"]
    resolution = runner.invoke(factory, ["resolve", *args])
    assert resolution.exit_code == 0, resolution.output
    assert (
        FactorySnapshot.from_dict(json.loads(resolution.output)).digest == resolved(project).digest
    )
    compilation = runner.invoke(factory, ["compile", *args, "--goal", "Fix"])
    assert compilation.exit_code == 0, compilation.output
    output = json.loads(compilation.output)
    assert not output["execution_started"]
    assert not output["snapshot_written"]
    assert not Path(output["snapshot_directory"]).exists()
    written = runner.invoke(factory, ["compile", *args, "--goal", "Fix", "--write-snapshot"])
    assert written.exit_code == 0, written.output
    assert json.loads(written.output)["snapshot_written"]


def test_cli_errors_are_actionable_without_traceback(project):
    rewrite(project, lambda d: d.update(apiVersion="unknown"))
    result = CliRunner().invoke(factory, ["validate", "--project", str(project)])
    assert result.exit_code != 0
    assert "apiVersion" in result.output
    assert "Traceback" not in result.output


def admitted(project, *, request_id="problem-42"):
    from superqode.factory.runtime import admit_factory, factory_store

    plan = compile_factory(resolved(project), root=project, goal="Fix the export freeze")
    materialize_snapshot(plan)
    order = admit_factory(plan, request_id=request_id, actor="operator")
    return plan, factory_store(project), order


def test_factory_admission_is_retry_safe_after_progress_and_application_drift(project):
    from superqode.factory.runtime import admit_factory

    plan, store, order = admitted(project)
    assert order.status == WorkOrderStatus.QUEUED
    store.claim_next_task(reference=order.work_order_id, worker_id="worker")
    (project / "app.py").write_text("uncommitted = True\n")
    retry = admit_factory(plan, request_id="problem-42", actor="operator")
    assert retry.work_order_id == order.work_order_id
    assert retry.tasks[0].attempts == 1
    assert (
        len([event for event in store.events(order.work_order_id) if event.type == "work.created"])
        == 1
    )
    with pytest.raises(ValueError, match="Commit or isolate"):
        admit_factory(plan, request_id="new-intake", actor="operator")


def test_factory_admission_rejects_changed_or_forged_contract(project):
    from superqode.factory.compiler import _compile_factory
    from superqode.factory.runtime import admit_factory

    plan, store, order = admitted(project)
    changed = _compile_factory(
        plan.snapshot,
        root=project,
        goal="Different goal",
        revision=order.metadata["factory"]["repository_commit"],
    )
    with pytest.raises(ValueError, match="different WorkOrder contract"):
        admit_factory(changed, request_id="problem-42", actor="operator")
    forged = replace(
        plan,
        work_order=replace(
            plan.work_order,
            budget=replace(plan.work_order.budget, max_workers=99),
        ),
    )
    with pytest.raises(ValueError, match="pinned compiled contract"):
        admit_factory(forged, request_id="forged", actor="operator")


@pytest.mark.asyncio
async def test_factory_executes_in_worktrees_and_survives_human_wait(project, monkeypatch):
    from superqode.factory.runtime import factory_store
    from superqode.workorders import runner

    plan, store, order = admitted(project)
    calls = []

    async def execute(order, task, *, working_directory, **kwargs):
        calls.append(task.task_id)
        assert working_directory.is_relative_to(project / ".superqode/factory/worktrees")
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("answer = 43\n")
        if task.task_id == "verify":
            assert (working_directory / "app.py").read_text() == "answer = 43\n"
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    first = await runner.run_until_idle(store, work_order_id=order.work_order_id)
    assert [item.status for item in first] == ["succeeded", "succeeded"]
    assert calls == ["investigate", "implement"]
    reopened = factory_store(project)
    waiting = reopened.get(order.work_order_id)
    assert waiting.tasks[2].status.value == "waiting_for_human"
    assert waiting.tasks[2].attempts == 0
    assert waiting.tasks[2].lease_expires_at is None
    assert await runner.run_until_idle(reopened, work_order_id=order.work_order_id) == []
    token = waiting.tasks[2].metadata["gate_digest"]
    reopened.decide_gate(
        order.work_order_id, "verify", expected_digest=token, decision="hold", actor="owner"
    )
    assert await runner.run_until_idle(reopened, work_order_id=order.work_order_id) == []
    approved = reopened.decide_gate(
        order.work_order_id,
        "verify",
        expected_digest=token,
        decision="approve",
        actor="owner",
    )
    assert approved.decision is None
    last = await runner.run_until_idle(reopened, work_order_id=order.work_order_id)
    assert [item.status for item in last] == ["succeeded"]
    assert calls == ["investigate", "implement", "verify"]
    assert reopened.get(order.work_order_id).status == WorkOrderStatus.REVIEWING
    assert (project / "app.py").read_text() == "answer = 42\n"
    # Gate continuation cannot replace the application's acceptance/release checks.
    with pytest.raises(ValueError, match="acceptance checks"):
        reopened.accept(order.work_order_id, actor="owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["tampered-snapshot", "source-drift", "model-override"])
async def test_ordinary_workers_block_factory_contract_drift_before_model_calls(
    project, monkeypatch, problem
):
    from superqode.workorders import runner

    plan, store, order = admitted(project)

    async def must_not_execute(*args, **kwargs):
        pytest.fail("Factory integrity checks must precede model execution")

    monkeypatch.setattr(runner, "_execute_harness_task", must_not_execute)
    options = {}
    if problem == "tampered-snapshot":
        (plan.snapshot_directory / "harnesses/investigate.yaml").write_text("changed: true\n")
    elif problem == "source-drift":
        (project / "app.py").write_text("changed = True\n")
    else:
        options["model"] = "unreviewed-model"
    result = await runner.run_next_task(store, work_order_id=order.work_order_id, **options)
    assert result.status == "blocked"
    assert store.get(order.work_order_id).status == WorkOrderStatus.BLOCKED
    assert not (project / ".superqode/factory/worktrees").exists()


@pytest.mark.asyncio
async def test_snapshot_tampering_during_execution_blocks_then_reuses_committed_outcome(
    project, monkeypatch
):
    from superqode.workorders import runner

    plan, store, order = admitted(project)
    path = plan.snapshot_directory / "harnesses/investigate.yaml"
    original = path.read_text()
    calls = []

    async def execute(*args, **kwargs):
        calls.append("model-call")
        path.write_text("changed: true\n")
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    first = await runner.run_next_task(store, work_order_id=order.work_order_id)
    assert first.status == "blocked"
    assert store.invocations(order.work_order_id)[0]["status"] == "completed"
    path.write_text(original)
    store.resume(order.work_order_id)
    resumed = await runner.run_next_task(store, work_order_id=order.work_order_id)
    assert resumed.status == "succeeded"
    assert calls == ["model-call"]


def test_saved_plan_submission_inspection_and_explicit_worker_authorization(project, monkeypatch):
    import asyncio
    from superqode.factory.runtime import load_compiled_plan, factory_store
    from superqode.workorders import runner as work_runner, cleanup_integration_workspace

    plan = compile_factory(resolved(project), root=project, goal="Fix")
    materialize_snapshot(plan)
    document = plan.to_dict()
    assert load_compiled_plan(document, root=project).work_order == plan.work_order
    path = project / ".superqode/plan.json"
    path.write_text(json.dumps(document))
    runner = CliRunner()
    result = runner.invoke(
        factory,
        [
            "submit",
            "--project",
            str(project),
            "--plan",
            ".superqode/plan.json",
            "--request-id",
            "intake",
            "--actor",
            "owner",
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert not output["execution_started"]
    run_id = output["work_order"]["work_order_id"]
    inspection = runner.invoke(factory, ["inspect", run_id, "--project", str(project)])
    assert inspection.exit_code == 0, inspection.output
    assert json.loads(inspection.output)["work_order_id"] == run_id
    denied = runner.invoke(factory, ["worker", run_id, "--project", str(project)])
    assert denied.exit_code != 0
    assert "--live" in denied.output
    calls = []

    async def execute(order, task, **kwargs):
        calls.append(task.task_id)
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    monkeypatch.setattr(work_runner, "_execute_harness_task", execute)
    executed = runner.invoke(factory, ["worker", run_id, "--project", str(project), "--live"])
    assert executed.exit_code == 0, executed.output
    assert calls == ["investigate", "implement"]
    paused = runner.invoke(factory, ["inspect", run_id, "--project", str(project)])
    assert paused.exit_code == 0, paused.output
    gate = json.loads(paused.output)["tasks"][2]
    assert gate["status"] == "waiting_for_human"
    continued = runner.invoke(
        factory,
        [
            "gate",
            run_id,
            "verify",
            "--project",
            str(project),
            "--digest",
            gate["gate_digest"],
            "--decision",
            "approve",
            "--actor",
            "owner",
            "--reason",
            "Inspected evidence",
        ],
    )
    assert continued.exit_code == 0, continued.output
    finished = runner.invoke(factory, ["worker", run_id, "--project", str(project), "--live"])
    assert finished.exit_code == 0, finished.output
    assert calls == ["investigate", "implement", "verify"]
    store = factory_store(project)
    assert store.get(run_id).status == WorkOrderStatus.REVIEWING
    store.cancel(run_id, actor="owner", reason="Trial completed")
    asyncio.run(cleanup_integration_workspace(store, run_id))
    assert plan.snapshot_directory.is_dir()
    assert store.get(run_id).artifacts


@pytest.mark.asyncio
async def test_factory_detects_unrecorded_candidate_changes_during_a_human_wait(
    project, monkeypatch
):
    from superqode.factory.runtime import validate_factory_order
    from superqode.workorders import runner

    plan, store, order = admitted(project)

    async def execute(*args, **kwargs):
        return {"content": "Evidence", "stopped_reason": "complete", "tool_calls": 1}

    monkeypatch.setattr(runner, "_execute_harness_task", execute)
    await runner.run_until_idle(store, work_order_id=order.work_order_id)
    current = store.get(order.work_order_id)
    integration = next(
        a
        for a in current.artifacts
        if a.kind == "workspace" and a.metadata.get("scope") == "work-order"
    )
    (Path(integration.path) / "app.py").write_text("unrecorded = True\n")
    with pytest.raises(ValueError, match="outside recorded task integration"):
        validate_factory_order(current, store=store)


def test_factory_submission_rejects_resource_path_identifiers(project):
    from superqode.factory.runtime import admit_factory

    plan = compile_factory(resolved(project), root=project, goal="Fix")
    materialize_snapshot(plan)
    forged = replace(plan, work_order=replace(plan.work_order, work_order_id="../../outside"))
    with pytest.raises(ValueError, match="safe resource identifier"):
        admit_factory(forged, request_id="bad-id", actor="owner")
