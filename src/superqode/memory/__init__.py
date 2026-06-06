"""Agent memory layer for SuperQode.

This package is provider-neutral. The default provider is local, user-scoped
project memory. SpecMem is supported as a first-class read provider when a
project contains a `.specmem/` workspace.
"""

from __future__ import annotations

from pathlib import Path

from .config import MemoryConfig, MemoryProviderConfig, load_memory_config
from .providers import (
    AgentMemoryProvider,
    CogneeProvider,
    LocalAgentMemoryProvider,
    Mem0Provider,
    SpecMemProvider,
    SupermemoryProvider,
    default_local_memory_path,
    project_hash,
)
from .types import MemoryProviderStatus, MemoryRecord, MemorySearchResult


def create_memory_provider(
    provider: str = "local",
    *,
    project_root: str | Path = ".",
    path: str | Path | None = None,
) -> AgentMemoryProvider:
    """Create a memory provider by id."""
    provider_id = (provider or "local").strip().lower()
    memory_config = load_memory_config(project_root)
    provider_config = memory_config.provider(provider_id)
    if provider_id == "local":
        return LocalAgentMemoryProvider(project_root=project_root, path=path)
    if provider_id == "specmem":
        root = path or provider_config.get("root") or ".specmem"
        return SpecMemProvider(project_root=project_root, root=root, config=provider_config)
    if provider_id == "mem0":
        return Mem0Provider(project_root=project_root, config=provider_config)
    if provider_id == "cognee":
        return CogneeProvider(project_root=project_root, config=provider_config)
    if provider_id == "supermemory":
        return SupermemoryProvider(project_root=project_root, config=provider_config)
    raise ValueError(f"Unknown memory provider: {provider}")


def available_memory_providers(project_root: str | Path = ".") -> list[MemoryProviderStatus]:
    """Return status for local, SpecMem, and optional configured providers."""
    memory_config = load_memory_config(project_root)
    providers = [
        LocalAgentMemoryProvider(project_root=project_root),
        SpecMemProvider(project_root=project_root, config=memory_config.provider("specmem")),
        Mem0Provider(project_root=project_root, config=memory_config.provider("mem0")),
        CogneeProvider(project_root=project_root, config=memory_config.provider("cognee")),
        SupermemoryProvider(
            project_root=project_root, config=memory_config.provider("supermemory")
        ),
    ]
    return [provider.status() for provider in providers]


__all__ = [
    "AgentMemoryProvider",
    "CogneeProvider",
    "LocalAgentMemoryProvider",
    "Mem0Provider",
    "MemoryConfig",
    "MemoryProviderStatus",
    "MemoryProviderConfig",
    "MemoryRecord",
    "MemorySearchResult",
    "SpecMemProvider",
    "SupermemoryProvider",
    "available_memory_providers",
    "create_memory_provider",
    "default_local_memory_path",
    "load_memory_config",
    "project_hash",
]
