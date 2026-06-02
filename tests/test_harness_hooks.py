"""Tests for HarnessSpec -> HookRegistry wiring and store forwarders."""

from __future__ import annotations

import pytest

from superqode.agent.hooks import (
    AFTER_COMPACT,
    BEFORE_COMPACT,
    BEFORE_TOOL_CALL,
    DENY,
    PERMISSION_REQUEST,
    SESSION_START,
    STOP,
    USER_PROMPT_SUBMIT,
    HookDecision,
    LifecycleContext,
)
from superqode.harness import (
    HarnessSpec,
    HookRuleSpec,
    HooksSpec,
    build_hook_registry,
    harness_spec_from_dict,
    harness_spec_to_dict,
)
from superqode.harness.events import HarnessEvent


# ---------------------------------------------------------------------------
# Module-level handlers referenced by dotted path in specs
# ---------------------------------------------------------------------------


def deny_bash(ctx, name, arguments):
    return HookDecision(action=DENY, message="bash is blocked by policy")


def allow_all(ctx, name, arguments):
    return True


# ---------------------------------------------------------------------------
# Loader round-trip
# ---------------------------------------------------------------------------


def test_hooks_loaded_from_dict():
    spec = harness_spec_from_dict(
        {
            "name": "h",
            "hooks": {
                "enabled": True,
                "rules": [
                    {
                        "point": "permission_request",
                        "handler": "test_harness_hooks:deny_bash",
                        "matcher": "bash",
                        "name": "block-bash",
                    }
                ],
            },
        }
    )
    assert spec.hooks.enabled is True
    assert len(spec.hooks.rules) == 1
    rule = spec.hooks.rules[0]
    assert rule.point == "permission_request"
    assert rule.matcher == "bash"
    assert rule.name == "block-bash"


def test_hooks_round_trip_serialization():
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(
            rules=(
                HookRuleSpec(
                    point="before_tool_call",
                    handler="pkg.mod:fn",
                    matcher="write_*",
                    name="r1",
                ),
            )
        ),
    )
    data = harness_spec_to_dict(spec)
    assert data["hooks"]["rules"][0]["handler"] == "pkg.mod:fn"
    rebuilt = harness_spec_from_dict(data)
    assert rebuilt.hooks.rules == spec.hooks.rules


def test_hook_rule_requires_point_and_handler():
    with pytest.raises(ValueError):
        harness_spec_from_dict({"name": "h", "hooks": {"rules": [{"handler": "x:y"}]}})
    with pytest.raises(ValueError):
        harness_spec_from_dict({"name": "h", "hooks": {"rules": [{"point": "stop"}]}})


def test_hooks_omitted_when_default():
    data = harness_spec_to_dict(HarnessSpec(name="h"))
    assert "hooks" not in data


# ---------------------------------------------------------------------------
# Registry building
# ---------------------------------------------------------------------------


def test_build_registry_registers_declared_rule():
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(
            rules=(
                HookRuleSpec(
                    point=PERMISSION_REQUEST,
                    handler="test_harness_hooks:deny_bash",
                    matcher="bash",
                ),
            )
        ),
    )
    registry, errors = build_hook_registry(spec)
    assert errors == []
    assert registry.has_hooks(PERMISSION_REQUEST)


def test_build_registry_collects_resolution_errors():
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(rules=(HookRuleSpec(point=STOP, handler="no.such.module:fn"),)),
    )
    registry, errors = build_hook_registry(spec)
    assert len(errors) == 1
    assert errors[0][0].handler == "no.such.module:fn"


def test_disabled_hooks_not_registered():
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(
            enabled=False,
            rules=(
                HookRuleSpec(
                    point=PERMISSION_REQUEST,
                    handler="test_harness_hooks:allow_all",
                ),
            ),
        ),
    )
    registry, errors = build_hook_registry(spec)
    assert errors == []
    assert registry.has_hooks(PERMISSION_REQUEST) is False


@pytest.mark.asyncio
async def test_matcher_gates_by_tool_name():
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(
            rules=(
                HookRuleSpec(
                    point=PERMISSION_REQUEST,
                    handler="test_harness_hooks:deny_bash",
                    matcher="bash",
                ),
            )
        ),
    )
    registry, _ = build_hook_registry(spec)
    ctx = LifecycleContext(session_id="s", provider="p", model="m", working_directory=".")

    # Matching tool -> deny fires.
    denied = await registry.fire_decision(PERMISSION_REQUEST, ctx, "bash", {})
    assert denied.denied

    # Non-matching tool -> handler abstains, outcome is continue.
    other = await registry.fire_decision(PERMISSION_REQUEST, ctx, "read_file", {})
    assert not other.denied


# ---------------------------------------------------------------------------
# Store forwarders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_forwarders_emit_events():
    sink: list[HarnessEvent] = []
    spec = HarnessSpec(name="h")
    registry, _ = build_hook_registry(spec, event_sink=sink, session_id="sess-1")
    ctx = LifecycleContext(session_id="sess-1", provider="p", model="m", working_directory=".")

    await registry.fire(SESSION_START, ctx, "hello")
    await registry.fire_decision(USER_PROMPT_SUBMIT, ctx, "hello")
    await registry.fire_decision(
        PERMISSION_REQUEST,
        ctx,
        "bash",
        {"command": "ls", "api_key": "sk-secret", "token": "abc"},
    )
    await registry.fire_decision(BEFORE_COMPACT, ctx, 5000, 4000)
    await registry.fire(AFTER_COMPACT, ctx, 5000, [1, 2, 3], "summary")

    types = [e.type for e in sink]
    assert "harness.session.start" in types
    assert "harness.prompt.submit" in types
    assert "harness.permission.check" in types
    assert "harness.compaction.start" in types
    assert "harness.compaction.end" in types

    approval = next(e for e in sink if e.type == "harness.permission.check")
    assert approval.data["tool"] == "bash"
    assert approval.session_id == "sess-1"
    assert approval.data["arguments"]["keys"] == ["api_key", "command", "token"]
    assert approval.data["arguments"]["preview"]["command"] == "ls"
    assert approval.data["arguments"]["preview"]["api_key"] == "[redacted]"
    assert approval.data["arguments"]["preview"]["token"] == "[redacted]"

    compact_end = next(e for e in sink if e.type == "harness.compaction.end")
    assert compact_end.data["strategy"] == "summary"
    assert compact_end.data["message_count"] == 3


def test_build_registry_emits_hook_resolution_errors_to_store():
    sink: list[HarnessEvent] = []
    spec = HarnessSpec(
        name="h",
        hooks=HooksSpec(rules=(HookRuleSpec(point=STOP, handler="no.such.module:fn", name="bad"),)),
    )
    _registry, errors = build_hook_registry(spec, event_sink=sink, session_id="sess-1")
    assert len(errors) == 1
    event = next(e for e in sink if e.type == "harness.hook.error")
    assert event.session_id == "sess-1"
    assert event.data["name"] == "bad"
    assert event.data["handler"] == "no.such.module:fn"


@pytest.mark.asyncio
async def test_forwarders_abstain_and_dont_change_decisions():
    """Store forwarders must never affect a decision outcome."""
    sink: list[HarnessEvent] = []
    spec = HarnessSpec(name="h")
    registry, _ = build_hook_registry(spec, event_sink=sink)
    ctx = LifecycleContext(session_id="s", provider="p", model="m", working_directory=".")
    outcome = await registry.fire_decision(PERMISSION_REQUEST, ctx, "bash", {})
    assert not outcome.denied and not outcome.allowed
    # forwarder still recorded the event
    assert any(e.type == "harness.permission.check" for e in sink)
