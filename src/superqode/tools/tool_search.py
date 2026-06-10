"""Deferred tool loading + tool_search, built for local-model context budgets.

Every tool schema sent to the model costs prompt tokens on *every* call.
On an 8K-context local model, a 20-tool registry can eat a quarter of the
window before any conversation happens. Deferred loading fixes that:
heavy/rarely-used tools stay registered but unadvertised, and a
lightweight ``tool_search`` tool lets the model discover and activate them
on demand. Activated schemas appear on the very next model call.

Enable with ``SUPERQODE_DEFERRED_TOOLS``:

- unset/empty/``off`` — disabled (all tools advertised, today's behavior)
- ``auto`` — defer a curated heavy set, but only for local providers
  (hosted models have big windows; the savings don't matter)
- ``all``  — defer the heavy set for every provider
- comma-separated tool names — defer exactly those

Scoring is a dependency-free lexical rank over name + description (term
frequency with name matches weighted up), which is plenty for double-digit
tool counts.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

from .base import Tool, ToolContext, ToolRegistry, ToolResult

DEFERRED_TOOLS_ENV = "SUPERQODE_DEFERRED_TOOLS"

# Tools that earn their prompt cost only occasionally. The core coding loop
# (read/write/edit/apply_patch/bash/grep/glob/todo) is never deferred.
DEFAULT_DEFERRABLE = (
    "web_search",
    "web_fetch",
    "fetch",
    "download",
    "view_image",
    "shell_session",
    "lsp",
    "code_search",
    "diagnostics",
    "monty_python_repl",
    "skill",
    "read_skill",
    "create_skill",
    "mcp_search",
    "mcp_execute",
    "mcp_list_resources",
    "mcp_read_resource",
    "mcp_list_prompts",
    "mcp_get_prompt",
    "a2a_call",
    "a2a_discover",
    "sub_agent",
    "task_coordinator",
    "spawn_agent",
    "send_input",
    "wait_agent",
    "list_agents",
    "close_agent",
    "request_permissions",
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def score_tool(query_tokens: List[str], name: str, description: str) -> float:
    """Lexical relevance of one tool for a query. 0 when nothing matches."""
    if not query_tokens:
        return 0.0
    name_tokens = set(_tokens(name))
    desc_tokens = _tokens(description)
    desc_counts: Dict[str, int] = {}
    for t in desc_tokens:
        desc_counts[t] = desc_counts.get(t, 0) + 1
    score = 0.0
    for term in query_tokens:
        if term in name_tokens:
            score += 3.0
        score += min(desc_counts.get(term, 0), 3) * 1.0
        # Prefix matches help with stemming-ish queries ("search" ~ "searches").
        if any(t.startswith(term) or term.startswith(t) for t in name_tokens):
            score += 1.0
    return score


def search_deferred(registry: ToolRegistry, query: str, limit: int = 3) -> List[Tuple[float, Tool]]:
    """Rank deferred tools for a query, best first."""
    query_tokens = _tokens(query)
    scored: List[Tuple[float, Tool]] = []
    for tool in registry.deferred_tools():
        s = score_tool(query_tokens, tool.name, tool.description)
        if s > 0:
            scored.append((s, tool))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return scored[:limit]


def apply_deferred_tool_policy(registry: ToolRegistry, provider: str = "", model: str = "") -> int:
    """Defer tools per the SUPERQODE_DEFERRED_TOOLS policy. Returns count deferred.

    Registers the tool_search tool whenever anything was deferred so the
    model can always find what was hidden.
    """
    raw = os.environ.get(DEFERRED_TOOLS_ENV, "").strip().lower()
    if not raw or raw in ("0", "off", "false", "no"):
        return 0
    if not hasattr(registry, "defer"):
        return 0

    if raw == "auto":
        try:
            from ..providers.registry import PROVIDERS, ProviderCategory

            provider_def = PROVIDERS.get((provider or "").lower())
            is_local = bool(provider_def and provider_def.category == ProviderCategory.LOCAL)
        except Exception:
            is_local = False
        if not is_local:
            return 0
        names = DEFAULT_DEFERRABLE
    elif raw == "all":
        names = DEFAULT_DEFERRABLE
    else:
        names = tuple(part.strip() for part in raw.split(",") if part.strip())

    count = registry.defer(*names)
    if count and registry.get("tool_search") is None:
        registry.register(ToolSearchTool())
    return count


class ToolSearchTool(Tool):
    """Discover and activate tools that are not currently advertised."""

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Search for additional tools that exist but are not currently "
            "loaded (web access, images, interactive sessions, LSP, MCP, "
            "sub-agents, ...). Matching tools are activated and their full "
            "schemas become available on your next step. Use this when no "
            "currently available tool fits the task."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you need, e.g. 'fetch a web page' or 'run interactive REPL'.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        registry = getattr(ctx, "tool_registry", None)
        if registry is None or not hasattr(registry, "deferred_tools"):
            return ToolResult(
                success=False, output="", error="tool_search is unavailable in this context."
            )
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Provide a query.")

        deferred = registry.deferred_tools()
        if not deferred:
            return ToolResult(
                success=True,
                output="No additional tools are deferred - everything available is already loaded.",
            )

        matches = search_deferred(registry, query)
        if not matches:
            available = ", ".join(t.name for t in deferred)
            return ToolResult(
                success=True,
                output=(
                    f"No deferred tool matched {query!r}. "
                    f"Deferred tools that can be activated: {available}"
                ),
            )

        activated = []
        for _score, tool in matches:
            registry.activate(tool.name)
            first_sentence = tool.description.split(". ")[0][:140]
            activated.append(f"- {tool.name}: {first_sentence}")
        return ToolResult(
            success=True,
            output=(
                "Activated tool(s) - full schemas are available from your next step:\n"
                + "\n".join(activated)
            ),
            metadata={"activated": [t.name for _s, t in matches]},
        )


__all__ = [
    "DEFAULT_DEFERRABLE",
    "DEFERRED_TOOLS_ENV",
    "ToolSearchTool",
    "apply_deferred_tool_policy",
    "score_tool",
    "search_deferred",
]
