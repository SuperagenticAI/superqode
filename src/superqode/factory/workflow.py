"""Whole-workflow instruction experiments over exact saved Factory contracts."""

from pathlib import Path
from copy import deepcopy

import yaml

from . import trials, experiments
from .definition import load_factory, project_path
from .snapshot import resolve_factory, FactorySnapshot, canonical, digest
from .versioning import source_path, _safe_text
from superqode.desktop_service.ownership import Lease


def validate_composition(definition):
    orchestration = definition["orchestration"]
    stages = orchestration["stages"]
    loop = orchestration.get("revision_loop")
    if (
        any(s.get("when") for s in stages)
        and definition["governance"]["budget"]["max_workers"] != 1
    ):
        raise ValueError("Conditional Factory stages require a single worker")
    if not loop:
        return
    by_id = {s["id"]: s for s in stages}
    implement, review = by_id.get(loop["implement"]), by_id.get(loop["review"])
    if (
        implement is None
        or review is None
        or implement["role"] != "implementer"
        or review["role"] != "reviewer"
        or review.get("depends_on") != [implement["id"]]
        or implement.get("when")
        or review.get("when")
        or len(implement["id"]) > 55
        or len(review["id"]) > 55
    ):
        raise ValueError(
            "A revision loop requires one implementer followed directly by one unconditional reviewer"
        )
    outputs = review.get("outputs", {})
    if len(outputs) != 1 or next(iter(outputs.values()))["type"] != "review":
        raise ValueError("Revision loops require exactly one typed review output")
    if "revision-feedback" in implement.get("inputs", {}):
        raise ValueError("revision-feedback is reserved for the prior iteration review")
    if not any(
        ref["stage"] == implement["id"] and ref.get("candidate_bound")
        for ref in review.get("inputs", {}).values()
    ):
        raise ValueError("Loop reviewers require a candidate-bound implementer output")
    if definition["governance"]["budget"]["max_workers"] != 1:
        raise ValueError("Revision loops require a single worker and shared WorkOrder budget")
    if len(stages) + 2 * (loop["max_iterations"] - 1) > 64:
        raise ValueError("Expanded Factory workflow exceeds 64 stages")
    expanded = [s["id"] for s in stages if s["id"] not in {implement["id"], review["id"]}]
    expanded += [
        f"{name}-r{i}"
        for i in range(1, loop["max_iterations"] + 1)
        for name in (implement["id"], review["id"])
    ]
    if len(expanded) != len(set(expanded)):
        raise ValueError("Expanded loop stage identities collide with another stage")


def expand(definition):
    """Compile one finite implement/review revision block into a static DAG."""
    orchestration = definition["orchestration"]
    stages = deepcopy(orchestration["stages"])
    loop = orchestration.get("revision_loop")
    if not loop:
        return stages
    members = {loop["implement"], loop["review"]}
    count = loop["max_iterations"]
    by_id = {s["id"]: s for s in stages}
    output = next(iter(by_id[loop["review"]]["outputs"]))

    def identity(name, iteration):
        return f"{name}-r{iteration}" if name in members else name

    result = []
    inserted = False
    for original in stages:
        if original["id"] in members:
            if inserted:
                continue
            inserted = True
            for iteration in range(1, count + 1):
                for name in (loop["implement"], loop["review"]):
                    stage = deepcopy(by_id[name])
                    stage["id"] = identity(name, iteration)
                    stage["_origin"] = name
                    stage["_loop"] = {
                        "iteration": iteration,
                        "max_iterations": count,
                        "output": output,
                        "previous_reviews": [
                            identity(loop["review"], i) for i in range(iteration - 1, 0, -1)
                        ],
                    }
                    stage["depends_on"] = [
                        identity(d, iteration) for d in stage.get("depends_on", [])
                    ]
                    for reference in stage.get("inputs", {}).values():
                        reference["stage"] = identity(reference["stage"], iteration)
                    if name == loop["implement"] and iteration > 1:
                        stage["depends_on"].append(identity(loop["review"], iteration - 1))
                        stage.setdefault("inputs", {})["revision-feedback"] = {
                            "stage": identity(loop["review"], iteration - 1),
                            "output": output,
                            "candidate_bound": True,
                        }
                    result.append(stage)
        else:
            stage = deepcopy(original)
            stage["depends_on"] = [identity(d, count) for d in stage.get("depends_on", [])]
            for reference in stage.get("inputs", {}).values():
                source = reference["stage"]
                if source in members:
                    reference["stage"] = identity(source, count)
                    reference["candidates"] = [identity(source, i) for i in range(count, 0, -1)]
            result.append(stage)
    return result


def experiment(root, *, stage, goal, work_goal, expected_snapshot):
    """Export a paired suite, without preparing projects, running models or adopting."""
    root = Path(root).resolve()
    snapshot = resolve_factory(load_factory(root=root))
    if snapshot.digest != expected_snapshot:
        raise ValueError(
            "Save the reviewed Factory and validate again before creating a workflow experiment"
        )
    payload = snapshot.payload
    selected = next(
        (s for s in payload["definition"]["orchestration"]["stages"] if s["id"] == stage), None
    )
    if selected is None:
        raise ValueError("Choose a saved workflow stage")
    for value in (goal, work_goal):
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > 8000:
            raise ValueError("Enter a bounded stage goal and overall trial task")
        _safe_text("workflow.md", value)
    if goal == selected["goal"]:
        raise ValueError("Propose a different stage goal")
    experiments.protect(
        payload["definition"],
        payload["harnesses"][selected["harness"]],
        "workflow",
        selected["harness"],
        stage,
        whole_workflow=True,
    )
    selected["goal"] = goal
    text = yaml.safe_dump(payload["definition"], sort_keys=False)
    payload["sources"][".superqode/factory.yaml"] = {"text": text, "digest": digest(text)}
    candidate = FactorySnapshot.from_dict({"digest": digest(canonical(payload)), **payload})
    revision = trials.repository_revision(root)
    trials._paired(snapshot, candidate, root, revision)
    token = digest(
        canonical({"baseline": snapshot.digest, "candidate": candidate.digest, "task": work_goal})
    )[7:]
    prefix = ".superqode/trials/workflow-experiments/" + token
    budget = {
        k: v
        for k, v in payload["definition"]["governance"]["budget"].items()
        if k in {"max_seconds", "max_tokens", "max_tool_calls", "max_cost_usd"}
    }
    suite = {
        "format": "superqode.factory-trial-suite/1",
        "name": "workflow-experiment",
        "baseline": prefix + "/baseline.json",
        "candidate": prefix + "/candidate.json",
        "budget": budget,
        "cases": [{"id": "workflow", "goal": work_goal}],
    }
    suite_text = yaml.safe_dump(suite, sort_keys=False)
    trials.parse_suite(suite_text)
    lease = Lease(project_path(root, ".superqode/factory-workflow/writer.lock"))
    try:
        folder = source_path(root, ".superqode/trials/workflow-experiments")
        if (
            not (folder / token).exists()
            and folder.exists()
            and sum(p.is_dir() for p in folder.iterdir()) >= 32
        ):
            raise ValueError("Workflow experiment export limit reached; review existing proposals")
        from superqode.desktop_service.studio import _atomic

        sources = {
            "baseline.json": canonical(snapshot.to_dict()),
            "candidate.json": canonical(candidate.to_dict()),
            "suite.yaml": suite_text,
        }
        for name, content in sources.items():
            path = source_path(root, prefix + "/" + name)
            if path.exists() and trials._read(path) != content:
                raise ValueError("Immutable workflow experiment source changed")
        for name, content in sources.items():
            path = source_path(root, prefix + "/" + name)
            if not path.exists():
                _atomic(path, content)
    finally:
        lease.close()
    return {
        "id": token,
        "suite_path": prefix + "/suite.yaml",
        "suite_yaml": suite_text,
        "suite_file_digest": digest(suite_text)[7:],
        "baseline_digest": snapshot.digest,
        "candidate_digest": candidate.digest,
        "model_calls": 0,
        "promotion_authority": False,
        "scope": "Whole-workflow paired experiment; dependencies, typed outputs and human gates execute normally",
    }
