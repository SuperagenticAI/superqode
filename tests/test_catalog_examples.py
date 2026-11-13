"""Mac Catalog examples follow models.dev, newest release first."""

from __future__ import annotations

from datetime import datetime, timedelta

from superqode.providers.models import (
    LATEST_GOOGLE_MODEL_IDS,
    ModelInfo,
    catalog_examples,
)
from superqode.providers.models_dev import CacheMetadata, ModelsDev


def _info(model_id: str, provider: str, released: str) -> ModelInfo:
    return ModelInfo(id=model_id, name=model_id, provider=provider, released=released)


def _client(catalog: dict[str, dict[str, ModelInfo]]) -> ModelsDev:
    client = ModelsDev()
    client._models = catalog
    client._metadata = CacheMetadata(
        fetched_at=(datetime.now() + timedelta(hours=1)).isoformat(),
        ttl_hours=24,
    )
    client._loaded = True
    return client


def test_hosted_catalog_is_every_chat_model_newest_first(monkeypatch):
    client = _client(
        {
            "openai": {
                "text-embedding-ada-002": _info("text-embedding-ada-002", "openai", "2024-01-01"),
                "gpt-4o": _info("gpt-4o", "openai", "2024-05-13"),
                "gpt-5.4": _info("gpt-5.4", "openai", "2026-03-01"),
                "gpt-6.1-terra": _info("gpt-6.1-terra", "openai", "2026-10-26"),
                "gpt-4o-audio-preview": _info("gpt-4o-audio-preview", "openai", "2026-11-01"),
            },
            "anthropic": {
                "claude-opus-4-8": _info("claude-opus-4-8", "anthropic", "2026-05-01"),
                "claude-fable-5-2": _info("claude-fable-5-2", "anthropic", "2026-11-09"),
                "claude-sonnet-5": _info("claude-sonnet-5", "anthropic", "2026-06-29"),
            },
            "xai": {
                "grok-imagine-image": _info("grok-imagine-image", "xai", "2026-11-12"),
                "grok-4.7": _info("grok-4.7", "xai", "2026-09-21"),
                "grok-4.5": _info("grok-4.5", "xai", "2026-07-08"),
            },
            "alibaba": {
                "qwen-max": _info("qwen-max", "alibaba", "2025-06-01"),
                "qwen3.8-max": _info("qwen3.8-max", "alibaba", "2026-08-03"),
            },
            "alibaba-cn": {
                "qwen-plus": _info("qwen-plus", "alibaba-cn", "2025-01-01"),
                "qwen3.8-flash": _info("qwen3.8-flash", "alibaba-cn", "2026-08-26"),
            },
            "moonshotai": {
                "kimi-k2.6": _info("kimi-k2.6", "moonshotai", "2026-04-20"),
                "kimi-k3.1-pro": _info("kimi-k3.1-pro", "moonshotai", "2026-10-23"),
            },
            "meta": {
                "muse-spark-1.1": _info("muse-spark-1.1", "meta", "2026-04-08"),
                "muse-ember-1.0": _info("muse-ember-1.0", "meta", "2026-11-09"),
            },
        }
    )
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)

    openai = catalog_examples("openai")
    assert [model_id for model_id, _label in openai] == ["gpt-6.1-terra", "gpt-5.4", "gpt-4o"]
    assert openai[0][1] == "2026-10-26 · gpt-6.1-terra"
    assert [model_id for model_id, _label in catalog_examples("anthropic")] == [
        "claude-fable-5-2",
        "claude-sonnet-5",
        "claude-opus-4-8",
    ]
    assert [model_id for model_id, _label in catalog_examples("xai")] == ["grok-4.7", "grok-4.5"]
    assert [model_id for model_id, _label in catalog_examples("qwen-cn")] == [
        "qwen4-max-preview",
        "qwen3.8-flash",
        "qwen-plus",
    ]
    assert catalog_examples("qwen-cn")[0][1] == "Qwen 4 Max Preview · Token Plan"
    assert [model_id for model_id, _label in catalog_examples("qwen-intl")] == [
        "qwen4-max-preview",
        "qwen3.8-max",
        "qwen-max",
    ]
    assert [model_id for model_id, _label in catalog_examples("alibaba")] == [
        "qwen3.8-max",
        "qwen-max",
    ]
    assert catalog_examples("moonshot")[0][0] == "kimi-k3.1-pro"
    assert catalog_examples("meta")[0][0] == "muse-ember-1.0"


def test_catalogued_qwen4_preview_is_not_duplicated(monkeypatch):
    client = _client(
        {
            "alibaba-cn": {
                "qwen4-max-preview": _info("qwen4-max-preview", "alibaba-cn", "2026-11-11"),
                "qwen3.8-flash": _info("qwen3.8-flash", "alibaba-cn", "2026-08-26"),
            }
        }
    )
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    listed = catalog_examples("qwen-cn")
    assert [model_id for model_id, _label in listed] == [
        "qwen4-max-preview",
        "qwen3.8-flash",
    ]
    assert listed[0][1] == "2026-11-11 · qwen4-max-preview"


def test_google_and_local_catalogs_stay_curated(monkeypatch):
    client = _client(
        {
            "google": {
                "gemini-4-carbon": _info("gemini-4-carbon", "google", "2026-11-10"),
                "gemini-4-argon": _info("gemini-4-argon", "google", "2026-10-13"),
            }
        }
    )
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)

    google = catalog_examples("google")
    assert [model_id for model_id, _label in google] == list(LATEST_GOOGLE_MODEL_IDS)
    assert "gemini-4-carbon" not in [model_id for model_id, _label in google]
    assert google[1][1] == "2026-10-13 · gemini-4-argon"
    assert catalog_examples("ollama")[0][0] != "gemini-4-carbon"
    assert catalog_examples("apple-foundation") == [("system-on-device", "system-on-device")]
    assert catalog_examples("grok-cli")[0][0] == "grok-4.6"


def test_missing_catalog_keeps_registry_examples(monkeypatch):
    monkeypatch.setattr(
        "superqode.providers.models_dev.get_models_dev",
        lambda: _client({}),
    )
    assert catalog_examples("deepseek")[0] == ("deepseek-chat", "deepseek-chat")


def test_provider_list_uses_models_dev_order(monkeypatch):
    from superqode.desktop_service import connections

    client = _client(
        {
            "anthropic": {
                "claude-opus-4-8": _info("claude-opus-4-8", "anthropic", "2026-05-01"),
                "claude-fable-5-2": _info("claude-fable-5-2", "anthropic", "2026-11-09"),
            }
        }
    )
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    monkeypatch.setattr(connections, "provider_api_key", lambda _definition: None)
    rows = {row["id"]: row for row in connections.list_connections({})}
    assert rows["anthropic"]["example_models"][0] == "claude-fable-5-2"
    assert rows["anthropic"]["example_model_labels"][0] == "2026-11-09 · claude-fable-5-2"
    assert rows["google"]["example_models"] == list(LATEST_GOOGLE_MODEL_IDS)
    assert rows["google"]["example_models"][0] != "gemini-4-carbon"


def test_listing_providers_does_not_download(monkeypatch):
    client = _client({"openai": {"gpt-6.1-terra": _info("gpt-6.1-terra", "openai", "2026-10-26")}})

    def fail_download(timeout=30):
        raise AssertionError("provider list must not download models.dev")

    monkeypatch.setattr(client, "refresh_blocking", fail_download)
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    assert catalog_examples("openai")[0][0] == "gpt-6.1-terra"


def test_refresh_uses_saved_catalog_until_a_check_is_requested(monkeypatch):
    import superqode.providers.models as models

    client = _client({"openai": {"gpt-6.1-terra": _info("gpt-6.1-terra", "openai", "2026-10-26")}})
    calls = []

    def download(timeout=30):
        calls.append(timeout)
        client._models["openai"]["gpt-6.2"] = _info("gpt-6.2", "openai", "2026-11-13")
        return True

    monkeypatch.setattr(models, "_catalog_session_checked", False)
    monkeypatch.setattr(client, "refresh_blocking", download)
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)

    assert models.refresh_model_catalog(force=False)["status"] == "fresh"
    assert calls == []
    downloaded = models.refresh_model_catalog(force=True)
    assert downloaded["status"] == "downloaded"
    assert calls == [20]
    assert models.refresh_model_catalog(force=True)["status"] == "fresh"
    assert calls == [20]


def test_refresh_keeps_saved_catalog_when_offline(monkeypatch):
    import superqode.providers.models as models

    client = _client(
        {"anthropic": {"claude-fable-5-2": _info("claude-fable-5-2", "anthropic", "2026-11-09")}}
    )
    monkeypatch.setattr(models, "_catalog_session_checked", False)
    monkeypatch.setattr(client, "refresh_blocking", lambda timeout=30: False)
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    result = models.refresh_model_catalog(force=True)
    assert result["status"] == "offline"
    assert result["model_count"] == 1
    assert catalog_examples("anthropic")[0][0] == "claude-fable-5-2"


def test_desktop_discovery_lists_terminal_hosts_and_loads_models_on_demand(tmp_path, monkeypatch):
    from superqode.desktop_service import connections
    from superqode.desktop_service.service import DesktopService
    from superqode.providers.dynamic import connect_provider_ids
    from superqode.providers.models_dev import ProviderInfo

    client = _client({"test-host": {"code-model": _info("code-model", "test-host", "2026-11-09")}})
    client._providers = {
        "test-host": ProviderInfo(
            id="test-host",
            name="Test Model Host",
            env_vars=["TEST_HOST_API_KEY"],
            api_url="https://example.test/v1",
        )
    }
    monkeypatch.setattr("superqode.providers.models_dev.get_models_dev", lambda: client)
    monkeypatch.setattr("superqode.providers.dynamic.get_models_dev", lambda: client)
    monkeypatch.setattr(connections, "provider_api_key", lambda _definition: None)

    service = DesktopService(tmp_path / "state")
    try:
        rows = {row["id"]: row for row in service.dispatch("providers.list", {"compact": True})}
        assert set(rows) == set(connect_provider_ids())
        assert "example_models" not in rows["test-host"]
        assert rows["test-host"]["key_supported"] and not rows["test-host"]["curated"]
        assert not rows["amazon-bedrock"]["key_supported"]
        assert service.dispatch("providers.catalog.models", {"provider": "test-host"}) == {
            "example_models": ["code-model"],
            "example_model_labels": ["2026-11-09 · code-model"],
        }
        service.dispatch("providers.credentials.set", {"provider": "test-host", "key": "test-key"})
        assert service.credential_environment({"test-host"}) == {"TEST_HOST_API_KEY": "test-key"}
        assert service.credential_environment({"openai"}) == {}
        result = service.dispatch(
            "providers.check", {"provider": "test-host", "model": "code-model"}
        )
        assert result["state"] == "needs-test"
    finally:
        service.close()
