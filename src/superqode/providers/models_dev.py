"""
Models.dev Integration - Fetch latest AI model data from models.dev

Provides real-time model information including:
- Pricing (input/output per 1M tokens)
- Context window and output limits
- Capabilities (tools, vision, reasoning, etc.)
- Provider metadata

The data is cached locally with a configurable TTL to reduce API calls.

Usage:
    from superqode.providers.models_dev import ModelsDev

    client = ModelsDev()
    await client.refresh()  # Fetch latest data
    models = client.get_models_for_provider("anthropic")
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import aiohttp

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .models import ModelInfo, ModelCapability

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

MODELS_DEV_API_URL = "https://models.dev/api.json"
CACHE_FILE = Path.home() / ".superqode" / "models_cache.json"
DEFAULT_CACHE_TTL = timedelta(hours=24)

# Providers we actively support (others available via OpenRouter)
SUPPORTED_PROVIDERS = {
    "anthropic",
    "openai",
    "google",
    "deepseek",
    "groq",
    "openrouter",
    "xai",
    "mistral",
    "cohere",
    "together",
    "fireworks",
    "perplexity",
}

# Provider ID mappings (models.dev ID -> our ID)
PROVIDER_ID_MAP = {
    "google-ai-studio": "google",
    "google-vertex": "google",
    "google-vertex-anthropic": "google-vertex-anthropic",
    "x-ai": "xai",
}


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ProviderInfo:
    """Provider metadata from models.dev."""

    id: str
    name: str
    env_vars: List[str] = field(default_factory=list)
    doc_url: str = ""
    api_url: str = ""


@dataclass
class CacheMetadata:
    """Metadata for the cached models data."""

    fetched_at: str
    ttl_hours: int = 24
    provider_count: int = 0
    model_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if the cache has expired."""
        try:
            fetched = datetime.fromisoformat(self.fetched_at)
            return datetime.now() - fetched > timedelta(hours=self.ttl_hours)
        except (ValueError, TypeError):
            return True


# ============================================================================
# MODELS.DEV CLIENT
# ============================================================================


class ModelsDev:
    """
    Client for fetching and caching model data from models.dev.

    Features:
    - Async HTTP fetching with aiohttp/httpx fallback
    - Local JSON cache with TTL
    - Transforms models.dev format to ModelInfo
    - Provider filtering and mapping
    """

    def __init__(self, cache_ttl: timedelta = DEFAULT_CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._providers: Dict[str, ProviderInfo] = {}
        self._models: Dict[str, Dict[str, ModelInfo]] = {}
        self._raw_data: Dict[str, Any] = {}
        self._metadata: Optional[CacheMetadata] = None
        self._loaded = False

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    async def ensure_loaded(self) -> bool:
        """
        Ensure model data is loaded, fetching if needed.

        Returns True if data is available (cached or fetched).
        """
        if self._loaded and self._metadata and not self._metadata.is_expired:
            return True

        # Try loading from cache first
        if self._load_cache():
            self._loaded = True
            if not self._metadata.is_expired:
                logger.debug("Using cached models.dev data")
                return True
            logger.debug("Cache expired, will refresh in background")

        # Fetch fresh data
        success = await self.refresh()
        return success or self._loaded

    async def refresh(self, force: bool = False) -> bool:
        """
        Fetch fresh data from models.dev API.

        Args:
            force: If True, fetch even if cache is valid

        Returns:
            True if fetch succeeded
        """
        if not force and self._metadata and not self._metadata.is_expired:
            return True

        logger.info("Fetching models from models.dev...")

        try:
            raw_data = await self._fetch_api()
            if raw_data:
                self._raw_data = raw_data
                self._parse_data(raw_data)
                self._save_cache(raw_data)
                self._loaded = True
                logger.info(
                    f"Loaded {len(self._models)} providers, {sum(len(m) for m in self._models.values())} models"
                )
                return True
        except Exception as e:
            logger.error(f"Failed to fetch from models.dev: {e}")

        return False

    def get_providers(self) -> Dict[str, ProviderInfo]:
        """Get all available providers."""
        return self._providers.copy()

    def get_supported_providers(self) -> Dict[str, ProviderInfo]:
        """Get only the providers we actively support."""
        return {pid: info for pid, info in self._providers.items() if pid in SUPPORTED_PROVIDERS}

    def get_provider(self, provider_id: str) -> Optional[ProviderInfo]:
        """Get a specific provider's info."""
        # Check direct match first
        if provider_id in self._providers:
            return self._providers[provider_id]
        # Check mapped IDs
        mapped_id = PROVIDER_ID_MAP.get(provider_id)
        if mapped_id and mapped_id in self._providers:
            return self._providers[mapped_id]
        return None

    def get_models_for_provider(self, provider_id: str) -> Dict[str, ModelInfo]:
        """Get all models for a provider."""
        # Check direct match
        if provider_id in self._models:
            return self._models[provider_id].copy()
        # Check mapped IDs
        mapped_id = PROVIDER_ID_MAP.get(provider_id)
        if mapped_id and mapped_id in self._models:
            return self._models[mapped_id].copy()
        return {}

    def get_model(self, provider_id: str, model_id: str) -> Optional[ModelInfo]:
        """Get a specific model's info."""
        models = self.get_models_for_provider(provider_id)
        return models.get(model_id)

    def get_all_models(self) -> List[ModelInfo]:
        """Get all models across all providers."""
        all_models = []
        for provider_models in self._models.values():
            all_models.extend(provider_models.values())
        return all_models

    def search_models(self, query: str, limit: int = 20) -> List[ModelInfo]:
        """
        Search models by name or ID.

        Args:
            query: Search string (case-insensitive)
            limit: Maximum results to return
        """
        query_lower = query.lower()
        results = []

        for model in self.get_all_models():
            score = 0
            # Exact ID match
            if query_lower == model.id.lower():
                score = 100
            # ID contains query
            elif query_lower in model.id.lower():
                score = 80
            # Name contains query
            elif query_lower in model.name.lower():
                score = 60
            # Provider contains query
            elif query_lower in model.provider.lower():
                score = 40
            # Description contains query
            elif query_lower in model.description.lower():
                score = 20

            if score > 0:
                results.append((score, model))

        # Sort by score descending, then by name
        results.sort(key=lambda x: (-x[0], x[1].name))
        return [model for _, model in results[:limit]]

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the cache status."""
        return {
            "loaded": self._loaded,
            "provider_count": len(self._providers),
            "model_count": sum(len(m) for m in self._models.values()),
            "cache_file": str(CACHE_FILE),
            "cache_exists": CACHE_FILE.exists(),
            "fetched_at": self._metadata.fetched_at if self._metadata else None,
            "is_expired": self._metadata.is_expired if self._metadata else True,
        }

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    async def _fetch_api(self) -> Optional[Dict[str, Any]]:
        """Fetch data from the models.dev API."""
        # Try aiohttp first (more common in async contexts)
        if HAS_AIOHTTP:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        MODELS_DEV_API_URL, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        logger.error(f"models.dev API returned {resp.status}")
            except Exception as e:
                logger.warning(f"aiohttp fetch failed: {e}")

        # Fallback to httpx
        if HAS_HTTPX:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(MODELS_DEV_API_URL)
                    if resp.status_code == 200:
                        return resp.json()
                    logger.error(f"models.dev API returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"httpx fetch failed: {e}")

        # Last resort: sync request in thread
        try:
            import urllib.request

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._sync_fetch)
            return data
        except Exception as e:
            logger.error(f"All fetch methods failed: {e}")

        return None

    def _sync_fetch(self) -> Optional[Dict[str, Any]]:
        """Synchronous fallback fetch using urllib."""
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        req = urllib.request.Request(MODELS_DEV_API_URL, headers={"User-Agent": "SuperQode/1.0"})

        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))

    def _parse_data(self, raw_data: Dict[str, Any]) -> None:
        """Parse raw models.dev data into our format."""
        self._providers.clear()
        self._models.clear()

        for provider_id, provider_data in raw_data.items():
            if not isinstance(provider_data, dict):
                continue

            # Normalize provider ID
            normalized_id = PROVIDER_ID_MAP.get(provider_id, provider_id)

            # Parse provider info
            provider_info = ProviderInfo(
                id=normalized_id,
                name=provider_data.get("name", provider_id),
                env_vars=provider_data.get("env", []),
                doc_url=provider_data.get("doc", ""),
                api_url=provider_data.get("api", ""),
            )

            # Merge if provider already exists (e.g., google-ai-studio + google-vertex)
            if normalized_id in self._providers:
                existing = self._providers[normalized_id]
                # Merge env vars
                existing.env_vars = list(set(existing.env_vars + provider_info.env_vars))
            else:
                self._providers[normalized_id] = provider_info

            # Parse models
            models_data = provider_data.get("models", {})
            if normalized_id not in self._models:
                self._models[normalized_id] = {}

            for model_id, model_data in models_data.items():
                if not isinstance(model_data, dict):
                    continue

                model_info = self._parse_model(normalized_id, model_id, model_data)
                if model_info:
                    self._models[normalized_id][model_id] = model_info

        # Update metadata
        self._metadata = CacheMetadata(
            fetched_at=datetime.now().isoformat(),
            ttl_hours=int(self.cache_ttl.total_seconds() / 3600),
            provider_count=len(self._providers),
            model_count=sum(len(m) for m in self._models.values()),
        )

    def _parse_model(
        self, provider_id: str, model_id: str, data: Dict[str, Any]
    ) -> Optional[ModelInfo]:
        """Parse a single model's data."""
        try:
            # Extract cost info
            cost = data.get("cost", {})
            input_price = cost.get("input", 0) if isinstance(cost, dict) else 0
            output_price = cost.get("output", 0) if isinstance(cost, dict) else 0

            # Extract limits
            limits = data.get("limit", {})
            context_window = limits.get("context", 128000) if isinstance(limits, dict) else 128000
            max_output = limits.get("output", 4096) if isinstance(limits, dict) else 4096

            # Build capabilities list
            capabilities = []
            if data.get("tool_call"):
                capabilities.append(ModelCapability.TOOLS)
            if data.get("reasoning"):
                capabilities.append(ModelCapability.REASONING)

            # Check modalities for vision
            modalities = data.get("modalities", {})
            input_modalities = modalities.get("input", []) if isinstance(modalities, dict) else []
            if "image" in input_modalities or "video" in input_modalities:
                capabilities.append(ModelCapability.VISION)

            # Assume streaming for most models
            capabilities.append(ModelCapability.STREAMING)

            # JSON mode if tools supported
            if data.get("tool_call"):
                capabilities.append(ModelCapability.JSON_MODE)

            # Long context flag
            if context_window >= 100000:
                capabilities.append(ModelCapability.LONG_CONTEXT)

            # Code optimization (heuristic based on name/family)
            name_lower = data.get("name", "").lower()
            family_lower = data.get("family", "").lower()
            if any(kw in name_lower or kw in family_lower for kw in ["code", "coder", "codex"]):
                capabilities.append(ModelCapability.CODE)

            # Build description
            description = ""
            if data.get("reasoning"):
                description = "Advanced reasoning model"
            elif "flash" in name_lower or "mini" in name_lower or "haiku" in name_lower:
                description = "Fast and cost-effective"
            elif "opus" in name_lower or "pro" in name_lower:
                description = "Most capable variant"
            elif "sonnet" in name_lower:
                description = "Balanced performance and cost"

            # Recommended for
            recommended = []
            if ModelCapability.CODE in capabilities:
                recommended.append("coding")
            if ModelCapability.REASONING in capabilities:
                recommended.append("complex reasoning")
            if ModelCapability.VISION in capabilities:
                recommended.append("vision")
            if input_price == 0 and output_price == 0:
                recommended.append("free")
            if input_price < 1:
                recommended.append("budget")
            if not recommended:
                recommended.append("general")

            return ModelInfo(
                id=model_id,
                name=data.get("name", model_id),
                provider=provider_id,
                input_price=float(input_price),
                output_price=float(output_price),
                context_window=int(context_window),
                max_output=int(max_output),
                capabilities=capabilities,
                description=description,
                recommended_for=recommended,
                released=data.get("release_date", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to parse model {provider_id}/{model_id}: {e}")
            return None

    def _load_cache(self) -> bool:
        """Load data from local cache file."""
        if not CACHE_FILE.exists():
            return False

        try:
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)

            # Parse metadata
            meta = cache_data.get("_metadata", {})
            self._metadata = CacheMetadata(
                fetched_at=meta.get("fetched_at", ""),
                ttl_hours=meta.get("ttl_hours", 24),
                provider_count=meta.get("provider_count", 0),
                model_count=meta.get("model_count", 0),
            )

            # Parse the actual data
            raw_data = {k: v for k, v in cache_data.items() if k != "_metadata"}
            if raw_data:
                self._raw_data = raw_data
                self._parse_data(raw_data)
                return True

        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

        return False

    def _save_cache(self, raw_data: Dict[str, Any]) -> bool:
        """Save data to local cache file."""
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            cache_data = raw_data.copy()
            cache_data["_metadata"] = {
                "fetched_at": datetime.now().isoformat(),
                "ttl_hours": int(self.cache_ttl.total_seconds() / 3600),
                "provider_count": len(self._providers),
                "model_count": sum(len(m) for m in self._models.values()),
            }

            with open(CACHE_FILE, "w") as f:
                json.dump(cache_data, f)

            logger.debug(f"Saved models cache to {CACHE_FILE}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
            return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_instance: Optional[ModelsDev] = None


def get_models_dev() -> ModelsDev:
    """Get the singleton ModelsDev instance."""
    global _instance
    if _instance is None:
        _instance = ModelsDev()
    return _instance


async def get_model_info_live(provider_id: str, model_id: str) -> Optional[ModelInfo]:
    """
    Get model info, fetching from models.dev if needed.

    This is a convenience function that ensures data is loaded.
    """
    client = get_models_dev()
    await client.ensure_loaded()
    return client.get_model(provider_id, model_id)


async def get_models_for_provider_live(provider_id: str) -> Dict[str, ModelInfo]:
    """
    Get all models for a provider, fetching from models.dev if needed.
    """
    client = get_models_dev()
    await client.ensure_loaded()
    return client.get_models_for_provider(provider_id)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ModelsDev",
    "ProviderInfo",
    "CacheMetadata",
    "get_models_dev",
    "get_model_info_live",
    "get_models_for_provider_live",
    "SUPPORTED_PROVIDERS",
    "MODELS_DEV_API_URL",
]
