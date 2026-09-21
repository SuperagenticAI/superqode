"""Codex app-server dynamic-tool adapter.

Codex's supported app-server API does not let clients replace its built-in
tool set.  It does, however, accept experimental ``dynamicTools`` on
``thread/start``.  This adapter narrows that client-owned catalogue before a
thread is created and leaves tool execution with the app-server client.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .sdk import RoutingResult


class _Router(Protocol):
    async def route(
        self,
        request: str,
        tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
    ) -> RoutingResult: ...


class CodexDynamicToolsAdapter:
    """Build routed ``thread/start`` parameters for Codex app-server."""

    def __init__(self, router: _Router) -> None:
        self.router = router

    async def thread_start_params(
        self,
        request: str,
        dynamic_tools: Sequence[Mapping[str, Any]],
        *,
        turn_id: str = "",
        base: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], RoutingResult]:
        result = await self.router.route(request, dynamic_tools, turn_id=turn_id)
        params = dict(base or {})
        params["dynamicTools"] = list(result.tools)
        return params, result

    @staticmethod
    def initialize_capabilities(
        base: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return capabilities required by app-server dynamic tools."""
        capabilities = dict(base or {})
        capabilities["experimentalApi"] = True
        return capabilities


__all__ = ["CodexDynamicToolsAdapter"]
