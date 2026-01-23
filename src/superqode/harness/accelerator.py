"""
Harness Accelerator - Performance Optimizations for QE.

Centralized performance optimizations for the SuperQode harness:
- Pre-computed tool definitions (compute once, reuse)
- Message format caching (don't rebuild identical messages)
- Background prewarming for slow imports
- Parallel execution utilities

Usage:
    from superqode.harness.accelerator import Accelerator

    # Initialize once during startup
    accel = Accelerator()
    accel.prewarm()

    # Use cached tool definitions
    tools = accel.get_tool_definitions(tool_registry)
"""

import asyncio
import concurrent.futures
import hashlib
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")


@dataclass
class AcceleratorConfig:
    """Configuration for the accelerator."""

    prewarm_litellm: bool = True
    cache_tool_defs: bool = True
    cache_messages: bool = True
    max_cache_size: int = 1000


class Accelerator:
    """Centralized performance optimizations for SuperQode.

    Provides caching, prewarming, and parallel execution utilities
    to minimize latency during QE sessions.
    """

    _instance: Optional["Accelerator"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern - only one accelerator instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[AcceleratorConfig] = None):
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self.config = config or AcceleratorConfig()

        # Thread pool for background tasks
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        # Caches
        self._tool_def_cache: Dict[str, List[Dict]] = {}
        self._message_cache: Dict[str, Any] = {}

        # Prewarm state
        self._prewarm_complete = threading.Event()
        self._prewarm_started = False

    def prewarm(self) -> None:
        """Start prewarming in background (non-blocking).

        Call this during app startup for faster first operations.
        """
        if self._prewarm_started:
            return

        self._prewarm_started = True

        def do_prewarm():
            # Prewarm LiteLLM
            if self.config.prewarm_litellm:
                try:
                    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

                    LiteLLMGateway.prewarm()
                except ImportError:
                    pass

            # Prewarm other heavy imports
            try:
                import rich
                import textual
            except ImportError:
                pass

            self._prewarm_complete.set()

        self._executor.submit(do_prewarm)

    async def prewarm_async(self) -> None:
        """Async version - await to ensure prewarming is complete."""
        if self._prewarm_complete.is_set():
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._wait_for_prewarm)

    def _wait_for_prewarm(self) -> None:
        """Wait for prewarming to complete."""
        self.prewarm()  # Start if not started
        self._prewarm_complete.wait(timeout=10.0)

    def is_ready(self) -> bool:
        """Check if prewarming is complete."""
        return self._prewarm_complete.is_set()

    def get_tool_definitions(self, registry) -> List[Dict]:
        """Get cached tool definitions for a registry.

        Args:
            registry: A ToolRegistry instance

        Returns:
            List of tool definitions in OpenAI format
        """
        if not self.config.cache_tool_defs:
            return self._compute_tool_definitions(registry)

        # Use registry id as cache key
        cache_key = str(id(registry))

        if cache_key not in self._tool_def_cache:
            self._tool_def_cache[cache_key] = self._compute_tool_definitions(registry)

        return self._tool_def_cache[cache_key]

    def _compute_tool_definitions(self, registry) -> List[Dict]:
        """Compute tool definitions from a registry."""
        definitions = []
        for tool in registry.list():
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return definitions

    def cache_message(self, key: str, message: Any) -> None:
        """Cache a message for later retrieval.

        Args:
            key: Cache key (e.g., message hash)
            message: The message object to cache
        """
        if not self.config.cache_messages:
            return

        # Limit cache size
        if len(self._message_cache) >= self.config.max_cache_size:
            # Simple eviction - clear half the cache
            keys = list(self._message_cache.keys())[: self.config.max_cache_size // 2]
            for k in keys:
                self._message_cache.pop(k, None)

        self._message_cache[key] = message

    def get_cached_message(self, key: str) -> Optional[Any]:
        """Get a cached message.

        Args:
            key: Cache key

        Returns:
            Cached message or None if not found
        """
        return self._message_cache.get(key)

    def message_hash(self, content: str, role: str = "user") -> str:
        """Compute a hash for a message.

        Args:
            content: Message content
            role: Message role

        Returns:
            Hash string for caching
        """
        data = f"{role}:{content}".encode("utf-8")
        return hashlib.md5(data).hexdigest()

    def invalidate_tool_cache(self) -> None:
        """Invalidate all cached tool definitions."""
        self._tool_def_cache.clear()

    def invalidate_message_cache(self) -> None:
        """Invalidate all cached messages."""
        self._message_cache.clear()

    def clear_all_caches(self) -> None:
        """Clear all caches."""
        self.invalidate_tool_cache()
        self.invalidate_message_cache()

    async def run_parallel(
        self,
        tasks: List[Callable[[], T]],
        max_concurrent: int = 10,
    ) -> List[T]:
        """Run multiple async tasks in parallel.

        Args:
            tasks: List of async callables
            max_concurrent: Maximum concurrent tasks

        Returns:
            List of results in same order as tasks
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_task(task):
            async with semaphore:
                if asyncio.iscoroutinefunction(task):
                    return await task()
                else:
                    return task()

        return await asyncio.gather(*[limited_task(t) for t in tasks])

    def shutdown(self) -> None:
        """Shutdown the accelerator and release resources."""
        self._executor.shutdown(wait=False)
        self.clear_all_caches()


# Module-level convenience functions
_accelerator: Optional[Accelerator] = None


def get_accelerator() -> Accelerator:
    """Get the global accelerator instance."""
    global _accelerator
    if _accelerator is None:
        _accelerator = Accelerator()
    return _accelerator


def prewarm() -> None:
    """Prewarm the accelerator (call during startup)."""
    get_accelerator().prewarm()


@lru_cache(maxsize=32)
def cached_system_prompt(
    prompt_type: str,
    working_dir: str,
    custom_prompt: str = "",
) -> str:
    """Get a cached system prompt.

    Args:
        prompt_type: Type of prompt (e.g., "minimal", "standard")
        working_dir: Working directory path
        custom_prompt: Optional custom prompt to append

    Returns:
        Cached system prompt string
    """
    from superqode.agent.system_prompts import get_system_prompt, SystemPromptLevel
    from pathlib import Path

    level = getattr(SystemPromptLevel, prompt_type.upper(), SystemPromptLevel.MINIMAL)
    prompt = get_system_prompt(level=level, working_directory=Path(working_dir))

    if custom_prompt:
        prompt += f"\n\n{custom_prompt}"

    return prompt
