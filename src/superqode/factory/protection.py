"""Keep protected acceptance evaluators out of worker working copies and sandboxes.

Workers implement against the goal and the visible repository. The evaluator
files that judge their work are removed from each task working copy, masked in
sandboxed shell commands and denied to file tools by policy. Any attempt to read
or write those paths is recorded as a protection flag on the run.
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
from dataclasses import replace
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

PROTECTED_DIRECTORY = ".superqode/evaluators"
FLAG_KINDS = ("factory_protected_access", "factory_protected_write")

_HIDDEN: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "superqode_factory_hidden_paths", default=()
)


def evaluator_paths(definition) -> tuple[str, ...]:
    """Relative evaluator paths declared by a Factory definition, plus the default folder."""
    paths = {
        PurePosixPath(asset["path"]).as_posix()
        for asset in definition.get("data_context", {}).get("files", {}).values()
        if asset.get("purpose") == "evaluator"
    }
    paths.add(PROTECTED_DIRECTORY)
    return tuple(sorted(paths))


def protected_paths(order) -> tuple[str, ...]:
    """Evaluator paths for a Factory WorkOrder, or nothing for ordinary WorkOrders."""
    from .runtime import is_factory_order, _pinned_plan

    if not is_factory_order(order):
        return ()
    plan = _pinned_plan(order)
    return evaluator_paths(plan.snapshot.payload["definition"])


def is_protected(path: str, protected: tuple[str, ...] | list[str]) -> bool:
    candidate = PurePosixPath(str(path).replace("\\", "/")).as_posix().lstrip("/")
    return any(
        candidate == item or candidate.startswith(item.rstrip("/") + "/") for item in protected
    )


def touched(files, protected) -> list[str]:
    return sorted({str(path) for path in files if is_protected(path, protected)})


def _git(repository: Path, args, env=None) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=60,
    ).stdout


def tree_without(repository: Path, tree: str, protected) -> str:
    """Return a Git tree equal to ``tree`` with protected paths removed."""
    if not protected:
        return tree
    with tempfile.TemporaryDirectory(prefix="superqode-protect-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        _git(repository, ["read-tree", tree], env=env)
        _git(
            repository,
            ["rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *protected],
            env=env,
        )
        return _git(repository, ["write-tree"], env=env).strip()


def restore_protected(repository: Path, candidate_tree: str, baseline_tree: str, protected) -> str:
    """Drop worker changes to protected paths by resetting them to the visible baseline."""
    if not protected:
        return candidate_tree
    stripped = tree_without(repository, candidate_tree, protected)
    with tempfile.TemporaryDirectory(prefix="superqode-protect-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        _git(repository, ["read-tree", stripped], env=env)
        listing = _git(repository, ["ls-tree", "-r", "-z", baseline_tree, "--", *protected])
        for item in filter(None, listing.split("\0")):
            metadata, name = item.split("\t", 1)
            mode, _, blob = metadata.split()
            _git(
                repository,
                ["update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}"],
                env=env,
            )
        return _git(repository, ["write-tree"], env=env).strip()


def mask_targets(order) -> tuple[str, ...]:
    """Absolute host paths a sandboxed worker command must not see."""
    protected = protected_paths(order)
    if not protected:
        return ()
    roots = {Path(order.repository).resolve()}
    for artifact in order.artifacts:
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "work-order":
            roots.add(Path(artifact.path).resolve())
    return tuple(sorted(str(root / item) for root in roots for item in protected))


@contextmanager
def hidden_paths_scope(paths):
    token = _HIDDEN.set(tuple(paths))
    try:
        yield
    finally:
        _HIDDEN.reset(token)


def hidden_paths() -> tuple[str, ...]:
    return _HIDDEN.get()


def guard_governance(bundle, order):
    """Add a deny rule for protected paths and record every matching tool call."""
    from superqode.governance import ContextualPolicyEngine, PolicyLayer, ContextualPolicyRule

    protected = protected_paths(order)
    if not protected:
        return bundle, []
    patterns = [f"*{item}*" for item in protected]
    rule = ContextualPolicyRule(
        rule_id="factory-protected-evaluators",
        action="deny",
        phases=("tool_call",),
        tools=("*",),
        argument_patterns={"*": tuple(patterns)},
        message="Protected acceptance evaluators are not available to Factory workers",
    )
    layer = PolicyLayer(
        name="factory_protection",
        source="Factory protected evaluators",
        rules=(rule,),
        defaults={},
    )
    hits: list[dict] = []

    class RecordingEngine(ContextualPolicyEngine):
        def evaluate(self, request):
            decision = super().evaluate(request)
            if any(match.rule_id == rule.rule_id for match in decision.matches):
                if len(hits) < 64:
                    hits.append({"tool": request.tool, "phase": request.phase})
            return decision

    engine = RecordingEngine((*bundle.engine.layers, layer))
    return replace(bundle, engine=engine), hits


def flags(order) -> list[dict]:
    """Protection flags recorded on a run: protected reads denied or writes dropped."""
    import json

    rows = []
    for artifact in order.artifacts:
        if artifact.kind in FLAG_KINDS:
            try:
                value = json.loads(artifact.content) if artifact.content else {}
            except ValueError:
                value = {}
            rows.append(
                {
                    "kind": "read" if artifact.kind == "factory_protected_access" else "write",
                    "task_id": artifact.task_id,
                    "artifact_id": artifact.artifact_id,
                    **({"paths": value.get("paths", [])} if "paths" in value else {}),
                    **({"tools": value.get("tools", [])} if "tools" in value else {}),
                }
            )
    return rows


def provenance(order) -> dict:
    """Whether every task working copy was created without the evaluator files."""
    tasks = [
        artifact
        for artifact in order.artifacts
        if artifact.kind == "workspace" and artifact.metadata.get("scope") == "task"
    ]
    hidden = bool(tasks) and all(a.metadata.get("evaluators_hidden") is True for a in tasks)
    return {
        "evaluators_hidden": hidden,
        "task_workspaces": len(tasks),
        "hidden_paths": sorted({p for a in tasks for p in a.metadata.get("hidden_paths", [])}),
        "flags": flags(order),
    }
