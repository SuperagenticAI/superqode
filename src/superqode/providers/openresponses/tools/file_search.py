"""
File Search Tool for Open Responses.

Implements file search functionality for the workspace.
Provides both text-based and semantic search capabilities.

Features:
- Full-text search with ripgrep
- Glob pattern matching
- File content indexing
- Result ranking

Usage:
    tool = FileSearchTool(workspace_root="/path/to/project")
    results = await tool.search("error handling")
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """A single search result."""

    file_path: str
    line_number: int
    content: str
    score: float = 1.0


@dataclass
class SearchResults:
    """Collection of search results."""

    results: List[SearchResult] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False


class FileSearchTool:
    """
    File search tool for Open Responses.

    Provides text-based file search using ripgrep or grep.

    Args:
        workspace_root: Root directory for search
        max_results: Maximum number of results
        context_lines: Lines of context around matches
    """

    def __init__(
        self,
        workspace_root: str,
        max_results: int = 20,
        context_lines: int = 2,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.max_results = max_results
        self.context_lines = context_lines

    async def search(
        self,
        query: str,
        file_pattern: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Search for text in workspace files.

        Args:
            query: Search query (supports regex)
            file_pattern: Optional glob pattern to filter files
            max_results: Override default max results

        Returns:
            Dict with search results and metadata
        """
        use_max_results = max_results if max_results is not None else self.max_results

        # Try ripgrep first, fall back to grep
        try:
            results = await self._search_ripgrep(query, file_pattern, use_max_results)
        except FileNotFoundError:
            results = await self._search_grep(query, file_pattern, use_max_results)

        return {
            "success": True,
            "results": [
                {
                    "file": r.file_path,
                    "line": r.line_number,
                    "content": r.content,
                    "score": r.score,
                }
                for r in results.results
            ],
            "total_matches": results.total_matches,
            "truncated": results.truncated,
        }

    async def find_files(
        self,
        pattern: str,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.py")
            max_results: Override default max results

        Returns:
            Dict with matching file paths
        """
        use_max_results = max_results if max_results is not None else self.max_results

        try:
            # Use glob to find files
            matches = list(self.workspace_root.glob(pattern))
            truncated = len(matches) > use_max_results

            # Sort by modification time (newest first)
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            matches = matches[:use_max_results]

            # Convert to relative paths
            file_paths = [str(p.relative_to(self.workspace_root)) for p in matches if p.is_file()]

            return {
                "success": True,
                "files": file_paths,
                "total_matches": len(file_paths),
                "truncated": truncated,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "files": [],
            }

    async def read_file(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Read file content.

        Args:
            file_path: Path to file (relative to workspace)
            start_line: Optional start line (1-indexed)
            end_line: Optional end line (1-indexed)

        Returns:
            Dict with file content
        """
        full_path = self.workspace_root / file_path

        if not full_path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "content": "",
            }

        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")

            # Apply line range if specified
            if start_line is not None or end_line is not None:
                start = (start_line - 1) if start_line else 0
                end = end_line if end_line else len(lines)
                lines = lines[start:end]
                content = "\n".join(lines)

            return {
                "success": True,
                "content": content,
                "line_count": len(lines),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": "",
            }

    async def _search_ripgrep(
        self,
        query: str,
        file_pattern: Optional[str],
        max_results: int,
    ) -> SearchResults:
        """Search using ripgrep (rg)."""
        cmd = [
            "rg",
            "--json",
            "--max-count",
            str(max_results * 2),  # Over-fetch for filtering
            "-C",
            str(self.context_lines),
        ]

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        cmd.extend([query, str(self.workspace_root)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        results = []
        total_matches = 0

        import json

        for line in stdout.decode("utf-8").split("\n"):
            if not line.strip():
                continue

            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    path = match_data.get("path", {}).get("text", "")
                    line_num = match_data.get("line_number", 0)
                    lines = match_data.get("lines", {}).get("text", "")

                    # Make path relative
                    try:
                        rel_path = str(Path(path).relative_to(self.workspace_root))
                    except ValueError:
                        rel_path = path

                    results.append(
                        SearchResult(
                            file_path=rel_path,
                            line_number=line_num,
                            content=lines.strip(),
                        )
                    )
                    total_matches += 1

                    if len(results) >= max_results:
                        break

            except json.JSONDecodeError:
                continue

        return SearchResults(
            results=results,
            total_matches=total_matches,
            truncated=total_matches > max_results,
        )

    async def _search_grep(
        self,
        query: str,
        file_pattern: Optional[str],
        max_results: int,
    ) -> SearchResults:
        """Search using grep (fallback)."""
        cmd = f"grep -rn --include='{file_pattern or '*'}' '{query}' {self.workspace_root}"

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        results = []
        total_matches = 0

        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            if not line.strip():
                continue

            # Parse grep output: file:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path, line_num, content = parts[0], parts[1], parts[2]

                # Make path relative
                try:
                    rel_path = str(Path(file_path).relative_to(self.workspace_root))
                except ValueError:
                    rel_path = file_path

                try:
                    results.append(
                        SearchResult(
                            file_path=rel_path,
                            line_number=int(line_num),
                            content=content.strip(),
                        )
                    )
                    total_matches += 1

                    if len(results) >= max_results:
                        break
                except ValueError:
                    continue

        return SearchResults(
            results=results,
            total_matches=total_matches,
            truncated=total_matches > max_results,
        )

    def get_tool_definition(self) -> Dict[str, Any]:
        """Get the Open Responses tool definition for file_search."""
        return {
            "type": "file_search",
            "max_num_results": self.max_results,
        }
