"""Provider credential resolution.

Keeps provider API-key lookup in one place so status checks, model discovery,
and request execution all use the same precedence:

1. Environment variables.
2. Explicit local auth storage (``~/.superqode/auth.json``).

SuperQode account identity is intentionally not involved here.
"""

from __future__ import annotations

import os
from typing import Optional

from superqode.auth import ApiAuth, OAuthAuth, WellKnownAuth, get as get_local_auth

from .registry import ProviderDef


def provider_api_key(provider_def: ProviderDef) -> Optional[str]:
    """Resolve the API key/token for a provider without exposing it.

    Environment variables win over local storage. OAuth access tokens are used
    only while still valid; refresh is provider-specific and should live in the
    provider's OAuth implementation, not in this generic resolver.
    """
    for env_name in provider_def.env_vars or []:
        value = os.environ.get(env_name)
        if value:
            return value

    local_auth = get_local_auth(provider_def.id)
    if isinstance(local_auth, ApiAuth):
        return local_auth.key or None
    if isinstance(local_auth, OAuthAuth) and not local_auth.is_expired():
        return local_auth.access or None
    if isinstance(local_auth, WellKnownAuth):
        return local_auth.token or local_auth.key or None
    return None


def sync_provider_env(provider_def: ProviderDef) -> Optional[str]:
    """Populate the provider's primary env var from local auth when needed.

    Some SDKs/LiteLLM integrations read only environment variables. This helper
    keeps env precedence intact: existing environment values are never replaced.
    """
    key = provider_api_key(provider_def)
    if not key or not provider_def.env_vars:
        return key

    if provider_def.id == "google":
        os.environ.setdefault("GOOGLE_API_KEY", key)
        os.environ.setdefault("GEMINI_API_KEY", key)
        return key

    primary = provider_def.env_vars[0]
    os.environ.setdefault(primary, key)
    return key
