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
    closed_key_profile_id,
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

    def test_droid_notice_points_at_closed_key_path(self):
        assert closed_key_profile_id("droid") == "droid-key"
        lines = subscription_notice("Factory Droid", ["FACTORY_API_KEY"], vendor="droid")

        joined = " ".join(lines)
        assert "FACTORY_API_KEY" in joined
        assert ":connect droid-key" in joined
        assert "Closed harnesses" in joined
        assert ":connect byok" not in joined

    def test_junie_notice_points_at_closed_key_path(self):
        assert closed_key_profile_id("junie") == "junie-key"
        lines = subscription_notice("Junie", ["JETBRAINS_API_KEY"], vendor="junie")

        joined = " ".join(lines)
        assert "JETBRAINS_API_KEY" in joined
        assert ":connect junie-key" in joined
        assert "Closed harnesses" in joined
        assert ":connect byok" not in joined

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

    def test_droid_subscription_strips_factory_key_and_points_at_droid_key(self, monkeypatch):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.providers.connection_profiles import get_connection_profile

        monkeypatch.setenv("FACTORY_API_KEY", "factory-secret")
        messages = []

        class Log:
            def add_info(self, value):
                messages.append(str(value))

        class Stub(ConnectMixin):
            pass

        stub = Stub()
        ConnectMixin._apply_subscription_billing_policy(
            stub, get_connection_profile("droid"), Log()
        )

        assert stub._acp_subscription_vendor == "droid"
        joined = " ".join(messages)
        assert "FACTORY_API_KEY" in joined
        assert ":connect droid-key" in joined
        assert "factory-secret" not in joined


class TestFactoryKeyPath:
    def test_subscription_child_still_strips_factory_key(self):
        env = {"PATH": "/usr/bin", "FACTORY_API_KEY": "factory-secret"}

        child, stripped = subscription_child_env("droid", env)

        assert stripped == ["FACTORY_API_KEY"]
        assert "FACTORY_API_KEY" not in child
        assert child["PATH"] == "/usr/bin"

    def test_acp_subscription_client_starts_without_factory_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FACTORY_API_KEY", "factory-secret")
        captured = {}

        async def fake_exec(cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise RuntimeError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_exec)
        from superqode.acp.client import ACPClient

        client = ACPClient(
            project_root=tmp_path,
            command="true",
            subscription_vendor="droid",
            startup_timeout=1.0,
        )
        asyncio.run(client.start())

        assert "FACTORY_API_KEY" not in captured["env"]
        assert client.stripped_api_keys == ["FACTORY_API_KEY"]

    def test_key_path_injects_factory_key_child_only(self, tmp_path, monkeypatch):
        """auth.json key reaches the child via extra_env, never the parent."""
        monkeypatch.delenv("FACTORY_API_KEY", raising=False)
        captured = {}

        async def fake_exec(cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise RuntimeError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_exec)
        from superqode.acp.client import ACPClient

        client = ACPClient(
            project_root=tmp_path,
            command="true",
            extra_env={"FACTORY_API_KEY": "from-auth-json"},
            startup_timeout=1.0,
        )
        asyncio.run(client.start())

        assert captured["env"].get("FACTORY_API_KEY") == "from-auth-json"
        assert "FACTORY_API_KEY" not in __import__("os").environ
        assert client.stripped_api_keys == []

    def test_begin_vendor_key_sets_child_extra_env_from_auth_json(self, monkeypatch, tmp_path):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.auth import ApiAuth, LocalAuthStorage
        from superqode.providers.connection_profiles import get_connection_profile
        import superqode.auth as auth_module

        monkeypatch.delenv("FACTORY_API_KEY", raising=False)
        monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))
        auth_module._storage.set("factory", ApiAuth(key="from-store"))
        monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path))

        class Log:
            def __init__(self):
                self.messages = []
                self.panels = []

            def add_info(self, value):
                self.messages.append(str(value))

            def add_error(self, value):
                self.messages.append(str(value))

            def write(self, value):
                self.panels.append(value)

            def write_feedback(self, value):
                self.panels.append(value)

        class Stub(ConnectMixin):
            def __init__(self):
                self.acp_calls = []

            def _connect_acp_cmd(self, name, log):
                self.acp_calls.append(name)

        stub = Stub()
        profile = get_connection_profile("droid-key")
        ConnectMixin._begin_vendor_key(stub, profile, Log())

        import os

        assert stub.acp_calls == ["droid"]
        assert stub._acp_subscription_vendor is None
        assert stub._acp_extra_env == {"FACTORY_API_KEY": "from-store"}
        assert stub._acp_extra_env_agent == "droid"
        assert stub._pending_vendor_key["agent"] == "droid"
        assert "FACTORY_API_KEY" not in os.environ
        assert stub._pending_vendor_key["note"] == "API key path — not your Droid CLI login."

    def test_begin_vendor_key_env_wins_and_does_not_setdefault(self, monkeypatch, tmp_path):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.auth import ApiAuth, LocalAuthStorage
        from superqode.providers.connection_profiles import get_connection_profile
        import superqode.auth as auth_module
        import os

        monkeypatch.setenv("FACTORY_API_KEY", "from-env")
        monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))
        auth_module._storage.set("factory", ApiAuth(key="from-store"))
        monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path))

        class Log:
            def add_info(self, value):
                pass

            def add_error(self, value):
                pass

        class Stub(ConnectMixin):
            def _connect_acp_cmd(self, name, log):
                pass

        stub = Stub()
        ConnectMixin._begin_vendor_key(stub, get_connection_profile("droid-key"), Log())

        assert stub._acp_extra_env == {"FACTORY_API_KEY": "from-env"}
        assert stub._acp_extra_env_agent == "droid"
        assert os.environ["FACTORY_API_KEY"] == "from-env"

    def test_begin_vendor_key_missing_key_shows_panel(self, monkeypatch, tmp_path):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.providers.connection_profiles import get_connection_profile
        import superqode.auth as auth_module
        from superqode.auth import LocalAuthStorage

        monkeypatch.delenv("FACTORY_API_KEY", raising=False)
        monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))

        class Log:
            def __init__(self):
                self.panels = []

            def add_info(self, value):
                pass

            def add_error(self, value):
                pass

            def write_feedback(self, value):
                self.panels.append(value.plain if hasattr(value, "plain") else str(value))

        class Stub(ConnectMixin):
            def __init__(self):
                self.acp_calls = []

            def _connect_acp_cmd(self, name, log):
                self.acp_calls.append(name)

        stub = Stub()
        log = Log()
        ConnectMixin._begin_vendor_key(stub, get_connection_profile("droid-key"), log)

        assert stub.acp_calls == []
        assert getattr(stub, "_acp_extra_env", None) in (None, {})
        rendered = " ".join(str(panel) for panel in log.panels)
        assert "API Key Required" in rendered
        assert "FACTORY_API_KEY" in rendered
        assert "superqode auth login factory" in rendered
        assert ":connect droid-key" in rendered

    def test_droid_key_is_not_a_vendors_subscription_profile(self):
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_VENDORS,
            get_connection_profile,
            connection_profile_ids,
        )

        profile = get_connection_profile("droid-key")
        assert profile.menu != CONNECT_MENU_VENDORS
        assert profile.connector == "vendor-key"
        assert "droid-key" not in connection_profile_ids(menu=CONNECT_MENU_VENDORS)

    def test_factory_provider_is_harness_only_and_hidden_from_byok(self):
        from superqode.providers.dynamic import connect_provider_ids
        from superqode.providers.registry import PROVIDERS

        assert "factory" in PROVIDERS
        assert PROVIDERS["factory"].harness_only is True
        assert PROVIDERS["factory"].env_vars == ["FACTORY_API_KEY"]
        assert "factory" not in connect_provider_ids()

    def test_extra_env_is_scoped_to_the_factory_agent(self):
        from superqode.app.mixins.connect import ConnectMixin

        class Stub(ConnectMixin):
            pass

        stub = Stub()
        stub._set_acp_extra_env({"FACTORY_API_KEY": "child-only"}, "droid")

        assert stub._merge_acp_session_extra_env("droid") == {"FACTORY_API_KEY": "child-only"}
        assert stub._merge_acp_session_extra_env("opencode") == {}
        assert stub._merge_acp_session_extra_env("droid", {"OTHER": "x"}) == {
            "OTHER": "x",
            "FACTORY_API_KEY": "child-only",
        }

        stub._retain_acp_extra_env_for("opencode")
        assert stub._acp_extra_env is None
        assert stub._acp_extra_env_agent is None
        assert stub._merge_acp_session_extra_env("droid") == {}

    def test_named_acp_and_disconnect_clear_extra_env(self):
        from superqode.app.mixins.connect import ConnectMixin

        class Stub(ConnectMixin):
            def __init__(self):
                self.agents = []

            def _show_agents(self, log, **kwargs):
                self.agents.append(kwargs)

            def _connect_agent(self, name, model_hint=None):
                self.agents.append(name)

        stub = Stub()
        stub._set_acp_extra_env({"FACTORY_API_KEY": "child-only"}, "droid")
        ConnectMixin._connect_acp_cmd(stub, "opencode", log=None)
        assert stub._acp_extra_env is None
        assert stub._acp_extra_env_agent is None
        assert stub.agents == ["opencode"]

        stub._set_acp_extra_env({"FACTORY_API_KEY": "child-only"}, "droid")
        stub._pending_vendor_key = {"agent": "droid"}
        stub._clear_acp_extra_env()
        assert stub._pending_vendor_key is None

    def test_begin_vendor_key_does_not_record_success_before_attach(self, monkeypatch, tmp_path):
        from superqode.app.mixins.connect import ConnectMixin
        from superqode.providers.connection_profiles import get_connection_profile

        monkeypatch.setenv("FACTORY_API_KEY", "from-env")
        monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path))
        recorded = []
        monkeypatch.setattr(
            "superqode.app.progress.record_milestone",
            lambda name: recorded.append(name),
        )

        class Log:
            def add_info(self, value):
                pass

            def add_error(self, value):
                pass

        class Stub(ConnectMixin):
            def _connect_acp_cmd(self, name, log):
                pass

        stub = Stub()
        ConnectMixin._begin_vendor_key(stub, get_connection_profile("droid-key"), Log())
        assert recorded == []
        assert stub._pending_vendor_key["agent"] == "droid"

        stub.current_agent = "droid"
        stub.current_model = ""
        ConnectMixin._finish_vendor_key_or_teach(stub, Log(), {"name": "Factory Droid"})
        assert recorded == ["connected_closed_harness", "connected"]
        assert stub._pending_vendor_key is None

    def test_failed_attach_does_not_keep_the_inject(self):
        from superqode.app.mixins.connect import ConnectMixin

        stub = ConnectMixin()
        stub._set_acp_extra_env({"FACTORY_API_KEY": "child-only"}, "droid")
        stub._pending_vendor_key = {"agent": "droid"}
        stub._abandon_vendor_key_attach("droid")
        assert stub._acp_extra_env is None
        assert stub._pending_vendor_key is None

    def test_unrelated_attach_failure_does_not_drop_droid_key_staging(self):
        """An earlier exclusive worker must not wipe a newer droid-key pin."""
        from superqode.app.mixins.connect import ConnectMixin

        stub = ConnectMixin()
        stub._set_acp_extra_env({"FACTORY_API_KEY": "child-only"}, "droid")
        stub._pending_vendor_key = {
            "agent": "droid",
            "note": "API key path — not your Droid CLI login.",
        }
        stub._abandon_vendor_key_attach("opencode")
        assert stub._acp_extra_env == {"FACTORY_API_KEY": "child-only"}
        assert stub._acp_extra_env_agent == "droid"
        assert stub._pending_vendor_key["agent"] == "droid"

    def test_harness_only_factory_is_rejected_from_byok(self):
        from superqode.app.mixins.connect import ConnectMixin

        messages = []

        class Log:
            def add_info(self, value):
                messages.append(str(value))

        class Stub(ConnectMixin):
            pass

        stub = Stub()
        assert stub._redirect_harness_only_provider("factory", Log()) is True
        joined = " ".join(messages)
        assert ":connect droid-key" in joined
        assert stub._redirect_harness_only_provider("openai", Log()) is False
