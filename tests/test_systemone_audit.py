from superqode.systemone.audit import disagreement_report
from superqode.systemone.config import resolve_systemone


def test_report_does_not_treat_policy_as_human_label():
    events = [
        {
            "intendedAction": "allow",
            "policyAction": "deny",
            "evaluation": {"status": "success", "latency_ms": 10},
        },
        {
            "intendedAction": "ask",
            "policyAction": "allow",
            "humanAction": "allow",
            "evaluation": {"status": "success"},
        },
        {"evaluation": {"status": "error"}},
    ]
    policy = disagreement_report(events)
    assert policy["disagreements"] == 2
    assert policy["allow_against_deny"] == 1
    assert policy["errors"] == 1
    human = disagreement_report(events, "humanAction")
    assert human["labelled"] == human["unlabelled"] == 1
    assert human["allow_against_deny"] == 0


def test_mode_env_validation():
    import pytest

    assert resolve_systemone(environ={"SUPERQODE_SYSTEMONE_MODE": "shadow"}).mode == "shadow"
    with pytest.raises(ValueError):
        resolve_systemone(environ={"SUPERQODE_SYSTEMONE_MODE": "typo"})


def test_shadow_spec_round_trip_and_relative_trace_path(tmp_path):
    from superqode.harness.loader import harness_spec_to_dict, load_harness_spec

    path = tmp_path / "shadow.yaml"
    path.write_text(
        "name: shadow\nsystemone:\n  enabled: true\n  mode: shadow\n  trace_dir: traces\n"
    )
    spec = load_harness_spec(path)
    payload = harness_spec_to_dict(spec)
    assert spec.systemone.mode == payload["systemone"]["mode"] == "shadow"
    assert spec.systemone.trace_dir == str(tmp_path / "traces")


def test_report_cli(tmp_path):
    import json
    from click.testing import CliRunner
    from superqode.commands.harness.systemone import harness_decision_report

    (tmp_path / "trace.json").write_text(
        json.dumps(
            {"intendedAction": "deny", "policyAction": "allow", "evaluation": {"status": "success"}}
        )
    )
    result = CliRunner().invoke(harness_decision_report, [str(tmp_path)])
    assert result.exit_code == 0
    assert json.loads(result.output)["deny_against_allow"] == 1


def test_near_ties_and_confidence_sweep():
    from superqode.systemone.audit import confidence_sweep, distribution_diagnostics
    from superqode.systemone.pack import ToolGateThresholds

    diagnostics = distribution_diagnostics({"allow": 0.49, "deny": 0.48, "ask": 0.03})
    assert abs(diagnostics["top_two_margin"] - 0.01) < 1e-10
    assert diagnostics["entropy"] > 0
    answers = {
        key: {"noul": value}
        for key, value in {
            "in_grant": 0.95,
            "args_plausible": 0.95,
            "on_task": 0.95,
            "destructive": 0.01,
            "exfil_risk": 0.01,
        }.items()
    }
    answers["disposition"] = {
        "choice": "allow",
        "confidence": 0.85,
        "probabilities": {"allow": 0.9, "deny": 0.05, "ask": 0.05},
    }
    event = {
        "answers": answers,
        "thresholds": ToolGateThresholds().model_dump(),
        "confidence": 0.85,
        "intendedAction": "allow",
        "humanAction": "deny",
        "evaluation": {"status": "success"},
    }
    reports = confidence_sweep([event], (0.75, 0.9), "humanAction")
    assert reports[0]["allow_against_deny"] == 1
    assert reports[1]["allow_against_deny"] == 0
    assert reports[1]["ask_rate"] == 1
    assert event["intendedAction"] == "allow"
