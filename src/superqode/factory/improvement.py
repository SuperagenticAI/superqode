"""Pinned Factory improvement, shared evaluation and deliberate draft adoption.

Experiments compare one bounded surface on explicit output tasks. This is neither
full Factory reliability measurement nor application release authorization.
"""

from __future__ import annotations

from copy import deepcopy
import difflib
import fnmatch
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time
from uuid import uuid4

import yaml

from superqode.harness.acceptance import heldout_acceptance
from superqode.harness.eval import load_eval_tasks, run_harness_eval
from superqode.harness.eval_workspace import EvaluationWorkspace, file_manifest, manifest_digest
from superqode.harness.loader import (
    harness_spec_from_dict,
    harness_spec_to_dict,
    validate_harness_data,
)
from superqode.harness.self_improve import audit_harness_candidate
from .compiler import _compile_factory, repository_revision
from .definition import FactoryDefinition, load_factory, project_path, read_mapping, relative_path
from .generation import check_generation_route
from .snapshot import FactorySnapshot, canonical, digest, resolve_factory
from .versioning import source_path, _safe_text
from .skills import bound_harness, parse_skill, check_candidate as check_skill_candidate
from . import experiments
from .metering import BudgetLedger, BudgetHalt

FORMAT = "superqode.factory-improvement/1"
PREFIX = ".superqode/factory-improvements"
MAX_REPORT = 4_000_000


def optimizer_versions(engine):
    from importlib.metadata import PackageNotFoundError, distribution

    names = {
        "gepa": ["gepa"],
        "metaharness": ["superagentic-metaharness"],
        "omni": ["gepa", "superagentic-metaharness"],
    }.get(engine, [])
    values = {}
    for name in names:
        try:
            package = distribution(name)
            value = package.version
            direct = package.read_text("direct_url.json")
            if direct:
                commit = json.loads(direct).get("vcs_info", {}).get("commit_id", "")
                if isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40,64}", commit):
                    value += "+" + commit
            values[name] = value
        except PackageNotFoundError:
            values[name] = None
    return values


def _write(path, text):
    from superqode.desktop_service.studio import _atomic

    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("Immutable improvement artifact changed")
    else:
        _atomic(path, text)


def _read(path, limit=MAX_REPORT):
    if (
        any(part.is_symlink() for part in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > limit
    ):
        raise ValueError("Missing or oversized improvement artifact")
    return path.read_text(encoding="utf-8")


def folder(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"improve_[a-f0-9]{32}", identity):
        raise ValueError("Choose a prepared Factory improvement plan")
    return project_path(Path(root).resolve(), PREFIX + "/" + identity)


def capabilities():
    from .external import techniques

    return {
        "import": True,
        "gepa": importlib.util.find_spec("gepa") is not None,
        "metaharness": importlib.util.find_spec("metaharness") is not None,
        "scope": "harness, bound skill, selected model route or ungated entry-stage instructions",
        "targets": ["harness", "skill", "route", "workflow"],
        "techniques": techniques(),
        "optimizer_engines": [
            {"id": "evaluator-optimizer", "available": True, "metered": True},
            {
                "id": "gepa",
                "available": importlib.util.find_spec("gepa") is not None,
                "metered": True,
            },
            {
                "id": "metaharness",
                "available": importlib.util.find_spec("metaharness") is not None,
                "metered": True,
            },
            {
                "id": "omni",
                "available": all(
                    importlib.util.find_spec(p) is not None for p in ("gepa", "metaharness")
                ),
                "metered": True,
            },
        ],
        "adoption": "explicit draft proposal after a non-regressing comparison meets its pinned quality, cost or latency objective",
    }


def _protected(definition, binding, changes=()):
    policy = definition["improvement"].get("optimization", {})
    if "harnesses" not in policy.get("editable", []):
        raise ValueError("Factory policy does not allow harness improvement")
    paths = ["inference.harnesses." + binding, "harnesses." + binding]
    paths += [base + "." + change for base in paths[:] for change in changes]
    for pattern in policy.get("protected", []):
        for path in paths:
            parents = [".".join(path.split(".")[:i]) for i in range(1, len(path.split(".")) + 1)]
            if any(fnmatch.fnmatchcase(parent, pattern) for parent in parents):
                raise ValueError("Factory policy protects this harness improvement surface")


def _protected_skill(definition, binding, skill, harness):
    policy = definition["improvement"].get("optimization", {})
    if "skills" not in policy.get("editable", []):
        raise ValueError("Factory policy does not allow skill improvement")
    if skill not in definition["inference"]["harnesses"][binding].get("skills", []):
        raise ValueError("Choose a skill explicitly bound to this Factory harness")
    if any(
        key != binding and skill in value.get("skills", [])
        for key, value in definition["inference"]["harnesses"].items()
    ):
        raise ValueError("Use a skill asset dedicated to this binding before improving it")
    paths = [
        "skills." + skill,
        "skills." + skill + ".instructions",
        "data_context.files." + skill,
        "data_context.files." + skill + ".path",
        "inference.harnesses." + binding + ".skills",
        "harnesses." + binding + ".skills",
    ]
    paths += [
        prefix + binding + suffix
        for prefix in ("inference.harnesses.", "harnesses.")
        for suffix in (".agents.system_prompt", ".agents.0.system_prompt")
    ]
    for pattern in policy.get("protected", []):
        if any(
            fnmatch.fnmatchcase(".".join(path.split(".")[:i]), pattern)
            for path in paths
            for i in range(1, len(path.split(".")) + 1)
        ):
            raise ValueError("Factory policy protects this skill or its bound harness")
    for pattern in harness_spec_from_dict(harness).optimization.protected_surfaces:
        if any(
            fnmatch.fnmatchcase(path, pattern)
            for path in ("agents", "agents.system_prompt", "agents.0", "agents.0.system_prompt")
        ):
            raise ValueError("Harness policy protects the instructions supplied by this skill")


def proposal_suffix(plan):
    return ".md" if plan.get("target_kind") == "skill" else ".yaml"


def baseline_proposal(root, plan):
    kind = plan.get("target_kind")
    name = (
        "baseline.skill.md"
        if kind == "skill"
        else "baseline.proposal.yaml"
        if kind in {"route", "workflow"}
        else "baseline.yaml"
    )
    return _read(folder(root, plan["id"]) / name, 250000)


def _suite(path):
    raw = _read(path, 250000)
    data = read_mapping(raw)
    if data.get("variants"):
        raise ValueError("Factory improvement suites cannot add unreviewed harness variants")
    data = load_eval_tasks(path)
    if (
        len(data["tasks"]) > 24
        or not data["split_counts"]["held-in"]
        or not data["split_counts"]["held-out"]
    ):
        raise ValueError("Use at most 24 graded tasks with both held-in and held-out splits")
    for task in data["tasks"]:
        kind = (task.get("evaluator") or {}).get(
            "type", "contains" if task.get("expect_contains") else "non_empty"
        )
        if kind not in {"contains", "decision", "review"}:
            raise ValueError(
                "This improvement adapter requires deterministic contains or decision output graders"
            )
    return raw, data


def _context_path(relative):
    return "factory-pinned-context/" + (
        "internal/" + relative[len(".superqode/") :]
        if relative.startswith(".superqode/")
        else "project/" + relative
    )


def prepare(
    root,
    *,
    binding,
    tasks,
    fixture,
    max_evals=4,
    max_seconds=120,
    reflection_model="",
    target_kind="harness",
    skill="",
    stage="",
    route_models=None,
    optimizer_engine="gepa",
    budget_limits=None,
    absolute_deadline=None,
    objective="quality",
):
    root = Path(root).resolve()
    definition = load_factory(root=root)
    snapshot = resolve_factory(definition)
    revision = repository_revision(root)
    _compile_factory(snapshot, root=root, goal="Review harness improvement", revision=revision)
    if binding not in snapshot.payload["harnesses"]:
        raise ValueError("Choose a bound Factory harness")
    if target_kind not in {"harness", "skill", "route", "workflow"}:
        raise ValueError("Choose a supported Factory improvement target")
    if target_kind == "skill":
        _protected_skill(definition.data, binding, skill, snapshot.payload["harnesses"][binding])
    elif target_kind in {"route", "workflow"}:
        experiments.protect(
            definition.data, snapshot.payload["harnesses"][binding], target_kind, binding, stage
        )
        if target_kind == "route":
            route_models = experiments.route_choices(
                snapshot, binding, route_models, root=root, revision=revision
            )
    else:
        _protected(definition.data, binding)
    suite_path = source_path(root, tasks)
    suite_text, suite = _suite(suite_path)
    if objective not in {"quality", "cost", "latency"}:
        raise ValueError("Choose quality, cost or latency as the improvement objective")
    if objective != "quality" and suite["split_counts"]["held-out"] < 3:
        raise ValueError("Cost and latency comparisons require at least three held-out tasks")
    if (
        target_kind == "workflow"
        and experiments.stage_definition(definition.data, stage)["role"] == "reviewer"
    ):
        if any((task.get("evaluator") or {}).get("type") != "review" for task in suite["tasks"]):
            raise ValueError(
                "Reviewer experiments require labelled typed-review graders for every case"
            )
        names = set(experiments.stage_definition(definition.data, stage).get("outputs", {}))
        if any(set(task["evaluator"].get("output_names", [])) != names for task in suite["tasks"]):
            raise ValueError("Reviewer graders must pin the declared output_names")
        outputs = experiments.stage_definition(definition.data, stage).get("outputs", {})
        maximum = min(
            (output.get("max_bytes", 16000) for output in outputs.values()), default=16000
        )
        if any(task["evaluator"].get("max_bytes", 16000) != maximum for task in suite["tasks"]):
            raise ValueError("Reviewer grader max_bytes must preserve the declared output limit")
    _safe_text(tasks, suite_text)
    if fixture == "@empty":
        empty = project_path(root, ".superqode/factory-improvement-fixtures/empty")
        _write(empty / "README.txt", "Empty disposable fixture for deterministic output tasks.\n")
        fixture = ".superqode/factory-improvement-fixtures/empty"
    fixture_path = project_path(root, fixture)
    if not fixture_path.is_dir():
        raise ValueError("Choose an explicit disposable fixture directory inside the project")
    ceiling = deepcopy(definition.data["governance"]["budget"])
    if budget_limits is not None:
        if not isinstance(budget_limits, dict) or set(budget_limits) - {
            "max_tokens",
            "max_cost_usd",
            "max_tool_calls",
        }:
            raise ValueError("Experiment budget overrides may only narrow metered limits")
        for key, value in budget_limits.items():
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value <= 0
                or (key != "max_cost_usd" and type(value) is not int)
                or value > ceiling.get(key, value)
            ):
                raise ValueError(
                    "Experiment budget limits must be positive and within Factory limits"
                )
        ceiling.update(budget_limits)
    if optimizer_engine not in {"gepa", "evaluator-optimizer", "metaharness", "omni"}:
        raise ValueError("Choose a supported metered optimizer engine")
    if type(max_evals) is not int or not 1 <= max_evals <= 20:
        raise ValueError("Choose between 1 and 20 optimizer metric calls")
    if type(max_seconds) is not int or not 1 <= max_seconds <= min(600, ceiling["max_seconds"]):
        raise ValueError(
            "Improvement wall time must fit the Factory budget and be at most 600 seconds"
        )
    if absolute_deadline is not None and (
        type(absolute_deadline) not in {int, float}
        or not math.isfinite(absolute_deadline)
        or absolute_deadline <= time.time()
    ):
        raise ValueError("Campaign deadline must be a finite future timestamp")
    primary = snapshot.payload["harnesses"][binding]["model_policy"]["primary"]
    from superqode.providers.model_specs import split_provider_model_ref

    route = split_provider_model_ref(primary)
    if route.provider in {"synthetic", "acp"}:
        raise ValueError("Choose a real model route for an improvement contract")
    if reflection_model:
        reflection = split_provider_model_ref(reflection_model)
        if (
            reflection.provider in {"acp", "synthetic"}
            or not reflection.provider
            or not reflection.model
        ):
            raise ValueError("Reflection requires an explicit direct model route")
        check_generation_route(definition.data, reflection.provider, reflection.model)
    identity = "improve_" + uuid4().hex
    directory = folder(root, identity)
    directory.mkdir(parents=True, mode=0o700)
    temporary = project_path(root, f"{PREFIX}/{identity}/temporary")
    temporary.mkdir()
    try:
        with EvaluationWorkspace(
            fixture_path, exclude_paths=(suite_path,), temporary_dir=temporary
        ) as workspace:
            for relative, entry in workspace.manifest.items():
                source_path(root, relative)
                if "link" in entry:
                    raise ValueError("Improvement fixtures cannot contain symbolic links")
            fixture_digest = workspace.digest
            shutil.copytree(workspace.snapshot, directory / "fixture")
        baseline = snapshot.payload["harnesses"][binding]
        _safe_text("baseline.yaml", yaml.safe_dump(baseline))
        if any(agent.model for agent in harness_spec_from_dict(baseline).agents):
            raise ValueError(
                "This improvement adapter requires model selection through the Factory binding"
            )
        # Captured instructions are injected into trial copies; evaluator assets
        # are never automatically included in that instruction tree.
        evaluators = {
            asset["path"]
            for asset in definition.data["data_context"].get("files", {}).values()
            if asset["purpose"] == "evaluator"
        }
        evaluators.add(tasks)
        context = harness_spec_from_dict(baseline).context
        context_paths = set(context.instruction_files)
        context_paths |= {
            p
            for p in snapshot.payload["sources"]
            if any(
                folder and p.startswith(folder.rstrip("/") + "/")
                for folder in (context.skills_dir, context.roles_dir)
            )
        }
        if context_paths & evaluators:
            raise ValueError("Harness context cannot expose protected evaluator files")
        for relative in context_paths:
            if relative not in snapshot.payload["sources"]:
                continue
            source_path(root, relative)
            _safe_text(relative, snapshot.payload["sources"][relative]["text"])
            target = project_path(directory / "fixture", _context_path(relative))
            _write(target, snapshot.payload["sources"][relative]["text"])
        skill_text = ""
        if target_kind == "skill":
            skill_path = relative_path(
                definition.data["data_context"]["files"][skill]["path"]
            ).as_posix()
            if skill_path == tasks:
                raise ValueError("The improvement skill cannot also be its evaluation suite")
            skill_text = snapshot.payload["sources"][skill_path]["text"]
            _safe_text("skill.md", skill_text)
            parse_skill(skill_text)
        plan = {
            "format": FORMAT,
            "target_kind": target_kind,
            "objective": objective,
            "minimum_relative_improvement": 0.05,
            "stage": stage if target_kind == "workflow" else "",
            "route_models": route_models if target_kind == "route" else [],
            "skill": skill if target_kind == "skill" else "",
            "skill_digest": digest(skill_text) if target_kind == "skill" else "",
            "id": identity,
            "repository": str(root),
            "revision": revision,
            "factory_digest": snapshot.digest,
            "binding": binding,
            "tasks": tasks,
            "tasks_digest": digest(suite_text),
            "fixture": fixture,
            "source_fixture_digest": fixture_digest,
            "trial_fixture_digest": manifest_digest(file_manifest(directory / "fixture")),
            "baseline_digest": digest(canonical(baseline)),
            "provider": route.provider,
            "model": route.model,
            "reflection_model": reflection_model,
            "optimizer_engine": optimizer_engine,
            "optimizer_versions": optimizer_versions(optimizer_engine),
            "metering_version": 1,
            "max_evals": max_evals,
            "max_seconds": max_seconds,
            "split_counts": suite["split_counts"],
            "heldout_ids": [t["id"] for t in suite["tasks"] if t["split"] == "held-out"],
            "limits": ceiling,
            "scope": {
                "skill": "selected bound skill",
                "harness": "selected harness",
                "route": "selected binding's primary model",
                "workflow": "selected ungated entry-stage goal; no predecessor execution or workflow-topology evaluation",
            }[target_kind]
            + " only; output grading; copied fixtures are not an OS sandbox",
        }
        if absolute_deadline is not None:
            plan["absolute_deadline"] = min(absolute_deadline, time.time() + max_seconds)
        plan["digest"] = digest(canonical(plan))
        _write(directory / "snapshot.json", canonical(snapshot.to_dict()))
        _write(directory / "tasks.yaml", suite_text)
        _write(directory / "baseline.yaml", yaml.safe_dump(baseline, sort_keys=False))
        if target_kind == "skill":
            _write(directory / "baseline.skill.md", skill_text)
        elif target_kind in {"route", "workflow"}:
            _write(
                directory / "baseline.proposal.yaml",
                yaml.safe_dump(
                    experiments.baseline(snapshot.payload, target_kind, binding, stage),
                    sort_keys=False,
                ),
            )
        _write(directory / "plan.json", canonical(plan))
        BudgetLedger(directory, plan).initialize()
        return plan
    except BaseException:
        shutil.rmtree(directory)
        raise


def load(root, identity, expected="", *, fresh=False):
    root = Path(root).resolve()
    directory = folder(root, identity)
    plan = json.loads(_read(project_path(root, f"{PREFIX}/{identity}/plan.json")))
    token = plan.pop("digest", "")
    if (
        token != digest(canonical(plan))
        or (expected and token != expected)
        or plan.get("repository") != str(root)
        or plan.get("id") != identity
        or plan.get("format") != FORMAT
    ):
        raise ValueError("Improvement plan digest or project mismatch")
    plan["digest"] = token
    if (
        plan.get("objective", "quality") not in {"quality", "cost", "latency"}
        or plan.get("minimum_relative_improvement", 0.05) != 0.05
    ):
        raise ValueError("Unsupported pinned improvement objective")
    snapshot = FactorySnapshot.from_dict(
        json.loads(_read(project_path(root, f"{PREFIX}/{identity}/snapshot.json"), 8_000_000))
    )
    if (
        snapshot.digest != plan["factory_digest"]
        or digest(canonical(snapshot.payload["harnesses"][plan["binding"]]))
        != plan["baseline_digest"]
    ):
        raise ValueError("Improvement baseline snapshot changed")
    if (
        _read(directory / "baseline.yaml")
        != yaml.safe_dump(snapshot.payload["harnesses"][plan["binding"]], sort_keys=False)
        or digest(_read(directory / "tasks.yaml")) != plan["tasks_digest"]
    ):
        raise ValueError("Improvement harness or criteria changed")
    if plan.get("target_kind", "harness") not in {"harness", "skill", "route", "workflow"}:
        raise ValueError("Unknown improvement artifact target")
    if plan.get("target_kind") == "skill":
        _protected_skill(
            snapshot.payload["definition"],
            plan["binding"],
            plan["skill"],
            snapshot.payload["harnesses"][plan["binding"]],
        )
        asset = snapshot.payload["definition"]["data_context"]["files"][plan["skill"]]
        original = snapshot.payload["sources"][relative_path(asset["path"]).as_posix()]["text"]
        if (
            digest(original) != plan.get("skill_digest")
            or baseline_proposal(root, plan) != original
        ):
            raise ValueError("Pinned improvement skill changed")
    if plan.get("target_kind") in {"route", "workflow"}:
        kind = plan["target_kind"]
        original = experiments.baseline(
            snapshot.payload, kind, plan["binding"], plan.get("stage", "")
        )
        if baseline_proposal(root, plan) != yaml.safe_dump(original, sort_keys=False):
            raise ValueError("Pinned improvement proposal changed")
        experiments.protect(
            snapshot.payload["definition"],
            snapshot.payload["harnesses"][plan["binding"]],
            kind,
            plan["binding"],
            plan.get("stage", ""),
        )
    # Check every descendant through project_path before inventorying it.
    fixture_root = project_path(root, f"{PREFIX}/{identity}/fixture")
    for path in fixture_root.rglob("*"):
        project_path(root, path.relative_to(root).as_posix())
    if manifest_digest(file_manifest(fixture_root)) != plan["trial_fixture_digest"]:
        raise ValueError("Pinned improvement fixture changed")
    if fresh:
        if (
            repository_revision(root) != plan["revision"]
            or resolve_factory(load_factory(root=root)).digest != plan["factory_digest"]
        ):
            raise ValueError(
                "Factory source or application baseline changed; prepare a new improvement plan"
            )
        if digest(_read(source_path(root, plan["tasks"]), 250000)) != plan["tasks_digest"]:
            raise ValueError("Improvement suite changed; prepare a new plan")
        with EvaluationWorkspace(
            project_path(root, plan["fixture"]),
            exclude_paths=(root / plan["tasks"],),
            temporary_dir=directory / "temporary",
        ) as current:
            if current.digest != plan["source_fixture_digest"]:
                raise ValueError("Improvement fixture changed; prepare a new plan")
    return plan, snapshot


def candidate_text(root, plan, text):
    from superqode.desktop_service.studio import _credentials

    if not isinstance(text, str) or len(text.encode()) > 250000:
        raise ValueError("Use a candidate HarnessSpec smaller than 250 KB")
    if plan.get("target_kind") in {"route", "workflow"}:
        _safe_text("proposal.yaml", text)
        data = read_mapping(text)
        _credentials(data)
        _, snapshot = load(root, plan["id"], plan["digest"])
        experiments.check_proposal(snapshot, plan, data, root=root)
        return yaml.safe_dump(data, sort_keys=False)
    if plan.get("target_kind") == "skill":
        _, snapshot = load(root, plan["id"], plan["digest"])
        _protected_skill(
            snapshot.payload["definition"],
            plan["binding"],
            plan["skill"],
            snapshot.payload["harnesses"][plan["binding"]],
        )
        text = text.replace("\r\n", "\n").rstrip() + "\n"
        _safe_text("candidate.md", text)
        metadata, _ = parse_skill(text)
        _credentials(metadata)
        check_skill_candidate(baseline_proposal(root, plan), text)
        return text
    _safe_text("candidate.yaml", text)
    data = read_mapping(text)
    data = data.get("harness", data)
    if "inherits" in data or "extends" in data:
        raise ValueError("Improvement candidates must be self-contained resolved HarnessSpecs")
    _credentials(data)
    validate_harness_data(data)
    value = harness_spec_to_dict(harness_spec_from_dict(data))
    _, snapshot = load(root, plan["id"], plan["digest"])
    baseline = snapshot.payload["harnesses"][plan["binding"]]
    allowed = deepcopy(baseline)
    if len(value["agents"]) != 1 or len(allowed["agents"]) != 1:
        raise ValueError("The improvement adapter supports one native agent")
    for field in ("description",):
        if field in value:
            allowed[field] = value[field]
        else:
            allowed.pop(field, None)
    for field in ("system_prompt", "role"):
        if field in value["agents"][0]:
            allowed["agents"][0][field] = value["agents"][0][field]
        else:
            allowed["agents"][0].pop(field, None)
    if value != allowed:
        raise ValueError(
            "Candidate changes protected routes, context, tools, permissions, checks or workflow; only instructions, role and description are editable"
        )
    changes = []
    if baseline.get("description") != value.get("description"):
        changes.append("description")
    for field in ("system_prompt", "role"):
        if baseline["agents"][0].get(field) != value["agents"][0].get(field):
            changes.append("agents." + field)
    _protected(snapshot.payload["definition"], plan["binding"], changes)
    for pattern in harness_spec_from_dict(baseline).optimization.protected_surfaces:
        for change in changes:
            variants = [change, change.replace("agents.", "agents.0.")]
            if any(
                fnmatch.fnmatchcase(".".join(path.split(".")[:i]), pattern)
                for path in variants
                for i in range(1, len(path.split(".")) + 1)
            ):
                raise ValueError("Candidate changes a protected harness instruction surface")
    return yaml.safe_dump(value, sort_keys=False)


def stage(root, identity, text):
    plan, _ = load(root, identity, fresh=True)
    text = candidate_text(root, plan, text)
    token = digest(text)[7:]
    path = project_path(
        Path(root).resolve(), f"{PREFIX}/{identity}/candidates/{token}{proposal_suffix(plan)}"
    )
    _write(path, text)
    return {
        "candidate": token,
        "candidate_digest": digest(text),
        "plan": identity,
        "proposal_only": True,
    }


def get_candidate(root, plan, token):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Choose an imported or generated improvement candidate")
    path = project_path(
        Path(root).resolve(), f"{PREFIX}/{plan['id']}/candidates/{token}{proposal_suffix(plan)}"
    )
    text = _read(path, 250000)
    if digest(text) != "sha256:" + token or candidate_text(root, plan, text) != text:
        raise ValueError("Improvement candidate changed or is not canonical")
    return path, text


def preview(root, identity, token):
    plan, _ = load(root, identity)
    path, text = get_candidate(root, plan, token)
    baseline = baseline_proposal(root, plan)
    patch = "".join(
        difflib.unified_diff(
            baseline.splitlines(True),
            text.splitlines(True),
            fromfile="Baseline " + plan.get("target_kind", "harness"),
            tofile="Candidate " + plan.get("target_kind", "harness"),
        )
    )
    return {
        "plan": plan,
        "candidate": token,
        "candidate_digest": digest(text),
        "diff": patch,
        "compared": (folder(root, identity) / "comparison.claim").exists(),
        "yaml": text,
        "budget": budget_summary(root, plan),
    }


def budget(root, plan):
    if plan.get("metering_version") != 1:
        raise ValueError(
            "Legacy improvement plans have no shared usage ledger; prepare a fresh plan"
        )
    return BudgetLedger(folder(root, plan["id"]), plan)


def budget_summary(root, plan, *, detail=False):
    try:
        ledger = budget(root, plan)
        return ledger.detail() if detail else ledger.summary()
    except (ValueError, OSError) as exc:
        return {
            "evidence_complete": False,
            "issues": [str(exc)],
            "legacy": plan.get("metering_version") != 1,
        }


def _evaluation_spec(root, plan, data, *, skill_text=None, proposal=None):
    root = Path(root).resolve()
    _, snapshot = load(root, plan["id"], plan["digest"])
    value = bound_harness(
        snapshot.payload,
        plan["binding"],
        harness=data,
        skill_overrides={plan["skill"]: skill_text} if skill_text is not None else None,
    )
    kind = plan.get("target_kind")
    if kind in {"route", "workflow"}:
        proposal = proposal or experiments.baseline(
            snapshot.payload, kind, plan["binding"], plan.get("stage", "")
        )
        if kind == "route":
            value["model_policy"]["primary"] = proposal["model"]
        else:
            candidate = experiments.proposed_snapshot(
                snapshot, kind, plan["binding"], plan["stage"], proposal
            )
            compiled = _compile_factory(
                candidate, root=root, goal="Evaluation case", revision=plan["revision"]
            )
            value["execution_policy"] = compiled.harnesses[plan["stage"]]["execution_policy"]
            value.setdefault("metadata", {})["factory_workflow_stage"] = proposal
    spec = harness_spec_from_dict(value)
    ceiling = load(root, plan["id"], plan["digest"])[1].payload["definition"]["governance"][
        "permissions"
    ]
    value["execution_policy"].update(
        {
            key: getattr(spec.execution_policy, key) and ceiling.get(key, False)
            for key in ("allow_read", "allow_write", "allow_shell", "allow_network")
        }
    )
    config = value.setdefault("model_policy", {}).setdefault("config", {})
    previous = config.get("max_iterations", 0)
    config["max_iterations"] = min(
        previous if type(previous) is int and previous > 0 else 20,
        20,
        plan["limits"].get("max_tool_calls", 20),
    )
    value["context"]["instruction_files"] = [
        _context_path(p)
        for p in spec.context.instruction_files
        if (folder(root, plan["id"]) / "fixture" / (_context_path(p))).is_file()
    ]
    value["context"]["skills_dir"] = (
        _context_path(spec.context.skills_dir) if spec.context.skills_dir else ""
    )
    for agent in value["agents"]:
        previous_agent = agent.get("max_iterations")
        agent["max_iterations"] = min(
            previous_agent
            if type(previous_agent) is int and previous_agent > 0
            else config["max_iterations"],
            config["max_iterations"],
        )
    value["context"]["roles_dir"] = (
        _context_path(spec.context.roles_dir) if spec.context.roles_dir else ""
    )
    return value


def _audit(root, plan, candidate):
    directory = folder(root, plan["id"])
    _, snapshot = load(root, plan["id"], plan["digest"])
    _, text = (
        get_candidate(root, plan, candidate.stem)
        if candidate.parent.name == "candidates"
        else (candidate, candidate_text(root, plan, _read(candidate)))
    )
    if plan.get("target_kind") in {"route", "workflow"}:
        experiments.check_proposal(snapshot, plan, read_mapping(text), root=root)
        return {
            "accepted": True,
            "violations": [],
            "changed_surfaces": [
                "inference.harnesses." + plan["binding"] + ".model"
                if plan["target_kind"] == "route"
                else "orchestration.stages." + plan["stage"] + ".goal"
            ],
        }
    if plan.get("target_kind") == "skill":
        check = check_skill_candidate(baseline_proposal(root, plan), text)
        return {
            "accepted": check["ok"],
            "violations": [],
            "changed_surfaces": ["skills." + plan["skill"] + ".instructions"],
            "bounded_edit_check": check,
        }
    with tempfile.TemporaryDirectory(dir=directory / "temporary") as temporary:
        baseline = Path(temporary) / "baseline.yaml"
        proposed = Path(temporary) / "candidate.yaml"
        baseline.write_text(
            yaml.safe_dump(snapshot.payload["harnesses"][plan["binding"]], sort_keys=False),
            encoding="utf-8",
        )
        proposed.write_text(text, encoding="utf-8")
        return audit_harness_candidate(
            base_spec_path=baseline,
            candidate_spec_path=proposed,
            tasks_path=directory / "tasks.yaml",
            editable_surfaces=("agents", "description"),
            protected_surfaces=(
                "execution_policy",
                "checks",
                "model_policy",
                "context",
                "workflow",
                "runtime",
                "optimization",
            ),
            ledger_path=Path(temporary) / "ledger.jsonl",
            allow_ungated=True,
        )


def _effective_specs(root, plan, text):
    _, snapshot = load(root, plan["id"], plan["digest"])
    baseline = snapshot.payload["harnesses"][plan["binding"]]
    kind = plan.get("target_kind", "harness")
    proposed = read_mapping(text) if kind == "harness" else baseline
    return [
        _evaluation_spec(
            root,
            plan,
            data,
            skill_text=text if candidate and kind == "skill" else None,
            proposal=read_mapping(text) if candidate and kind in {"route", "workflow"} else None,
        )
        for candidate, data in ((False, baseline), (True, proposed))
    ]


def _effective_files(root, plan, candidate, directory):
    if candidate.parent.name == "candidates":
        _, text = get_candidate(root, plan, candidate.stem)
    else:
        text = candidate_text(root, plan, _read(candidate))
    paths = [directory / "baseline.yaml", directory / "candidate.yaml"]
    for path, data in zip(paths, _effective_specs(root, plan, text)):
        _write(path, yaml.safe_dump(data, sort_keys=False))
    return paths


def _spec_bindings(root, plan, candidate_text_value):
    return {
        str(folder(root, plan["id"]) / "comparison" / (name + ".yaml")): digest(
            canonical(harness_spec_to_dict(harness_spec_from_dict(data)))
        )
        for name, data in zip(
            ("baseline", "candidate"), _effective_specs(root, plan, candidate_text_value)
        )
    }


def _evaluation_context(root, plan, text, paths, tasks_path, split):
    kind = plan.get("target_kind")
    if kind not in {"route", "workflow"}:
        return {}
    _, snapshot = load(root, plan["id"], plan["digest"])
    baseline = experiments.baseline(snapshot.payload, kind, plan["binding"], plan.get("stage", ""))
    candidate = read_mapping(text)
    # Search supplies candidate only; comparisons supply both frozen variants.
    proposals = [baseline, candidate] if len(paths) == 2 else [candidate]
    if kind == "route":
        return {
            "model_routes": {
                str(path): proposal["model"] for path, proposal in zip(paths, proposals)
            }
        }
    tasks = [t for t in load_eval_tasks(tasks_path)["tasks"] if t["split"] == split]
    return {
        "readonly_workspace": experiments.stage_definition(
            snapshot.payload["definition"], plan["stage"]
        )["role"]
        != "implementer",
        "task_prompts": {
            str(path): experiments.workflow_prompts(snapshot, plan, proposal, tasks, root=root)
            for path, proposal in zip(paths, proposals)
        },
    }


def _context_evidence(context):
    result = {}
    if context.get("readonly_workspace"):
        result["readonly_workspace"] = True
    if "model_routes" in context:
        result["inference_routes"] = context["model_routes"]
    if "task_prompts" in context:
        result["prompt_digests"] = {
            key: {identity: digest(value) for identity, value in values.items()}
            for key, values in context["task_prompts"].items()
        }
    return result


def _expected_context(root, plan, text):
    directory = folder(root, plan["id"])
    paths = [directory / "comparison" / name for name in ("baseline.yaml", "candidate.yaml")]
    return _context_evidence(
        _evaluation_context(root, plan, text, paths, directory / "tasks.yaml", "held-out")
    )


def _gate(plan, report, expected_specs, expected_context=None):
    gate = heldout_acceptance(report)
    expected = set(plan["heldout_ids"])
    for key, value in (expected_context or {}).items():
        if report.get(key) != value:
            gate["issues"].append("Comparison is missing pinned execution evidence: " + key)
    if report.get("spec_digests") != expected_specs or [
        v.get("spec") for v in report.get("variants", [])
    ] != list(expected_specs):
        gate["issues"].append("Comparison harnesses do not match the pinned baseline and candidate")
    if report.get("tasks_hash") != plan["tasks_digest"] or len(report.get("variants", [])) != 2:
        gate["issues"].append(
            "Comparison is not bound to the pinned suite and exactly two variants"
        )
    for variant in report.get("variants", []):
        if (expected_context or {}).get("readonly_workspace") and any(
            row.get("workspace_integrity")
            != {
                "before": plan["trial_fixture_digest"],
                "after": plan["trial_fixture_digest"],
                "unchanged": True,
            }
            for row in variant.get("tasks", [])
        ):
            gate["issues"].append("Evidence-only stage has missing or changed fixture evidence")
        if {row.get("id") for row in variant.get("tasks", [])} != expected:
            gate["issues"].append(
                "Comparison does not cover the exact pinned held-out task identities"
            )
    objective = plan.get("objective", "quality")
    if objective == "quality" and gate["candidate_score"] <= gate["baseline_score"]:
        gate["issues"].append("Candidate has no strictly higher held-out pass rate")
    elif objective in {"cost", "latency"}:
        if len(expected) < 3 or gate["candidate_score"] <= 0:
            gate["issues"].append(
                "Efficiency comparisons need three held-out tasks and successful grading"
            )
        field = "cost_usd" if objective == "cost" else "duration_seconds"
        values = [
            (v.get("usage", {}) if objective == "cost" else v).get(field)
            for v in report.get("variants", [])
        ]
        valid = len(values) == 2 and all(
            type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in values
        )
        threshold = 0.05
        if not valid or values[0] <= 0:
            gate["issues"].append(
                "Efficiency objective requires known positive baseline and complete " + field
            )
        elif values[1] > values[0] * (1 - threshold):
            gate["issues"].append(
                "Candidate must improve " + field + " by at least 5% without quality regressions"
            )
        gate["objective_evidence"] = {
            "objective": objective,
            "metric": field,
            "values": values if valid else [None, None],
            "minimum_relative_improvement": threshold,
            "statistical_significance_established": False,
        }
    elif objective != "quality":
        gate["issues"].append("Unsupported improvement objective")
    if report.get("workspace", {}).get("snapshot_sha256") != plan["trial_fixture_digest"]:
        gate["issues"].append("Comparison fixture does not match the pinned inputs")
    for field, maximum in (
        ("cost_usd", plan["limits"].get("max_cost_usd")),
        ("tokens", plan["limits"].get("max_tokens")),
        ("tool_calls", plan["limits"].get("max_tool_calls")),
    ):
        if maximum is None:
            continue
        usages = [v.get("usage", {}) for v in report.get("variants", [])]
        values = [
            (u.get("tokens_in") + u.get("tokens_out"))
            if field == "tokens"
            and all(type(u.get(k)) in (int, float) for k in ("tokens_in", "tokens_out"))
            else u.get(field)
            for u in usages
        ]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            gate["issues"].append("Required usage evidence is missing: " + field)
        elif sum(values) > maximum:
            gate["issues"].append("Factory experiment usage exceeds its " + field + " budget")
    gate["accepted"] = not gate["issues"]
    return gate


async def compare(root, identity, token, expected=""):
    from .maintenance import execution

    plan, _ = load(root, identity, expected, fresh=True)
    with execution(root), budget(root, plan).action():
        return await _compare(root, identity, token, expected)


async def _compare(root, identity, token, expected=""):
    started = time.monotonic()
    plan, _ = load(root, identity, expected, fresh=True)
    candidate, candidate_value = get_candidate(root, plan, token)
    expected_specs = _spec_bindings(root, plan, candidate_value)
    expected_context = _expected_context(root, plan, candidate_value)
    audit = _audit(root, plan, candidate)
    if not audit["accepted"]:
        raise ValueError("Harness audit rejected the improvement candidate")
    directory = folder(root, identity)
    ledger = budget(root, plan)
    claim = project_path(Path(root).resolve(), f"{PREFIX}/{identity}/comparison.claim")
    if claim.exists():
        raise FileExistsError("This plan already consumed its final comparison attempt")
    ledger.check_admission()
    with claim.open("x") as handle:
        handle.write(token)
    result_dir = directory / "comparison"
    result_dir.mkdir()
    specs = _effective_files(root, plan, candidate, result_dir)
    report = {}
    failure = ""
    try:
        with EvaluationWorkspace(
            directory / "fixture", temporary_dir=directory / "temporary", git_discovery=False
        ) as workspace:
            report = await run_harness_eval(
                spec_paths=specs,
                tasks_path=directory / "tasks.yaml",
                provider=plan["provider"],
                model=plan["model"],
                working_dir=directory / "fixture",
                live=True,
                eval_split="held-out",
                workspace_snapshot=workspace,
                evaluation_observer=ledger.observer("held-out"),
                **_evaluation_context(
                    root, plan, candidate_value, specs, directory / "tasks.yaml", "held-out"
                ),
            )
        operations = [o for o in ledger.detail()["operations"] if o["phase"] == "held-out"]
        identities = [
            row.get("factory_usage_operation")
            for v in report.get("variants", [])
            for row in v.get("tasks", [])
        ]
        if not identities or None in identities or set(identities) != {o["id"] for o in operations}:
            ledger.mark_unobserved("held-out")
    except BudgetHalt as exc:
        failure = str(exc)
    finally:
        usage_summary = ledger.finalize()
    load(root, identity, plan["digest"], fresh=True)
    if time.monotonic() - started > plan["max_seconds"]:
        raise ValueError("Improvement comparison exhausted its wall-time budget")
    gate = _gate(plan, report, expected_specs, expected_context)
    gate["issues"].extend(ledger.report_issues(report))
    if failure:
        gate["issues"].append(failure)
    gate["accepted"] = not gate["issues"]
    receipt = {
        "format": FORMAT,
        "plan_digest": plan["digest"],
        "candidate": token,
        "candidate_digest": "sha256:" + token,
        "tasks_digest": plan["tasks_digest"],
        "baseline_digest": plan["baseline_digest"],
        "audit": audit,
        "budget_digest": usage_summary["digest"],
        "budget": usage_summary,
        "report": report,
        "gate": gate,
        "scope": plan["scope"],
        "release_authorization": False,
    }
    text = canonical(receipt)
    if len(text.encode()) > MAX_REPORT:
        raise ValueError("Improvement evidence exceeds its report limit")
    _write(result_dir / "receipt.json", text)
    return {
        "plan": identity,
        "candidate": token,
        "receipt_digest": digest(text),
        "eligible": gate["accepted"],
        "budget": usage_summary,
        "baseline_score": gate["baseline_score"],
        "candidate_score": gate["candidate_score"],
        "issues": gate["issues"],
        "scope": plan["scope"],
    }


def evidence(root, identity, token, expected):
    plan, _ = load(root, identity, fresh=True)
    candidate, text = get_candidate(root, plan, token)
    raw = _read(project_path(Path(root).resolve(), f"{PREFIX}/{identity}/comparison/receipt.json"))
    if digest(raw) != expected:
        raise ValueError("Improvement evidence changed after its completed comparison job")
    receipt = json.loads(raw)
    ledger = budget(root, plan)
    if receipt.get("budget_digest") != ledger.summary()["digest"] or ledger.report_issues(
        receipt.get("report", {})
    ):
        raise ValueError("Shared improvement usage evidence changed or is incomplete")
    if (
        receipt["plan_digest"] != plan["digest"]
        or receipt["candidate"] != token
        or receipt["tasks_digest"] != plan["tasks_digest"]
        or not _audit(root, plan, candidate)["accepted"]
        or not _gate(
            plan,
            receipt["report"],
            _spec_bindings(root, plan, text),
            _expected_context(root, plan, text),
        )["accepted"]
    ):
        raise ValueError("Improvement evidence does not authorize this draft proposal")
    return plan, text, receipt


def adoption(root, identity, token, expected):
    root = Path(root).resolve()
    plan, text, receipt = evidence(root, identity, token, expected)
    definition = load_factory(root=root)
    data = deepcopy(definition.data)
    kind = plan.get("target_kind", "harness")
    if kind in {"route", "workflow"}:
        proposal = read_mapping(text)
        if kind == "route":
            data["inference"]["harnesses"][plan["binding"]]["model"] = proposal["model"]
        else:
            experiments.stage_definition(data, plan["stage"])["goal"] = proposal["goal"]
        path = ""
    elif kind == "skill":
        path = f".superqode/skills/improved-{token}/SKILL.md"
        data["data_context"]["files"][plan["skill"]]["path"] = path
    else:
        path = f".superqode/components/improved-{token}.yaml"
        previous = data["inference"]["harnesses"][plan["binding"]]
        data["inference"]["harnesses"][plan["binding"]] = {
            "path": path,
            **{key: previous[key] for key in ("model", "skills") if key in previous},
        }
    proposed = yaml.safe_dump(data, sort_keys=False)
    snapshot = resolve_factory(
        FactoryDefinition(root, definition.path, data),
        source_text=proposed,
        source_overlays={path: text} if path else None,
    )
    _compile_factory(
        snapshot,
        root=root,
        goal="Review improved " + plan.get("target_kind", "harness"),
        revision=plan["revision"],
    )
    if path:
        _write(source_path(root, path), text)
    return {
        "yaml": proposed,
        "component": path,
        "snapshot_digest": snapshot.digest,
        "proposal_only": True,
        "notice": "Loaded an improved "
        + plan.get("target_kind", "harness")
        + " into a draft. Review, save, commit sources and prepare a new trial explicitly.",
    }


def optimize(root, identity, expected):
    """Search with a pinned engine and shared, durable request accounting."""
    from .search import run_search
    from .maintenance import execution

    plan, _ = load(root, identity, expected, fresh=True)
    with execution(root), budget(root, plan).action():
        return run_search(root, identity, expected)
