"""A subscription connection must spend the subscription, and say so.

Vendor CLIs generally prefer an exported API key over their own OAuth login, so
an unrelated key left in a shell would silently move a subscription session onto
per-token billing. SuperQode has a dedicated BYOK path for API-key use, so
subscription routes drop those keys and always report it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from superqode.providers.subscription_env import (
    EXPLICIT_OPT_IN_ENVS,
    VENDOR_API_KEY_ENVS,
    diverting_api_keys,
    resolve_vendor,
    subscription_child_env,
    subscription_notice,
)


class TestVendorResolution:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("grok", "grok"),
            ("glm-cli", "glm"),
            ("qwen-code", "qwen"),
            ("kimi-code", "kimi"),
            ("copilot-sdk", "copilot"),
            ("copilot-cli", "copilot"),
            ("codex-sdk", "codex"),
            ("antigravity-cli", "antigravity"),
            ("muse-code", "muse"),
            ("muse-cli", "muse"),
            ("GROK", "grok"),
            ("", None),
            ("not-a-vendor", None),
        ],
    )
    def test_aliases_resolve_to_a_vendor(self, name, expected):
        assert resolve_vendor(name) == expected


class TestKeyDetection:
    def test_reports_only_keys_that_are_actually_set(self):
        env = {"XAI_API_KEY": "k", "UNRELATED": "x"}

        assert diverting_api_keys("grok", env) == ["XAI_API_KEY"]

    def test_no_keys_set_means_nothing_to_report(self):
        assert diverting_api_keys("grok", {"PATH": "/usr/bin"}) == []

    def test_muse_strips_its_cli_key_but_never_the_byok_key(self):
        """Muse reads META_API_KEY ahead of a login; it never reads the BYOK key.

        META_MODEL_API_KEY belongs to the `meta` BYOK provider, so removing it
        would break an unrelated route without protecting this one.
        """
        assert diverting_api_keys("muse", {"META_API_KEY": "k"}) == ["META_API_KEY"]
        assert diverting_api_keys("muse", {"META_MODEL_API_KEY": "k"}) == []

    def test_unknown_vendor_never_strips_anything(self):
        env = {"OPENAI_API_KEY": "k"}

        assert diverting_api_keys("some-other-agent", env) == []

    def test_explicit_opt_in_token_is_respected(self):
        """A token supplied on purpose is not an accident to protect against."""
        env = {"GH_TOKEN": "k", "COPILOT_GITHUB_TOKEN": "deliberate"}

        assert diverting_api_keys("copilot", env) == []
        assert EXPLICIT_OPT_IN_ENVS  # the opt-in list must not be empty


class TestChildEnvironment:
    def test_subscription_env_removes_the_keys_and_names_them(self):
        env = {
            "PATH": "/usr/bin",
            "GROK_CODE_XAI_API_KEY": "xai-secret",
            "XAI_API_KEY": "xai-secret-2",
        }

        child, stripped = subscription_child_env("grok", env)

        assert stripped == ["GROK_CODE_XAI_API_KEY", "XAI_API_KEY"]
        assert "GROK_CODE_XAI_API_KEY" not in child
        assert "XAI_API_KEY" not in child
        assert child["PATH"] == "/usr/bin"

    def test_secret_values_are_never_carried_into_the_result(self):
        env = {"XAI_API_KEY": "xai-secret", "PATH": "/usr/bin"}

        child, stripped = subscription_child_env("grok", env)

        assert not any("xai-secret" in value for value in child.values())
        assert all("xai-secret" not in name for name in stripped)

    def test_the_caller_environment_is_not_mutated(self):
        env = {"XAI_API_KEY": "k"}

        subscription_child_env("grok", env)

        assert env == {"XAI_API_KEY": "k"}

    def test_the_process_environment_is_never_mutated(self, monkeypatch):
        """SuperQode must never touch the user's own API keys.

        Only the dict handed to one vendor subprocess omits them. Nothing is
        removed from the user's shell, config, or keyring, so BYOK and every
        other tool keeps working exactly as before.
        """
        import os

        monkeypatch.setenv("XAI_API_KEY", "user-real-key")
        monkeypatch.setenv("OPENAI_API_KEY", "byok-key")
        before = dict(os.environ)

        child, stripped = subscription_child_env("grok")

        assert stripped == ["XAI_API_KEY"]
        assert dict(os.environ) == before
        assert os.environ["XAI_API_KEY"] == "user-real-key"
        assert "XAI_API_KEY" not in child

    def test_byok_keys_for_other_providers_are_left_alone(self, monkeypatch):
        """A subscription to one vendor must not disturb another vendor's key."""
        monkeypatch.setenv("OPENAI_API_KEY", "byok-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "byok-key-2")
        monkeypatch.setenv("XAI_API_KEY", "xai")

        child, stripped = subscription_child_env("grok")

        assert stripped == ["XAI_API_KEY"]
        assert child["OPENAI_API_KEY"] == "byok-key"
        assert child["ANTHROPIC_API_KEY"] == "byok-key-2"

    def test_byok_credential_lookup_still_resolves_after_a_subscription_connect(self, monkeypatch):
        """BYOK is a separate path and must keep resolving the user's key."""
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.registry import PROVIDERS

        monkeypatch.setenv("OPENAI_API_KEY", "byok-key")
        monkeypatch.setenv("XAI_API_KEY", "xai")

        subscription_child_env("grok")

        assert provider_api_key(PROVIDERS["openai"]) == "byok-key"

    def test_every_vendor_entry_is_reachable(self):
        """A typo in the table would silently disable protection for a vendor."""
        for vendor in VENDOR_API_KEY_ENVS:
            assert resolve_vendor(vendor) == vendor


class TestUserNotice:
    def test_nothing_stripped_produces_no_output(self):
        assert subscription_notice("Grok", []) == []

    def test_notice_names_the_keys_and_points_at_byok(self):
        lines = subscription_notice("Grok", ["XAI_API_KEY"])

        joined = " ".join(lines)
        assert "XAI_API_KEY" in joined
        assert "subscription" in joined
        assert ":connect byok" in joined

    def test_notice_never_contains_a_secret_value(self):
        lines = subscription_notice("Grok", ["XAI_API_KEY"])

        assert not any("secret" in line for line in lines)


class TestACPClientIntegration:
    def _client(self, vendor, tmp_path):
        from superqode.acp.client import ACPClient

        return ACPClient(
            project_root=tmp_path,
            command="true",
            subscription_vendor=vendor,
            startup_timeout=1.0,
        )

    def test_subscription_client_starts_without_the_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-secret")
        monkeypatch.setenv("GROK_CODE_XAI_API_KEY", "xai-secret-2")
        captured = {}

        async def fake_exec(cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise RuntimeError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_exec)
        client = self._client("grok", tmp_path)

        asyncio.run(client.start())

        assert "XAI_API_KEY" not in captured["env"]
        assert "GROK_CODE_XAI_API_KEY" not in captured["env"]
        assert client.stripped_api_keys == ["GROK_CODE_XAI_API_KEY", "XAI_API_KEY"]

    def test_plain_acp_client_keeps_the_environment_untouched(self, tmp_path, monkeypatch):
        """Only Subscriptions changes billing; the ACP channel is unaffected."""
        monkeypatch.setenv("XAI_API_KEY", "xai-secret")
        captured = {}

        async def fake_exec(cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise RuntimeError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_exec)
        client = self._client(None, tmp_path)

        asyncio.run(client.start())

        assert captured["env"].get("XAI_API_KEY") == "xai-secret"
        assert client.stripped_api_keys == []


class TestConnectFlowInformsTheUser:
    def test_subscription_profile_reports_the_ignored_key(self, monkeypatch):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.providers.connection_profiles import get_connection_profile

        monkeypatch.setenv("XAI_API_KEY", "xai-secret")
        messages = []

        class Log:
            def add_info(self, value):
                messages.append(str(value))

        class Stub(ConnectMixin):
            pass

        stub = Stub()
        ConnectMixin._apply_subscription_billing_policy(stub, get_connection_profile("grok"), Log())

        assert stub._acp_subscription_vendor == "grok"
        joined = " ".join(messages)
        assert "XAI_API_KEY" in joined
        assert ":connect byok" in joined
        assert "xai-secret" not in joined

    def test_non_subscription_profile_changes_nothing(self, monkeypatch):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.providers.connection_profiles import get_connection_profile

        monkeypatch.setenv("XAI_API_KEY", "xai-secret")
        messages = []

        class Log:
            def add_info(self, value):
                messages.append(str(value))

        class Stub(ConnectMixin):
            pass

        stub = Stub()
        ConnectMixin._apply_subscription_billing_policy(stub, get_connection_profile("acp"), Log())

        assert stub._acp_subscription_vendor is None
        assert messages == []
