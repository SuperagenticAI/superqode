from superqode.providers import models as model_db
from superqode.providers.manager import ProviderManager
from superqode.providers.models import ModelInfo, get_models_for_provider, set_live_models


def teardown_function():
    model_db._live_models = None
    model_db._use_live_data = False
    model_db._live_autoload_attempted = False


def test_builtin_google_byok_models_are_current_and_newest_first(monkeypatch):
    monkeypatch.setattr(model_db, "_use_live_data", False)
    monkeypatch.setattr(model_db, "_live_models", None)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)

    models = get_models_for_provider("google")

    assert list(models) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
    ]


def test_builtin_xai_grok_4_5_metadata(monkeypatch):
    # Keep this unit test independent of an optional local models.dev cache.
    monkeypatch.setattr(model_db, "_use_live_data", False)
    monkeypatch.setattr(model_db, "_live_models", None)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)

    models = get_models_for_provider("xai")
    model = models["grok-4.5"]

    # Newest release sorts first so grok-4.5 leads the BYOK picker.
    assert list(models)[0] == "grok-4.5"
    assert {"grok-4.5", "grok-4.3", "grok-build-0.1"} <= set(models)

    assert model.context_window == 500000
    assert model.input_price == 2.0
    assert model.output_price == 6.0
    assert model.supports_tools is True
    assert model.supports_reasoning is True
    assert model.supports_vision is True


def test_stale_live_cache_does_not_shadow_newer_builtin_models():
    # Regression: a months-old models.dev cache (grok-4 era) used to replace
    # the builtin xAI list wholesale, hiding day-one models like grok-4.5.
    set_live_models(
        {
            "xai": {
                "grok-4": ModelInfo(
                    "grok-4", "Grok 4", "xai", input_price=3.0, released="2025-07-09"
                ),
                "grok-3": ModelInfo("grok-3", "Grok 3", "xai", released="2025-02-17"),
            },
            # Provider with no builtin entry: live data must still be used.
            "cerebras": {
                "llama-5-70b": ModelInfo("llama-5-70b", "Llama 5 70B", "cerebras"),
            },
        }
    )

    xai = get_models_for_provider("xai")
    assert "grok-4.5" in xai
    assert "grok-4" not in xai
    assert "llama-5-70b" in get_models_for_provider("cerebras")


def test_fresh_live_models_still_replace_builtin_lists():
    set_live_models(
        {
            "xai": {
                "grok-4.5": ModelInfo(
                    "grok-4.5", "Grok 4.5", "xai", input_price=2.0, released="2026-07-08"
                ),
                "grok-5-preview": ModelInfo(
                    "grok-5-preview", "Grok 5 Preview", "xai", released="2026-09-01"
                ),
            }
        }
    )

    xai = get_models_for_provider("xai")
    assert "grok-5-preview" in xai
    # Builtin-only entries are replaced by the (newer) live list, as before.
    assert "grok-build-0.1" not in xai


def test_full_catalog_option_keeps_new_openai_variants_selectable():
    set_live_models(
        {
            "openai": {
                "gpt-5.3-chat-latest": ModelInfo(
                    "gpt-5.3-chat-latest", "GPT 5.3 Chat Latest", "openai"
                ),
                "gpt-5.6": ModelInfo("gpt-5.6", "GPT-5.6", "openai"),
                "gpt-5.6-luna": ModelInfo("gpt-5.6-luna", "GPT-5.6 Luna", "openai"),
                "gpt-5.6-terra": ModelInfo("gpt-5.6-terra", "GPT-5.6 Terra", "openai"),
                "gpt-5.6-sol": ModelInfo("gpt-5.6-sol", "GPT-5.6 Sol", "openai"),
            }
        }
    )

    full_catalog = get_models_for_provider("openai", include_all=True)

    assert {
        "gpt-5.6",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    } <= set(full_catalog)


def test_default_byok_catalog_keeps_only_six_newest_chat_models():
    set_live_models(
        {
            "acme": {
                f"acme-{version}": ModelInfo(
                    f"acme-{version}",
                    f"Acme {version}",
                    "acme",
                    released=f"2026-{version:02d}-01",
                )
                for version in range(1, 9)
            }
        }
    )

    byok_models = get_models_for_provider("acme")
    full_catalog = get_models_for_provider("acme", include_all=True)

    assert list(byok_models) == [f"acme-{version}" for version in range(8, 2, -1)]
    assert list(full_catalog) == [f"acme-{version}" for version in range(8, 0, -1)]


def test_builtin_xai_catalog_drops_retired_grok_models(monkeypatch):
    # xAI no longer serves grok-3/grok-2/grok-beta; they must not reappear.
    monkeypatch.setattr(model_db, "_use_live_data", False)
    monkeypatch.setattr(model_db, "_live_models", None)
    monkeypatch.setattr(model_db, "_live_autoload_attempted", True)

    builtin_ids = set(get_models_for_provider("xai"))
    manager_ids = {
        m.id for p in ProviderManager().list_providers() if p.id == "xai" for m in p.models
    }

    retired = {"grok-3", "grok-3-mini", "grok-2", "grok-beta"}
    assert not (builtin_ids & retired)
    assert not (manager_ids & retired)
    assert "grok-4.5" in manager_ids


def test_live_google_models_drop_deprecated_aliases_and_specialty_endpoints():
    set_live_models(
        {
            "google": {
                "gemini-2.0-flash": ModelInfo(
                    "gemini-2.0-flash",
                    "Gemini 2.0 Flash",
                    "google",
                    released="2025-02-05",
                ),
                "gemini-2.5-pro": ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro", "google"),
                "gemini-3.6-flash": ModelInfo(
                    "gemini-3.6-flash",
                    "Gemini 3.6 Flash",
                    "google",
                    released="2026-07-21",
                ),
                "gemini-3.5-flash-lite": ModelInfo(
                    "gemini-3.5-flash-lite",
                    "Gemini 3.5 Flash-Lite",
                    "google",
                    released="2026-07-21",
                ),
                "gemini-3.5-flash": ModelInfo(
                    "gemini-3.5-flash",
                    "Gemini 3.5 Flash",
                    "google",
                    released="2026-05-19",
                ),
                "gemini-3.1-pro-preview": ModelInfo(
                    "gemini-3.1-pro-preview",
                    "Gemini 3.1 Pro Preview",
                    "google",
                    released="2026-02-19",
                ),
                "gemini-3.1-pro-preview-customtools": ModelInfo(
                    "gemini-3.1-pro-preview-customtools",
                    "Gemini 3.1 Pro Preview Custom Tools",
                    "google",
                    released="2026-02-19",
                ),
                "gemini-flash-latest": ModelInfo(
                    "gemini-flash-latest",
                    "Gemini Flash Latest",
                    "google",
                    released="2026-07-21",
                ),
            }
        }
    )

    models = get_models_for_provider("google")
    full_catalog = get_models_for_provider("google", include_all=True)

    expected = [
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
    ]
    assert list(models) == expected
    assert list(full_catalog) == expected
    assert "gemini-2.0-flash" not in full_catalog
    assert "gemini-2.5-pro" not in full_catalog
    assert "gemini-flash-latest" not in full_catalog
    assert "gemini-3.1-pro-preview-customtools" not in full_catalog


def test_live_provider_models_replace_stale_builtin_models():
    set_live_models(
        {
            "anthropic": {
                "claude-future-latest": ModelInfo(
                    "claude-future-latest",
                    "Claude Future Latest",
                    "anthropic",
                    released="2026-05-01",
                )
            }
        }
    )

    models = get_models_for_provider("anthropic")

    assert list(models) == ["claude-future-latest"]


def test_live_hosted_models_newest_first_with_aliases_alongside():
    """Rolling "-latest" aliases must not hide newer real models.

    Regression: the old exclusive-alias rule made the OpenAI picker show only
    stale gpt-5.x-chat-latest entries while the brand-new GPT-5.6 family was
    invisible. Newest release now leads; aliases stay in the list and win only
    date ties.
    """
    set_live_models(
        {
            "acme": {
                "gpt-old": ModelInfo("gpt-old", "GPT Old", "acme", released="2024-01-01"),
                "gpt-new": ModelInfo("gpt-new", "GPT New", "acme", released="2026-01-01"),
                "gpt-new-latest": ModelInfo(
                    "gpt-new-latest",
                    "GPT New Latest",
                    "acme",
                    released="2025-01-01",
                ),
                "gpt-tie-latest": ModelInfo(
                    "gpt-tie-latest",
                    "GPT Tie Latest",
                    "acme",
                    released="2026-01-01",
                ),
            }
        }
    )

    models = get_models_for_provider("acme")

    # Date tie between gpt-new and gpt-tie-latest: the alias wins the tie,
    # then the real newest model, then older entries — nothing hidden.
    assert list(models) == ["gpt-tie-latest", "gpt-new", "gpt-new-latest", "gpt-old"]

    # The full catalog view reads newest-first too.
    assert list(get_models_for_provider("acme", include_all=True)) == [
        "gpt-tie-latest",
        "gpt-new",
        "gpt-new-latest",
        "gpt-old",
    ]


def test_find_providers_for_model_resolves_bare_model_ids():
    from superqode.providers.models import find_providers_for_model

    set_live_models(
        {
            "acme": {
                "shared-model": ModelInfo("shared-model", "Shared", "acme"),
                "acme-only": ModelInfo("acme-only", "Acme Only", "acme"),
            },
            "beta": {
                "shared-model": ModelInfo("shared-model", "Shared", "beta"),
            },
            # Local providers never participate in bare-model resolution.
            "ollama": {
                "acme-only": ModelInfo("acme-only", "Acme Only", "ollama"),
            },
        }
    )

    assert find_providers_for_model("acme-only") == ["acme"]
    assert find_providers_for_model("Acme-Only") == ["acme"]  # case-insensitive
    assert find_providers_for_model("shared-model") == ["acme", "beta"]
    assert find_providers_for_model("nope") == []


def test_sort_models_newest_first_orders_picker_dicts():
    from superqode.providers.models import sort_models_newest_first

    set_live_models(
        {
            "acme": {
                "gpt-new": ModelInfo("gpt-new", "GPT New", "acme", released="2026-01-01"),
                "gpt-old": ModelInfo("gpt-old", "GPT Old", "acme", released="2024-01-01"),
            }
        }
    )

    entries = [
        {"id": "mystery-model"},  # unknown release — keeps advertised order, after dated
        {"id": "gpt-old"},
        {"id": "acme/gpt-new"},  # OpenCode-style provider/model pair id
        {"id": "another-mystery"},
    ]

    ordered = [e["id"] for e in sort_models_newest_first(entries)]
    assert ordered == ["acme/gpt-new", "gpt-old", "mystery-model", "another-mystery"]


def test_provider_manager_mlx_models_do_not_fall_back_to_cache(monkeypatch):
    import superqode.providers.local.mlx as mlx

    class _Client:
        async def is_available(self):
            return False

        async def list_models(self):
            raise AssertionError("server is not available")

    async def _get_client():
        return _Client()

    monkeypatch.setattr(mlx, "get_mlx_client", _get_client)
    monkeypatch.setattr(
        mlx.MLXClient,
        "discover_huggingface_models",
        staticmethod(
            lambda: [
                {
                    "id": "mlx-community/not-running",
                    "size_bytes": 123,
                    "path": "/cache/not-running",
                    "modified": 0,
                }
            ]
        ),
    )

    assert ProviderManager()._get_mlx_models() == []
