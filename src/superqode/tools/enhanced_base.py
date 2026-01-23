"""
Enhanced Tool Framework - Production-Ready Tool System.

Builds upon the base tool system with:
- Tool result caching
- Retry logic with backoff
- Tool metrics and timing
- Tool validation
- Async-first design

Provides a robust foundation for tool execution.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, Union
import json

from .base import Tool, ToolContext, ToolResult


T = TypeVar("T")


class ToolCategory(Enum):
    """Categories of tools."""

    FILE = "file"  # File operations
    SHELL = "shell"  # Shell commands
    SEARCH = "search"  # Search operations
    EDIT = "edit"  # Code editing
    NETWORK = "network"  # Network requests
    ANALYSIS = "analysis"  # Code analysis
    TEST = "test"  # Testing tools
    OTHER = "other"


@dataclass
class ToolMetrics:
    """Metrics for tool execution."""

    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0
    last_called: Optional[datetime] = None

    @property
    def avg_duration_ms(self) -> float:
        """Average execution duration."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        if self.call_count == 0:
            return 100.0
        return (self.success_count / self.call_count) * 100


@dataclass
class CacheEntry:
    """A cached tool result."""

    result: ToolResult
    created_at: datetime = field(default_factory=datetime.now)
    hits: int = 0

    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if cache entry is expired."""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > ttl_seconds


class ToolCache:
    """
    Cache for tool results.

    Caches results based on tool name and arguments hash.
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 300.0,  # 5 minutes
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._tool_ttls: Dict[str, float] = {}

    def _make_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Create cache key from tool name and arguments."""
        args_json = json.dumps(args, sort_keys=True, default=str)
        args_hash = hashlib.md5(args_json.encode()).hexdigest()
        return f"{tool_name}:{args_hash}"

    def set_tool_ttl(self, tool_name: str, ttl: float) -> None:
        """Set TTL for a specific tool."""
        self._tool_ttls[tool_name] = ttl

    def get(self, tool_name: str, args: Dict[str, Any]) -> Optional[ToolResult]:
        """Get cached result."""
        key = self._make_key(tool_name, args)
        entry = self._cache.get(key)

        if entry is None:
            return None

        ttl = self._tool_ttls.get(tool_name, self.default_ttl)
        if entry.is_expired(ttl):
            del self._cache[key]
            return None

        entry.hits += 1
        return entry.result

    def set(self, tool_name: str, args: Dict[str, Any], result: ToolResult) -> None:
        """Cache a result."""
        # Enforce size limit
        if len(self._cache) >= self.max_size:
            # Remove oldest entries
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k].created_at,
            )
            for key in sorted_keys[: self.max_size // 4]:
                del self._cache[key]

        key = self._make_key(tool_name, args)
        self._cache[key] = CacheEntry(result=result)

    def invalidate(self, tool_name: str) -> int:
        """Invalidate all cache entries for a tool."""
        prefix = f"{tool_name}:"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_hits = sum(e.hits for e in self._cache.values())
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "total_hits": total_hits,
        }


class EnhancedTool(Tool):
    """
    Enhanced base class for tools.

    Adds caching, metrics, and retry support to the base Tool class.
    """

    # Override in subclasses
    category: ToolCategory = ToolCategory.OTHER
    cacheable: bool = False
    cache_ttl: float = 300.0  # 5 minutes
    max_retries: int = 0
    retry_delay: float = 1.0

    def __init__(self):
        self._metrics = ToolMetrics()

    @property
    def metrics(self) -> ToolMetrics:
        """Get tool metrics."""
        return self._metrics

    async def execute_with_cache(
        self,
        args: Dict[str, Any],
        ctx: ToolContext,
        cache: Optional[ToolCache] = None,
    ) -> ToolResult:
        """Execute tool with caching support."""
        # Check cache
        if self.cacheable and cache:
            cached = cache.get(self.name, args)
            if cached:
                return cached

        # Execute
        result = await self.execute(args, ctx)

        # Cache result if successful
        if self.cacheable and cache and result.success:
            cache.set(self.name, args, result)

        return result

    async def execute_with_retry(
        self,
        args: Dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute tool with retry logic."""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await self.execute(args, ctx)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)

            if attempt < self.max_retries:
                delay = self.retry_delay * (2**attempt)  # Exponential backoff
                await asyncio.sleep(delay)

        return ToolResult(
            success=False,
            output="",
            error=f"Failed after {self.max_retries + 1} attempts: {last_error}",
        )

    async def execute_with_metrics(
        self,
        args: Dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute tool and track metrics."""
        start_time = time.monotonic()

        self._metrics.call_count += 1
        self._metrics.last_called = datetime.now()

        try:
            result = await self.execute(args, ctx)

            if result.success:
                self._metrics.success_count += 1
            else:
                self._metrics.error_count += 1

            return result

        except Exception as e:
            self._metrics.error_count += 1
            raise

        finally:
            duration_ms = (time.monotonic() - start_time) * 1000
            self._metrics.total_duration_ms += duration_ms

    def validate_args(self, args: Dict[str, Any]) -> List[str]:
        """Validate tool arguments.

        Returns list of validation errors (empty if valid).
        Override in subclasses for custom validation.
        """
        errors = []

        # Check required parameters
        params = self.parameters
        required = params.get("required", [])
        properties = params.get("properties", {})

        for param_name in required:
            if param_name not in args:
                errors.append(f"Missing required parameter: {param_name}")

        # Type checking
        for param_name, value in args.items():
            if param_name in properties:
                param_schema = properties[param_name]
                expected_type = param_schema.get("type")

                if expected_type == "string" and not isinstance(value, str):
                    errors.append(f"Parameter '{param_name}' must be a string")
                elif expected_type == "integer" and not isinstance(value, int):
                    errors.append(f"Parameter '{param_name}' must be an integer")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"Parameter '{param_name}' must be a boolean")
                elif expected_type == "array" and not isinstance(value, list):
                    errors.append(f"Parameter '{param_name}' must be an array")

        return errors

    def to_openai_format_extended(self) -> Dict[str, Any]:
        """Extended OpenAI format with metadata."""
        base = self.to_openai_format()
        base["metadata"] = {
            "category": self.category.value,
            "cacheable": self.cacheable,
            "max_retries": self.max_retries,
        }
        return base


class EnhancedToolRegistry:
    """
    Enhanced tool registry with additional features.

    Provides caching, metrics tracking, and tool management.
    """

    def __init__(
        self,
        enable_cache: bool = True,
        cache_config: Optional[Dict[str, Any]] = None,
    ):
        self._tools: Dict[str, Tool] = {}
        self._cache = ToolCache(**(cache_config or {})) if enable_cache else None
        self._execution_order: List[str] = []  # Track execution order

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """List all tools."""
        return list(self._tools.values())

    def list_by_category(self, category: ToolCategory) -> List[Tool]:
        """List tools by category."""
        return [
            t
            for t in self._tools.values()
            if isinstance(t, EnhancedTool) and t.category == category
        ]

    async def execute(
        self,
        name: str,
        args: Dict[str, Any],
        ctx: ToolContext,
        use_cache: bool = True,
        use_retry: bool = True,
        track_metrics: bool = True,
    ) -> ToolResult:
        """Execute a tool with all enhancements."""
        tool = self.get(name)

        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool not found: {name}",
            )

        # Track execution order
        self._execution_order.append(name)

        # Validate arguments
        if isinstance(tool, EnhancedTool):
            errors = tool.validate_args(args)
            if errors:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Validation errors: {'; '.join(errors)}",
                )

        # Execute with enhancements
        if isinstance(tool, EnhancedTool):
            if track_metrics:
                if use_cache and self._cache:
                    result = await tool.execute_with_cache(args, ctx, self._cache)
                elif use_retry and tool.max_retries > 0:
                    result = await tool.execute_with_retry(args, ctx)
                else:
                    result = await tool.execute_with_metrics(args, ctx)
            else:
                result = await tool.execute(args, ctx)
        else:
            result = await tool.execute(args, ctx)

        return result

    def get_metrics(self) -> Dict[str, ToolMetrics]:
        """Get metrics for all enhanced tools."""
        return {
            name: tool.metrics
            for name, tool in self._tools.items()
            if isinstance(tool, EnhancedTool)
        }

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Get cache statistics."""
        return self._cache.stats() if self._cache else None

    def invalidate_cache(self, tool_name: Optional[str] = None) -> int:
        """Invalidate cache entries."""
        if not self._cache:
            return 0

        if tool_name:
            return self._cache.invalidate(tool_name)
        else:
            count = len(self._cache._cache)
            self._cache.clear()
            return count

    def get_execution_history(self, limit: int = 100) -> List[str]:
        """Get recent tool execution history."""
        return self._execution_order[-limit:]

    @classmethod
    def default(cls) -> "EnhancedToolRegistry":
        """Create registry with default tools."""
        from .file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
        from .edit_tools import EditFileTool, InsertTextTool
        from .shell_tools import BashTool
        from .search_tools import GrepTool, GlobTool

        registry = cls()

        # File operations
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(ListDirectoryTool())

        # Editing
        registry.register(EditFileTool())
        registry.register(InsertTextTool())

        # Shell
        registry.register(BashTool())

        # Search
        registry.register(GrepTool())
        registry.register(GlobTool())

        return registry


def cacheable(ttl: float = 300.0):
    """Decorator to make a tool method cacheable."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
            # Check if we have a cache in context
            cache = getattr(ctx, "_tool_cache", None)

            if cache:
                cached = cache.get(self.name, args)
                if cached:
                    return cached

            result = await func(self, args, ctx)

            if cache and result.success:
                cache.set(self.name, args, result)

            return result

        wrapper._cacheable = True
        wrapper._cache_ttl = ttl
        return wrapper

    return decorator


def retry(max_retries: int = 3, delay: float = 1.0):
    """Decorator to add retry logic to a tool method."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    result = await func(self, args, ctx)
                    if result.success:
                        return result
                    last_error = result.error
                except Exception as e:
                    last_error = str(e)

                if attempt < max_retries:
                    await asyncio.sleep(delay * (2**attempt))

            return ToolResult(
                success=False,
                output="",
                error=f"Failed after {max_retries + 1} attempts: {last_error}",
            )

        return wrapper

    return decorator
