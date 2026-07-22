from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from superqode.governance import (
    ContextualPolicyEngine,
    ContextualPolicyRule,
    CredentialBinding,
    CredentialBroker,
    GovernanceBundle,
    PolicyLayer,
    PolicyRequest,
    governance_scope,
    load_governance,
)
from superqode.main import cli_main
from superqode.tools.base import Tool, ToolContext, ToolResult
from superqode.tools.env_policy import build_shell_env
from superqode.tools.governed import execute_governed_tool


class _RecordingFetch(Tool):
    def __init__(self) -> None:
        self.arguments = {}

    @property
    def name(self) -> str:
        return "fetch"

    @property
    def description(self) -> str:
        return "record a fetch"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, args, ctx):
        self.arguments = dict(args)
        return ToolResult(success=True, output="ok")


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="test", working_directory=tmp_path)


def test_layered_policy_uses_deny_overrides_and_keeps_trace():
    engine = ContextualPolicyEngine(
        (
            PolicyLayer(
                "organization",
                "/org/policy.yaml",
                rules=(
                    ContextualPolicyRule(
                        "deny-high-risk",
                        "deny",
                        risks=("high",),
                        message="organization blocks high-risk tools",
                    ),
                ),
            ),
            PolicyLayer(
                "project",
                "/repo/.superqode/policy.yaml",
                rules=(ContextualPolicyRule("allow-bash", "allow", tools=("bash",)),),
            ),
        )
    )

    decision = engine.evaluate(PolicyRequest(phase="tool_call", tool="bash", risk="high"))

    assert decision.action == "deny"
    assert decision.reason == "organization blocks high-risk tools"
    assert [item.layer for item in decision.matches] == ["organization", "project"]


def test_project_policy_loads_rules_guardrails_and_redacted_bindings(tmp_path, monkeypatch):
    policy_path = tmp_path / ".superqode" / "policy.yaml"
    policy_path.parent.mkdir()
    policy_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "guardrails": {
                    "shell_env": "filter-secrets",
                    "network_strict": True,
                },
                "rules": [
                    {
                        "id": "github-only",
                        "phase": "tool_call",
                        "action": "allow",
                        "tools": ["fetch"],
                        "hosts": ["api.github.com"],
                    }
                ],
                "credentials": {
                    "github": {
                        "source": "env:GITHUB_TOKEN",
                        "hosts": ["api.github.com"],
                    }
                },
            },
            sort_keys=False,
        )
    )
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")

    bundle = load_governance(tmp_path)
    public = bundle.to_public_dict()

    assert bundle.network_strict
    assert bundle.shell_env == "filter-secrets"
    assert public["credentials"]["bindings"][0]["source"] == "env:<redacted>"
    assert "secret-value" not in json.dumps(public)


@pytest.mark.asyncio
async def test_credential_broker_injects_only_for_bound_host_and_never_returns_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    broker = CredentialBroker(
        (
            CredentialBinding(
                "github",
                "env:GITHUB_TOKEN",
                ("api.github.com",),
            ),
        )
    )
    bundle = GovernanceBundle(ContextualPolicyEngine(), broker)
    tool = _RecordingFetch()

    with governance_scope(bundle):
        result = await execute_governed_tool(
            tool,
            {"url": "https://api.github.com/user", "credential": "github"},
            _context(tmp_path),
        )

    assert result.success
    assert tool.arguments["headers"]["Authorization"] == "Bearer secret-value"
    assert "secret-value" not in json.dumps(result.metadata)
    assert result.metadata["governance"]["credential"]["credential"] == "github"

    with governance_scope(bundle):
        denied = await execute_governed_tool(
            tool,
            {"url": "https://example.com", "credential": "github"},
            _context(tmp_path),
        )
    assert not denied.success
    assert "not permitted" in denied.error


@pytest.mark.asyncio
async def test_governance_blocks_model_supplied_authorization_header(tmp_path):
    bundle = GovernanceBundle(ContextualPolicyEngine(), CredentialBroker())
    with governance_scope(bundle):
        result = await execute_governed_tool(
            _RecordingFetch(),
            {
                "url": "https://api.example.com",
                "headers": {"Authorization": "Bearer visible-to-model"},
            },
            _context(tmp_path),
        )

    assert not result.success
    assert "named SuperQode credential binding" in result.error


def test_governed_shell_environment_filters_secrets_without_global_env_mutation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PATH", "/bin")
    bundle = GovernanceBundle(
        ContextualPolicyEngine(), CredentialBroker(), shell_env="filter-secrets"
    )

    with governance_scope(bundle):
        filtered = build_shell_env()

    assert "OPENAI_API_KEY" not in filtered
    assert filtered["PATH"] == "/bin"
    assert build_shell_env() is None


def test_policy_cli_initializes_and_explains_without_executing(tmp_path):
    runner = CliRunner()
    initialized = runner.invoke(
        cli_main,
        ["policy", "init", "--repo", str(tmp_path)],
    )
    explained = runner.invoke(
        cli_main,
        [
            "policy",
            "explain",
            "tool_call",
            "--repo",
            str(tmp_path),
            "--tool",
            "bash",
            "--risk",
            "critical",
            "--json",
        ],
    )

    assert initialized.exit_code == 0, initialized.output
    assert (tmp_path / ".superqode" / "policy.yaml").is_file()
    assert explained.exit_code == 0, explained.output
    assert json.loads(explained.output)["decision"]["action"] == "deny"
