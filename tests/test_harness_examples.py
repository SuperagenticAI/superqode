from pathlib import Path

import pytest

from superqode.harness import inspect_harness_backend, load_harness_spec


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "harnesses"


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.yaml")))
def test_harness_examples_load_and_match_backend(path: Path):
    spec = load_harness_spec(path)

    assert spec.name
    assert spec.runtime.backend
    if spec.is_decision:
        assert spec.runtime.backend == "systemone"
        assert spec.systemone.enabled
    else:
        assert spec.agents
    assert spec.metadata.get("example")

    inspection = inspect_harness_backend(spec.runtime.backend, spec)
    assert inspection.ok, [issue.to_dict() for issue in inspection.issues]


@pytest.mark.parametrize("runtime", [None, "builtin"])
def test_rlm_monty_example_doctor_uses_native_tool_and_sandbox_contract(runtime, tmp_path):
    from superqode.harness.diagnostics import doctor_harness

    spec = load_harness_spec(EXAMPLES_DIR / "rlm-a2a.yaml")
    report = doctor_harness(spec, runtime=runtime, cwd=tmp_path)
    checks = {check.name: check for check in report.checks}
    assert checks["agents"].status == "ok"
    assert checks["tools"].status == "ok"
    assert checks["sandbox"].status in {"ok", "warning"}
    assert checks["sandbox"].data["backend"] == "monty"
    assert checks["sandbox"].data["can_shell"] is False


def test_monty_does_not_validate_for_other_harnesses():
    from superqode.harness.diagnostics import _sandbox_check
    from superqode.harness.templates import core_template

    assert _sandbox_check("monty", spec=core_template())["status"] == "error"
