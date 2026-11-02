"""Explicit model-client options for SDKs talking to local OpenAI-compatible servers."""

import os
from urllib.parse import urlsplit

LOCAL_SDK_PROVIDERS = {"ollama", "lmstudio", "mlx", "llamacpp"}


def local_endpoint(provider):
    from superqode.providers.model_specs import normalize_provider_id
    from superqode.providers.registry import PROVIDERS

    provider = normalize_provider_id(provider)
    if provider not in LOCAL_SDK_PROVIDERS:
        return None
    definition = PROVIDERS[provider]
    base = (os.environ.get(definition.base_url_env) or definition.default_base_url or "").rstrip(
        "/"
    )
    url = urlsplit(base)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Configure a valid local inference endpoint without embedded credentials")
    # These SDK clients use Chat Completions, including Ollama's /v1 interface.
    return base if base.endswith("/v1") else base + "/v1"


def local_litellm_options(provider, model):
    endpoint = local_endpoint(provider)
    if not endpoint:
        return None
    return {"model": "openai/" + model, "api_base": endpoint, "api_key": "superqode-local"}
