"""Bounded route and workflow-stage proposals over a pinned Factory snapshot."""

from copy import deepcopy
from dataclasses import replace
import fnmatch
from pathlib import Path

import yaml

from .definition import validate_definition
from .snapshot import FactorySnapshot, canonical, digest


def stage_definition(definition, identity):
    stages = [s for s in definition["orchestration"]["stages"] if s["id"] == identity]
    if not stages:
        raise ValueError("Choose a declared workflow stage")
    stage = stages[0]
    if stage.get("depends_on") or stage.get("human_gate"):
        raise ValueError("Workflow experiments currently require an ungated entry stage")
    if stage["role"] == "reviewer" and any(
        o["type"] != "review" for o in stage.get("outputs", {}).values()
    ):
        raise ValueError("Reviewer experiments require exclusively typed review outputs")
    return stage


def protect(definition, harness, kind, binding, stage="", *, whole_workflow=False):
    policy = definition["improvement"].get("optimization", {})
    if ("routes" if kind == "route" else "workflow") not in policy.get("editable", []):
        raise ValueError("Factory policy does not allow this improvement target")
    paths = (
        [
            "routes",
            f"inference.harnesses.{binding}.model",
            f"inference.harnesses.{binding}.model_policy.primary",
            f"harnesses.{binding}.model_policy.primary",
        ]
        if kind == "route"
        else ["workflow", f"workflow.{stage}.goal", f"orchestration.stages.{stage}.goal"]
    )
    if kind == "workflow":
        selected = (
            next((s for s in definition["orchestration"]["stages"] if s["id"] == stage), None)
            if whole_workflow
            else stage_definition(definition, stage)
        )
        if selected is None:
            raise ValueError("Choose a declared workflow stage")
        if selected["harness"] != binding:
            raise ValueError("Workflow stage belongs to a different harness binding")
        index = definition["orchestration"]["stages"].index(selected)
        paths += [f"orchestration.stages.{index}.goal"]
    for pattern in policy.get("protected", []):
        if any(
            fnmatch.fnmatchcase(".".join(p.split(".")[:i]), pattern)
            for p in paths
            for i in range(1, len(p.split(".")) + 1)
        ):
            raise ValueError("Factory policy protects this improvement surface")
    if kind == "route":
        from superqode.harness.loader import harness_spec_from_dict

        spec = harness_spec_from_dict(harness)
        if spec.model_policy.fallbacks:
            raise ValueError("Route experiments require a primary-only harness without fallbacks")
        for pattern in spec.optimization.protected_surfaces:
            if any(
                fnmatch.fnmatchcase(p, pattern) for p in ("model_policy", "model_policy.primary")
            ):
                raise ValueError("Harness policy protects its model route")


def baseline(payload, kind, binding, stage=""):
    if kind == "route":
        return {"model": payload["harnesses"][binding]["model_policy"]["primary"]}
    selected = stage_definition(payload["definition"], stage)
    return {"stage": stage, "goal": selected["goal"]}


def proposed_snapshot(snapshot, kind, binding, stage, proposal):
    payload = snapshot.payload
    definition = payload["definition"]
    if kind == "route":
        definition["inference"]["harnesses"][binding]["model"] = proposal["model"]
        payload["harnesses"][binding]["model_policy"]["primary"] = proposal["model"]
    else:
        stage_definition(definition, stage)["goal"] = proposal["goal"]
    validate_definition(definition)
    # Keep the transient snapshot self-contained, including its definition source.
    text = yaml.safe_dump(definition, sort_keys=False)
    payload["sources"][".superqode/factory.yaml"] = {"text": text, "digest": digest(text)}
    return FactorySnapshot.from_dict({"digest": digest(canonical(payload)), **payload})


def route_choices(snapshot, binding, choices, *, root, revision):
    from superqode.providers.model_specs import split_provider_model_ref
    from .compiler import _compile_factory

    root = Path(root).resolve()

    payload = snapshot.payload
    current = baseline(payload, "route", binding)["model"]
    if choices is None:
        definition = payload["definition"]
        choices = [
            current,
            *definition.get("routes", {})
            .get(definition.get("default_route"), {})
            .get("prefer", []),
        ]
        choices = list(dict.fromkeys(choices))
    if (
        not isinstance(choices, list)
        or not 1 <= len(choices) <= 8
        or len(set(map(str, choices))) != len(choices)
    ):
        raise ValueError("Explicitly select one to eight unique model routes")
    if current not in choices:
        raise ValueError("Include the baseline model in the selected route choices")
    for model in choices:
        if (
            not isinstance(model, str)
            or len(model) > 256
            or "/" not in model
            or model.strip() != model
        ):
            raise ValueError("Model routes must use provider/model names")
        route = split_provider_model_ref(model)
        if route.provider in {"synthetic", "acp"} or not route.provider or not route.model:
            raise ValueError("Route experiments require direct model providers")
        candidate = proposed_snapshot(snapshot, "route", binding, "", {"model": model})
        _compile_factory(candidate, root=root, goal="Review route choice", revision=revision)
    return deepcopy(choices)


def check_proposal(snapshot, plan, proposal, *, root):
    from .compiler import _compile_factory

    root = Path(root).resolve()

    kind = plan["target_kind"]
    protect(
        snapshot.payload["definition"],
        snapshot.payload["harnesses"][plan["binding"]],
        kind,
        plan["binding"],
        plan.get("stage", ""),
    )
    if kind == "route":
        if (
            set(proposal) != {"model"}
            or not isinstance(proposal["model"], str)
            or proposal["model"] not in plan["route_models"]
        ):
            raise ValueError("Route proposals may select only a model from the pinned choices")
    elif (
        set(proposal) != {"stage", "goal"}
        or proposal.get("stage") != plan["stage"]
        or not isinstance(proposal.get("goal"), str)
        or not proposal["goal"].strip()
        or len(proposal["goal"].encode()) > 8000
    ):
        raise ValueError("Workflow proposals may edit only the selected stage goal (up to 8 KB)")
    candidate = proposed_snapshot(snapshot, kind, plan["binding"], plan.get("stage", ""), proposal)
    _compile_factory(
        candidate, root=root, goal="Review improvement proposal", revision=plan["revision"]
    )
    return proposal


def workflow_prompts(snapshot, plan, proposal, tasks, *, root):
    """Use the actual WorkOrder prompt builder, without inventing predecessor evidence."""
    from .compiler import _compile_factory
    from superqode.workorders.runner import _task_prompt

    root = Path(root).resolve()

    candidate = proposed_snapshot(snapshot, "workflow", plan["binding"], plan["stage"], proposal)
    compiled = _compile_factory(
        candidate, root=root, goal="Evaluation case", revision=plan["revision"]
    )
    task = next(t for t in compiled.work_order.tasks if t.task_id == plan["stage"])
    return {
        case["id"]: _task_prompt(
            replace(compiled.work_order, work_order_id="factory-improvement", goal=case["prompt"]),
            task,
        )
        for case in tasks
    }
