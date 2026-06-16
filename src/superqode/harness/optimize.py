"""Bridge SuperQode HarnessSpec optimization to superagentic-metaharness."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .eval import load_eval_tasks
from .loader import load_harness_spec


@dataclass(frozen=True)
class MetaHarnessExport:
    project_dir: Path
    baseline_dir: Path
    spec_path: Path
    tasks_path: Path
    trace_evidence_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "baseline_dir": str(self.baseline_dir),
            "spec_path": str(self.spec_path),
            "tasks_path": str(self.tasks_path),
            "trace_evidence_path": str(self.trace_evidence_path)
            if self.trace_evidence_path
            else None,
        }


def export_metaharness_project(
    *,
    spec_path: str | Path,
    tasks_path: str | Path,
    project_dir: str | Path,
    backend: str = "fake",
    budget: int = 1,
    objective: str | None = None,
    model: str | None = None,
    hosted: bool = False,
    oss: bool = False,
    local_provider: str | None = None,
    proposal_timeout: float | None = None,
    search_mode: str = "hill-climb",
    proposal_batch_size: int = 1,
    selection_policy: str = "single",
    trace_evidence_path: str | Path | None = None,
    force: bool = False,
) -> MetaHarnessExport:
    """Create a meta-harness project for optimizing one SuperQode HarnessSpec."""
    source_spec = Path(spec_path).expanduser().resolve()
    source_tasks = Path(tasks_path).expanduser().resolve()
    project = Path(project_dir).expanduser().resolve()
    baseline = project / "baseline"
    if project.exists() and any(project.iterdir()) and not force:
        raise FileExistsError(f"{project} already exists and is not empty; pass --force")

    spec = load_harness_spec(source_spec)
    load_eval_tasks(source_tasks)

    baseline.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_spec, baseline / "harness.yaml")
    shutil.copyfile(source_tasks, baseline / "eval-tasks.yaml")
    _write_baseline_docs(baseline, spec.name)

    tasks = _metaharness_tasks()
    (project / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    config = _metaharness_config(
        spec_name=spec.name,
        backend=backend,
        budget=budget,
        objective=objective,
        model=model,
        hosted=hosted,
        oss=oss,
        local_provider=local_provider,
        proposal_timeout=proposal_timeout,
        search_mode=search_mode,
        proposal_batch_size=proposal_batch_size,
        selection_policy=selection_policy,
    )
    (project / "metaharness.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    evidence_target = None
    if trace_evidence_path:
        source_evidence = Path(trace_evidence_path).expanduser().resolve()
        evidence_target = project / "trace-evidence.md"
        shutil.copyfile(source_evidence, evidence_target)
    else:
        evidence_target = project / "trace-evidence.md"
        evidence_target.write_text(_default_trace_evidence(spec.name), encoding="utf-8")

    return MetaHarnessExport(
        project_dir=project,
        baseline_dir=baseline,
        spec_path=baseline / "harness.yaml",
        tasks_path=project / "tasks.json",
        trace_evidence_path=evidence_target,
    )


def run_metaharness_project(
    *,
    project_dir: str | Path,
    backend: str = "fake",
    budget: int = 1,
    run_name: str = "superqode-optimize",
    metaharness_bin: str = "metaharness",
    trace_evidence_path: str | Path | None = None,
    hosted: bool = False,
    oss: bool = False,
    local_provider: str | None = None,
    model: str | None = None,
    proposal_timeout: float | None = None,
    search_mode: str | None = None,
    proposal_batch_size: int | None = None,
    selection_policy: str | None = None,
) -> dict[str, Any]:
    """Run `metaharness run` and return command output plus expected run dir."""
    project = Path(project_dir).expanduser().resolve()
    command = [
        metaharness_bin,
        "run",
        str(project),
        "--backend",
        backend,
        "--budget",
        str(budget),
        "--run-name",
        run_name,
    ]
    if trace_evidence_path:
        command.extend(["--trace-evidence", str(Path(trace_evidence_path).expanduser().resolve())])
    if hosted:
        command.append("--hosted")
    if oss:
        command.append("--oss")
    if local_provider:
        command.extend(["--local-provider", local_provider])
    if model:
        command.extend(["--model", model])
    if proposal_timeout is not None:
        command.extend(["--proposal-timeout", str(proposal_timeout)])
    if search_mode:
        command.extend(["--search-mode", search_mode])
    if proposal_batch_size is not None:
        command.extend(["--proposal-batch-size", str(proposal_batch_size)])
    if selection_policy:
        command.extend(["--selection-policy", selection_policy])

    try:
        completed = subprocess.run(
            command,
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "metaharness executable not found. Install it with "
            "`uv tool install superagentic-metaharness` or pass --metaharness-bin."
        ) from exc

    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "run_dir": str(project / "runs" / run_name),
        "ok": completed.returncode == 0,
    }


def summarize_metaharness_run(run_dir: str | Path) -> dict[str, Any]:
    """Read a meta-harness run summary without importing the package."""
    run = Path(run_dir).expanduser().resolve()
    leaderboard = _read_json(run / "indexes" / "leaderboard.json")
    candidates_dir = run / "candidates"
    candidates = []
    if candidates_dir.is_dir():
        for candidate_dir in sorted(path for path in candidates_dir.iterdir() if path.is_dir()):
            manifest = candidate_dir / "manifest.json"
            if manifest.is_file():
                candidates.append(_read_json(manifest))
    best_id = str(leaderboard.get("best_candidate_id") or "c0000")
    best = next((item for item in candidates if item.get("candidate_id") == best_id), None)
    best_workspace = Path(best["workspace_dir"]) if best and best.get("workspace_dir") else None
    best_spec = best_workspace / "harness.yaml" if best_workspace else None
    return {
        "run_dir": str(run),
        "best_candidate_id": best_id,
        "best_objective": leaderboard.get("best_objective"),
        "frontier_candidate_ids": leaderboard.get("frontier_candidate_ids", []),
        "candidate_count": len(candidates),
        "best_workspace_dir": str(best_workspace) if best_workspace else None,
        "best_spec_path": str(best_spec) if best_spec and best_spec.is_file() else None,
        "best_outcome": best.get("outcome") if best else None,
        "best_outcome_summary": best.get("outcome_summary") if best else None,
    }


def apply_metaharness_best_spec(
    *,
    run_dir: str | Path,
    output_spec: str | Path,
    force: bool = False,
) -> dict[str, Any]:
    """Copy the best candidate harness.yaml from a meta-harness run."""
    summary = summarize_metaharness_run(run_dir)
    best_spec = summary.get("best_spec_path")
    if not best_spec:
        raise FileNotFoundError("No best candidate harness.yaml found in meta-harness run")
    source = Path(best_spec)
    load_harness_spec(source)
    target = Path(output_spec).expanduser()
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {**summary, "applied_to": str(target)}


def render_optimize_payload(payload: dict[str, Any]) -> str:
    lines = [
        f"Meta-harness project: {payload['export']['project_dir']}",
        f"Baseline: {payload['export']['baseline_dir']}",
    ]
    if payload.get("run"):
        run = payload["run"]
        lines.append(f"Run: {run['run_dir']}")
        lines.append(f"Status: {'ok' if run['ok'] else 'failed'}")
    if payload.get("summary"):
        summary = payload["summary"]
        lines.append(f"Best candidate: {summary['best_candidate_id']}")
        lines.append(f"Best objective: {summary['best_objective']}")
        if summary.get("best_spec_path"):
            lines.append(f"Best spec: {summary['best_spec_path']}")
    if payload.get("applied"):
        lines.append(f"Applied optimized spec to: {payload['applied']['applied_to']}")
    if payload.get("next_steps"):
        lines.append("Next steps:")
        lines.extend(f"  {item}" for item in payload["next_steps"])
    return "\n".join(lines)


def _metaharness_config(
    *,
    spec_name: str,
    backend: str,
    budget: int,
    objective: str | None,
    model: str | None,
    hosted: bool,
    oss: bool,
    local_provider: str | None,
    proposal_timeout: float | None,
    search_mode: str,
    proposal_batch_size: int,
    selection_policy: str,
) -> dict[str, Any]:
    backend_config: dict[str, Any] = {}
    if backend == "codex":
        backend_config = {
            "sandbox_mode": "workspace-write",
            "approval_policy": "never",
            "use_oss": bool(oss or local_provider),
            "local_provider": local_provider,
            "model": model,
            "proposal_timeout_seconds": proposal_timeout,
        }
        if hosted:
            backend_config.update({"use_oss": False, "local_provider": "", "model": model or ""})
    elif backend == "gemini":
        backend_config = {
            "model": model,
            "sandbox": "workspace-write",
            "proposal_timeout_seconds": proposal_timeout,
        }
    elif backend == "omnigent":
        backend_config = {
            "harness": "codex",
            "model": model,
            "allow_network": True,
            "proposal_timeout_seconds": proposal_timeout,
        }

    return {
        "objective": objective
        or (
            f"Improve the SuperQode HarnessSpec `{spec_name}` so it validates, "
            "passes readiness checks, and performs better on the supplied eval tasks."
        ),
        "constraints": [
            "Keep harness.yaml valid as a SuperQode HarnessSpec.",
            "Do not widen write, shell, network, or sandbox permissions unless the change manifest explains why.",
            "Prefer targeted model_policy, workflow, context, checks, and hook changes over broad rewrites.",
            "Use eval-tasks.yaml as the task contract and keep the file runnable by SuperQode.",
        ],
        "baseline_dir": "baseline",
        "runs_dir": "runs",
        "tasks_file": "tasks.json",
        "required_files": ["harness.yaml", "eval-tasks.yaml", "README.md", "AGENTS.md"],
        "allowed_write_paths": ["harness.yaml", "README.md", "AGENTS.md"],
        "backends": {backend: _drop_none(backend_config)},
        "example_profile": "superqode-harness",
        "default_budget": int(budget),
        "search_mode": search_mode,
        "proposal_batch_size": int(proposal_batch_size),
        "selection_policy": selection_policy,
    }


def _metaharness_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "harness-name",
            "type": "file_phrase",
            "path": "harness.yaml",
            "weight": 0.5,
            "required_phrases": ["name:"],
        },
        {
            "id": "harness-validates",
            "type": "command",
            "weight": 1.5,
            "command": "superqode harness validate --spec harness.yaml --json",
            "expect_exit_code": 0,
        },
        {
            "id": "harness-test-dry",
            "type": "command",
            "weight": 1.5,
            "command": "superqode harness test --spec harness.yaml --json",
            "expect_exit_code": 0,
        },
        {
            "id": "harness-eval-dry",
            "type": "command",
            "weight": 2.0,
            "command": "superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml --json",
            "expect_exit_code": 0,
        },
    ]


def _write_baseline_docs(baseline: Path, spec_name: str) -> None:
    (baseline / "README.md").write_text(
        (
            f"# SuperQode Harness Optimization: {spec_name}\n\n"
            "This workspace is optimized by meta-harness. The primary artifact is "
            "`harness.yaml`; `eval-tasks.yaml` is the evaluation contract.\n"
        ),
        encoding="utf-8",
    )
    (baseline / "AGENTS.md").write_text(
        (
            "# Optimization Instructions\n\n"
            "- Edit `harness.yaml` first.\n"
            "- Keep the spec valid for `superqode harness validate`.\n"
            "- Run or preserve the dry checks in `tasks.json`.\n"
            "- Do not widen permissions unless the change is necessary and documented.\n"
            "- If you make a policy change, explain it in `.metaharness/change_manifest.json`.\n"
        ),
        encoding="utf-8",
    )


def _default_trace_evidence(spec_name: str) -> str:
    return (
        f"# Trace Evidence for {spec_name}\n\n"
        "No external trace evidence was supplied. Optimize against the exported "
        "SuperQode validation, readiness, and eval tasks.\n"
    )


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
