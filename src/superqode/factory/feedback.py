"""Evidence-bound failure triage and operator-authored experiment proposals.

No inference calls, automatic retries, acceptance edits or activation occur here.
"""

from __future__ import annotations

from copy import deepcopy
import fnmatch
import json
from pathlib import Path
import re
import time

import yaml

from . import trials, experiments
from .compiler import _compile_factory
from .definition import project_path, read_mapping
from .snapshot import FactorySnapshot, canonical, digest
from .versioning import source_path, _safe_text
from superqode.harness.self_improve import build_failure_record
from superqode.desktop_service.ownership import Lease
from superqode.desktop_service.redaction import redact

PREFIX = ".superqode/factory-feedback"
CATEGORIES = (
    "application_defect",
    "model_protocol",
    "provider_infrastructure",
    "runtime_infrastructure",
    "evaluation_fault",
    "evidence_or_recovery",
    "policy_budget",
    "unknown",
)


def _directory(root):
    return project_path(Path(root).resolve(), PREFIX)


def _load(root):
    path = _directory(root) / "inbox.json"
    if not path.exists():
        return {"format": "superqode.factory-feedback/1", "issues": {}}
    value = json.loads(trials._read(path))
    if value.get("format") != "superqode.factory-feedback/1" or not isinstance(
        value.get("issues"), dict
    ):
        raise ValueError("Invalid Factory feedback catalog")
    return value


def _save(root, value):
    if len(canonical(value).encode()) > 8_000_000:
        raise ValueError(
            "Feedback catalog reached its bound; archive it before scanning more evidence"
        )
    trials._save(_directory(root) / "inbox.json", value)


def _text(value, root, secrets=()):
    text = redact(str(value), [v for v in secrets if isinstance(v, str) and v])
    text = text.replace(str(Path(root).resolve()), "<project>")
    text = re.sub(r"(?i)(bearer\s+|api[_-]?key\s*[=:]\s*)[^\s\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
    return text[:2000]


def _classify(error):
    value = error.lower()
    for category, words in (
        (
            "evidence_or_recovery",
            ("uncertain", "reconcil", "fingerprint", "snapshot", "digest", "tamper", "unrecorded"),
        ),
        ("policy_budget", ("budget", "token limit", "wall-time", "usage evidence")),
        (
            "evaluation_fault",
            ("evaluator infrastructure", "probe infrastructure", "verification infrastructure"),
        ),
        (
            "model_protocol",
            (
                "xml syntax",
                "malformed",
                "tool_call",
                "tool call",
                "closed by",
                "schema error",
                "superqode_review",
                "superqode_output",
                "stage output does not match",
            ),
        ),
        (
            "provider_infrastructure",
            ("connection", "timeout", "timed out", "rate limit", "authentication", "api key"),
        ),
        (
            "runtime_infrastructure",
            ("permission denied", "sandbox", "no such file", "modulenotfound", "infrastructure"),
        ),
    ):
        if any(word in value for word in words):
            return category
    return "unknown"


def _review_digest(issue):
    return digest(canonical(issue["reviews"]))


def _source(root, observation):
    plan = trials.load(root, observation["suite"], observation["plan_digest"])
    entry = next((e for e in plan["entries"] if e["id"] == observation["entry"]), None)
    if entry is None:
        raise ValueError("Failure entry is not in the pinned suite")
    project, store, order, compiled = trials._order(root, entry)
    if entry["snapshot_digest"] != observation["snapshot_digest"]:
        raise ValueError("Failure Factory snapshot changed")
    if observation["kind"] == "task_failure":
        event = next(
            (
                e
                for e in store.events(
                    entry["run"], after_sequence=max(0, observation["sequence"] - 1), limit=1
                )
                if e.event_id == observation["event"]
            ),
            None,
        )
        if (
            event is None
            or event.task_id != observation["stage"]
            or event.sequence != observation["sequence"]
            or event.type not in {"task.failed", "task.recovery_blocked", "task.blocked"}
            or digest(canonical(event.to_dict())) != observation["evidence_digest"]
        ):
            raise ValueError("Recorded failure event changed")
    elif observation["kind"] == "acceptance_failure":
        row = next(
            r
            for r in trials.scorecard(root, plan["id"], plan["digest"])["entries"]
            if r["id"] == entry["id"]
        )
        if row.get("verification", {}).get("digest") != observation["evidence_digest"]:
            raise ValueError("Recorded acceptance evidence changed or was replaced")
    else:
        raise ValueError(
            "Integrity and infrastructure findings require source repair before an experiment"
        )
    return plan, entry, order, compiled


def _insert(catalog, observation, message, category, route, role, source):
    for existing in catalog["issues"].values():
        for recorded in existing["observations"].values():
            if recorded["source_ref"] != observation["source_ref"]:
                continue
            if recorded["evidence_digest"] != observation["evidence_digest"]:
                raise ValueError(
                    "Previously recorded failure source changed; inspect its integrity before rescanning"
                )
            return 0
    message = re.sub(r"\b(?:work|artifact|suite|verification|release)_[a-f0-9]+\b", "<id>", message)
    normalized = re.sub(r"\b(?:[a-f0-9]{24,}|\d+(?:\.\d+)?)\b", "#", message.lower())
    field = (
        "model_policy.primary"
        if category == "model_protocol"
        else "checks"
        if category == "application_defect"
        else "runtime"
    )
    record = build_failure_record(
        source_type="factory_trial",
        source=source,
        source_ref=observation["source_ref"],
        harness=route,
        spec=observation["snapshot_digest"],
        task_id=observation["stage"],
        check_name=observation.get("check", "stage"),
        status="failed",
        symptom=normalized,
        reason=message,
        digest={
            "failure_category": category,
            "dimension": {"id": "D5", "label": "Factory trial evidence", "field": field},
            "evidence": [observation["source_ref"]],
        },
    )
    identity = (
        "failure_"
        + digest(
            canonical(
                {
                    "fingerprint": record["fingerprint"],
                    "symptom": normalized,
                    "category": category,
                    "route": route,
                    "role": role,
                }
            )
        )[7:]
    )
    observation_id = digest(canonical(observation))[7:]
    if any(observation_id in issue["observations"] for issue in catalog["issues"].values()):
        return 0
    issue = catalog["issues"].setdefault(
        identity,
        {
            "id": identity,
            "suggested_category": category,
            "record": record,
            "observations": {},
            "reviews": [],
            "proposals": [],
            "created": time.time(),
        },
    )
    added = observation_id not in issue["observations"]
    if sum(len(i["observations"]) for i in catalog["issues"].values()) >= 2000 and added:
        raise ValueError("Feedback observation limit reached; archive before scanning more suites")
    issue["observations"].setdefault(
        observation_id, {"id": observation_id, **observation, "message": message}
    )
    return int(added)


def scan(root, suite, expected="", secrets=()):
    root = Path(root).resolve()
    plan = trials.load(root, suite, expected)
    lease = Lease(_directory(root) / "writer.lock")
    try:
        catalog = _load(root)
        added = 0
        scan_issues = []
        board = trials.scorecard(root, suite, plan["digest"])
        for entry in plan["entries"]:
            row = next(r for r in board["entries"] if r["id"] == entry["id"])
            try:
                project, store, order, compiled = trials._order(root, entry)
            except (ValueError, OSError, KeyError) as exc:
                # Untrusted inputs are never converted into an application regression.
                scan_issues.append({"entry": entry["id"], "issue": _text(exc, root, secrets)})
                continue
            events = store.events(entry["run"], limit=10000)
            if len(events) == 10000:
                raise ValueError(
                    "Trial event history exceeds this scan's bound; select a smaller archived run"
                )
            originals = {
                s["id"]: s
                for s in compiled.snapshot.payload["definition"]["orchestration"]["stages"]
            }
            stages = {
                task.task_id: originals[task.metadata["factory_stage"]] for task in order.tasks
            }
            common = {
                "suite": suite,
                "plan_digest": plan["digest"],
                "entry": entry["id"],
                "run": entry["run"],
                "snapshot_digest": entry["snapshot_digest"],
            }
            for event in events:
                if event.type not in {"task.failed", "task.recovery_blocked", "task.blocked"}:
                    continue
                stage = stages.get(event.task_id)
                if stage is None:
                    continue
                message = _text(
                    event.data.get("error") or event.data.get("reason") or event.type, root, secrets
                )
                category = _classify(message)
                if event.type == "task.recovery_blocked":
                    category = "evidence_or_recovery"
                attempt = event.data.get("attempt")
                reused = any(
                    e.type == "invocation.reused"
                    and e.sequence < event.sequence
                    and e.task_id == event.task_id
                    and e.data.get("attempt") == attempt
                    for e in events
                )
                observation = {
                    **common,
                    "kind": "task_failure",
                    "stage": event.task_id,
                    "event": event.event_id,
                    "sequence": event.sequence,
                    "attempt": attempt,
                    "evidence_digest": digest(canonical(event.to_dict())),
                    "reused_outcome": reused,
                    "source_ref": f"{store.path}#{entry['run']}/events/{event.sequence}",
                }
                route = compiled.snapshot.payload["harnesses"][stage["harness"]]["model_policy"][
                    "primary"
                ]
                added += _insert(
                    catalog, observation, message, category, route, stage["role"], store.path
                )
            if row["status"] == "failed" and row.get("verification"):
                artifact = next(
                    a for a in order.artifacts if a.artifact_id == row["verification"]["artifact"]
                )
                report = json.loads(artifact.content)
                implementation = next(
                    (
                        task.task_id
                        for task in reversed(order.tasks)
                        if task.role.value == "implementer" and task.status.value == "succeeded"
                    ),
                    order.tasks[0].task_id,
                )
                for result in report["results"]:
                    if result["status"] != "failed":
                        continue
                    observation = {
                        **common,
                        "kind": "acceptance_failure",
                        "stage": implementation,
                        "check": result["check"] + "/" + result["id"],
                        "evidence_digest": artifact.digest,
                        "source_ref": f"{store.path}#{entry['run']}/{artifact.artifact_id}/{result['id']}",
                        "reused_outcome": False,
                    }
                    added += _insert(
                        catalog,
                        observation,
                        "Protected acceptance mismatch: " + observation["check"],
                        "application_defect",
                        "protected acceptance",
                        "verifier",
                        store.path,
                    )
        _save(root, catalog)
    finally:
        lease.close()
    return {
        **list_issues(root),
        "added_observations": added,
        "scan_issues": scan_issues,
        "model_calls": 0,
    }


def list_issues(root):
    catalog = _load(root)
    return {
        "issues": [
            {
                "id": i["id"],
                "suggested_category": i["suggested_category"],
                "symptom": i["record"]["reason"],
                "observations": len(i["observations"]),
                "reused_outcomes": sum(
                    o.get("reused_outcome", False) for o in i["observations"].values()
                ),
                "review": i["reviews"][-1] if i["reviews"] else {},
                "review_digest": _review_digest(i),
                "proposals": len(i["proposals"]),
            }
            for i in catalog["issues"].values()
        ]
    }


def detail(root, identity):
    issue = _load(root)["issues"].get(identity)
    if issue is None:
        raise ValueError("Choose a recorded Factory failure")
    observations = []
    for observation in issue["observations"].values():
        try:
            _, _, order, compiled = _source(root, observation)
            task = next(t for t in order.tasks if t.task_id == observation["stage"])
            current = task.status.value
            stage = next(
                s
                for s in compiled.snapshot.payload["definition"]["orchestration"]["stages"]
                if s["id"] == task.metadata["factory_stage"]
            )
            observations.append(
                {
                    **observation,
                    "source_valid": True,
                    "current_stage_status": current,
                    "stage_goal": stage["goal"],
                    "model": compiled.snapshot.payload["harnesses"][stage["harness"]][
                        "model_policy"
                    ]["primary"],
                }
            )
        except (ValueError, OSError, KeyError) as exc:
            observations.append({**observation, "source_valid": False, "source_issue": str(exc)})
    return {
        **issue,
        "observations": observations,
        "review_digest": _review_digest(issue),
        "model_calls": 0,
        "promotion_authority": False,
    }


def review(root, identity, expected, category, status, notes):
    if (
        category not in CATEGORIES
        or status not in {"reviewed", "dismissed"}
        or not isinstance(notes, str)
        or not notes.strip()
        or len(notes.encode()) > 4000
    ):
        raise ValueError("Choose a classification and record a review note (up to 4 KB)")
    _safe_text("review.md", notes)
    lease = Lease(_directory(root) / "writer.lock")
    try:
        catalog = _load(root)
        issue = catalog["issues"].get(identity)
        if issue is None or _review_digest(issue) != expected:
            raise ValueError("Failure review changed; reload before saving")
        issue["reviews"].append(
            {
                "category": category,
                "status": status,
                "notes": notes,
                "at": time.time(),
                "actor": "feedback-operator",
            }
        )
        _save(root, catalog)
    finally:
        lease.close()
    return detail(root, identity)


def propose(root, identity, observation_id, expected, kind, value):
    root = Path(root).resolve()
    lease = Lease(_directory(root) / "writer.lock")
    try:
        catalog = _load(root)
        issue = catalog["issues"].get(identity)
        if issue is None or _review_digest(issue) != expected:
            raise ValueError("Review changed; reload before proposing an experiment")
        if (
            not issue["reviews"]
            or issue["reviews"][-1]["status"] != "reviewed"
            or issue["reviews"][-1]["category"] not in {"application_defect", "model_protocol"}
        ):
            raise ValueError(
                "Review the failure first; infrastructure, evaluator, budget and unknown findings need source repair rather than agent tuning"
            )
        observation = issue["observations"].get(observation_id)
        if observation is None:
            raise ValueError("Choose a failure observation")
        plan, entry, order, compiled = _source(root, observation)
        payload = compiled.snapshot.payload
        definition = payload["definition"]
        origin = next(
            t.metadata["factory_stage"] for t in order.tasks if t.task_id == observation["stage"]
        )
        stage = next(s for s in definition["orchestration"]["stages"] if s["id"] == origin)
        binding = stage["harness"]
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > 8000:
            raise ValueError("Provide a bounded, nonempty experiment change")
        _safe_text("proposal.md", value)
        if kind == "stage_goal":
            if "workflow" not in definition["improvement"].get("optimization", {}).get(
                "editable", []
            ):
                raise ValueError("Factory policy does not allow workflow instruction improvement")
            index = definition["orchestration"]["stages"].index(stage)
            paths = [
                "workflow",
                f"workflow.{stage['id']}.goal",
                f"orchestration.stages.{stage['id']}.goal",
                f"orchestration.stages.{index}.goal",
            ]
            for pattern in definition["improvement"].get("optimization", {}).get("protected", []):
                if any(
                    fnmatch.fnmatchcase(".".join(p.split(".")[:i]), pattern)
                    for p in paths
                    for i in range(1, len(p.split(".")) + 1)
                ):
                    raise ValueError("Factory policy protects this stage goal")
            if value == stage["goal"]:
                raise ValueError("Propose a different stage goal")
            stage["goal"] = value
        elif kind == "model_route":
            from superqode.providers.model_specs import split_provider_model_ref

            route = split_provider_model_ref(value)
            if "/" not in value or route.provider in {"synthetic", "acp"} or len(value) > 256:
                raise ValueError("Choose an explicit direct provider/model route")
            experiments.protect(definition, payload["harnesses"][binding], "route", binding)
            if value == payload["harnesses"][binding]["model_policy"]["primary"]:
                raise ValueError("Propose a different model route")
            definition["inference"]["harnesses"][binding]["model"] = value
            payload["harnesses"][binding]["model_policy"]["primary"] = value
        else:
            raise ValueError("Choose a stage-goal or model-route experiment")
        text = yaml.safe_dump(definition, sort_keys=False)
        payload["sources"][".superqode/factory.yaml"] = {"text": text, "digest": digest(text)}
        candidate = FactorySnapshot.from_dict({"digest": digest(canonical(payload)), **payload})
        trials._paired(compiled.snapshot, candidate, root, entry["revision"])
        _compile_factory(candidate, root=root, goal=entry["goal"], revision=entry["revision"])
        token = digest(
            canonical(
                {
                    "issue": identity,
                    "observation": observation_id,
                    "review": expected,
                    "kind": kind,
                    "candidate": candidate.digest,
                }
            )
        )[7:]
        prefix = f".superqode/trials/proposals/{token}"
        suite = {
            "format": "superqode.factory-trial-suite/1",
            "name": "failure-experiment",
            "baseline": prefix + "/baseline.json",
            "candidate": prefix + "/candidate.json",
            "budget": deepcopy(plan["suite"]["budget"]),
            "cases": [{"id": entry["case"], "goal": entry["goal"]}],
        }
        suite_text = yaml.safe_dump(suite, sort_keys=False)
        trials.parse_suite(suite_text)
        proposal = {
            "id": token,
            "issue": identity,
            "observation": observation_id,
            "review_digest": expected,
            "kind": kind,
            "suite_path": prefix + "/suite.yaml",
            "suite_yaml": suite_text,
            "baseline_digest": compiled.snapshot.digest,
            "candidate_digest": candidate.digest,
            "fixture_digest": plan["fixture_digest"],
            "model_calls": 0,
            "promotion_authority": False,
            "status": "unmeasured",
            "evaluations": [],
            "requires": "Prepare a new suite, explicitly execute it and assess its evidence; this proposal has no adoption or release authority",
        }
        artifacts = {
            prefix + "/baseline.json": canonical(compiled.snapshot.to_dict()),
            prefix + "/candidate.json": canonical(candidate.to_dict()),
            prefix + "/suite.yaml": suite_text,
        }
        proposal["artifacts"] = {path: digest(content) for path, content in artifacts.items()}
        if not any(p["id"] == token for p in issue["proposals"]) and len(issue["proposals"]) >= 3:
            raise ValueError(
                "This failure reached its three-proposal limit; review the recorded experiments before starting another cycle"
            )
        from superqode.desktop_service.studio import _atomic

        for path, content in artifacts.items():
            target = source_path(root, path)
            if target.exists() and trials._read(target) != content:
                raise ValueError("Immutable experiment proposal changed")
        for path, content in artifacts.items():
            target = source_path(root, path)
            if not target.exists():
                _atomic(target, content)
        if not any(p["id"] == token for p in issue["proposals"]):
            issue["proposals"].append(proposal)
        _save(root, catalog)
        return get_proposal(root, identity, token)
    finally:
        lease.close()


def get_proposal(root, identity, token, *, for_execution=False):
    issue = _load(root)["issues"].get(identity)
    if issue is None:
        raise ValueError("Choose a recorded failure")
    proposal = next((p for p in issue["proposals"] if p["id"] == token), None)
    if proposal is None:
        raise ValueError("Choose a proposal for this failure")
    for path, expected in proposal["artifacts"].items():
        if digest(trials._read(source_path(Path(root).resolve(), path))) != expected:
            raise ValueError("Pinned experiment proposal source changed")
    _source(root, issue["observations"][proposal["observation"]])
    runnable = bool(
        issue["reviews"]
        and issue["reviews"][-1]["status"] == "reviewed"
        and issue["reviews"][-1]["category"] in {"application_defect", "model_protocol"}
        and _review_digest(issue) == proposal["review_digest"]
    )
    if for_execution and not runnable:
        raise ValueError(
            "The review changed or was dismissed; review a new proposal before execution"
        )
    evaluations = []
    for link in proposal["evaluations"]:
        try:
            board = trials.scorecard(root, link["suite"], link["digest"])
            evaluations.append(
                {
                    **link,
                    "verdict": board["verdict"],
                    "complete": board["complete"],
                    "summary": board["summary"],
                }
            )
        except (ValueError, OSError, KeyError) as exc:
            evaluations.append({**link, "verdict": "hold", "complete": False, "issue": str(exc)})
    return {
        **proposal,
        "runnable": runnable,
        "evaluations": evaluations,
        "status": (
            "measured"
            if any(e.get("complete") for e in evaluations)
            else "held"
            if any(e.get("verdict") == "hold" for e in evaluations)
            else "awaiting_measurement"
            if evaluations
            else "unmeasured"
        ),
        "suite_file_digest": proposal["artifacts"][proposal["suite_path"]][7:],
        "model_calls": 0,
        "promotion_authority": False,
    }


def attach_evaluation(root, identity, token, suite, expected=""):
    root = Path(root).resolve()
    lease = Lease(_directory(root) / "writer.lock")
    try:
        proposal = get_proposal(root, identity, token)
        plan = trials.load(root, suite, expected)
        if (
            plan["suite"] != read_mapping(proposal["suite_yaml"])
            or plan["fixture_digest"] != proposal["fixture_digest"]
        ):
            raise ValueError(
                "Evaluation must use the exact proposed suite and original application seed"
            )
        if any(
            e["original_snapshot_digest"] != proposal[e["variant"] + "_digest"]
            for e in plan["entries"]
        ):
            raise ValueError("Evaluation Factory revisions do not match this proposal")
        catalog = _load(root)
        stored = next(p for p in catalog["issues"][identity]["proposals"] if p["id"] == token)
        if not any(e["suite"] == suite for e in stored["evaluations"]):
            if len(stored["evaluations"]) >= 3:
                raise ValueError(
                    "Proposal reached its three-evaluation limit; review existing results"
                )
            stored["evaluations"].append(
                {"suite": suite, "digest": plan["digest"], "at": time.time()}
            )
        _save(root, catalog)
    finally:
        lease.close()
    return get_proposal(root, identity, token)
