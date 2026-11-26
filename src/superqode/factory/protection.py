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
_WORKER = contextvars.ContextVar("superqode_factory_worker_boundary", default=None)
WORKER_BOUNDARY = "sanitized-repository/1"


@contextmanager
def worker_scope(root, controller, *, allow_network=False):
    token = _WORKER.set((Path(root).resolve(), Path(controller).resolve(), bool(allow_network)))
    try:
        from superqode.pipy.tools.host import tool_operations_scope

        with tool_operations_scope(
            validate_path=confine_tool_path, prepare_command=_prepare_command
        ):
            yield
    finally:
        _WORKER.reset(token)


def worker_boundary():
    return _WORKER.get()


def _prepare_command(argv, cwd):
    from superqode.sandbox.local_sandbox import build_sandboxed_argv

    plan = build_sandboxed_argv(argv, cwd)
    if not plan.applied:
        raise RuntimeError("Factory worker shell isolation was not applied")
    return plan.argv


def confine_tool_path(path):
    boundary = worker_boundary()
    if boundary is None:
        return
    target = Path(path).resolve()
    if not target.is_relative_to(boundary[0]):
        raise ValueError("Factory worker file access must stay inside its isolated repository")
    relative = target.relative_to(boundary[0])
    metadata = bool(relative.parts and relative.parts[0].casefold() == ".git")
    if relative.parts and not metadata:
        try:
            metadata = (boundary[0] / relative.parts[0]).samefile(boundary[0] / ".git")
        except OSError:
            pass
    if metadata:
        raise ValueError("Factory worker Git metadata is managed by the controller")


def create_worker_repository(repository, tree, destination):
    """Copy only the sanitized tree objects, with no controller history or alternates."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.update(
        GIT_AUTHOR_NAME="SuperQode WorkOrder",
        GIT_AUTHOR_EMAIL="workorders@superqode.local",
        GIT_COMMITTER_NAME="SuperQode WorkOrder",
        GIT_COMMITTER_EMAIL="workorders@superqode.local",
    )

    def run(root, args, **kwargs):
        return subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(root),
                *args,
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=120,
            **kwargs,
        )

    run(
        destination,
        [
            "init",
            "--quiet",
            "--template=",
            "--object-format=" + _git(repository, ["rev-parse", "--show-object-format"]).strip(),
        ],
    )
    # A tree revision has no commit parents. Streaming the pack through a private
    # file bounds memory and never exposes protected objects to the worker store.
    with tempfile.TemporaryFile() as pack:
        subprocess.run(
            ["git", "-C", str(repository), "pack-objects", "--stdout", "--revs"],
            input=(tree + "\n").encode(),
            stdout=pack,
            stderr=subprocess.PIPE,
            env=env,
            check=True,
            timeout=120,
        )
        pack.seek(0)
        subprocess.run(
            ["git", "-C", str(destination), "unpack-objects", "-q"],
            stdin=pack,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=True,
            timeout=120,
        )
    commit = (
        run(destination, ["commit-tree", tree, "-m", "Isolated task baseline"])
        .stdout.decode()
        .strip()
    )
    run(destination, ["reset", "--hard", "--quiet", commit])
    run(destination, ["config", "core.hooksPath", os.devnull])
    run(destination, ["config", "core.fsmonitor", "false"])
    return commit


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
    targets = {str(root / item) for root in roots for item in protected}
    # A controller can itself be a linked worktree. Hide both its pointer and
    # the actual common object database, which may live outside the project.
    repository = Path(order.repository).resolve()
    targets.add(str(repository / ".git"))
    common = _git(repository, ["rev-parse", "--git-common-dir"]).strip()
    targets.add(str((repository / common).resolve()))
    return tuple(sorted(targets))


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
    hidden = bool(tasks) and all(
        a.metadata.get("evaluators_hidden") is True
        and a.metadata.get("worker_boundary") == WORKER_BOUNDARY
        and a.metadata.get("sandbox_masking") is True
        for a in tasks
    )
    return {
        "evaluators_hidden": hidden,
        "task_workspaces": len(tasks),
        "hidden_paths": sorted({p for a in tasks for p in a.metadata.get("hidden_paths", [])}),
        "flags": flags(order),
    }
