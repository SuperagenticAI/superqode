"""Billing and launch regressions for the account/model connection boundary."""

from types import SimpleNamespace

import pytest

from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
from superqode.providers.connection_profiles import get_connection_profile
from superqode.providers.credentials import provider_api_key
from superqode.providers.registry import PROVIDERS


class Log:
    def __init__(self):
        self.messages = []

    def add_info(self, message):
        self.messages.append(message)

    def add_error(self, message):
        self.messages.append(message)

    def write_feedback(self, value):
        self.messages.append(value.plain)


class AccountApp(ConnectMixin):
    def __init__(self):
        self.calls = []
        self.current_harness = "pipy"
        self.current_model = "existing-model"

    def _reset_connect_selection_states(self):
        pass

    def _open_connect_screen(self, log):
        pass

    def _connect_acp_cmd(self, agent, log):
        self._clear_acp_extra_env()
        self.calls.append(agent)


@pytest.mark.parametrize("profile", ["plan-zai", "plan-qwen"])
def test_unsupported_native_plan_preserves_current_model(profile):
    app = AccountApp()
    log = Log()
    app._dispatch_connection_profile(get_connection_profile(profile), log)
    assert app.current_harness == "pipy"
    assert app.current_model == "existing-model"
    assert app.calls == []
    assert any("kept" in message for message in log.messages)


@pytest.mark.parametrize("credential", [None, "ordinary-api-key"])
def test_minimax_plan_never_uses_general_or_global_api_key(monkeypatch, credential):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    monkeypatch.setenv("MINIMAX_API_KEY", "general-key")
    monkeypatch.setenv("OPENAI_API_KEY", "global-key")
    monkeypatch.delenv("MINIMAX_TOKEN_PLAN_API_KEY", raising=False)
    monkeypatch.setattr("superqode.providers.credentials.get_local_auth", lambda _: None)
    if credential:
        monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", credential)
    assert provider_api_key(PROVIDERS["minimax-token-plan"]) is None
    with pytest.raises(ValueError, match="subscription credential"):
        LiteLLMGateway()._apply_dynamic_provider("minimax-token-plan", {"api_key": "global-key"})


def test_minimax_plan_pairs_credential_and_endpoint(monkeypatch):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "sk-cp-test-plan")
    request = {"api_key": "general-key", "api_base": "https://wrong.example/v1"}
    LiteLLMGateway()._apply_dynamic_provider("minimax-token-plan", request)
    assert request == {"api_key": "sk-cp-test-plan", "api_base": "https://api.minimax.io/v1"}


@pytest.mark.parametrize("provider", ["minimax-token-plan", "anthropic"])
def test_missing_credentials_leave_existing_acp_session_intact(provider, monkeypatch):
    monkeypatch.setattr("superqode.providers.credentials.provider_api_key", lambda _: None)
    app = AccountApp()
    existing_client = object()
    app._acp_client = existing_client
    app._set_acp_extra_env({"FACTORY_API_KEY": "active-agent-key"}, "droid")
    app._redirect_harness_owned_provider_connect = lambda *args: False
    app._attach_key_harness_over_acp = lambda *args: False
    app._attach_key_harness_over_rpc = lambda *args: False
    app._connect_byok_mode(provider, "test-model", Log())
    assert app._acp_client is existing_client
    assert app._merge_acp_session_extra_env("droid") == {"FACTORY_API_KEY": "active-agent-key"}
    assert app.current_model == "existing-model"


def test_native_reconnect_restores_saved_harness_and_exact_local_route(monkeypatch):
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    app = AccountApp()
    selected = []
    app._pure_mode = SimpleNamespace(select_harness=selected.append)
    app._load_connection_config = lambda: {
        "category": "models",
        "auth_mode": "local",
        "harness_id": "pipy",
        "provider": "ollama",
        "model": "saved-local-model",
    }
    app._connect_byok_mode = lambda provider, model, log: app.calls.append((provider, model))
    app._connect_last(Log())
    assert selected == ["pipy"]
    assert app.calls == [("ollama", "saved-local-model")]
    import os

    assert os.environ["SUPERQODE_HARNESS"] == "pipy"


def test_account_model_picker_and_reconnect_restore_fast_agent_plan(monkeypatch):
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS
    from superqode.providers.harness_catalog import get_entry

    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda _: True)
    app = AccountApp()
    entry = get_entry("fast-agent")
    app._key_harness_session = KeyHarnessSession(
        entry_id=entry.id,
        openness=entry.openness,
        auth_spec=entry.auth[0],
        return_menu="open-harnesses",
        after_auth=entry.auth[0].after_auth,
    )
    app._connect_menu = CONNECT_MENU_KEY_MODELS
    profile = next(p for p in app._connect_menu_profiles() if p.connector == "harness-account")
    app._dispatch_connection_profile(profile, Log())
    assert app.calls == ["fast-agent"]
    assert app._acp_subscription_vendor == "codex"
    assert app._merge_acp_session_extra_env("fast-agent") == {"FAST_AGENT_MODEL": "codexplan"}
    assert app._merge_acp_session_extra_env("pi") == {}
    app._load_connection_config = lambda: {
        "category": "subscriptions",
        "auth_mode": "subscription",
        "profile_id": "account-fast-agent",
        "acp_agent": "fast-agent",
        "provider": "anthropic",
        "model": "stale-model",
    }
    app._connect_last(Log())
    assert app.calls == ["fast-agent", "fast-agent"]
    assert app._merge_acp_session_extra_env("fast-agent") == {"FAST_AGENT_MODEL": "codexplan"}


def test_missing_account_agent_installs_before_connect_and_resumes(monkeypatch):
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda _: False)
    app = AccountApp()
    callbacks = []
    app._show_agent_install_picker = lambda agent, log, on_ready: callbacks.append(on_ready) or True
    app._dispatch_connection_profile(get_connection_profile("account-fast-agent"), Log())
    assert app.calls == []
    assert app.current_model == "existing-model"
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda _: True)
    callbacks[0]()
    assert app.calls == ["fast-agent"]
    assert app._merge_acp_session_extra_env("fast-agent")["FAST_AGENT_MODEL"] == "codexplan"


def test_manifest_environment_only_applies_to_matching_agent(monkeypatch):
    monkeypatch.setattr(
        "superqode.app.mixins.connect.get_session",
        lambda: SimpleNamespace(
            connected_agent={"short_name": "pi", "launch_env": {"PI_MODE": "acp"}}
        ),
    )
    app = AccountApp()
    assert app._merge_acp_session_extra_env("pi") == {"PI_MODE": "acp"}
    assert app._merge_acp_session_extra_env("gemini") == {}


def test_binary_manifest_provides_platform_setup_and_preserves_environment(monkeypatch):
    from superqode.providers import acp_registry

    monkeypatch.setattr(acp_registry.sys, "platform", "darwin")
    monkeypatch.setattr(acp_registry.platform, "machine", lambda: "arm64")
    agent = acp_registry.convert_registry_agent(
        {
            "id": "future-agent",
            "license": "Proprietary",
            "website": "https://vendor.example",
            "distribution": {
                "binary": {
                    "darwin-aarch64": {
                        "cmd": "./bin/future-agent",
                        "args": ["--acp"],
                        "env": {"MODE": "acp"},
                        "archive": "https://vendor.example/mac.tar.gz",
                        "sha256": "test-checksum",
                    }
                }
            },
        }
    )
    assert agent["run_command"]["*"] == "future-agent --acp"
    assert agent["launch_env"] == {"MODE": "acp"}
    assert agent["registry_license"] == "Proprietary"
    assert "mac.tar.gz" in agent["installation_instructions"]
    assert "test-checksum" in agent["installation_instructions"]


def test_cli_health_allows_vendor_login_and_local_models(monkeypatch):
    from superqode.commands.acp import validate_agent_environment

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert validate_agent_environment({"short_name": "gemini"}) == []
    assert validate_agent_environment(
        {"short_name": "gemini", "required_env": ["TEST_PLAN_KEY"]}
    ) == ["TEST_PLAN_KEY"]


@pytest.mark.asyncio
async def test_discovery_keeps_registry_defaults_and_user_overrides(monkeypatch, tmp_path):
    from pathlib import Path
    from superqode.agents.discovery import read_agents

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    async def manifests():
        return [
            {
                "id": "fast-agent",
                "distribution": {
                    "uvx": {
                        "package": "fast-agent-mcp==9.9.9",
                        "args": ["--acp-new"],
                        "env": {"FAST_AGENT_MODEL": "registry-default"},
                    }
                },
            }
        ]

    monkeypatch.setattr("superqode.providers.acp_registry.get_acp_registry_agents", manifests)
    agents = await read_agents(include_registry=True)
    agent = next(a for a in agents.values() if a["short_name"] == "fast-agent")
    assert agent["run_command"]["*"] == "uvx fast-agent-mcp==9.9.9 --acp-new"
    assert agent["launch_env"] == {"FAST_AGENT_MODEL": "registry-default"}

    custom_dir = tmp_path / ".superqode" / "agents"
    custom_dir.mkdir(parents=True)
    (custom_dir / "custom.toml").write_text(
        'identity = "custom.fast-agent"\nname = "My Fast Agent"\n'
        'short_name = "fast-agent"\nprotocol = "acp"\n'
        '[run_command]\n"*" = "my-fast-agent --custom"\n'
        '[launch_env]\nFAST_AGENT_MODEL = "my-model"\n'
    )
    agents = await read_agents(include_registry=True)
    custom = agents["custom.fast-agent"]
    assert custom["user_defined"] is True
    assert custom["run_command"]["*"] == "my-fast-agent --custom"
    assert custom["launch_env"] == {"FAST_AGENT_MODEL": "my-model"}


@pytest.mark.parametrize(
    "profile",
    [
        "plan-agent-codex",
        "plan-zai",
        "account-fast-agent",
        "plan-minimax",
        "plan-grok",
        "plan-deepseek",
    ],
)
def test_interactive_account_route_cannot_answer_as_default_vendor(profile, monkeypatch):
    from click.testing import CliRunner
    from superqode.main import cli_main

    async def unexpected(**kwargs):
        raise AssertionError("interactive route must not reach a headless model")

    monkeypatch.setattr("superqode.headless.run_headless", unexpected)
    result = CliRunner().invoke(cli_main, ["-p", "--connect", profile, "hello"])
    assert result.exit_code == 2
    assert "interactive account/setup route" in result.output


def test_legacy_acp_persistence_does_not_infer_plan_verification():
    app = AccountApp()
    app._read_user_config = lambda: {
        "connection": {
            "auth_mode": "acp",
            "acp_agent": "pi",
            "profile_id": "account-pi",
            "billing_verified": "subscription",
        }
    }
    saved = app._load_connection_config()
    assert saved["transport"] == "ACP"
    assert saved["auth_mode"] == "agent-managed"
    assert saved["billing_requested"] == "agent-managed"
    assert saved["billing_verified"] == "unknown"
    assert saved["fallback_policy"] == "stop"


def test_invalid_saved_route_cannot_fall_back_to_previous_byok():
    app = AccountApp()
    app._load_connection_config = lambda: {
        "profile_id": "no-longer-supported",
        "auth_mode": "subscription",
    }
    app._load_byok_config = lambda: pytest.fail("must not inspect BYOK fallback")
    log = Log()
    app._connect_last(log)
    assert any("will not fall back" in message for message in log.messages)


def test_runtime_reconnect_restores_exact_billing_and_model():
    app = AccountApp()
    app._load_connection_config = lambda: {
        "runtime_name": "codex-sdk",
        "model": "chosen-model",
        "billing_requested": "subscription",
    }

    def connect(name, log):
        app.calls.append((name, app._requested_runtime_billing, app._requested_runtime_model))

    app._runtime_cmd = connect
    app._connect_last(Log())
    assert app.calls == [("codex-sdk", "subscription", "chosen-model")]


@pytest.mark.parametrize("agent", ["pi", "opencode", "omp"])
def test_configured_agent_account_never_claims_verified_subscription(monkeypatch, agent):
    profile = get_connection_profile(f"account-{agent}")
    if profile is None:
        pytest.skip("not a catalog account route")
    monkeypatch.setattr("superqode.commands.acp.check_agent_installed", lambda _: True)
    app = AccountApp()
    log = Log()
    app._dispatch_connection_profile(profile, log)
    assert app._acp_subscription_vendor is None
    assert any("agent-managed, unverified" in message for message in log.messages)


def test_empty_connection_config_allows_legacy_reconnect():
    app = AccountApp()
    app._read_user_config = lambda: {}
    assert app._load_connection_config() == {}


def test_saved_runtime_model_update_preserves_route():
    app = AccountApp()
    saved = {
        "runtime_name": "codex-sdk",
        "auth_mode": "subscription",
        "billing_requested": "subscription",
        "model": "before",
    }
    app._load_connection_config = lambda: saved
    app._save_connection_config = lambda **fields: app.calls.append(fields)
    app._save_runtime_model_choice("copilot-sdk", "wrong")
    assert not app.calls
    app._save_runtime_model_choice("codex-sdk", "after")
    assert app.calls[0]["billing_requested"] == "subscription"
    assert app.calls[0]["model"] == "after"


def test_headless_codex_preserves_requested_subscription_billing(monkeypatch):
    from click.testing import CliRunner
    from superqode.main import cli_main
    from superqode.agent.loop import AgentResponse

    captured = []

    async def run(**kwargs):
        captured.append(kwargs)
        return AgentResponse(
            content="mock answer",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )

    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner().invoke(cli_main, ["-p", "--connect", "codex", "hello"])
    assert result.exit_code == 0, result.output
    assert captured[0]["runtime"] == "codex-sdk"
    assert captured[0]["billing_requested"] == "subscription"


def test_headless_subscription_cannot_override_runtime(monkeypatch):
    from click.testing import CliRunner
    from superqode.main import cli_main

    async def run(**kwargs):
        pytest.fail("conflicting subscription route must stop before a model call")

    monkeypatch.setattr("superqode.headless.run_headless", run)
    result = CliRunner().invoke(
        cli_main, ["-p", "--connect", "codex", "--runtime", "builtin", "hello"]
    )
    assert result.exit_code == 2
    assert "cannot override its runtime" in result.output
