"""Desktop connection metadata and ephemeral credentials, never persisted secrets."""

from __future__ import annotations

from superqode.providers.credentials import provider_api_key
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


def install(credentials: dict[str, str], params: dict):
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
        credentials[definition.id] = value.strip()
    return {"ok": True}


def environment(credentials: dict[str, str]) -> dict[str, str]:
    output = {}
    for provider, value in credentials.items():
        for variable in key_provider(provider).env_vars:
            output[variable] = value
    return output


def list_connections(credentials: dict[str, str]):
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
                "verified": False,
            }
        )
    return result


def inspect_route(credentials: dict[str, str], params: dict):
    provider = str(params.get("provider") or "").strip()
    model = str(params.get("model") or "").strip()
    if not provider or not model:
        return {"ready": False, "state": "incomplete", "message": "Choose a provider and model."}
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
