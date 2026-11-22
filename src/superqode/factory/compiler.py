"""Compile a resolved factory into a draft WorkOrder, without admitting work."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import yaml

from superqode import __version__
from superqode.harness.loader import harness_spec_from_dict, harness_spec_to_dict
from superqode.harness.spec import WorkflowMode
from superqode.workorders.models import (
    WorkOrder,
    WorkOrderBudget,
    WorkOrderTask,
    WorkTaskRole,
    generate_work_order_id,
)

from .definition import project_path
from .snapshot import FactorySnapshot


def _snapshot_directory(root, snapshot):
    token = snapshot.digest.removeprefix("sha256:")
    return project_path(root, f".superqode/factory/snapshots/{token}")


def _git(root, *args):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Git baseline inspection failed or timed out") from exc
    if result.returncode:
        raise ValueError("Factory compilation requires a Git repository with a committed baseline")
    return result.stdout.strip()


@dataclass(frozen=True)
class CompiledFactory:
    snapshot: FactorySnapshot
    work_order: WorkOrder
    harnesses_json: str
    snapshot_directory: Path

    @property
    def harnesses(self):
        return json.loads(self.harnesses_json)

    def to_dict(self):
        return {
            "format": "superqode.factory-plan/1",
            "snapshot_digest": self.snapshot.digest,
            "snapshot_directory": str(self.snapshot_directory),
            "work_order": self.work_order.to_dict(),
            "harnesses": self.harnesses,
            "execution_started": False,
            "limitations": [
                "Draft compilation does not establish execution quality or evaluator independence.",
                "Compilation does not admit or execute work; submit and worker are explicit operations.",
                "Protected verification and authenticated release authorization are not established by this plan.",
            ],
        }


def compile_factory(snapshot: FactorySnapshot, *, root=".", goal: str) -> CompiledFactory:
    """Prepare existing WorkOrder contracts and pinned stage harnesses in memory."""
    root = Path(root).resolve()
    revision = repository_revision(root)
    plan = _compile_factory(snapshot, root=root, goal=goal, revision=revision)
    if repository_revision(root) != revision:
        raise ValueError("Repository starting commit changed during factory compilation")
    return plan


def repository_revision(root: Path) -> str:
    """Require a clean committed application baseline before admission/execution."""
    top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise ValueError("Factory project must be the Git repository root")
    revision = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError(
            "Commit or isolate repository changes before compiling a reproducible factory trial"
        )
    if _git(root, "ls-files", "--stage").find("160000 ") >= 0:
        raise ValueError("Factory trials with Git submodules need an explicit dependency contract")
    return revision


def _compile_factory(
    snapshot: FactorySnapshot, *, root: Path, goal: str, revision: str
) -> CompiledFactory:
    """Rebuild a pinned contract without inspecting the mutable application tree."""
    snapshot = FactorySnapshot.from_dict(snapshot.to_dict())
    payload = snapshot.payload
    if payload["engine_version"] != __version__:
        raise ValueError(
            "Factory snapshot engine version differs; explicitly re-resolve before compiling"
        )
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Factory compilation requires a non-empty goal")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("Factory plan requires a pinned Git commit")
    definition = payload["definition"]
    directory = _snapshot_directory(root, snapshot)
    governance = definition["governance"]
    if not governance["permissions"].get("allow_shell", False):
        raise ValueError("This compiler requires factory shell permission for acceptance commands")
    from superqode.session.factory import classify_model_ref, default_policy

    defaults = default_policy()
    route_name = definition.get("default_route", defaults["default_route"])
    if route_name not in defaults["routes"] and route_name not in definition.get("routes", {}):
        raise ValueError(f"Unknown factory default route: {route_name}")
    route = {
        **defaults["routes"].get(route_name, {}),
        **definition.get("routes", {}).get(route_name, {}),
    }
    checks = definition["improvement"]["checks"]
    harnesses, tasks = {}, []
    from .workflow import expand

    for stage in expand(definition):
        from .skills import bound_harness

        spec = harness_spec_from_dict(bound_harness(payload, stage["harness"]))
        if (
            spec.runtime.backend != "builtin"
            or spec.runtime.fallback_backends
            or spec.runtime.config
            or spec.hooks.rules
            or spec.recursion.enabled
            or spec.remote_harness.enabled
            or spec.tool_discovery.enabled
            or spec.systemone.enabled
            or spec.context.memory
            or spec.context.compaction
            or spec.workflow.mode != WorkflowMode.SINGLE
            or spec.optimization.enabled
            or spec.execution_policy.permission_rules
            or spec.execution_policy.config
            or spec.workflow.config
            or len(spec.agents) != 1
            or spec.checks.enabled
            or spec.observability.exporters
            or spec.observability.config
        ):
            raise ValueError(
                f"Stage {stage['id']}: first factory compiler supports simple native builtin "
                "harnesses; advanced runtime, hooks, checks and delegation require adapter contracts"
            )
        if not spec.model_policy.primary:
            raise ValueError(f"Stage {stage['id']} requires an explicit primary model binding")
        for model in (spec.model_policy.primary, *spec.model_policy.fallbacks):
            classification = classify_model_ref(model)
            local = (
                "LOCAL" in classification["tags"]
                or classification["provider"] == "apple-foundation"
            )
            if route.get("allow_cloud") is False and not local:
                raise ValueError(
                    f"Stage {stage['id']}: route {route_name} disallows non-local inference"
                )
            if (
                route.get("allow_subscription_runtimes") is False
                and "RUNTIME" in classification["tags"]
            ):
                raise ValueError(
                    f"Stage {stage['id']}: route {route_name} disallows subscription runtimes"
                )
        limits = governance["permissions"]
        local = stage.get("permissions", {})
        permissions = {
            key: getattr(spec.execution_policy, key)
            and limits.get(key, False)
            and local.get(key, True)
            for key in ("allow_read", "allow_write", "allow_shell", "allow_network")
        }
        if stage["role"] != "implementer":
            permissions["allow_write"] = False
        context = spec.context
        project_path(root, context.session_storage)
        # Context is read from the captured source tree, not mutable project files.
        source_root = directory / "sources"
        instruction_files = tuple(
            str(source_root / relative)
            for relative in context.instruction_files
            if relative in payload["sources"]
        )
        skills = (
            source_root / context.skills_dir if context.skills_dir else source_root / "no-skills"
        )
        roles = source_root / context.roles_dir if context.roles_dir else source_root / "no-roles"
        spec = replace(
            spec,
            name=f"factory-{stage['id']}",
            inherits=None,
            execution_policy=replace(spec.execution_policy, **permissions),
            context=replace(
                context,
                instruction_files=instruction_files,
                skills_dir=str(skills),
                roles_dir=str(roles),
            ),
        )
        harness_path = directory / "harnesses" / f"{stage['id']}.yaml"
        harnesses[stage["id"]] = harness_spec_to_dict(spec)
        tasks.append(
            WorkOrderTask(
                task_id=stage["id"],
                title=stage.get("title", stage["id"]),
                goal=stage["goal"],
                role=WorkTaskRole(stage["role"]),
                dependencies=tuple(stage.get("depends_on", ())),
                harness=str(harness_path),
                acceptance_tests=tuple(checks[key]["command"] for key in stage.get("checks", ())),
                metadata={
                    "factory_snapshot": snapshot.digest,
                    "factory_stage": stage.get("_origin", stage["id"]),
                    "human_gate": stage.get("human_gate", False),
                    **(
                        {
                            "factory_contract": {
                                "inputs": stage.get("inputs", {}),
                                "outputs": stage.get("outputs", {}),
                                **({"when": stage["when"]} if stage.get("when") else {}),
                                **({"loop": stage["_loop"]} if stage.get("_loop") else {}),
                            }
                        }
                        if stage.get("inputs")
                        or stage.get("outputs")
                        or stage.get("when")
                        or stage.get("_loop")
                        else {}
                    ),
                },
            )
        )
    order = WorkOrder(
        work_order_id=generate_work_order_id(),
        goal=goal.strip(),
        repository=str(root),
        harness=tasks[0].harness,
        harness_version=snapshot.digest,
        budget=WorkOrderBudget.from_dict(governance["budget"]),
        tasks=tuple(tasks),
        acceptance_tests=tuple(
            checks[key]["command"] for key in definition["orchestration"]["acceptance_checks"]
        ),
        metadata={
            "factory": {
                "name": definition["metadata"]["name"],
                "snapshot_digest": snapshot.digest,
                "repository_commit": revision,
                "release": governance["release"],
                "snapshot_directory": str(directory),
            },
        },
    )
    return CompiledFactory(snapshot, order, json.dumps(harnesses, sort_keys=True), directory)


def materialize_snapshot(plan: CompiledFactory, *, verify_only=False) -> Path:
    """Write a verified bundle atomically; never enqueue or execute its draft."""
    root = Path(plan.work_order.repository)
    target = _snapshot_directory(root, plan.snapshot)
    if target != plan.snapshot_directory:
        raise ValueError("Factory snapshot destination mismatch")
    expected = {"snapshot.json": json.dumps(plan.snapshot.to_dict(), indent=2) + "\n"}
    for name, harness in plan.harnesses.items():
        expected[f"harnesses/{name}.yaml"] = yaml.safe_dump(harness, sort_keys=False)
    for relative, source in plan.snapshot.payload["sources"].items():
        expected[f"sources/{relative}"] = source["text"]

    def verify_existing():
        actual = set()
        for path in target.rglob("*"):
            safe = project_path(root, path.relative_to(root).as_posix())
            if safe.is_file():
                actual.add(safe.relative_to(target).as_posix())
            if len(actual) > len(expected):
                raise ValueError("Existing factory snapshot has unexpected files")
        if actual != set(expected):
            raise ValueError("Existing factory snapshot has missing or unexpected files")
        for relative, text in expected.items():
            path = project_path(root, (target.relative_to(root) / relative).as_posix())
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise ValueError(
                    "Existing factory snapshot differs; refusing to overwrite evidence"
                )

    if target.exists():
        verify_existing()
        return target
    if verify_only:
        raise ValueError("Pinned factory snapshot is missing; materialize it before execution")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=target.parent))
    try:
        for relative, text in expected.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        try:
            staging.rename(target)
        except OSError:
            if not target.exists():
                raise
            verify_existing()
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target
