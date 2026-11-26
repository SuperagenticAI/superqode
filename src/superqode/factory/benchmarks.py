"""Reviewed historical workloads over the existing paired Factory trial engine."""

import json
import os
from pathlib import Path
import re

import yaml

from . import trials
from .definition import project_path
from .maintenance import execution
from .operations import ownership, write
from .runtime import factory_store, _pinned_plan
from .snapshot import canonical, digest
from .versioning import _safe_text


def _safe_task(text):
    """Reject common credential formats before task text crosses dataset interfaces."""
    _safe_text("historical-task.txt", text)
    patterns = (
        r"\bsk-[A-Za-z0-9_-]{12,}",
        r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}",
        r"\bAIza[A-Za-z0-9_-]{30,}",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{12,}",
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}",
        r"""(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\b["']?\s*[:=]\s*["']?(?!\$\{)[^\s,;"'}]{8,}""",
    )
    configured = [
        value
        for name, value in os.environ.items()
        if re.search(r"(?:API_KEY|TOKEN|PASSWORD|SECRET)$", name) and len(value) >= 8
    ]
    if any(re.search(pattern, text) for pattern in patterns) or any(
        value in text for value in configured
    ):
        raise ValueError(
            "Historical task text may contain credentials. Remove sensitive task text before creating a benchmark."
        )


def history(root):
    """List bounded task identities; never infer a correct answer from past output."""
    root = Path(root).resolve()
    rows = []
    if not project_path(root, ".superqode/workorders/store.sqlite3").is_file():
        return {"runs": [], "model_calls": 0}
    for order in factory_store(root, read_only=True).list(limit=100):
        if "factory" not in order.metadata:
            continue
        try:
            _safe_task(order.goal)
            sensitive = False
        except ValueError:
            sensitive = True
        rows.append(
            {
                "run": order.work_order_id,
                "goal": "Task text withheld: review possible credentials locally"
                if sensitive
                else order.goal,
                "task_text_withheld": sensitive,
                "status": order.status.value,
                "revision": order.metadata["factory"].get("repository_commit", ""),
            }
        )
    return {"runs": rows, "model_calls": 0}


def draft(root, *, held_in, held_out, candidate):
    """Return a local dataset proposal, including explicit original Git revisions.

    Historical outputs never become expected answers. Every replay retains the
    pinned protected acceptance checks, and trials enforce paired comparability.
    """
    root = Path(root).resolve()
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("Choose a project-relative candidate Factory revision")
    if not isinstance(held_in, list) or not isinstance(held_out, list):
        raise ValueError("Select held-in and held-out run lists")
    selected = held_in + held_out
    if (
        not held_in
        or not held_out
        or not 2 <= len(selected) <= 8
        or any(not isinstance(v, str) or not v for v in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError(
            "Select two to eight distinct runs, including both held-in and held-out cases"
        )
    candidate_snapshot = trials._snapshot(root, candidate)
    files = {}

    def capture(snapshot):
        name = ".superqode/trials/history/" + snapshot.digest[7:] + ".json"
        files[name] = canonical(snapshot.to_dict())
        if sum(len(v.encode()) for v in files.values()) > 4_000_000:
            raise ValueError("Historical benchmark source package exceeds 4 MB")
        return name

    candidate_ref = capture(candidate_snapshot)
    cases, sources = [], []
    store = factory_store(root, read_only=True)
    for index, reference in enumerate(selected):
        order = store.get(reference)
        if order.repository != str(root):
            raise ValueError("Choose historical runs from this project")
        plan = _pinned_plan(order)
        revision = plan.work_order.metadata["factory"]["repository_commit"]
        # Read the original committed application, never today's edited tree.
        if trials._git(root, "cat-file", "-t", revision).strip() != b"commit":
            raise ValueError("Restore the original application commit before replay")
        trials._seed(root, revision)
        trials._paired(plan.snapshot, candidate_snapshot, root, revision)
        _safe_task(order.goal)
        split = "held-in" if reference in held_in else "held-out"
        cases.append(
            {
                "id": f"history-{index + 1}",
                "goal": order.goal,
                "baseline": capture(plan.snapshot),
                "revision": revision,
                "split": split,
            }
        )
        sources.append(
            {
                "run": reference,
                "snapshot_digest": plan.snapshot.digest,
                "revision": revision,
                "split": split,
            }
        )
    suite = {
        "format": "superqode.factory-trial-suite/1",
        "name": "historical-workload",
        "baseline": cases[0]["baseline"],
        "candidate": candidate_ref,
        "budget": {"max_seconds": 3600, "max_tokens": 120000, "max_tool_calls": 100},
        "cases": cases,
    }
    suite_yaml = yaml.safe_dump(suite, sort_keys=False)
    trials.parse_suite(suite_yaml)
    value = {
        "format": "superqode.factory-benchmark-proposal/1",
        "candidate": candidate,
        "sources": sources,
        "yaml": suite_yaml,
        "files": files,
        "proposal_only": True,
        "execution_started": False,
        "notice": "Review task text and split selection before saving. Historical cases are familiar workloads, not proof of unseen-task generalization. Held-out cases stay outside optimizer search; this paired trial suite is diagnostic and grants no promotion authority.",
    }
    value["digest"] = digest(canonical(value))
    if len(canonical(value).encode()) > 5_000_000:
        raise ValueError("Historical benchmark proposal exceeds 5 MB")
    return value


def install(root, proposal, *, expected, confirmed=False):
    """Save reviewed dataset sources only. Preparation and execution stay explicit."""
    if confirmed is not True:
        raise ValueError("Confirm saving the reviewed historical workload")
    root = Path(root).resolve()
    if (
        not isinstance(proposal, dict)
        or proposal.get("format") != "superqode.factory-benchmark-proposal/1"
    ):
        raise ValueError("Choose a historical benchmark proposal")
    with execution(root, exclusive=True), ownership(root):
        fresh = draft(
            root,
            held_in=[s["run"] for s in proposal["sources"] if s["split"] == "held-in"],
            held_out=[s["run"] for s in proposal["sources"] if s["split"] == "held-out"],
            candidate=proposal["candidate"],
        )
        if fresh != proposal or fresh["digest"] != expected:
            raise ValueError("Historical workload or candidate changed; review a fresh proposal")
        sources = {
            **fresh["files"],
            f".superqode/trials/history-{expected[7:23]}.yaml": fresh["yaml"],
        }
        for name, content in sources.items():
            path = project_path(root, name)
            if path.exists() and trials._read(path) != content:
                raise ValueError("Historical benchmark source conflicts with an existing file")
        for name, content in sources.items():
            write(project_path(root, name), content)
    return {"path": next(reversed(sources)), "digest": expected, "execution_started": False}


def prepare_review(root, *, held_in, held_out, candidate, confirmed=False):
    """Keep protected snapshot contents local when an agent requests a dataset."""
    if confirmed is not True:
        raise ValueError("Confirm preparing the local benchmark review")
    root = Path(root).resolve()
    with execution(root, exclusive=True), ownership(root):
        proposal = draft(root, held_in=held_in, held_out=held_out, candidate=candidate)
        path = project_path(
            root, ".superqode/factory-benchmark-drafts/" + proposal["digest"][7:] + ".json"
        )
        write(path, canonical(proposal))
    return {
        "proposal_id": proposal["digest"],
        "yaml": proposal["yaml"],
        "notice": proposal["notice"],
        "execution_started": False,
        "protected_artifact_contents_included": False,
        "file_digests": {name: digest(text) for name, text in proposal["files"].items()},
    }


def install_review(root, proposal_id, *, confirmed=False):
    if not isinstance(proposal_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", proposal_id):
        raise ValueError("Choose a prepared benchmark review digest")
    path = project_path(
        Path(root).resolve(), ".superqode/factory-benchmark-drafts/" + proposal_id[7:] + ".json"
    )
    proposal = json.loads(trials._read(path, 5_000_000))
    return install(root, proposal, expected=proposal_id, confirmed=confirmed)
