"""Tests for provider/model recommendation helpers."""

from superqode.providers.recommendations import (
    normalize_task,
    provider_doctor_cards,
    provider_setup_hint,
    recommend_models,
)


def test_normalize_task_aliases():
    assert normalize_task("build") == "coding"
    assert normalize_task("large") == "large-context"
    assert normalize_task(None) == "coding"


def test_recommend_models_include_quality_labels():
    recommendations = recommend_models("coding", limit=5)

    assert recommendations
    assert recommendations[0].score > 0
    assert recommendations[0].price
    assert recommendations[0].context
    assert recommendations[0].tool_support in {"yes", "no"}
    assert recommendations[0].labels


def test_provider_setup_hint_reports_missing_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    hint = provider_setup_hint("openai")

    assert hint.provider == "openai"
    assert hint.configured is False
    assert "OPENAI_API_KEY" in hint.required_env_vars
    assert "OPENAI_API_KEY" in hint.setup_hint


def test_provider_doctor_cards_include_model_labels():
    cards = provider_doctor_cards(["openai"])

    assert cards[0]["provider"] == "openai"
    assert cards[0]["models"]
    assert "setup_hint" in cards[0]


def test_ds4_setup_hint_checks_local_server(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "superqode.providers.recommendations.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    hint = provider_setup_hint("ds4")

    assert hint.provider == "ds4"
    assert hint.configured is True
    assert "Ready" in hint.setup_hint


def test_local_recommendations_include_ds4():
    recommendations = recommend_models("local", limit=5)

    assert any(item.provider == "ds4" for item in recommendations)
