"""Harness smoke tests and compact failure digests."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .diagnostics import doctor_harness
from .kernel import init_harness
from .loader import load_harness_spec
from .store import create_harness_store


@dataclass(frozen=True)
class HarnessTestCheck:
    name: str
    status: str
    duration_seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 3),
            "details": self.details,
            **({"error": self.error} if self.error else {}),
        }


# The nine behavioral dimensions of a harness (HarnessX taxonomy, D1-D9), each
# mapped to the canonical HarnessSpec field you would edit to address it. Used to
# tag a failure with WHERE in the harness to look, not just what failed.
HARNESS_DIMENSIONS: dict[str, dict[str, str]] = {
    "D1": {"label": "model selection", "field": "model_policy"},
    "D2": {"label": "context assembly", "field": "context"},
    "D3": {"label": "memory management", "field": "context.memory"},
    "D4": {"label": "tool ecosystem", "field": "agents.tools"},
    "D5": {"label": "execution environment", "field": "execution_policy.sandbox"},
    "D6": {"label": "evaluation and reward", "field": "checks"},
    "D7": {"label": "control and safety", "field": "execution_policy"},
    "D8": {"label": "observability", "field": "observability"},
    "D9": {"label": "training bridge", "field": "metadata"},
}

# Which dimension each failure category most directly implicates.
_DIMENSION_FOR_CATEGORY: dict[str, str] = {
    "spec_load_error": "D2",  # the spec/composition does not assemble
    "model_endpoint_error": "D1",
    "tool_or_permission_error": "D7",
    "runtime_error": "D5",
}


def dimension_for_category(category: str) -> dict[str, str]:
    """Tag a failure category with its harness dimension (D1-D9) + field.

    Returns ``{"id", "label", "field"}``; an empty id when there is no failure.
    """
    dim_id = _DIMENSION_FOR_CATEGORY.get(category, "")
    if not dim_id:
        return {"id": "", "label": "", "field": ""}
    meta = HARNESS_DIMENSIONS[dim_id]
    return {"id": dim_id, "label": meta["label"], "field": meta["field"]}


def build_failure_digest(checks: list[HarnessTestCheck]) -> dict[str, Any]:
    failed = [check for check in checks if check.status == "failed"]
    if not failed:
        return {
            "outcome": "passed",
            "failure_category": "",
            "dimension": {"id": "", "label": "", "field": ""},
            "implicated_components": [],
            "evidence": [],
            "suggested_next_checks": [],
        }
    first = failed[0]
    category, components, suggestions = _classify_failure(first)
    evidence = [f"{check.name}: {check.error or check.details}" for check in failed]
    return {
        "outcome": "failed",
        "failure_category": category,
        "dimension": dimension_for_category(category),
        "implicated_components": components,
        "evidence": evidence,
        "suggested_next_checks": suggestions,
    }


def _classify_failure(check: HarnessTestCheck) -> tuple[str, list[str], list[str]]:
    text = f"{check.name} {check.error} {check.details}".lower()
    if check.name == "load":
        return (
            "spec_load_error",
            ["harness_spec", "inheritance"],
            ["Run `superqode harness validate --spec <path> --json`."],
        )
    if "provider" in text or "model" in text or "endpoint" in text:
        return (
            "model_endpoint_error",
            ["model_policy", "provider"],
            ["Run `superqode providers doctor` or pass --provider/--model overrides."],
        )
    if "tool" in text or "permission" in text or "approval" in text:
        return (
            "tool_or_permission_error",
            ["execution_policy", "agents.tools"],
            ["Run `superqode harness doctor --spec <path>` and inspect tool permissions."],
        )
    return (
        "runtime_error",
        ["runtime", "harness_kernel"],
        ["Run `superqode harness doctor --spec <path> --json` for compatibility details."],
    )


async def run_harness_smoke_test(
    spec_path: str | Path,
    *,
    provider: str,
    model: str,
    runtime: str | None = None,
    working_dir: str | Path = ".",
    sandbox_backend: str = "local",
    prompt: str = "Reply with exactly: superqode harness ok",
    live: bool = False,
) -> dict[str, Any]:
    """Run a fast HarnessSpec smoke test.

    By default this validates load/doctor/init paths without calling a model.
    Pass ``live=True`` to send the prompt through the configured runtime.
    """
    checks: list[HarnessTestCheck] = []
    spec = None
    started_all = time.monotonic()

    started = time.monotonic()
    try:
        spec = load_harness_spec(spec_path)
        checks.append(
            HarnessTestCheck(
                "load",
                "passed",
                time.monotonic() - started,
                {"name": spec.name, "inherits": spec.inherits or ""},
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            HarnessTestCheck("load", "failed", time.monotonic() - started, error=str(exc))
        )
        return _smoke_payload(spec_path, checks, started_all)

    started = time.monotonic()
    try:
        report = doctor_harness(spec, runtime=runtime, sandbox=sandbox_backend)
        report_payload = report.to_dict()
        status = "passed" if report.status != "error" else "failed"
        checks.append(
            HarnessTestCheck(
                "doctor",
                status,
                time.monotonic() - started,
                {
                    "status": report.status,
                    "ready": report_payload["ready"],
                    "blockers": report_payload["summary"].get("blockers", 0),
                    "warnings": report_payload["summary"].get("warnings", 0),
                },
                "" if status == "passed" else "doctor reported blockers",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            HarnessTestCheck("doctor", "failed", time.monotonic() - started, error=str(exc))
        )

    started = time.monotonic()
    try:
        store = create_harness_store("memory")
        kernel = await init_harness(spec, store=store)
        checks.append(
            HarnessTestCheck(
                "init",
                "passed",
                time.monotonic() - started,
                {"store": "memory", "runtime": runtime or spec.runtime.backend},
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            HarnessTestCheck("init", "failed", time.monotonic() - started, error=str(exc))
        )
        return _smoke_payload(spec_path, checks, started_all)

    if live:
        started = time.monotonic()
        try:
            session = await kernel.session()
            result = await session.prompt(
                prompt,
                provider=provider,
                model=model,
                runtime=runtime,
                working_directory=Path(working_dir),
                sandbox_backend=sandbox_backend,
            )
            checks.append(
                HarnessTestCheck(
                    "model_prompt",
                    "passed" if result.content else "failed",
                    time.monotonic() - started,
                    {
                        "run_id": result.run_id,
                        "content_chars": len(result.content or ""),
                        "tool_calls_made": result.tool_calls_made,
                    },
                    "" if result.content else "model returned no content",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                HarnessTestCheck(
                    "model_prompt", "failed", time.monotonic() - started, error=str(exc)
                )
            )
    else:
        checks.append(
            HarnessTestCheck(
                "model_prompt",
                "skipped",
                0.0,
                {"reason": "pass --live to call the model endpoint"},
            )
        )

    return _smoke_payload(spec_path, checks, started_all)


def _smoke_payload(
    spec_path: str | Path,
    checks: list[HarnessTestCheck],
    started_all: float,
) -> dict[str, Any]:
    failed = [check for check in checks if check.status == "failed"]
    return {
        "spec": str(spec_path),
        "status": "failed" if failed else "passed",
        "duration_seconds": round(time.monotonic() - started_all, 3),
        "checks": [check.to_dict() for check in checks],
        "failure_digest": build_failure_digest(checks),
    }


def render_harness_smoke_test(payload: dict[str, Any]) -> str:
    lines = [
        f"Harness test: {payload['status']}",
        f"Spec: {payload['spec']}",
    ]
    for check in payload["checks"]:
        line = f"  {check['status']:<7} {check['name']}"
        if check.get("error"):
            line += f" - {check['error']}"
        elif check.get("details", {}).get("reason"):
            line += f" - {check['details']['reason']}"
        lines.append(line)
    digest = payload.get("failure_digest") or {}
    if digest.get("outcome") == "failed":
        lines.append("")
        lines.append(f"Failure: {digest.get('failure_category')}")
        for item in digest.get("suggested_next_checks", []):
            lines.append(f"  next: {item}")
    return "\n".join(lines)
