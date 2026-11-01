"""Provider-scoped credentials and process configuration for Strands."""

from __future__ import annotations

import os
from pathlib import Path

from ..strands_setup import BASE_VARIABLES

PROVIDER_VARIABLES = {
    "anthropic": {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"},
    "openai": {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"},
    "google": {"GOOGLE_API_KEY", "GEMINI_API_KEY"},
    "ollama": {"OLLAMA_HOST", "OLLAMA_API_KEY"},
    "litellm": {"LITELLM_BASE_URL", "LITELLM_API_KEY"},
    "bedrock": {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_CA_BUNDLE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
        "AWS_ROLE_SESSION_NAME",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
        "AWS_EC2_METADATA_DISABLED",
        "AWS_SDK_LOAD_CONFIG",
        "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
    },
}
KEY_VARIABLES = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "ollama": ("OLLAMA_API_KEY",),
    "litellm": ("LITELLM_API_KEY",),
}


def worker_environment(provider: str, interpreter: Path) -> dict[str, str]:
    """Resolve only the selected provider's key without mutating parent state."""
    from superqode.providers.credentials import provider_api_key
    from superqode.providers.registry import PROVIDERS

    provider = "google" if provider == "gemini" else provider
    allowed = BASE_VARIABLES | PROVIDER_VARIABLES.get(provider, set())
    environment = {name: value for name, value in os.environ.items() if name in allowed}
    definition = PROVIDERS.get(provider)
    # Use the common resolver so env overrides, local auth and app-injected keys
    # have exactly the same precedence as the other provider integrations.
    if definition and provider in KEY_VARIABLES:
        key = provider_api_key(definition)
        if key:
            for name in KEY_VARIABLES[provider]:
                environment[name] = key
    environment["PATH"] = str(interpreter.parent) + os.pathsep + environment.get("PATH", "")
    environment["OTEL_TRACES_EXPORTER"] = "none"
    return environment


def redact_error(message: str, environment: dict[str, str]) -> str:
    """Bound diagnostics and remove forwarded credential values."""
    for name, value in sorted(environment.items(), key=lambda pair: len(pair[1]), reverse=True):
        if value and any(
            word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PROXY")
        ):
            message = message.replace(value, "[REDACTED]")
    return message[:2000]
