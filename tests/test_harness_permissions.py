"""Tests for rule-based approval policy on the permission_request seam."""

from __future__ import annotations

import pytest

from superqode.agent.hooks import LifecycleContext, PERMISSION_REQUEST
from superqode.harness import (
    ContextSpec,
    HarnessSpec,
    PermissionRuleSpec,
    build_hook_registry,
    evaluate_permission_rules,
    harness_spec_from_dict,
    harness_spec_to_dict,
    remember_approval_decision,
    rule_matches,
)
from superqode.harness.permissions import build_permission_handler
from superqode.harness.spec import ExecutionPolicySpec


def _ctx():
    return LifecycleContext(session_id="s", provider="p", model="m", working_directory=".")


# ---------------------------------------------------------------------------
# Matching + evaluation
# ---------------------------------------------------------------------------


def test_tool_only_rule_matches_any_call():
    rule = PermissionRuleSpec(tool="read_file", action="allow")
    assert rule_matches(rule, "read_file", {"path": "a"})
    assert not rule_matches(rule, "write_file", {"path": "a"})


def test_tool_glob_matches():
    rule = PermissionRuleSpec(tool="write_*", action="deny")
    assert rule_matches(rule, "write_file", {})
    assert not rule_matches(rule, "read_file", {})


def test_argument_pattern_matches_named_arg():
    rule = PermissionRuleSpec(tool="bash", argument="command", pattern="git *", action="allow")
    assert rule_matches(rule, "bash", {"command": "git status"})
    assert not rule_matches(rule, "bash", {"command": "rm -rf /"})


def test_argument_pattern_against_any_value():
    rule = PermissionRuleSpec(tool="bash", pattern="*secret*", action="deny")
    assert rule_matches(rule, "bash", {"command": "echo my-secret-token"})
    assert not rule_matches(rule, "bash", {"command": "ls"})


def test_argument_scoped_rule_skips_absent_argument():
    rule = PermissionRuleSpec(tool="bash", argument="command", pattern="*", action="allow")
    assert not rule_matches(rule, "bash", {})


def test_first_match_wins_ordering():
    rules = [
        PermissionRuleSpec(tool="bash", argument="command", pattern="git *", action="allow"),
        PermissionRuleSpec(tool="bash", action="deny"),
    ]
    # git command hits the allow rule first
    assert evaluate_permission_rules(rules, "bash", {"command": "git log"}).action == "allow"
    # everything else falls to the catch-all deny
    assert evaluate_permission_rules(rules, "bash", {"command": "curl x"}).action == "deny"


def test_no_match_returns_none():
    rules = [PermissionRuleSpec(tool="bash", action="deny")]
    assert evaluate_permission_rules(rules, "read_file", {"path": "x"}) is None


# ---------------------------------------------------------------------------
# Handler behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_allow_deny_ask_abstain():
    handler = build_permission_handler(
        [
            PermissionRuleSpec(tool="read_file", action="allow"),
            PermissionRuleSpec(tool="bash", argument="command", pattern="rm *", action="deny"),
            PermissionRuleSpec(tool="write_file", action="ask"),
        ]
    )
    allow = handler(_ctx(), "read_file", {"path": "a"})
    assert allow is not None and allow.action == "allow"

    deny = handler(_ctx(), "bash", {"command": "rm -rf build"})
    assert deny is not None and deny.action == "deny"

    # ask -> abstain so the human prompt still runs
    assert handler(_ctx(), "write_file", {"path": "x"}) is None
    # no match -> abstain
    assert handler(_ctx(), "glob", {"pattern": "*"}) is None


# ---------------------------------------------------------------------------
# Registry wiring + deny-precedence composition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_registered_when_rules_present():
    spec = HarnessSpec(
        name="h",
        execution_policy=ExecutionPolicySpec(
            permission_rules=(PermissionRuleSpec(tool="bash", action="deny"),)
        ),
    )
    registry, errors = build_hook_registry(spec)
    assert errors == []
    assert "harness_permission_policy" in registry.list_hooks(PERMISSION_REQUEST)

    denied = await registry.fire_decision(PERMISSION_REQUEST, _ctx(), "bash", {"command": "ls"})
    assert denied.denied
    allowed_passthrough = await registry.fire_decision(
        PERMISSION_REQUEST, _ctx(), "read_file", {"path": "a"}
    )
    assert not allowed_passthrough.denied and not allowed_passthrough.allowed


def test_no_policy_without_rules():
    spec = HarnessSpec(name="h")
    registry, _ = build_hook_registry(spec)
    assert "harness_permission_policy" not in registry.list_hooks(PERMISSION_REQUEST)


# ---------------------------------------------------------------------------
# Loader round-trip
# ---------------------------------------------------------------------------


def test_permission_rules_loaded_and_round_trip():
    spec = harness_spec_from_dict(
        {
            "name": "h",
            "execution_policy": {
                "permission_rules": [
                    {"tool": "bash", "argument": "command", "pattern": "git *", "action": "allow"},
                    {"tool": "write_*", "action": "deny"},
                ]
            },
        }
    )
    rules = spec.execution_policy.permission_rules
    assert len(rules) == 2
    assert rules[0].action == "allow"
    assert rules[1].tool == "write_*"

    data = harness_spec_to_dict(spec)
    assert data["execution_policy"]["permission_rules"][0]["pattern"] == "git *"
    rebuilt = harness_spec_from_dict(data)
    assert rebuilt.execution_policy.permission_rules == rules


def test_invalid_action_rejected():
    with pytest.raises(ValueError):
        harness_spec_from_dict(
            {
                "name": "h",
                "execution_policy": {"permission_rules": [{"tool": "bash", "action": "maybe"}]},
            }
        )


def test_remembered_approval_rules_load_into_permission_policy(tmp_path):
    spec = HarnessSpec(
        name="h",
        context=ContextSpec(session_storage=str(tmp_path)),
    )
    remember_approval_decision(
        spec,
        tool_name="bash",
        arguments={"command": "git status"},
        action="allow",
    )
    registry, errors = build_hook_registry(spec)
    assert errors == []
    assert "harness_permission_policy" in registry.list_hooks(PERMISSION_REQUEST)


@pytest.mark.asyncio
async def test_remembered_approval_rule_allows_exact_future_call(tmp_path):
    spec = HarnessSpec(name="h", context=ContextSpec(session_storage=str(tmp_path)))
    remember_approval_decision(
        spec,
        tool_name="bash",
        arguments={"command": "git *"},
        action="allow",
    )
    registry, _ = build_hook_registry(spec)
    exact = await registry.fire_decision(PERMISSION_REQUEST, _ctx(), "bash", {"command": "git *"})
    assert exact.allowed
    # Remembered decisions escape glob metacharacters, so this does not broaden
    # to every git command.
    other = await registry.fire_decision(
        PERMISSION_REQUEST, _ctx(), "bash", {"command": "git status"}
    )
    assert not other.allowed and not other.denied


# ---------------------------------------------------------------------------
# doctor / inspect visibility
# ---------------------------------------------------------------------------


def _spec_with_rules_and_hooks():
    from superqode.harness import HookRuleSpec, HooksSpec

    return HarnessSpec(
        name="coding",
        execution_policy=ExecutionPolicySpec(
            allow_read=True,
            allow_write=True,
            allow_shell=True,
            permission_rules=(
                PermissionRuleSpec(
                    tool="bash", argument="command", pattern="git *", action="allow"
                ),
                PermissionRuleSpec(tool="bash", action="deny"),
            ),
        ),
        hooks=HooksSpec(
            rules=(
                HookRuleSpec(
                    point="before_tool_call",
                    handler="test_harness_hooks:deny_bash",
                    matcher="write_*",
                    name="audit",
                ),
            )
        ),
    )


def test_inspect_summary_includes_rules_and_hooks():
    from superqode.harness.diagnostics import inspect_harness

    summary = inspect_harness(_spec_with_rules_and_hooks())
    assert len(summary["permissions"]["rules"]) == 2
    assert summary["permissions"]["rules"][0]["action"] == "allow"
    hooks = summary["hooks"]
    assert hooks["enabled"] is True
    # one declared hook + the built-in permission policy
    assert hooks["count"] == 2
    assert any(b["handler"] == "harness_permission_policy" for b in hooks["builtin"])
    assert any(d["name"] == "audit" for d in hooks["declared"])


def test_render_inspect_shows_rules_and_hooks():
    from superqode.harness.diagnostics import inspect_harness, render_harness_inspect

    text = render_harness_inspect(inspect_harness(_spec_with_rules_and_hooks()))
    assert "Permission rules (2):" in text
    assert "bash command~'git *' -> allow" in text
    assert "Hooks (2):" in text
    assert "harness_permission_policy" in text
    assert "before_tool_call" in text


def test_doctor_hooks_check_passes_for_resolvable_handlers():
    from superqode.harness.diagnostics import doctor_harness

    report = doctor_harness(_spec_with_rules_and_hooks())
    hooks_check = next(c for c in report.checks if c.name == "hooks")
    assert hooks_check.status == "ok"
    assert hooks_check.data["resolved"] == 1
    assert "harness_permission_policy" in hooks_check.data["builtin"]


def test_doctor_hooks_check_errors_on_bad_handler():
    from superqode.harness import HookRuleSpec, HooksSpec
    from superqode.harness.diagnostics import doctor_harness

    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(rules=(HookRuleSpec(point="stop", handler="no.such.module:fn"),)),
    )
    report = doctor_harness(spec)
    hooks_check = next(c for c in report.checks if c.name == "hooks")
    assert hooks_check.status == "error"
    assert report.status == "error"
    assert hooks_check.data["errors"]


def test_doctor_hooks_check_warns_when_disabled_with_rules():
    from superqode.harness import HookRuleSpec, HooksSpec
    from superqode.harness.diagnostics import doctor_harness

    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(
            enabled=False,
            rules=(HookRuleSpec(point="stop", handler="test_harness_hooks:deny_bash"),),
        ),
    )
    report = doctor_harness(spec)
    hooks_check = next(c for c in report.checks if c.name == "hooks")
    assert hooks_check.status == "warning"
