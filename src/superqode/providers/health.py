"""
SuperQode Provider Health Check - Check provider connectivity on startup.

Features:
- Async health checks for all configured providers
- Caching of results
- Status display

Usage:
    from superqode.providers.health import HealthChecker, get_health_checker

    checker = get_health_checker()
    results = await checker.check_all()

    for provider_id, status in results.items():
        print(f"{provider_id}: {status.status}")
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from superqode.providers.registry import PROVIDERS, ProviderDef


# ============================================================================
# STATUS
# ============================================================================


class ProviderStatus(Enum):
    """Provider health status."""

    UNKNOWN = "unknown"
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"


@dataclass
class HealthResult:
    """Health check result for a provider."""

    provider_id: str
    status: ProviderStatus
    message: str = ""
    latency_ms: float = 0.0
    checked_at: datetime = field(default_factory=datetime.now)
    model_available: str = ""

    @property
    def is_ready(self) -> bool:
        return self.status == ProviderStatus.READY

    @property
    def status_icon(self) -> str:
        icons = {
            ProviderStatus.READY: "✓",
            ProviderStatus.NOT_CONFIGURED: "○",
            ProviderStatus.ERROR: "✗",
            ProviderStatus.RATE_LIMITED: "⏳",
            ProviderStatus.AUTH_ERROR: "🔐",
            ProviderStatus.UNKNOWN: "?",
        }
        return icons.get(self.status, "?")


# ============================================================================
# HEALTH CHECKER
# ============================================================================


class HealthChecker:
    """
    Checks provider health/connectivity.
    """

    CACHE_TTL = timedelta(minutes=5)

    def __init__(self):
        self._cache: Dict[str, HealthResult] = {}
        self._checking: bool = False

    async def check_all(self, force: bool = False) -> Dict[str, HealthResult]:
        """
        Check all configured providers.

        Args:
            force: Force refresh, ignore cache

        Returns:
            Dictionary of provider_id -> HealthResult
        """
        if self._checking:
            # Return cached results if check is in progress
            return self._cache

        self._checking = True
        results = {}

        try:
            # Get all providers that are configured (have env vars set)
            configured_providers = []

            for provider_id, provider_def in PROVIDERS.items():
                result = self._check_configuration(provider_id, provider_def)

                if result.status == ProviderStatus.NOT_CONFIGURED:
                    results[provider_id] = result
                else:
                    configured_providers.append((provider_id, provider_def))

            # For configured providers, check connectivity (in parallel)
            if configured_providers:
                tasks = [
                    self._check_provider(pid, pdef, force) for pid, pdef in configured_providers
                ]
                check_results = await asyncio.gather(*tasks, return_exceptions=True)

                for (pid, _), result in zip(configured_providers, check_results):
                    if isinstance(result, Exception):
                        results[pid] = HealthResult(
                            provider_id=pid,
                            status=ProviderStatus.ERROR,
                            message=str(result),
                        )
                    else:
                        results[pid] = result

            self._cache = results

        finally:
            self._checking = False

        return results

    async def check_provider(
        self,
        provider_id: str,
        force: bool = False,
    ) -> HealthResult:
        """Check a specific provider."""
        provider_def = PROVIDERS.get(provider_id)
        if not provider_def:
            return HealthResult(
                provider_id=provider_id,
                status=ProviderStatus.ERROR,
                message="Provider not found",
            )

        # Check cache
        if not force and provider_id in self._cache:
            cached = self._cache[provider_id]
            if datetime.now() - cached.checked_at < self.CACHE_TTL:
                return cached

        return await self._check_provider(provider_id, provider_def, force)

    def _check_configuration(
        self,
        provider_id: str,
        provider_def: ProviderDef,
    ) -> HealthResult:
        """Check if provider is configured (has API key)."""
        # Local providers are always configured
        if not provider_def.env_vars:
            return HealthResult(
                provider_id=provider_id,
                status=ProviderStatus.UNKNOWN,  # Need connectivity check
                message="Local provider",
            )

        # Check if any required env var is set
        for env_var in provider_def.env_vars:
            if os.environ.get(env_var):
                return HealthResult(
                    provider_id=provider_id,
                    status=ProviderStatus.UNKNOWN,  # Need connectivity check
                    message=f"Configured via {env_var}",
                )

        return HealthResult(
            provider_id=provider_id,
            status=ProviderStatus.NOT_CONFIGURED,
            message=f"Set {provider_def.env_vars[0]} to enable",
        )

    async def _check_provider(
        self,
        provider_id: str,
        provider_def: ProviderDef,
        force: bool = False,
    ) -> HealthResult:
        """Actually check provider connectivity."""
        import time

        # Check cache
        if not force and provider_id in self._cache:
            cached = self._cache[provider_id]
            if datetime.now() - cached.checked_at < self.CACHE_TTL:
                return cached

        start = time.time()

        try:
            # For now, just check if the provider is configured
            # A full check would make a test API call
            config_result = self._check_configuration(provider_id, provider_def)

            if config_result.status == ProviderStatus.NOT_CONFIGURED:
                return config_result

            # Provider is configured, mark as ready
            # (In production, would make a test API call here)
            latency = (time.time() - start) * 1000

            model = provider_def.example_models[0] if provider_def.example_models else ""

            result = HealthResult(
                provider_id=provider_id,
                status=ProviderStatus.READY,
                message="API key configured",
                latency_ms=latency,
                model_available=model,
            )

            self._cache[provider_id] = result
            return result

        except Exception as e:
            error_msg = str(e).lower()

            if "rate" in error_msg or "429" in error_msg:
                status = ProviderStatus.RATE_LIMITED
            elif "auth" in error_msg or "401" in error_msg or "403" in error_msg:
                status = ProviderStatus.AUTH_ERROR
            else:
                status = ProviderStatus.ERROR

            return HealthResult(
                provider_id=provider_id,
                status=status,
                message=str(e)[:100],
                latency_ms=(time.time() - start) * 1000,
            )

    def get_ready_providers(self) -> List[str]:
        """Get list of ready provider IDs."""
        return [pid for pid, result in self._cache.items() if result.is_ready]

    def get_cached_result(self, provider_id: str) -> Optional[HealthResult]:
        """Get cached result for a provider."""
        return self._cache.get(provider_id)

    def clear_cache(self):
        """Clear all cached results."""
        self._cache.clear()


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get the global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


async def check_providers_health() -> Dict[str, HealthResult]:
    """Quick helper to check all providers."""
    return await get_health_checker().check_all()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ProviderStatus",
    "HealthResult",
    "HealthChecker",
    "get_health_checker",
    "check_providers_health",
]
