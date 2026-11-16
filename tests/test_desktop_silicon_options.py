"""Harness Studio Silicon toggles: draft edits, diffs and YAML round-trips."""

import json

import pytest
import yaml

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import silicon_options
from superqode.harness.loader import harness_spec_from_dict

IMAGE = "docker.io/library/python@sha256:" + "a" * 64


@pytest.fixture
def silicon(desktop, monkeypatch):  # noqa: F811
    service, project, root = desktop
    (root / ".superqode").mkdir(exist_ok=True)
    (root / ".superqode" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"docs_local": {"command": "docs-server"}}})
    )
    monkeypatch.setattr(
        silicon_options, "container_support", lambda: {"available": True, "reason": ""}
    )
    monkeypatch.setattr(silicon_options, "monty_support", lambda: {"available": True, "reason": ""})
    draft = service.dispatch("studio.open", {"project": project["id"], "reference": "silicon"})
    return service, project["id"], draft


def apply(service, project, text, options):
    return service.dispatch(
        "studio.silicon.apply",
        {"project": project, "name": "my-silicon", "yaml": text, "options": options},
    )


MCP_ON = {"enabled": True, "allowlist": {"docs_local": ["lookup"]}}


def test_reads_defaults_and_lists_configured_servers(silicon):
    service, project, draft = silicon
    state = service.dispatch("studio.silicon.options", {"project": project, "yaml": draft["yaml"]})
    assert state["tools"] == ["read", "search", "edit", "write"]
    assert state["tool_count"] == 4 and state["tool_limit"] == 5
    assert state["mcp"]["enabled"] is False
    assert [row["id"] for row in state["mcp"]["servers"]] == ["docs_local"]
    assert state["code_mode"] is False and state["checks"]["steps"] == []


def test_rejects_non_silicon_drafts(silicon):
    service, project, _ = silicon
    core = service.dispatch("studio.open", {"project": project, "reference": "core"})
    with pytest.raises(ValueError, match="Silicon"):
        service.dispatch("studio.silicon.options", {"project": project, "yaml": core["yaml"]})


def test_mcp_and_code_mode_write_the_documented_keys(silicon):
    service, project, draft = silicon
    result = apply(service, project, draft["yaml"], {"mcp": MCP_ON, "code_mode": True})
    data = yaml.safe_load(result["yaml"])
    assert data["agents"][0]["tools"] == ["read", "search", "edit", "write", "execute"]
    assert data["runtime"]["config"]["silicon_mcp"] == {"docs_local": ["lookup"]}
    assert data["runtime"]["config"]["silicon_mcp_code"] is True
    assert data["execution_policy"]["allow_network"] is True
    assert data["execution_policy"]["permission_rules"] == [
        {"tool": "execute", "action": "allow"},
        {"tool": "mcp_docs_local_lookup", "action": "allow"},
    ]
    assert "+  - execute" in result["diff"] and result["changed"]
    assert result["state"]["tool_count"] == 5 and not result["state"]["warnings"]
    spec = harness_spec_from_dict(data)
    assert spec.runtime.config["silicon_mcp"] == {"docs_local": ["lookup"]}
    assert spec.execution_policy.allow_network


def test_turning_mcp_off_restores_the_original_draft(silicon):
    service, project, draft = silicon
    on = apply(service, project, draft["yaml"], {"mcp": MCP_ON, "code_mode": True})
    off = apply(service, project, on["yaml"], {"mcp": {"enabled": False}, "code_mode": False})
    assert yaml.safe_load(off["yaml"]) == yaml.safe_load(draft["yaml"])


def test_changing_allowlist_replaces_only_its_own_rules(silicon):
    service, project, draft = silicon
    data = yaml.safe_load(draft["yaml"])
    data["execution_policy"]["permission_rules"] = [{"tool": "read", "action": "allow"}]
    on = apply(service, project, yaml.safe_dump(data, sort_keys=False), {"mcp": MCP_ON})
    changed = apply(
        service,
        project,
        on["yaml"],
        {"mcp": {"enabled": True, "allowlist": {"docs_local": ["search_docs"]}}},
    )
    rules = yaml.safe_load(changed["yaml"])["execution_policy"]["permission_rules"]
    assert rules == [
        {"tool": "read", "action": "allow"},
        {"tool": "execute", "action": "allow"},
        {"tool": "mcp_docs_local_search_docs", "action": "allow"},
    ]


def test_code_mode_requires_mcp_and_unknown_servers_are_refused(silicon):
    service, project, draft = silicon
    with pytest.raises(ValueError, match="Turn on MCP"):
        apply(service, project, draft["yaml"], {"code_mode": True})
    with pytest.raises(ValueError, match="not configured"):
        apply(
            service,
            project,
            draft["yaml"],
            {"mcp": {"enabled": True, "allowlist": {"other": ["x"]}}},
        )
    with pytest.raises(ValueError, match="at least one tool"):
        apply(
            service,
            project,
            draft["yaml"],
            {"mcp": {"enabled": True, "allowlist": {"docs_local": []}}},
        )


def test_tool_budget_warning_when_execute_exceeds_five(silicon):
    service, project, draft = silicon
    data = yaml.safe_load(draft["yaml"])
    data["agents"][0]["tools"].append("glob")
    result = apply(service, project, yaml.safe_dump(data, sort_keys=False), {"mcp": MCP_ON})
    assert result["state"]["tool_count"] == 6
    assert any("at most 5" in warning for warning in result["state"]["warnings"])


def test_apple_container_check_round_trips_through_studio(silicon):
    service, project, draft = silicon
    added = apply(
        service,
        project,
        draft["yaml"],
        {"checks": {"add": [{"name": "Verify", "command": "python3 verify.py", "timeout": 60}]}},
    )
    result = apply(
        service,
        project,
        added["yaml"],
        {
            "checks": {
                "fail_on_error": True,
                "steps": [
                    {"index": 0, "apple_container": True, "image": IMAGE, "files": ["verify.py"]}
                ],
            }
        },
    )
    checks = yaml.safe_load(result["yaml"])["checks"]
    assert checks["enabled"] and checks["fail_on_error"]
    assert checks["custom_steps"][0]["apple_container"] == {"image": IMAGE, "files": ["verify.py"]}
    inspected = service.dispatch(
        "studio.inspect", {"project": project, "name": "my-silicon", "yaml": result["yaml"]}
    )
    again = yaml.safe_load(inspected["yaml"])["checks"]["custom_steps"][0]
    assert again["apple_container"] == {"image": IMAGE, "files": ["verify.py"]}
    state = service.dispatch(
        "studio.silicon.options", {"project": project, "yaml": inspected["yaml"]}
    )
    assert state["checks"]["steps"][0]["apple_container"] is True
    off = apply(
        service,
        project,
        inspected["yaml"],
        {"checks": {"steps": [{"index": 0, "apple_container": False}]}},
    )
    assert "apple_container" not in yaml.safe_load(off["yaml"])["checks"]["custom_steps"][0]


@pytest.mark.parametrize(
    "image, files, message",
    [
        ("python:3.12", ["verify.py"], "pinned by digest"),
        (IMAGE, ["../secret"], "project-relative"),
        (IMAGE, ["/etc/passwd"], "project-relative"),
        (IMAGE, ["a.py", "a.py"], "once"),
        (IMAGE, [], "between 1 and 64"),
    ],
)
def test_apple_container_inputs_are_validated(silicon, image, files, message):
    service, project, draft = silicon
    added = apply(
        service,
        project,
        draft["yaml"],
        {"checks": {"add": [{"name": "Verify", "command": "python3 verify.py"}]}},
    )
    with pytest.raises(ValueError, match=message):
        apply(
            service,
            project,
            added["yaml"],
            {
                "checks": {
                    "steps": [{"index": 0, "apple_container": True, "image": image, "files": files}]
                }
            },
        )


def test_unavailable_features_add_warnings(silicon, monkeypatch):
    service, project, draft = silicon
    monkeypatch.setattr(
        silicon_options, "monty_support", lambda: {"available": False, "reason": "missing"}
    )
    result = apply(service, project, draft["yaml"], {"mcp": MCP_ON, "code_mode": True})
    assert any("Monty is not installed" in warning for warning in result["state"]["warnings"])
