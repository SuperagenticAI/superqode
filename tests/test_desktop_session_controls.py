from dataclasses import replace

import pytest

from superqode.harness.compiler import compile_to_headless_profile
from superqode.harness.spec import ExecutionPolicySpec, HarnessSpec
from superqode.harness.templates import core_template
from superqode.tools.permissions import Permission, ToolGroup

from test_desktop_service import desktop  # noqa: F401

from superqode.desktop_service.session_controls import (
    accept,
    apply_controls,
    enforces_session_controls,
)


def test_missing_permission_mode_leaves_the_spec_unchanged():
    spec = core_template()
    params = {"interaction_mode": "code"}
    accept(params)
    assert "permission_mode" not in params
    assert apply_controls(spec, params) is spec


def test_ask_requires_approval_for_writes_and_keeps_network_closed():
    spec = apply_controls(core_template(), {"interaction_mode": "code", "permission_mode": "ask"})
    profile = compile_to_headless_profile(spec)
    assert profile.permissions.get_permission("read") is Permission.ALLOW
    assert profile.permissions.get_permission("write") is Permission.ASK
    assert profile.permissions.get_permission("bash") is Permission.ASK
    assert profile.permissions.groups[ToolGroup.NETWORK] is Permission.DENY


def test_auto_edit_allows_writes_and_still_asks_for_shell():
    spec = apply_controls(
        core_template(), {"interaction_mode": "code", "permission_mode": "auto-edit"}
    )
    profile = compile_to_headless_profile(spec)
    assert profile.permissions.get_permission("edit") is Permission.ALLOW
    assert profile.permissions.get_permission("bash") is Permission.ASK


def test_plan_mode_closes_writes_even_when_full_is_requested():
    spec = apply_controls(core_template(), {"interaction_mode": "plan", "permission_mode": "full"})
    profile = compile_to_headless_profile(spec)
    assert profile.permissions.groups[ToolGroup.WRITE] is Permission.DENY
    assert profile.permissions.groups[ToolGroup.SHELL] is Permission.DENY
    assert spec.agents[0].tools == ("read",)
    assert "Plan mode is active" in spec.agents[0].system_prompt


def test_closed_spec_gate_cannot_be_reopened_by_full():
    spec = replace(
        core_template(),
        execution_policy=ExecutionPolicySpec(
            allow_read=True, allow_write=False, allow_shell=False, allow_network=False
        ),
    )
    overlaid = apply_controls(spec, {"interaction_mode": "code", "permission_mode": "full"})
    profile = compile_to_headless_profile(overlaid)
    assert profile.permissions.groups[ToolGroup.WRITE] is Permission.DENY
    assert profile.permissions.groups[ToolGroup.SHELL] is Permission.DENY


def test_unknown_controls_are_rejected_before_a_job_starts():
    with pytest.raises(ValueError, match="Code, Plan, or Chat"):
        accept({"interaction_mode": "yolo"})
    with pytest.raises(ValueError, match="Ask, Auto-edit, or Full"):
        accept({"permission_mode": "host"})


def test_ask_and_plan_are_refused_when_the_backend_cannot_enforce_them(desktop):
    service, project, _ = desktop
    assert enforces_session_controls("builtin") is True
    assert enforces_session_controls("openai-agents") is True
    assert enforces_session_controls("pydanticai") is True
    assert enforces_session_controls("pipy") is False
    assert enforces_session_controls("deepseek-harness") is False
    assert enforces_session_controls("codegem") is False
    assert enforces_session_controls("") is False
    before = service._all("SELECT id FROM jobs")
    for harness in ("pipy", "deepseek-harness"):
        with pytest.raises(ValueError, match="can enforce it"):
            service.dispatch(
                "tasks.start",
                {
                    "project": project["id"],
                    "harness": harness,
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "prompt": "Write hello.txt",
                    "interaction_mode": "plan",
                    "command_id": "plan-" + harness,
                },
            )
        with pytest.raises(ValueError, match="own permissions"):
            service.dispatch(
                "tasks.start",
                {
                    "project": project["id"],
                    "harness": harness,
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "prompt": "Write hello.txt",
                    "interaction_mode": "code",
                    "permission_mode": "ask",
                    "command_id": "ask-" + harness,
                },
            )
    assert service._all("SELECT id FROM jobs") == before
    rows = {
        row["id"]: row for row in service.dispatch("harnesses.list", {"project": project["id"]})
    }
    assert rows["core"]["enforces_session_controls"] is True
    assert rows["workbench"]["enforces_session_controls"] is True
    assert rows["pipy"]["enforces_session_controls"] is False
    assert rows["deepseek-harness"]["enforces_session_controls"] is False


def test_group_permissions_do_not_change_a_spec_that_never_set_them():
    profile = compile_to_headless_profile(HarnessSpec(name="plain"))
    assert profile.permissions.default is Permission.ALLOW
    # Closed spec gates still deny. A missing overlay does not add Ask rules.
    assert profile.permissions.groups[ToolGroup.WRITE] is Permission.DENY
    assert profile.permissions.groups[ToolGroup.SHELL] is Permission.DENY
    assert profile.permissions.groups[ToolGroup.NETWORK] is Permission.DENY
    assert ToolGroup.READ not in profile.permissions.groups
