"""A HarnessSpec is a promise. These tests check that we notice when it breaks.

``harness doctor`` answers whether a harness can run. Drift answers whether the
harness that resolved is the one the spec described, which is the question that
matters once a spec is committed and nobody reads it again.
"""

from __future__ import annotations

import json

import pytest

from click.testing import CliRunner

from superqode.commands.harness import harness
from superqode.harness.drift import (
    DRIFT_DRIFT,
    DRIFT_OK,
    DRIFT_UNKNOWN,
    DriftCheck,
    DriftReport,
    detect_drift,
    render_drift,
)
from superqode.harness.spec import (
    AgentSpec,
    ChecksSpec,
    ExecutionPolicySpec,
    HarnessSpec,
    ObservabilitySpec,
    RuntimeSpec,
)


def _spec(**overrides) -> HarnessSpec:
    values = {
        "name": "under-test",
        "runtime": RuntimeSpec(backend="builtin"),
        "execution_policy": ExecutionPolicySpec(
            sandbox="local", allow_shell=True, allow_write=True
        ),
        "agents": (AgentSpec(id="coder", role="implementation", tools=("read", "bash")),),
    }
    values.update(overrides)
    return HarnessSpec(**values)


def _check(report, name):
    return next(check for check in report.checks if check.name == name)


def test_a_spec_that_keeps_its_promises_reports_no_drift():
    report = detect_drift(_spec())

    assert report.status == DRIFT_OK
    assert report.drifted == ()
    assert report.to_dict()["clean"] is True


def test_unknown_runtime_is_drift_rather_than_a_late_failure():
    report = detect_drift(_spec(runtime=RuntimeSpec(backend="no-such-runtime")))

    assert _check(report, "runtime").status == DRIFT_DRIFT
    assert report.status == DRIFT_DRIFT


def test_declared_tool_that_cannot_resolve_is_reported():
    """ToolRegistry.filtered drops unknown names silently, so nothing else notices."""
    report = detect_drift(
        _spec(agents=(AgentSpec(id="coder", role="implementation", tools=("read", "nope")),))
    )
    tools = _check(report, "tools")

    assert tools.status == DRIFT_DRIFT
    assert "nope" in tools.detail
    assert "read" in tools.observed


def test_real_tool_names_from_submodules_are_not_flagged():
    """repo_search lives in a submodule and is not re-exported; it is still real."""
    report = detect_drift(
        _spec(
            agents=(
                AgentSpec(id="coder", role="implementation", tools=("repo_search", "read_file")),
            )
        )
    )

    assert _check(report, "tools").status == DRIFT_OK


def test_local_sandbox_is_not_flagged_for_naming_alone():
    """The spec says "local" where the provider registry says "local-os"."""
    report = detect_drift(_spec())

    assert _check(report, "sandbox").status == DRIFT_OK


def test_shell_tool_under_a_blocking_policy_is_drift():
    report = detect_drift(
        _spec(
            execution_policy=ExecutionPolicySpec(
                sandbox="local", allow_shell=False, allow_write=True
            )
        )
    )

    assert _check(report, "allow_shell").status == DRIFT_DRIFT


def test_checks_enabled_without_steps_is_a_supported_configuration():
    """doctor treats this as ok, so drift must agree rather than invent a fault."""
    report = detect_drift(_spec(checks=ChecksSpec(enabled=True, custom_steps=())))

    assert _check(report, "checks").status == DRIFT_OK


def test_checks_promising_to_fail_a_run_while_defining_none_is_drift():
    report = detect_drift(
        _spec(checks=ChecksSpec(enabled=True, fail_on_error=True, custom_steps=()))
    )

    assert _check(report, "checks").status == DRIFT_DRIFT


def test_mcp_tools_are_not_flagged_because_servers_register_them_at_run_time():
    report = detect_drift(
        _spec(
            agents=(
                AgentSpec(
                    id="coder", role="implementation", tools=("read", "mcp_docs_search_docs")
                ),
            )
        )
    )
    tools = _check(report, "tools")

    assert tools.status == DRIFT_OK
    assert "MCP" in tools.detail


def test_events_declared_without_a_store_is_drift():
    report = detect_drift(_spec(observability=ObservabilitySpec(events=True, run_store="")))

    assert _check(report, "observability").status == DRIFT_DRIFT


def test_render_names_the_field_that_lied():
    report = detect_drift(_spec(runtime=RuntimeSpec(backend="no-such-runtime")))
    text = render_drift(report)

    assert "DRIFT" in text
    assert "runtime" in text
    assert "no-such-runtime" in text


def test_cli_exits_non_zero_on_drift_so_it_can_gate_a_pipeline(tmp_path):
    spec = tmp_path / "drifty.yaml"
    spec.write_text(
        "version: 1\n"
        "name: drifty\n"
        "flavor: coding\n"
        "runtime:\n"
        "  backend: no-such-runtime\n"
        "agents:\n"
        "- id: coder\n"
        "  role: implementation\n"
        "  tools: [read]\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(harness, ["drift", "--spec", str(spec), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["clean"] is False
    assert payload["summary"]["drift"] >= 1


def test_cli_exits_zero_when_the_spec_holds(tmp_path):
    spec = tmp_path / "clean.yaml"
    spec.write_text(
        "version: 1\n"
        "name: clean\n"
        "flavor: coding\n"
        "runtime:\n"
        "  backend: builtin\n"
        "execution_policy:\n"
        "  sandbox: local\n"
        "  allow_shell: true\n"
        "  allow_write: true\n"
        "agents:\n"
        "- id: coder\n"
        "  role: implementation\n"
        "  tools: [read, write, edit, bash]\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(harness, ["drift", "--spec", str(spec), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["clean"] is True


def test_every_shipped_example_spec_matches_its_own_declarations():
    """A shipped example that lies about itself is the worst place for drift."""
    from pathlib import Path

    from superqode.harness import load_harness_spec

    examples = sorted(Path("examples/harnesses").glob("*.yaml"))
    assert examples, "expected example harness specs to exist"

    offenders = {}
    for path in examples:
        report = detect_drift(load_harness_spec(path))
        # Sandbox and runtime availability depend on the machine, so only
        # declarations that are wrong everywhere count here.
        portable = [check for check in report.drifted if check.name not in {"sandbox", "runtime"}]
        if portable:
            offenders[path.name] = [check.name for check in portable]

    assert not offenders, f"example specs contradict themselves: {offenders}"


def test_native_rlm_tool_contract_is_checked_against_its_runtime():
    native = _spec(
        runtime=RuntimeSpec(backend="rlm"),
        agents=(AgentSpec(id="rlm", role="analysis", tools=("python",)),),
    )
    assert _check(detect_drift(native), "tools").status == DRIFT_OK
    invalid = _spec(
        runtime=RuntimeSpec(backend="rlm"),
        agents=(AgentSpec(id="rlm", role="analysis", tools=("python", "bash")),),
    )
    assert _check(detect_drift(invalid), "tools").status == DRIFT_DRIFT


@pytest.mark.parametrize(
    "statuses, complete, has_drift",
    [
        ([DRIFT_OK], True, False),
        ([DRIFT_UNKNOWN], False, False),
        ([DRIFT_OK, DRIFT_UNKNOWN], False, False),
        ([DRIFT_DRIFT], True, True),
        ([DRIFT_DRIFT, DRIFT_UNKNOWN], False, True),
        ([], False, False),
    ],
)
def test_summary_distinguishes_unknown_from_verified(statuses, complete, has_drift):
    checks = tuple(
        DriftCheck(f"check-{i}", status, "declared", "observed")
        for i, status in enumerate(statuses)
    )
    status = DRIFT_DRIFT if has_drift else DRIFT_UNKNOWN if not complete else DRIFT_OK
    report = DriftReport("probe", status, checks)
    payload = report.to_dict()
    assert payload["complete"] is complete
    assert payload["has_drift"] is has_drift
    assert payload["clean"] is (complete and not has_drift)
    assert payload["verification"] == "static"
    if not complete:
        assert "Every declaration matches" not in render_drift(report)
        assert "Verification incomplete" in render_drift(report)


@pytest.mark.parametrize("backend", ["rlm", "pipy", "tau", "deepagents"])
def test_harness_only_backends_are_recognized(monkeypatch, backend):
    from superqode.harness.backends import registry
    from superqode.harness.backends.base import HarnessBackendCapabilities

    monkeypatch.setattr(
        registry,
        "backend_capabilities",
        lambda name: HarnessBackendCapabilities(name, availability="available"),
    )
    check = _check(detect_drift(_spec(runtime=RuntimeSpec(backend=backend))), "runtime")
    assert check.status == DRIFT_OK
    assert check.observed == backend
    assert "Credentials and live behavior are not verified" in check.detail


def test_known_missing_backend_is_not_unknown(monkeypatch):
    from superqode.harness.backends import registry

    monkeypatch.setattr(registry, "_optional_module_available", lambda name: False)
    check = _check(detect_drift(_spec(runtime=RuntimeSpec(backend="deepagents"))), "runtime")
    assert check.status == DRIFT_DRIFT
    assert check.observed == "not installed"
    assert "Known backend deepagents" in check.detail


def test_backend_alias_resolves_without_false_drift(monkeypatch):
    from superqode.harness.backends import registry
    from superqode.harness.backends.dsh import DSH_BACKEND_ALIASES, DSH_BACKEND_NAME
    from superqode.harness.backends.base import HarnessBackendCapabilities

    monkeypatch.setattr(
        registry,
        "backend_capabilities",
        lambda name: HarnessBackendCapabilities(DSH_BACKEND_NAME, availability="available"),
    )
    alias = next(iter(DSH_BACKEND_ALIASES))
    check = _check(detect_drift(_spec(runtime=RuntimeSpec(backend=alias))), "runtime")
    assert check.status == DRIFT_OK
    assert check.observed == DSH_BACKEND_NAME


def test_failed_availability_probe_is_incomplete(monkeypatch):
    from superqode.harness.backends import registry

    def unavailable(name):
        raise RuntimeError("probe unavailable")

    monkeypatch.setattr(registry, "backend_capabilities", unavailable)
    report = detect_drift(_spec())
    assert _check(report, "runtime").status == DRIFT_UNKNOWN
    assert report.to_dict()["clean"] is False


@pytest.mark.parametrize("strict, expected_exit", [(False, 0), (True, 2)])
def test_cli_preserves_default_exit_and_can_require_complete(
    monkeypatch, tmp_path, strict, expected_exit
):
    import superqode.harness.drift as drift

    spec_path = tmp_path / "unknown.yaml"
    spec_path.write_text("version: 1\nname: unknown\n")
    report = DriftReport(
        "unknown", DRIFT_UNKNOWN, (DriftCheck("runtime", DRIFT_UNKNOWN, "builtin", "unobserved"),)
    )
    monkeypatch.setattr(drift, "detect_drift", lambda spec: report)
    args = ["drift", "--spec", str(spec_path), "--json"] + (
        ["--require-complete"] if strict else []
    )
    result = CliRunner().invoke(harness, args)
    assert result.exit_code == expected_exit, result.output
    assert json.loads(result.output)["complete"] is False


def test_unrecognized_report_status_never_claims_complete():
    report = DriftReport(
        "skipped", "skipped", (DriftCheck("runtime", DRIFT_OK, "builtin", "builtin"),)
    )
    assert report.complete is False
    assert report.to_dict()["clean"] is False
