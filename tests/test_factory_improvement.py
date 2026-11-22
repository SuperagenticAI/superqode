"""Pinned improvement contracts never turn imported claims into adoption authority."""
# ruff: noqa: F811

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest
import yaml

from test_factory_definition import project, git, rewrite  # noqa: F401
from superqode.factory import improvement
from superqode.desktop_service.service import DesktopService


@pytest.fixture
def prepared(project):
    root = project
    fixture = root / "fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("A disposable input\n")
    git(root, "add", "fixture/input.txt")
    git(root, "commit", "-qm", "Evaluation fixture")
    suite = root / ".superqode/evals/output.yaml"
    suite.parent.mkdir()
    suite.write_text(
        "tasks:\n  - id: train\n    split: held-in\n    prompt: Say ready\n    expect_contains: ready\n  - id: gate\n    split: held-out\n    prompt: Say ready\n    expect_contains: ready\n"
    )
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=".superqode/evals/output.yaml",
        fixture="fixture",
        max_evals=2,
        max_seconds=60,
    )
    return root, plan


def proposed(root, plan, text=None):
    if text is None:
        data = yaml.safe_load((improvement.folder(root, plan["id"]) / "baseline.yaml").read_text())
        data["agents"][0]["system_prompt"] = (
            "Answer carefully and check the requested output format."
        )
        text = yaml.safe_dump(data, sort_keys=False)
    return improvement.stage(root, plan["id"], text)


def test_native_historical_budget_remains_readable_without_authorizing_new_work(prepared):
    root, plan = prepared
    rewrite(root, lambda data: data["orchestration"]["stages"][0].update(goal="Changed workflow"))
    service = DesktopService(root.parent / "historical-desktop-state")
    try:
        identity = service.open_project(str(root))["id"]
        params = {"project": identity, "plan": plan["id"]}
        opened = service.dispatch("factory.improvement.open", params)
        assert opened["fresh"] is False
        budget = service.dispatch("factory.improvement.budget", params)
        assert budget["plan_digest"] == plan["digest"]
        assert budget["request_count"] == 0
        with pytest.raises(ValueError, match="baseline changed"):
            service.dispatch("factory.improvement.propose", {**params, "yaml": "unused"})
    finally:
        service.close()


def graded_report(kwargs, before="failed", after="passed"):
    from superqode.harness.eval import load_eval_tasks

    tasks = load_eval_tasks(kwargs["tasks_path"])
    snapshot = kwargs["workspace_snapshot"].digest
    rows = []
    for path, status in zip(kwargs["spec_paths"], (before, after)):
        rows.append(
            {
                "spec": str(path),
                "harness": "core",
                "score": float(status == "passed"),
                "tasks": [
                    {
                        "id": task["id"],
                        "split": "held-out",
                        "status": status,
                        "score": float(status == "passed"),
                        "evaluation": {"evaluator": "contains", "status": status},
                        "workspace": {"mode": "isolated-copy", "snapshot_sha256": snapshot},
                        **(
                            {
                                "workspace_integrity": {
                                    "before": snapshot,
                                    "after": snapshot,
                                    "unchanged": True,
                                }
                            }
                            if kwargs.get("readonly_workspace")
                            else {}
                        ),
                    }
                    for task in tasks["tasks"]
                    if task["split"] == "held-out"
                ],
                "usage": {"tokens_in": 2, "tokens_out": 2, "cost_usd": 0.001, "tool_calls": 1},
            }
        )
    from superqode.harness.loader import load_harness_spec, harness_spec_to_dict

    report = {
        **({"inference_routes": kwargs["model_routes"]} if "model_routes" in kwargs else {}),
        **(
            {
                "prompt_digests": {
                    key: {identity: improvement.digest(value) for identity, value in values.items()}
                    for key, values in kwargs["task_prompts"].items()
                }
            }
            if "task_prompts" in kwargs
            else {}
        ),
        **({"readonly_workspace": True} if kwargs.get("readonly_workspace") else {}),
        "spec_digests": {
            str(path): improvement.digest(
                improvement.canonical(harness_spec_to_dict(load_harness_spec(path)))
            )
            for path in kwargs["spec_paths"]
        },
        "live": True,
        "split": "held-out",
        "task_count": 1,
        "tasks_hash": tasks["tasks_hash"],
        "workspace": {"mode": "isolated-copy", "snapshot_sha256": snapshot},
        "variants": rows,
    }

    record_fixture_usage(kwargs, report)
    return report


def record_fixture_usage(kwargs, report):
    """Explicitly simulated request receipts for the mocked evaluator fixtures."""
    from superqode.providers.gateway.base import GatewayResponse, Usage, Cost

    observer = kwargs.get("evaluation_observer")
    if observer is None:
        return
    tasks = yaml.safe_load(Path(kwargs["tasks_path"]).read_text())["tasks"]
    selected = [t for t in tasks if t.get("split", "held-in") == kwargs["eval_split"]]
    for index, variant in enumerate(report["variants"]):
        spec = variant.setdefault("spec", str(kwargs["spec_paths"][index]))
        provider, model = kwargs["provider"], kwargs["model"]
        if spec in kwargs.get("model_routes", {}):
            from superqode.providers.model_specs import split_provider_model_ref

            route = split_provider_model_ref(kwargs["model_routes"][spec])
            provider, model = route.provider, route.model
        for row, task in zip(variant["tasks"], selected):
            with observer.operation(spec=spec, task=task, provider=provider, model=model) as scope:
                request = scope.ledger.begin_request(scope.identity, provider, model)
                scope.ledger.finish_request(
                    request,
                    GatewayResponse(
                        content="Explicitly simulated evaluator response",
                        usage=Usage(prompt_tokens=2, completion_tokens=2, total_tokens=4),
                        cost=Cost(total_cost=0.001),
                    ),
                )
                row.setdefault(
                    "usage",
                    {
                        "tokens_in": 2,
                        "tokens_out": 2,
                        "total_tokens": 4,
                        "tool_calls": 1,
                        "cost_usd": 0.001,
                    },
                )
                observer.complete(scope, row)


@pytest.fixture
def fake_eval(monkeypatch):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        assert kwargs["eval_split"] == "held-out"
        assert kwargs["working_dir"].name == "fixture"
        assert not (kwargs["workspace_snapshot"].snapshot / ".superqode/evals/output.yaml").exists()
        return graded_report(kwargs)

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    return calls


def test_preparation_pins_inputs_without_model_calls_or_definition_changes(prepared):
    root, plan = prepared
    original = (root / ".superqode/factory.yaml").read_text()
    pinned, snapshot = improvement.load(root, plan["id"], plan["digest"], fresh=True)
    assert pinned["split_counts"] == {"held-in": 1, "held-out": 1, "all": 2}
    assert pinned["heldout_ids"] == ["gate"]
    assert snapshot.digest == plan["factory_digest"]
    assert (root / ".superqode/factory.yaml").read_text() == original


def test_own_comparison_can_propose_draft_without_activating_it(prepared, fake_eval):
    root, plan = prepared
    original = (root / ".superqode/factory.yaml").read_text()
    candidate = proposed(root, plan)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert result["eligible"] and len(fake_eval) == 1
    draft = improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])
    assert draft["proposal_only"]
    after = yaml.safe_load(draft["yaml"])
    before = yaml.safe_load(original)
    assert (
        after["governance"] == before["governance"]
        and after["improvement"] == before["improvement"]
    )
    assert after["orchestration"] == before["orchestration"]
    assert (root / draft["component"]).is_file()
    assert (root / ".superqode/factory.yaml").read_text() == original


@pytest.mark.parametrize(
    "field", ["model_policy", "execution_policy", "workflow", "context", "tools"]
)
def test_protected_candidate_fields_are_rejected_before_model_calls(prepared, field):
    root, plan = prepared
    data = yaml.safe_load((improvement.folder(root, plan["id"]) / "baseline.yaml").read_text())
    if field == "model_policy":
        data[field]["primary"] = "openai/other"
    elif field == "execution_policy":
        data[field]["allow_network"] = True
    elif field == "workflow":
        data[field]["parallelism"] = 2
    elif field == "context":
        data[field]["instruction_files"] = [".env"]
    else:
        data["agents"][0]["tools"] = ["evil"]
    with pytest.raises(ValueError, match="protected"):
        proposed(root, plan, yaml.safe_dump(data))


@pytest.mark.parametrize("changed", ["factory", "suite", "fixture", "candidate", "receipt"])
def test_stale_or_modified_inputs_and_evidence_cannot_be_adopted(prepared, fake_eval, changed):
    root, plan = prepared
    candidate = proposed(root, plan)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    directory = improvement.folder(root, plan["id"])
    if changed == "factory":
        rewrite(root, lambda d: d["metadata"].update(description="changed"))
    elif changed == "suite":
        (root / plan["tasks"]).write_text("changed")
    elif changed == "fixture":
        (root / "fixture/input.txt").write_text("changed")
    elif changed == "candidate":
        (directory / "candidates" / (candidate["candidate"] + ".yaml")).write_text("changed")
    else:
        (directory / "comparison/receipt.json").write_text("{}")
    with pytest.raises(ValueError):
        improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])


@pytest.mark.parametrize(
    "before,after", [("passed", "failed"), ("passed", "passed"), ("failed", "error")]
)
def test_regression_tie_and_incomplete_grading_hold_adoption(prepared, monkeypatch, before, after):
    root, plan = prepared
    candidate = proposed(root, plan)

    async def evaluate(**kwargs):
        return graded_report(kwargs, before, after)

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert not result["eligible"]
    with pytest.raises(ValueError, match="does not authorize"):
        improvement.adoption(root, plan["id"], candidate["candidate"], result["receipt_digest"])


def test_one_heldout_comparison_per_plan(prepared, fake_eval):
    root, plan = prepared
    candidate = proposed(root, plan)
    asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    with pytest.raises(FileExistsError):
        asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    assert len(fake_eval) == 1


def test_native_adoption_requires_completed_matching_comparison_job(
    prepared, tmp_path, monkeypatch, fake_eval
):
    root, plan = prepared
    candidate = proposed(root, plan)
    result = asyncio.run(improvement.compare(root, plan["id"], candidate["candidate"]))
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        project_id = service.open_project(str(root))["id"]
        service._write(
            "INSERT INTO factory_improvement_plans VALUES(?,?,?,?)",
            (plan["id"], project_id, json.dumps(plan), time.time()),
        )
        params = {
            "project": project_id,
            "plan": plan["id"],
            "candidate": candidate["candidate"],
            "confirmed": True,
            "comparison_job": "invented",
        }
        with pytest.raises(ValueError, match="completed native comparison"):
            service.dispatch("factory.improvement.adopt", params)
        request = {
            "factory_action": "improvement-compare",
            "plan": plan["id"],
            "candidate": candidate["candidate"],
        }
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "real-fixture",
                project_id,
                "factory",
                "Comparison",
                "completed",
                json.dumps(request),
                json.dumps(result),
                time.time(),
                time.time(),
            ),
        )
        params["comparison_job"] = "real-fixture"
        assert service.dispatch("factory.improvement.adopt", params)["proposal_only"]
    finally:
        service.close()


@pytest.mark.parametrize("target_kind", ["harness", "skill", "route", "workflow"])
def test_real_model_fixture_comparison_uses_native_job_and_can_adopt(
    project, tmp_path, monkeypatch, target_kind
):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            improved = (
                "IMPROVEMENT_FIXTURE_CANDIDATE" in json.dumps(body["messages"])
                or body["model"] == "fixture-model-candidate"
            )
            message = {"role": "assistant", "content": "ready" if improved else "incorrect"}
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream" if body.get("stream") else "application/json"
            )
            self.end_headers()
            usage = {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}
            if body.get("stream"):
                for delta, finish in [(message, None), ({}, "stop")]:
                    packet = {
                        "id": "fixture",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "fixture-model",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                        "usage": usage,
                    }
                    self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "fixture",
                            "object": "chat.completion",
                            "created": 1,
                            "model": "fixture-model",
                            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                            "usage": usage,
                        }
                    ).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LMSTUDIO_HOST", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"]["coder"].update(model="lmstudio/fixture-model"),
    )
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]

        def rpc(method, **params):
            return service.dispatch(
                "factory.improvement." + method, {"project": identity, **params}
            )

        if target_kind == "skill":
            created = rpc(
                "skill.create",
                binding="coder",
                skill="review",
                confirmed=True,
                yaml=(project / ".superqode/factory.yaml").read_text(),
                markdown="---\nname: review\n---\nCheck the response format.\n",
            )
            (project / ".superqode/factory.yaml").write_text(created["yaml"])

        suite = rpc("suite.open", path=".superqode/evals/improve.yaml")
        rpc(
            "suite.save",
            path=".superqode/evals/improve.yaml",
            yaml=suite["yaml"],
            expected_file_digest=suite["expected_file_digest"],
        )
        plan = rpc(
            "prepare",
            binding="coder",
            tasks=".superqode/evals/improve.yaml",
            fixture="@empty",
            max_evals=1,
            max_seconds=45,
            reflection_model="",
            target_kind=target_kind,
            skill="review" if target_kind == "skill" else "",
            stage="investigate" if target_kind == "workflow" else "",
            route_models=["lmstudio/fixture-model", "lmstudio/fixture-model-candidate"]
            if target_kind == "route"
            else None,
        )
        if target_kind == "route":
            text = "model: lmstudio/fixture-model-candidate\n"
        elif target_kind == "workflow":
            text = "stage: investigate\ngoal: IMPROVEMENT_FIXTURE_CANDIDATE follow the requested output exactly.\n"
        elif target_kind == "skill":
            text = plan["baseline_yaml"].replace(
                "Check the response format.",
                "IMPROVEMENT_FIXTURE_CANDIDATE: follow the requested output exactly.",
            )
        else:
            data = yaml.safe_load(plan["baseline_yaml"])
            data["agents"][0]["system_prompt"] = (
                "IMPROVEMENT_FIXTURE_CANDIDATE: follow the requested output exactly."
            )
            text = yaml.safe_dump(data)
        candidate = rpc("propose", plan=plan["id"], yaml=text)
        job = service.dispatch(
            "factory.action.start",
            {
                "project": identity,
                "factory_action": "improvement-compare",
                "confirmed": True,
                "plan": plan["id"],
                "candidate": candidate["candidate"],
                "command_id": "comparison-once",
            },
        )
        for _ in range(600):
            result = service.dispatch("jobs.get", {"id": job["id"]})
            if result["status"] not in {"queued", "running", "needs_approval", "cancelling"}:
                break
            time.sleep(0.05)
        assert result["status"] == "completed", result
        assert result["result"]["eligible"], result
        assert len(calls) == 2
        original = (project / ".superqode/factory.yaml").read_text()
        draft = rpc(
            "adopt",
            plan=plan["id"],
            candidate=candidate["candidate"],
            comparison_job=job["id"],
            confirmed=True,
        )
        assert draft["proposal_only"]
        if target_kind in {"harness", "skill"}:
            assert (project / draft["component"]).is_file()
        if target_kind == "route":
            assert [c["model"] for c in calls] == ["fixture-model", "fixture-model-candidate"]
            assert (
                yaml.safe_load(draft["yaml"])["inference"]["harnesses"]["coder"]["model"]
                == "lmstudio/fixture-model-candidate"
            )
        if target_kind == "workflow":
            assert "Assigned role: investigator" in json.dumps(calls[1]["messages"])
            assert yaml.safe_load(draft["yaml"])["orchestration"]["stages"][0]["goal"].startswith(
                "IMPROVEMENT_FIXTURE_CANDIDATE"
            )
        assert (project / ".superqode/factory.yaml").read_text() == original
    finally:
        service.close()
        server.shutdown()
        server.server_close()


def test_gepa_adapter_never_supplies_heldout_examples_and_rejects_bad_proposals(
    prepared, monkeypatch
):
    from types import SimpleNamespace

    root, original = prepared
    plan = improvement.prepare(
        root,
        binding="coder",
        tasks=original["tasks"],
        fixture="fixture",
        max_evals=2,
        max_seconds=60,
        reflection_model="ollama/qwen3-coder",
    )
    rolled_out = []

    async def evaluate(**kwargs):
        rolled_out.append(kwargs)
        assert kwargs["eval_split"] == "held-in"
        tasks = yaml.safe_load(Path(kwargs["tasks_path"]).read_text())["tasks"]
        assert tasks[0]["id"] == "train" and tasks[0]["split"] == "held-in"
        report = {"variants": [{"tasks": [{"score": 1, "status": "passed", "reason": "Fixture"}]}]}
        record_fixture_usage(kwargs, report)
        return report

    def optimizer(**kwargs):
        assert kwargs["test_set"] == []
        assert all(row["split"] == "held-in" for row in kwargs["dataset"] + kwargs["valset"])
        seed = yaml.safe_load(kwargs["seed_candidate"])
        bad = deepcopy(seed)
        bad["execution_policy"]["allow_network"] = True
        assert kwargs["evaluator"](yaml.safe_dump(bad), kwargs["dataset"][0])[0] == 0
        seed["agents"][0]["system_prompt"] = "Check the requested output carefully."
        candidate = yaml.safe_dump(seed)
        assert kwargs["evaluator"](candidate, kwargs["dataset"][0])[0] == 1
        return SimpleNamespace(best_candidate=candidate, metadata={})

    monkeypatch.setattr(improvement, "run_harness_eval", evaluate)
    monkeypatch.setattr("superqode.skillopt._run_modern_optimizer", optimizer)
    result = improvement.optimize(root, plan["id"], plan["digest"])
    assert result["proposal_only"] and result["heldout_exposed"] is False
    assert len(rolled_out) == 1 and result["metric_calls"] == 2


def test_suite_editor_rejects_non_graded_tasks_and_stale_saves(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        path = ".superqode/evals/edited.yaml"
        starter = service.dispatch(
            "factory.improvement.suite.open", {"project": identity, "path": path}
        )
        saved = service.dispatch(
            "factory.improvement.suite.save",
            {
                "project": identity,
                "path": path,
                "yaml": starter["yaml"],
                "expected_file_digest": "",
            },
        )
        with pytest.raises(ValueError, match="changed"):
            service.dispatch(
                "factory.improvement.suite.save",
                {
                    "project": identity,
                    "path": path,
                    "yaml": starter["yaml"],
                    "expected_file_digest": "",
                },
            )
        with pytest.raises(ValueError, match="deterministic"):
            service.dispatch(
                "factory.improvement.suite.save",
                {
                    "project": identity,
                    "path": path,
                    "yaml": starter["yaml"].replace(
                        "expect_contains: ready", "evaluator: {type: non_empty}"
                    ),
                    "expected_file_digest": saved["digest"],
                },
            )
        assert (project / path).read_text() == starter["yaml"]
    finally:
        service.close()


def test_context_under_superqode_is_kept_in_pinned_trial_inputs(project):
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.harness.templates import core_template

    spec = harness_spec_to_dict(core_template())
    spec["context"]["instruction_files"] = [".superqode/context/rules.md"]
    component = project / ".superqode/components/coder.yaml"
    component.parent.mkdir()
    component.write_text(yaml.safe_dump(spec))
    instructions = project / ".superqode/context/rules.md"
    instructions.parent.mkdir()
    instructions.write_text("Pinned instruction")
    rewrite(
        project,
        lambda d: d["inference"]["harnesses"].update(
            coder={"path": ".superqode/components/coder.yaml", "model": "ollama/qwen3-coder"}
        ),
    )
    suite = project / ".superqode/evals/tasks.yaml"
    suite.parent.mkdir()
    suite.write_text(
        "tasks:\n  - {id: train, split: held-in, prompt: Say x, expect_contains: x}\n  - {id: gate, split: held-out, prompt: Say y, expect_contains: y}\n"
    )
    plan = improvement.prepare(
        project,
        binding="coder",
        tasks=".superqode/evals/tasks.yaml",
        fixture="@empty",
        max_evals=1,
        max_seconds=10,
    )
    directory = improvement.folder(project, plan["id"])
    with improvement.EvaluationWorkspace(
        directory / "fixture", temporary_dir=directory / "temporary", git_discovery=False
    ) as workspace:
        assert (
            workspace.snapshot / "factory-pinned-context/internal/context/rules.md"
        ).read_text() == "Pinned instruction"


def test_deadline_cancels_only_the_matching_owned_job(project, tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "state")
    try:
        identity = service.open_project(str(project))["id"]
        service._write(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "bounded",
                identity,
                "factory",
                "Bounded",
                "running",
                "{}",
                None,
                time.time(),
                time.time(),
            ),
        )

        class Process:
            def wait(self, timeout):
                raise subprocess.TimeoutExpired("fixture", timeout)

        process = Process()
        service.processes["bounded"] = process
        cancelled = []
        monkeypatch.setattr(
            service, "dispatch", lambda method, params: cancelled.append((method, params))
        )
        service._factory_deadline("bounded", process, 1)
        assert cancelled == [("jobs.cancel", {"id": "bounded"})]
        service.processes.pop("bounded")
    finally:
        service.close()
