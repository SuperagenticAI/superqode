"""Local provider auto-discovery service.

This module provides automatic discovery of running local LLM servers
by scanning common ports and detecting provider types.
"""

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from superqode.providers.local.base import (
    LocalProviderType,
    LocalProviderClient,
    LocalModel,
    ProviderStatus,
)


# Default ports for each provider type
DEFAULT_PORTS = {
    LocalProviderType.OLLAMA: [11434],
    LocalProviderType.LMSTUDIO: [1234],
    LocalProviderType.VLLM: [8000],
    LocalProviderType.SGLANG: [30000],
    LocalProviderType.TGI: [8080],
    LocalProviderType.MLX: [8080],
    LocalProviderType.LLAMACPP: [8080],
    LocalProviderType.OPENAI_COMPAT: [8000, 8080, 5000],
}

# All ports to scan for discovery
ALL_PORTS = [11434, 1234, 8000, 8080, 30000, 5000, 3000]


@dataclass
class DiscoveredProvider:
    """A discovered local LLM provider.

    Attributes:
        provider_type: Type of provider detected
        host: Provider host URL
        port: Port number
        version: Provider version (if available)
        models: List of available models
        running_models: List of models currently loaded
        latency_ms: Discovery latency
    """

    provider_type: LocalProviderType
    host: str
    port: int
    version: str = ""
    models: List[LocalModel] = field(default_factory=list)
    running_models: List[LocalModel] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def url(self) -> str:
        """Get the full provider URL."""
        return f"http://localhost:{self.port}"

    @property
    def model_count(self) -> int:
        """Get number of available models."""
        return len(self.models)

    @property
    def running_count(self) -> int:
        """Get number of running models."""
        return len(self.running_models)


class LocalProviderDiscovery:
    """Discovers running local LLM servers.

    Scans common ports and detects provider types:
    - 11434: Ollama
    - 1234: LM Studio
    - 8000: vLLM, OpenAI-compatible
    - 30000: SGLang
    - 8080: TGI, MLX, llama.cpp
    """

    def __init__(self, timeout: float = 2.0):
        """Initialize the discovery service.

        Args:
            timeout: Connection timeout for port scanning.
        """
        self._timeout = timeout
        self._discovered: Dict[str, DiscoveredProvider] = {}

    async def scan_all(self) -> Dict[str, DiscoveredProvider]:
        """Scan all common ports for local providers.

        Returns:
            Dict mapping host:port to DiscoveredProvider.
        """
        # Check all ports in parallel
        tasks = []
        for port in ALL_PORTS:
            tasks.append(self._scan_port(port))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        discovered = {}
        for result in results:
            if isinstance(result, DiscoveredProvider):
                key = f"localhost:{result.port}"
                discovered[key] = result

        self._discovered = discovered
        return discovered

    async def scan_port(self, port: int) -> Optional[DiscoveredProvider]:
        """Scan a specific port for a provider.

        Args:
            port: Port number to scan.

        Returns:
            DiscoveredProvider if found, None otherwise.
        """
        return await self._scan_port(port)

    async def _scan_port(self, port: int) -> Optional[DiscoveredProvider]:
        """Internal port scanning implementation."""
        # First check if port is open
        if not await self._is_port_open(port):
            return None

        start_time = time.time()

        # Try to detect provider type
        provider_type = await self._detect_provider_type(port)

        if provider_type is None:
            return None

        latency = (time.time() - start_time) * 1000

        # Get provider details
        version = await self._get_version(port, provider_type)
        models = await self._list_models(port, provider_type)
        running = await self._list_running(port, provider_type)

        return DiscoveredProvider(
            provider_type=provider_type,
            host=f"http://localhost:{port}",
            port=port,
            version=version,
            models=models,
            running_models=running,
            latency_ms=latency,
        )

    async def _is_port_open(self, port: int) -> bool:
        """Check if a port is open."""
        loop = asyncio.get_event_loop()

        def check():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._timeout)
            try:
                result = sock.connect_ex(("localhost", port))
                return result == 0
            finally:
                sock.close()

        return await loop.run_in_executor(None, check)

    async def _detect_provider_type(self, port: int) -> Optional[LocalProviderType]:
        """Detect the provider type from port responses."""
        loop = asyncio.get_event_loop()

        def detect():
            # Try Ollama-specific endpoint
            if port == 11434:
                try:
                    req = Request(f"http://localhost:{port}/api/tags")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        if "models" in data:
                            return LocalProviderType.OLLAMA
                except Exception:
                    pass

            # Try LM Studio-specific detection
            if port == 1234:
                try:
                    req = Request(f"http://localhost:{port}/v1/models")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        if "data" in data:
                            return LocalProviderType.LMSTUDIO
                except Exception:
                    pass

            # Try SGLang-specific detection (has /health endpoint)
            if port == 30000:
                try:
                    req = Request(f"http://localhost:{port}/health")
                    with urlopen(req, timeout=self._timeout) as resp:
                        return LocalProviderType.SGLANG
                except Exception:
                    pass

            # Try TGI-specific detection (has /info endpoint)
            try:
                req = Request(f"http://localhost:{port}/info")
                with urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read())
                    if "model_id" in data:
                        return LocalProviderType.TGI
            except Exception:
                pass

            # Try vLLM-specific detection
            if port == 8000:
                try:
                    req = Request(f"http://localhost:{port}/health")
                    with urlopen(req, timeout=self._timeout) as resp:
                        # vLLM health endpoint exists
                        pass
                    # Also check for models endpoint
                    req2 = Request(f"http://localhost:{port}/v1/models")
                    with urlopen(req2, timeout=self._timeout) as resp:
                        return LocalProviderType.VLLM
                except Exception:
                    pass

            # Generic OpenAI-compatible check
            try:
                req = Request(f"http://localhost:{port}/v1/models")
                with urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read())
                    if "data" in data:
                        # Could be MLX, llama.cpp, or generic OpenAI-compatible
                        if port == 8080:
                            return LocalProviderType.MLX  # Common MLX port
                        return LocalProviderType.OPENAI_COMPAT
            except Exception:
                pass

            return None

        return await loop.run_in_executor(None, detect)

    async def _get_version(self, port: int, provider_type: LocalProviderType) -> str:
        """Get provider version string."""
        loop = asyncio.get_event_loop()

        def get_ver():
            if provider_type == LocalProviderType.OLLAMA:
                try:
                    req = Request(f"http://localhost:{port}/api/version")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        return data.get("version", "")
                except Exception:
                    pass

            if provider_type == LocalProviderType.TGI:
                try:
                    req = Request(f"http://localhost:{port}/info")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        return data.get("version", "")
                except Exception:
                    pass

            return ""

        return await loop.run_in_executor(None, get_ver)

    async def _list_models(self, port: int, provider_type: LocalProviderType) -> List[LocalModel]:
        """List available models from provider."""
        loop = asyncio.get_event_loop()

        def list_mod():
            models = []

            if provider_type == LocalProviderType.OLLAMA:
                try:
                    req = Request(f"http://localhost:{port}/api/tags")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        for m in data.get("models", []):
                            models.append(
                                LocalModel(
                                    id=m.get("name", ""),
                                    name=m.get("name", "").split(":")[0].title(),
                                    size_bytes=m.get("size", 0),
                                )
                            )
                except Exception:
                    pass

            elif provider_type in (
                LocalProviderType.LMSTUDIO,
                LocalProviderType.VLLM,
                LocalProviderType.OPENAI_COMPAT,
                LocalProviderType.MLX,
            ):
                try:
                    req = Request(f"http://localhost:{port}/v1/models")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        for m in data.get("data", []):
                            models.append(
                                LocalModel(
                                    id=m.get("id", ""),
                                    name=m.get("id", "").split("/")[-1],
                                )
                            )
                except Exception:
                    pass

            elif provider_type == LocalProviderType.TGI:
                try:
                    req = Request(f"http://localhost:{port}/info")
                    with urlopen(req, timeout=self._timeout) as resp:
                        data = json.loads(resp.read())
                        model_id = data.get("model_id", "")
                        if model_id:
                            models.append(
                                LocalModel(
                                    id=model_id,
                                    name=model_id.split("/")[-1],
                                    context_window=data.get("max_input_length", 4096),
                                )
                            )
                except Exception:
                    pass

            return models

        return await loop.run_in_executor(None, list_mod)

    async def _list_running(self, port: int, provider_type: LocalProviderType) -> List[LocalModel]:
        """List running models from provider."""
        loop = asyncio.get_event_loop()

        def list_run():
            if provider_type != LocalProviderType.OLLAMA:
                return []  # Only Ollama has running model tracking

            try:
                req = Request(f"http://localhost:{port}/api/ps")
                with urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read())
                    return [
                        LocalModel(
                            id=m.get("name", ""),
                            name=m.get("name", "").split(":")[0].title(),
                            running=True,
                            vram_usage=m.get("size_vram", 0),
                        )
                        for m in data.get("models", [])
                    ]
            except Exception:
                return []

        return await loop.run_in_executor(None, list_run)

    async def discover_models(self) -> List[LocalModel]:
        """Discover all available models from all running providers.

        Returns:
            Combined list of LocalModel from all discovered providers.
        """
        if not self._discovered:
            await self.scan_all()

        all_models = []
        for provider in self._discovered.values():
            for model in provider.models:
                # Add provider info to model
                model.details["provider_type"] = provider.provider_type.value
                model.details["provider_host"] = provider.host
                all_models.append(model)

        return all_models

    def get_discovered(self) -> Dict[str, DiscoveredProvider]:
        """Get cached discovered providers."""
        return self._discovered


# Singleton instance
_discovery_instance: Optional[LocalProviderDiscovery] = None


def get_discovery_service() -> LocalProviderDiscovery:
    """Get the global discovery service instance.

    Returns:
        LocalProviderDiscovery instance.
    """
    global _discovery_instance
    if _discovery_instance is None:
        _discovery_instance = LocalProviderDiscovery()
    return _discovery_instance


async def quick_scan() -> Dict[str, DiscoveredProvider]:
    """Perform a quick scan for local providers.

    Returns:
        Dict of discovered providers.
    """
    service = get_discovery_service()
    return await service.scan_all()
