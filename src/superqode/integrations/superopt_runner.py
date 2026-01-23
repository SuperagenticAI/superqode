"""SuperOpt command-based runner for OSS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from superopt import AgenticEnvironment, ExecutionTrace, SuperOpt
from superopt.core.environment import PromptConfig, RetrievalConfig, ToolSchema

from superqode.agent.system_prompts import SystemPromptLevel, get_system_prompt
from superqode.config import load_config
from superqode.tools.base import ToolRegistry


def _pick_job_description(project_root: Path) -> str:
    try:
        config = load_config(project_root)
    except Exception:
        return "You are a QE agent."

    qe_mode = config.team.modes.get("qe") if config.team else None
    if qe_mode and qe_mode.roles:
        for role in qe_mode.roles.values():
            if role.enabled and role.job_description:
                return role.job_description.strip()

    if config.default and config.default.job_description:
        return config.default.job_description.strip()

    return "You are a QE agent."


def _build_environment(project_root: Path) -> AgenticEnvironment:
    system_prompt = get_system_prompt(
        level=SystemPromptLevel.STANDARD,
        working_directory=project_root,
    )
    job_description = _pick_job_description(project_root)

    prompt_config = PromptConfig(
        system_prompt=system_prompt,
        instruction_policy=job_description,
    )

    registry = ToolRegistry.default()
    tools: Dict[str, ToolSchema] = {}
    for tool in registry.list():
        tools[tool.name] = ToolSchema(
            name=tool.name,
            description=tool.description,
            arguments=tool.parameters,
        )

    retrieval_config = RetrievalConfig()

    return AgenticEnvironment(
        prompts=prompt_config,
        tools=tools,
        retrieval=retrieval_config,
        memory=[],
    )


def _build_trace(result: Dict[str, Any]) -> ExecutionTrace:
    findings = result.get("findings", [])
    critical = [f for f in findings if f.get("severity") == "critical"]
    tests_failed = result.get("tests_failed", 0)
    status = result.get("status", "")

    success = status == "completed" and tests_failed == 0 and not critical
    failure_message = result.get("verdict") if not success else None

    trace = ExecutionTrace(
        task_description=f"QE session {result.get('session_id', 'unknown')}",
        success=success,
        failure_message=failure_message,
    )

    if tests_failed:
        trace.test_failures = [f"{tests_failed} test(s) failed"]

    errors = result.get("errors", [])
    if errors:
        trace.runtime_exceptions = list(errors)

    return trace


def run_superopt(trace_path: Path, output_path: Path, project_root: Path) -> int:
    try:
        result = json.loads(trace_path.read_text())
    except Exception as exc:
        raise SystemExit(f"Failed to read trace: {exc}") from exc

    environment = _build_environment(project_root)
    trace = _build_trace(result)

    optimizer = SuperOpt(environment=environment)
    optimizer.step(trace)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(optimizer.environment.to_dict(), indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SuperOpt optimization.")
    parser.add_argument("--trace", required=True, help="Path to QE result JSON")
    parser.add_argument("--out", required=True, help="Output path for environment JSON")
    parser.add_argument("--project-root", default=".", help="Project root")
    args = parser.parse_args()

    trace_path = Path(args.trace).resolve()
    output_path = Path(args.out).resolve()
    project_root = Path(args.project_root).resolve()

    raise SystemExit(run_superopt(trace_path, output_path, project_root))


if __name__ == "__main__":
    main()
