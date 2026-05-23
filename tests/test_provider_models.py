from superqode.providers import models as model_db
from superqode.providers.models import ModelInfo, get_models_for_provider, set_live_models


def teardown_function():
    model_db._live_models = None
    model_db._use_live_data = False


def test_builtin_google_byok_models_only_expose_latest_pair():
    models = get_models_for_provider("google")

    assert list(models) == ["gemini-3.1-pro-preview", "gemini-flash-latest"]


def test_live_google_models_are_filtered_to_latest_pro_and_flash():
    set_live_models(
        {
            "google": {
                "gemini-2.5-pro": ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro", "google"),
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
                "gemini-3.5-flash": ModelInfo(
                    "gemini-3.5-flash",
                    "Gemini 3.5 Flash",
                    "google",
                    released="2026-05-19",
                ),
                "gemini-flash-latest": ModelInfo(
                    "gemini-flash-latest",
                    "Gemini Flash Latest",
                    "google",
                    released="2025-09-25",
                ),
            }
        }
    )

    models = get_models_for_provider("google")

    assert list(models) == ["gemini-3.1-pro-preview", "gemini-flash-latest"]


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


def test_live_hosted_models_prefer_latest_aliases():
    set_live_models(
        {
            "openai": {
                "gpt-old": ModelInfo("gpt-old", "GPT Old", "openai", released="2024-01-01"),
                "gpt-new": ModelInfo("gpt-new", "GPT New", "openai", released="2026-01-01"),
                "gpt-new-latest": ModelInfo(
                    "gpt-new-latest",
                    "GPT New Latest",
                    "openai",
                    released="2025-01-01",
                ),
            }
        }
    )

    models = get_models_for_provider("openai")

    assert list(models) == ["gpt-new-latest"]
