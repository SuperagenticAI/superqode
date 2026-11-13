"""Desktop connection metadata and ephemeral credentials, never persisted secrets."""

from __future__ import annotations

from superqode.providers.credentials import provider_api_key
from superqode.providers.dynamic import resolve_base_url
from superqode.providers.model_studio import (
    METERED_PROVIDERS,
    is_plan_model,
    thinking_policy,
    validate_metered_route,
    validate_workspace_endpoint,
)
from superqode.providers.registry import PROVIDERS, ProviderTier

# These definitions use multiple, unrelated fields rather than one API key.
ADVANCED_AUTH = {"bedrock", "azure", "vertex", "cloudflare"}


def key_provider(provider_id: str):
    definition = PROVIDERS.get(provider_id)
    if (
        not definition
        or not definition.env_vars
        or definition.harness_only
        or definition.auth_mode != "byok"
        or definition.tier == ProviderTier.LOCAL
        or provider_id in ADVANCED_AUTH
        or any("BASE" in field or "CREDENTIALS" in field for field in definition.env_vars)
    ):
        raise ValueError("This provider requires its existing local authentication workflow")
    return definition


def install(credentials: dict[str, str], params: dict, base_url: str | None = None):
    definition = key_provider(str(params.get("provider") or ""))
    value = params.get("key")
    if value is None:
        credentials.pop(definition.id, None)
    elif (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 16_000
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(
            "Enter a nonempty API key without control characters (up to 16,000 characters)"
        )
    elif definition.credential_prefix and not value.strip().startswith(
        definition.credential_prefix
    ):
        raise ValueError("The key does not match this provider's credential type")
    else:
        if definition.id in METERED_PROVIDERS:
            validate_metered_route(base_url or resolve_base_url(definition) or "", value)
        credentials[definition.id] = value.strip()
    return {"ok": True}


def list_workspace_models(credentials: dict[str, str], params: dict, base_url: str | None = None):
    import asyncio

    from superqode.providers.live_models import discover_provider_models

    provider = str(params.get("provider") or "")
    if provider not in METERED_PROVIDERS:
        raise ValueError("Workspace model discovery requires a Model Studio provider.")
    if "endpoint" in params:
        proposed = params["endpoint"]
        if not isinstance(proposed, str):
            raise ValueError("Enter a Model Studio API endpoint.")
        base_url = validate_workspace_endpoint(proposed) if proposed.strip() else None
    if "key" in params:
        # Use a copy: loading models must not store or replace a key.
        credentials = dict(credentials)
        install(credentials, params, base_url=base_url)
    result = asyncio.run(
        discover_provider_models(provider, api_key=credentials.get(provider), base_url=base_url)
    )
    return {
        "source": result.source,
        "models": [model.id for model in result.models],
        "model_details": [
            {
                "id": model.id,
                "name": model.name,
                "context_window": model.context_window or None,
                "max_output": model.max_output or None,
                "capabilities": [
                    capability.name.lower().replace("_", "-") for capability in model.capabilities
                ],
                "pricing_known": model.pricing_known,
                "thinking_policy": thinking_policy(model.id),
            }
            for model in result.models
        ],
        "error": result.error,
    }


def environment(credentials: dict[str, str]) -> dict[str, str]:
    output = {}
    for provider, value in credentials.items():
        for variable in key_provider(provider).env_vars:
            output[variable] = value
    return output


def list_connections(credentials: dict[str, str], endpoints: dict[str, str] | None = None):
    result = []
    for definition in PROVIDERS.values():
        if definition.harness_only:
            continue
        try:
            key_provider(definition.id)
            accepts_key = True
        except ValueError:
            accepts_key = False
        configured = definition.id in credentials or bool(provider_api_key(definition))
        local = definition.tier == ProviderTier.LOCAL and definition.deployment_mode != "cloud"
        configured_endpoint = (endpoints or {}).get(definition.id)
        result.append(
            {
                "id": definition.id,
                "name": definition.name,
                "local": local,
                "key_supported": accepts_key,
                "credential_configured": configured,
                "credential_source": "desktop session"
                if definition.id in credentials
                else "existing local configuration"
                if configured
                else "not configured",
                "example_models": definition.example_models,
                "docs_url": definition.docs_url,
                "category": definition.category.value,
                "notes": definition.notes,
                "credential_variables": list(definition.env_vars),
                "default_base_url": definition.default_base_url,
                "workspace_base_url": configured_endpoint or resolve_base_url(definition)
                if definition.id in METERED_PROVIDERS
                else None,
                "workspace_endpoint_override": configured_endpoint,
                "base_url_env": definition.base_url_env or "",
                "verified": False,
            }
        )
    return result


def inspect_route(credentials: dict[str, str], params: dict):
    provider = str(params.get("provider") or "").strip()
    model = str(params.get("model") or "").strip()
    if not provider or not model:
        return {"ready": False, "state": "incomplete", "message": "Choose a provider and model."}
    if provider in METERED_PROVIDERS and is_plan_model(model):
        return {
            "ready": False,
            "state": "unsupported",
            "message": "This model requires Token Plan.",
        }
    if provider == "ollama":
        from superqode.local.inventory import list_ollama_models

        if any(word in model.lower() for word in ("embed", "rerank")):
            return {
                "ready": False,
                "state": "unsupported",
                "message": "Choose a chat or coding model; this model is for embeddings or reranking.",
            }
        discovered = list_ollama_models()
        found = any(item.bare_id == model for item in discovered)
        return {
            "ready": found,
            "state": "model-discovered" if found else "model-unavailable",
            "message": "Model found on your Ollama server. Run a test to verify coding execution."
            if found
            else "Model not found. Open Ollama, install the model, then refresh.",
        }
    row = next((row for row in list_connections(credentials) if row["id"] == provider), None)
    if not row:
        return {
            "ready": False,
            "state": "unknown-provider",
            "message": "This provider is not in the installed engine catalog.",
        }
    if row["local"]:
        return {
            "ready": None,
            "state": "needs-test",
            "message": "Local server route configured. Run a test to verify the model and server.",
        }
    if row["key_supported"] and not row["credential_configured"]:
        return {
            "ready": False,
            "state": "missing-credential",
            "message": "Connect this provider with an API key before running a task.",
        }
    return {
        "ready": None,
        "state": "needs-test",
        "message": "Credential configured; not verified."
        if row["credential_configured"]
        else "This provider uses an existing local authentication workflow. Run a test to verify it.",
    }
