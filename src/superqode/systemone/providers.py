"""Documented decision endpoints, independent of the coding-model provider."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DecisionProvider:
    id: str
    label: str
    model: str
    endpoint: str
    api_key_env: str
    docs: str
    models: tuple[str, ...]


PROVIDERS = {
    "typesafe": DecisionProvider(
        "typesafe",
        "TypeSafe Jev",
        "jev-1.13.0",
        "https://api.typesafe.ai/v1/systemone",
        "TYPESAFE_API_KEY",
        "https://docs.typesafe.ai/models",
        ("jev-1.13.0", "jev-1.14.0"),
    ),
    "google": DecisionProvider(
        "google",
        "Google Gemini Decision",
        "gemini-decision-1",
        "https://generativelanguage.googleapis.com/v1beta/decisions",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/docs/decisions-api",
        ("gemini-decision-1",),
    ),
    "openai": DecisionProvider(
        "openai",
        "OpenAI Decisions",
        "gpt-6-luna",
        "https://api.openai.com/v1/decisions",
        "OPENAI_API_KEY",
        "https://developers.openai.com/api/docs/guides/decisions",
        ("gpt-6-luna",),
    ),
}


def get_provider(provider: str) -> DecisionProvider:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ValueError("Decision provider must be typesafe, google, or openai") from None


def provider_rows() -> list[dict]:
    return [asdict(provider) for provider in PROVIDERS.values()]
