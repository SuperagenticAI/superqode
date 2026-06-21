"""
Semantic Search Tool - AST-based semantic code search via cocoindex-code.

This complements the lexical/symbol search tools (grep, glob, code_search):

- grep         -> find an exact regex/text pattern
- code_search  -> find a symbol by name (definitions/references)
- semantic_search -> find code by MEANING ("how are sessions managed")

It is backed by the optional `cocoindex-code` package (Apache-2.0). AST chunking
and embedding work live in cocoindex-code's *daemon* process; this tool only
talks to that daemon over a local socket via ``cocoindex_code.client``.

Install the integration with::

    pip install 'superqode[semantic]'

then index a project once (the daemon starts automatically)::

    ccc init --litellm-model ollama/nomic-embed-text && ccc index

When `cocoindex-code` is not installed the tool is simply not registered, so
there is no hard dependency.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, ToolContext


@functools.lru_cache(maxsize=1)
def is_semantic_search_available() -> bool:
    """True when the optional cocoindex-code client is importable.

    Cached because importlib resolution is the only cost and it cannot change
    within a process. Use ``find_spec`` so registry construction does not import
    the client and its transitive dependencies.
    """
    try:
        return importlib.util.find_spec("cocoindex_code.client") is not None
    except (ImportError, ValueError):
        return False


_INSTALL_HINT = (
    "Semantic search needs the optional 'cocoindex-code' package. Install it with "
    "`pip install 'superqode[semantic]'`, then run "
    "`ccc init --litellm-model ollama/nomic-embed-text && ccc index` once in this project. "
    "For sentence-transformers instead of Ollama/LiteLLM, install `cocoindex-code[full]`."
)


def is_available() -> bool:
    """Backward-compatible alias for Airplane Mode readiness checks."""
    return is_semantic_search_available()


def install_hint() -> str:
    """Return the install hint for optional semantic search support."""
    return _INSTALL_HINT


class SemanticSearchTool(Tool):
    """Meaning-based code search backed by cocoindex-code's vector index."""

    read_only = True

    MAX_LIMIT = 50
    # Per-result snippet cap so a few large chunks can't flood the context.
    SNIPPET_MAX_LINES = 25

    @property
    def name(self) -> str:
        return "semantic_search"

    @property
    def description(self) -> str:
        return (
            "Search code by MEANING using semantic (embedding) similarity over an "
            "AST-chunked index. Finds relevant code even when you don't know the exact "
            "keywords or symbol names (e.g. 'where is the conversation history compacted', "
            "'logic that decides if a local model gets tools').\n"
            "- Use this for conceptual/fuzzy lookups and exploring unfamiliar code.\n"
            "- For an exact pattern use `grep`; for a known symbol name use `code_search`.\n"
            "- Returns ranked `file:start-end (score) [lang]` hits with a code snippet."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language description or code snippet to match.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maximum results to return (1-{self.MAX_LIMIT}, default 10).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of ranked results to skip for pagination (default 0).",
                },
                "languages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by language (e.g. ['python', 'typescript']).",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by file-path glob(s) (e.g. ['src/superqode/tools/*']).",
                },
                "refresh": {
                    "type": "boolean",
                    "description": (
                        "Re-index changed files before searching (slower, but reflects "
                        "uncommitted edits). Default: false."
                    ),
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="query is required")

        if not is_semantic_search_available():
            return ToolResult(success=False, output="", error=_INSTALL_HINT)

        limit = args.get("limit", 10)
        try:
            limit = max(1, min(int(limit), self.MAX_LIMIT))
        except (TypeError, ValueError):
            limit = 10
        offset = args.get("offset", 0)
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            offset = 0
        try:
            languages = self._string_list_arg(args.get("languages"), "languages")
            paths = self._string_list_arg(args.get("paths"), "paths")
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))
        refresh = bool(args.get("refresh", False))
        project_root = str(ctx.working_directory)

        try:
            resp = await asyncio.to_thread(
                self._search_blocking, project_root, query, languages, paths, limit, offset, refresh
            )
        except Exception as e:  # daemon/connection/index errors
            return ToolResult(
                success=False,
                output="",
                error=f"{e}\n\n{_INSTALL_HINT}",
            )

        if not getattr(resp, "success", False):
            msg = getattr(resp, "message", None) or "Semantic search failed."
            return ToolResult(
                success=False,
                output="",
                error=f"{msg}\n\nIf the index is missing, run `ccc index` in this project.",
            )

        return self._format(resp, query, project_root)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _search_blocking(
        project_root: str,
        query: str,
        languages: Optional[List[str]],
        paths: Optional[List[str]],
        limit: int,
        offset: int,
        refresh: bool,
    ):
        """Blocking socket call to the cocoindex-code daemon (run off the loop)."""
        import cocoindex_code.client as ccc_client

        if refresh:
            ccc_client.index(project_root)

        return ccc_client.search(
            project_root=project_root,
            query=query,
            languages=languages,
            paths=paths,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _string_list_arg(value: Any, name: str) -> Optional[List[str]]:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            return [value]
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value or None
        raise ValueError(f"{name} must be a string or list of strings")

    def _format(self, resp: Any, query: str, project_root: str) -> ToolResult:
        results = list(getattr(resp, "results", []) or [])
        if not results:
            return ToolResult(
                success=True,
                output=f"No semantic matches for: {query!r}",
                metadata={"matches": 0},
            )

        lines = [f"Found {len(results)} semantic match(es) for {query!r}:", ""]
        for r in results:
            header = (
                f"{r.file_path}:{r.start_line}-{r.end_line} (score {r.score:.3f}) [{r.language}]"
            )
            lines.append(header)
            snippet = (r.content or "").splitlines()
            if len(snippet) > self.SNIPPET_MAX_LINES:
                shown = snippet[: self.SNIPPET_MAX_LINES]
                shown.append(f"... ({len(snippet) - self.SNIPPET_MAX_LINES} more lines)")
                snippet = shown
            lines.extend(f"    {s}" for s in snippet)
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines).rstrip(),
            metadata={
                "matches": len(results),
                "project_root": project_root,
                "offset": getattr(resp, "offset", 0),
                "total_returned": getattr(resp, "total_returned", len(results)),
            },
        )
