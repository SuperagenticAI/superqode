"""Suite preparation, persisted gates and scorecards never confer release authority."""
# ruff: noqa: F811

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from test_factory_definition import project, git, rewrite  # noqa: F401
from test_factory_verification import simulated_probes  # noqa: F401
from superqode.factory import trials
from superqode.factory.runtime import factory_store
from superqode.desktop_service.service import DesktopService


@pytest.fixture
def suite_project(project):
    path = project / "protected/probes.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "format": "superqode.factory-probes/1",
                "cases": [{"id": "answer", "argv": ["python", "app.py"], "stdout": "43\n"}],
            }
        )
    )
    git(project, "add", "protected/probes.json")
    git(project, "commit", "-qm", "Pin suite acceptance")
    rewrite(
        project,
        lambda d: (
            d["data_context"]["files"].update(
                probes={"path": "protected/probes.json", "purpose": "evaluator"}
            ),
            d["improvement"]["checks"]["regression"].update(
                command="python3 app.py", evaluator="probes"
            ),
        ),
    )
    source = project / ".superqode/trials/candidate.yaml"
    source.parent.mkdir()
    data = yaml.safe_load((project / ".superqode/factory.yaml").read_text())
    data["orchestration"]["stages"][0]["goal"] = "Inspect the exact failing branch and edge cases."
    source.write_text(yaml.safe_dump(data, sort_keys=False))
    suite = yaml.safe_load(trials.starter())
    suite["candidate"] = ".superqode/trials/candidate.yaml"
    suite["cases"] = [{"id": "answer", "goal": "Make app.py print 43"}]
    return project, suite


@pytest.fixture
def execution(monkeypatch):
    calls = []

    async def execute(order, task, *, working_directory, **kwargs):
        calls.append((order.work_order_id, task.task_id))
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print(43)\n")
        return {
            "content": "Test-only execution",
            "stopped_reason": "complete",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    return calls


def test_preparation_creates_pinned_pairs_without_models_and_narrows_budgets(suite_project):
    root, suite = suite_project
    original = (root / "app.py").read_text()
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    assert len(plan["entries"]) == 2
    assert all(
        e["budget"]["max_tokens"] == suite["budget"]["max_tokens"] // 2 for e in plan["entries"]
    )
    board = trials.scorecard(root, plan["id"], plan["digest"])
    assert board["verdict"] == "incomplete" and not board["complete"]
    assert not board["promotion_authority"] and not board["release_authorization"]
    assert all(r["status"] == "pending" for r in board["entries"])
    assert (root / "app.py").read_text() == original


def test_resolved_snapshot_replay_ignores_later_definition_edits(suite_project):
    from superqode.factory import load_factory, resolve_factory

    root, suite = suite_project
    snapshot = resolve_factory(load_factory(root=root))
    path = root / ".superqode/trials/pinned.json"
    path.write_text(json.dumps(snapshot.to_dict()))
    suite["baseline"] = suite["candidate"] = path.relative_to(root).as_posix()
    rewrite(root, lambda d: d["orchestration"]["stages"][0].update(goal="Different current draft"))
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    assert all(e["original_snapshot_digest"] == snapshot.digest for e in plan["entries"])


def test_suite_pauses_at_each_gate_and_reopens_without_repeating_work(
    suite_project, execution, simulated_probes
):
    root, suite = suite_project
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    first = asyncio.run(trials.advance(root, plan["id"], plan["digest"]))
    next(r for r in first["entries"] if r["status"] == "waiting")
    assert len(execution) == 2
    before = list(execution)
    again = asyncio.run(trials.advance(root, plan["id"], plan["digest"]))
    assert execution == before and again["verdict"] == "incomplete"
    for _ in range(2):
        board = trials.scorecard(root, plan["id"])
        row = next(r for r in board["entries"] if r["status"] == "waiting")
        gate = row["gates"][0]
        detail = trials.inspect_entry(root, plan["id"], row["id"])
        assert "+print(43)" in detail["patch"]
        trials.gate(root, plan["id"], row["id"], gate["stage"], gate["digest"], "hold")
        assert asyncio.run(trials.advance(root, plan["id"]))["verdict"] == "incomplete"
        trials.gate(
            root, plan["id"], row["id"], gate["stage"], gate["digest"], "approve", "Test operator"
        )
        result = asyncio.run(trials.advance(root, plan["id"]))
    assert result["verdict"] == "tie" and result["complete"]
    assert result["summary"]["baseline"]["passed"] == result["summary"]["candidate"]["passed"] == 1
    assert len(execution) == 6
    assert len(set(execution)) == 6
    for entry in plan["entries"]:
        order = factory_store(root / entry["project"]).get(entry["run"])
        assert (
            order.status.value not in {"accepted", "ready_to_merge", "merging", "merged"}
            and order.decision is None
        )
        assert not order.metadata.get("factory_release")
    assert (root / "app.py").read_text() == "answer = 42\n"


@pytest.mark.parametrize("change", ["governance", "gate", "checks", "evaluator"])
def test_comparison_cannot_weaken_pinned_policy_or_evaluators(suite_project, change):
    root, suite = suite_project
    path = root / suite["candidate"]
    data = yaml.safe_load(path.read_text())
    if change == "governance":
        data["governance"]["permissions"]["allow_network"] = True
    elif change == "gate":
        data["orchestration"]["stages"][2]["human_gate"] = False
    elif change == "checks":
        data["improvement"]["checks"]["regression"]["command"] = "true"
    else:
        other = root / ".superqode/evaluators/other.json"
        other.parent.mkdir()
        other.write_text(
            json.dumps(
                {
                    "format": "superqode.factory-probes/1",
                    "cases": [{"id": "weaker", "argv": ["python", "app.py"], "stdout": ""}],
                }
            )
        )
        data["data_context"]["files"]["probes"]["path"] = ".superqode/evaluators/other.json"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="preserve|identical"):
        trials.prepare(root, suite_text=yaml.safe_dump(suite))


@pytest.mark.parametrize("target", ["fixture", "plan", "snapshot"])
def test_input_tampering_holds_or_rejects_suite(suite_project, target):
    root, suite = suite_project
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    directory = trials.folder(root, plan["id"])
    if target == "fixture":
        (directory / "fixture/app.py").write_text("modified")
    elif target == "plan":
        (directory / "plan.json").write_text("{}")
    else:
        entry = plan["entries"][0]
        project = root / entry["project"]
        order = factory_store(project).get(entry["run"])
        (Path(order.metadata["factory"]["snapshot_directory"]) / "snapshot.json").write_text("{}")
    if target == "snapshot":
        assert trials.scorecard(root, plan["id"])["verdict"] == "hold"
    else:
        with pytest.raises(ValueError):
            trials.scorecard(root, plan["id"], plan["digest"])


def test_native_editor_cas_and_registered_project_boundary(suite_project, tmp_path, monkeypatch):
    root, suite = suite_project
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop")
    try:
        identity = service.open_project(str(root))["id"]

        def rpc(method, **params):
            return service.dispatch("factory.suite." + method, {"project": identity, **params})

        path = ".superqode/trials/test.yaml"
        starter = rpc("source.open", path=path)
        rpc(
            "source.save",
            path=path,
            yaml=yaml.safe_dump(suite),
            expected_file_digest=starter["expected_file_digest"],
        )
        with pytest.raises(ValueError, match="changed"):
            rpc("source.save", path=path, yaml=yaml.safe_dump(suite), expected_file_digest="")
        board = rpc("prepare", yaml=yaml.safe_dump(suite), confirmed=True)
        assert len(rpc("list")["suites"]) == 1
        assert rpc("inspect", suite=board["plan"]["id"])["verdict"] == "incomplete"
        assert not service.processes
        from superqode.desktop_service.factory_studio import validate_request

        request = validate_request(
            root,
            {
                "factory_action": "suite-run",
                "project": identity,
                "suite": board["plan"]["id"],
                "confirmed": True,
                "factory_providers": ["unrelated"],
            },
            service=service,
        )
        assert request["factory_providers"] == ["ollama"]
        other = root / "other"
        other.mkdir()
        different = service.open_project(str(other))["id"]
        with pytest.raises(ValueError, match="prepared for this project"):
            service.dispatch(
                "factory.suite.inspect", {"project": different, "suite": board["plan"]["id"]}
            )
    finally:
        service.close()


def test_unknown_required_usage_is_held_and_never_displayed_as_zero(suite_project, monkeypatch):
    root, suite = suite_project

    async def unknown(order, task, **kwargs):
        return {"content": "No usage evidence", "stopped_reason": "complete"}

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", unknown)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    board = asyncio.run(trials.advance(root, plan["id"]))
    assert board["verdict"] == "hold"
    assert board["summary"]["baseline"]["usage"]["total_tokens"] is None
    assert any("unknown" in issue for issue in board["issues"])


def test_every_tracked_seed_file_is_pinned_even_in_dependency_directories(suite_project):
    root, suite = suite_project
    path = root / "node_modules/pinned.txt"
    path.parent.mkdir()
    path.write_text("pinned content")
    git(root, "add", "-f", "node_modules/pinned.txt")
    git(root, "commit", "-qm", "Track dependency fixture")
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    child = root / plan["entries"][0]["project"]
    assert git(child, "show", "HEAD:node_modules/pinned.txt") == "pinned content"
    (trials.folder(root, plan["id"]) / "fixture/node_modules/pinned.txt").write_text("tampered")
    with pytest.raises(ValueError, match="fixture changed"):
        trials.scorecard(root, plan["id"])


@pytest.mark.parametrize("problem", ["receipt", "history", "regression", "variation"])
def test_scorecard_evidence_history_and_regressions(
    suite_project, execution, simulated_probes, monkeypatch, problem
):
    root, suite = suite_project
    if problem in {"regression", "variation"}:
        if problem == "variation":
            suite["candidate"] = suite["baseline"]

        async def execute(order, task, *, working_directory, **kwargs):
            if task.task_id == "implement":
                text = "print(0)\n" if "candidate" in str(working_directory) else "print(43)\n"
                (working_directory / "app.py").write_text(text)
            return {
                "content": "Test-only execution",
                "stopped_reason": "complete",
                "tokens_in": 4,
                "tokens_out": 2,
                "cost_usd": 0,
                "tool_calls": 1,
            }

        monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    for _ in range(3):
        board = asyncio.run(trials.advance(root, plan["id"]))
        gates = [(r, r["gates"][0]) for r in board["entries"] if r["gates"]]
        if not gates:
            break
        row, gate = gates[0]
        trials.gate(
            root, plan["id"], row["id"], gate["stage"], gate["digest"], "approve", "Test operator"
        )
    assert board["complete"]
    if problem in {"regression", "variation"}:
        assert board["verdict"] == problem and board["regressions"] == ["answer"]
    else:
        path = trials.folder(root, plan["id"]) / "state.json"
        state = json.loads(path.read_text())
        if problem == "receipt":
            next(iter(state["receipts"].values()))["digest"] = "sha256:modified"
            path.write_text(json.dumps(state))
            assert trials.scorecard(root, plan["id"])["verdict"] == "hold"
        else:
            monkeypatch.setattr(trials.time, "time", lambda: state["finished"] + 10000)
            assert trials.scorecard(root, plan["id"])["verdict"] == "tie"
    assert not board["promotion_authority"] and not board["release_authorization"]


def test_failed_stage_retry_is_explicit_bounded_and_preserves_completed_work(
    suite_project, simulated_probes, monkeypatch
):
    root, suite = suite_project
    calls = []

    async def execute(order, task, *, working_directory, **kwargs):
        calls.append((order.work_order_id, task.task_id))
        if task.task_id == "implement":
            (working_directory / "app.py").write_text("print(43)\n")
        failed = (
            task.task_id == "verify" and "baseline" in str(working_directory) and task.attempts == 1
        )
        return {
            "content": "Test-only execution",
            "stopped_reason": "error" if failed else "complete",
            "error": "Recorded provider failure" if failed else "",
            "tokens_in": 4,
            "tokens_out": 2,
            "cost_usd": 0,
            "tool_calls": 1,
        }

    monkeypatch.setattr("superqode.workorders.runner._execute_harness_task", execute)
    plan = trials.prepare(root, suite_text=yaml.safe_dump(suite))
    first = asyncio.run(trials.advance(root, plan["id"]))
    row = first["entries"][0]
    gate = row["gates"][0]
    trials.gate(root, plan["id"], row["id"], gate["stage"], gate["digest"], "approve")
    held = asyncio.run(trials.advance(root, plan["id"]))
    assert held["entries"][0]["status"] == "held"
    with pytest.raises(ValueError, match="changed"):
        trials.retry(root, plan["id"], row["id"], "verify", 99)
    store = factory_store(root / row["project"])
    with store._transaction() as conn:
        conn.execute(
            "update work_invocations set status='uncertain' where work_order_id=? and task_id='verify'",
            (row["run"],),
        )
    with pytest.raises(ValueError, match="Reconcile"):
        trials.retry(root, plan["id"], row["id"], "verify", 1)
    with store._transaction() as conn:
        conn.execute(
            "update work_invocations set status='completed' where work_order_id=? and task_id='verify'",
            (row["run"],),
        )
    trials.retry(
        root, plan["id"], row["id"], "verify", 1, "Operator confirms a known failed attempt"
    )
    with pytest.raises(ValueError, match="changed"):
        trials.retry(root, plan["id"], row["id"], "verify", 1)
    board = asyncio.run(trials.advance(root, plan["id"]))
    if any(r["gates"] for r in board["entries"]):
        for _ in range(3):
            pending = next((r for r in board["entries"] if r["gates"]), None)
            if not pending:
                break
            gate = pending["gates"][0]
            trials.gate(root, plan["id"], pending["id"], gate["stage"], gate["digest"], "approve")
            board = asyncio.run(trials.advance(root, plan["id"]))
    assert board["complete"] and board["verdict"] == "tie"
    tasks = factory_store(root / row["project"]).get(row["run"]).tasks
    assert [t.attempts for t in tasks] == [1, 1, 2]
    assert calls.count((row["run"], "investigate")) == calls.count((row["run"], "implement")) == 1
