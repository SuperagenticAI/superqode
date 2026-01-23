"""Provider and model management for SuperQode CLI."""

from superqode.providers.manager import ProviderManager, ProviderInfo, ModelInfo
from superqode.providers.registry import (
    PROVIDERS,
    ProviderDef,
    ProviderTier,
    ProviderCategory,
    get_provider,
    get_providers_by_category,
    get_providers_by_tier,
    get_all_provider_ids,
    get_free_providers,
    get_local_providers,
)

__all__ = [
    # Legacy manager
    "ProviderManager",
    "ProviderInfo",
    "ModelInfo",
    # New registry
    "PROVIDERS",
    "ProviderDef",
    "ProviderTier",
    "ProviderCategory",
    "get_provider",
    "get_providers_by_category",
    "get_providers_by_tier",
    "get_all_provider_ids",
    "get_free_providers",
    "get_local_providers",
]
