"""
Search Tools - Code Search with ripgrep/grep.

Provides multiple search strategies:
- GrepTool: Text pattern search (ripgrep/grep)
- GlobTool: File pattern matching
- CodeSearchTool: Semantic code search (symbols, definitions, references)
"""

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import Tool, ToolResult, ToolContext
from .validation import validate_path_in_working_directory


class GrepTool(Tool):
    """Search for text patterns in files using ripgrep or grep."""

    MAX_RESULTS = 100

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search for a pattern in files. Uses ripgrep if available, falls back to grep."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex supported)"},
                "path": {
                    "type": "string",
                    "description": "Directory or file to search (default: current directory)",
                },
                "include": {
                    "type": "string",
                    "description": "File pattern to include (e.g., '*.py')",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case sensitive search (default: false)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        include = args.get("include")
        case_sensitive = args.get("case_sensitive", False)

        if not pattern:
            return ToolResult(success=False, output="", error="Pattern is required")

        try:
            # Validate and resolve path - ensures it stays within working directory
            search_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        # Check for ripgrep first, fall back to grep
        rg_path = shutil.which("rg")

        if rg_path:
            cmd = self._build_rg_command(pattern, search_path, include, case_sensitive)
        else:
            cmd = self._build_grep_command(pattern, search_path, include, case_sensitive)

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            output = stdout.decode("utf-8", errors="replace")

            # Limit results
            lines = output.strip().split("\n")
            if len(lines) > self.MAX_RESULTS:
                output = "\n".join(lines[: self.MAX_RESULTS])
                output += f"\n\n[Showing first {self.MAX_RESULTS} of {len(lines)} results]"

            if not output.strip():
                return ToolResult(success=True, output="No matches found", metadata={"matches": 0})

            return ToolResult(success=True, output=output, metadata={"matches": len(lines)})

        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error="Search timed out")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _build_rg_command(
        self, pattern: str, path: Path, include: str, case_sensitive: bool
    ) -> str:
        """Build ripgrep command."""
        cmd_parts = ["rg", "--line-number", "--no-heading"]

        if not case_sensitive:
            cmd_parts.append("-i")

        if include:
            cmd_parts.extend(["-g", f"'{include}'"])

        # Escape pattern for shell
        escaped_pattern = pattern.replace("'", "'\\''")
        cmd_parts.append(f"'{escaped_pattern}'")
        cmd_parts.append(f"'{path}'")

        return " ".join(cmd_parts)

    def _build_grep_command(
        self, pattern: str, path: Path, include: str, case_sensitive: bool
    ) -> str:
        """Build grep command."""
        cmd_parts = ["grep", "-rn"]

        if not case_sensitive:
            cmd_parts.append("-i")

        if include:
            cmd_parts.extend(["--include", f"'{include}'"])

        escaped_pattern = pattern.replace("'", "'\\''")
        cmd_parts.append(f"'{escaped_pattern}'")
        cmd_parts.append(f"'{path}'")

        return " ".join(cmd_parts)


class GlobTool(Tool):
    """Find files matching a pattern."""

    MAX_RESULTS = 200

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern (e.g., '**/*.py')."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts')",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from (default: current directory)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern", "")
        path = args.get("path", ".")

        if not pattern:
            return ToolResult(success=False, output="", error="Pattern is required")

        try:
            # Validate and resolve path - ensures it stays within working directory
            base_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        try:
            # Use pathlib glob
            matches = list(base_path.glob(pattern))

            # Filter out hidden files and common ignore patterns
            filtered = []
            for m in matches:
                parts = m.relative_to(base_path).parts
                if any(
                    p.startswith(".") or p in ("node_modules", "__pycache__", "venv") for p in parts
                ):
                    continue
                filtered.append(m)

            # Limit results
            if len(filtered) > self.MAX_RESULTS:
                filtered = filtered[: self.MAX_RESULTS]
                truncated = True
            else:
                truncated = False

            # Format output
            output_lines = [str(m.relative_to(ctx.working_directory)) for m in filtered]
            output = "\n".join(output_lines)

            if truncated:
                output += f"\n\n[Showing first {self.MAX_RESULTS} results]"

            if not output:
                return ToolResult(
                    success=True, output="No files found matching pattern", metadata={"matches": 0}
                )

            return ToolResult(success=True, output=output, metadata={"matches": len(filtered)})

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


@dataclass
class Symbol:
    """A code symbol (function, class, variable, etc.)."""

    name: str
    kind: str  # function, class, method, variable, etc.
    file: str
    line: int
    signature: str = ""


class CodeSearchTool(Tool):
    """
    Semantic code search - find symbols, definitions, and references.

    Supports:
    - Symbol search (find functions, classes, methods by name)
    - Definition search (where is X defined?)
    - Reference search (where is X used?)
    - Import search (what imports X?)

    Uses regex-based heuristics for broad language support.
    Can integrate with LSP for more accurate results when available.
    """

    MAX_RESULTS = 50

    # Language-specific patterns for symbol extraction
    PATTERNS = {
        "python": {
            "function": r"^(\s*)def\s+(\w+)\s*\([^)]*\)",
            "class": r"^(\s*)class\s+(\w+)\s*[:\(]",
            "method": r"^(\s+)def\s+(\w+)\s*\(self[^)]*\)",
            "variable": r"^(\w+)\s*=\s*",
            "import": r"^(?:from\s+[\w.]+\s+)?import\s+(.+)",
        },
        "javascript": {
            "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
            "class": r"^(?:export\s+)?class\s+(\w+)",
            "method": r"^\s+(?:async\s+)?(\w+)\s*\([^)]*\)\s*{",
            "const": r"^(?:export\s+)?const\s+(\w+)\s*=",
            "let": r"^(?:export\s+)?let\s+(\w+)\s*=",
            "import": r"^import\s+(?:{[^}]+}|\*\s+as\s+\w+|\w+)\s+from",
        },
        "typescript": {
            "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)",
            "class": r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)",
            "interface": r"^(?:export\s+)?interface\s+(\w+)",
            "type": r"^(?:export\s+)?type\s+(\w+)\s*=",
            "method": r"^\s+(?:public|private|protected)?\s*(?:async\s+)?(\w+)\s*\(",
            "const": r"^(?:export\s+)?const\s+(\w+)\s*[=:]",
        },
        "go": {
            "function": r"^func\s+(\w+)\s*\(",
            "method": r"^func\s+\([^)]+\)\s+(\w+)\s*\(",
            "type": r"^type\s+(\w+)\s+",
            "const": r"^const\s+(\w+)\s*=",
            "var": r"^var\s+(\w+)\s+",
        },
        "rust": {
            "function": r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
            "struct": r"^(?:pub\s+)?struct\s+(\w+)",
            "enum": r"^(?:pub\s+)?enum\s+(\w+)",
            "trait": r"^(?:pub\s+)?trait\s+(\w+)",
            "impl": r"^impl(?:<[^>]+>)?\s+(\w+)",
        },
    }

    # File extensions to language mapping
    EXTENSIONS = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
    }

    @property
    def name(self) -> str:
        return "code_search"

    @property
    def description(self) -> str:
        return "Search for code symbols (functions, classes, methods). Find definitions and references."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symbol name or pattern to search for"},
                "kind": {
                    "type": "string",
                    "enum": ["symbol", "definition", "reference", "import"],
                    "description": "Search type: symbol (find symbol defs), definition (where defined), reference (where used), import (import statements)",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory)",
                },
                "language": {
                    "type": "string",
                    "description": "Filter by language (python, javascript, typescript, go, rust)",
                },
                "symbol_type": {
                    "type": "string",
                    "description": "Filter by symbol type (function, class, method, variable, etc.)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "")
        kind = args.get("kind", "symbol")
        path = args.get("path", ".")
        language = args.get("language")
        symbol_type = args.get("symbol_type")

        if not query:
            return ToolResult(success=False, output="", error="Query is required")

        try:
            # Validate and resolve path - ensures it stays within working directory
            search_path = validate_path_in_working_directory(path, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not search_path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        try:
            # Try LSP first for more accurate results
            lsp_results = await self._try_lsp_search(query, kind, search_path, ctx)
            if lsp_results:
                return self._format_results(lsp_results, query, kind)

            # Fall back to regex-based search
            if kind == "symbol" or kind == "definition":
                results = await self._search_definitions(
                    query, search_path, ctx, language, symbol_type
                )
            elif kind == "reference":
                results = await self._search_references(query, search_path, ctx, language)
            elif kind == "import":
                results = await self._search_imports(query, search_path, ctx, language)
            else:
                results = await self._search_definitions(
                    query, search_path, ctx, language, symbol_type
                )

            return self._format_results(results, query, kind)

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Search error: {str(e)}")

    async def _try_lsp_search(
        self, query: str, kind: str, path: Path, ctx: ToolContext
    ) -> Optional[List[Symbol]]:
        """Try to use LSP for more accurate search."""
        # TODO: Integrate with LSP workspace/symbol request
        return None

    async def _search_definitions(
        self,
        query: str,
        path: Path,
        ctx: ToolContext,
        language: Optional[str],
        symbol_type: Optional[str],
    ) -> List[Symbol]:
        """Search for symbol definitions using regex patterns."""
        results = []
        query_pattern = re.compile(re.escape(query), re.IGNORECASE)

        # Find files
        for file_path in self._find_code_files(path, language):
            lang = self._get_language(file_path)
            if not lang:
                continue

            patterns = self.PATTERNS.get(lang, {})
            if symbol_type:
                patterns = {k: v for k, v in patterns.items() if k == symbol_type}

            try:
                content = file_path.read_text(errors="replace")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    for kind_name, pattern in patterns.items():
                        match = re.match(pattern, line)
                        if match:
                            # Extract symbol name (last group usually)
                            groups = match.groups()
                            name = groups[-1] if groups else ""

                            # Handle comma-separated names (imports)
                            if "," in name:
                                names = [n.strip() for n in name.split(",")]
                            else:
                                names = [name]

                            for n in names:
                                if query_pattern.search(n):
                                    rel_path = file_path.relative_to(ctx.working_directory)
                                    results.append(
                                        Symbol(
                                            name=n,
                                            kind=kind_name,
                                            file=str(rel_path),
                                            line=line_num,
                                            signature=line.strip()[:100],
                                        )
                                    )

            except Exception:
                continue

        return results[: self.MAX_RESULTS]

    async def _search_references(
        self, query: str, path: Path, ctx: ToolContext, language: Optional[str]
    ) -> List[Symbol]:
        """Search for references to a symbol."""
        results = []

        # Use ripgrep for fast search
        rg_path = shutil.which("rg")
        if rg_path:
            cmd = f"rg -n --no-heading '\\b{query}\\b'"
            if language:
                ext_map = {
                    "python": "py",
                    "javascript": "js",
                    "typescript": "ts",
                    "go": "go",
                    "rust": "rs",
                }
                if language in ext_map:
                    cmd += f" -t {ext_map[language]}"
            cmd += f" '{path}'"

            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(ctx.working_directory),
                )

                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)

                for line in stdout.decode("utf-8", errors="replace").split("\n"):
                    if ":" in line:
                        parts = line.split(":", 2)
                        if len(parts) >= 2:
                            file_path = parts[0]
                            try:
                                line_num = int(parts[1])
                                content = parts[2] if len(parts) > 2 else ""
                                results.append(
                                    Symbol(
                                        name=query,
                                        kind="reference",
                                        file=file_path,
                                        line=line_num,
                                        signature=content.strip()[:100],
                                    )
                                )
                            except ValueError:
                                continue

            except Exception:
                pass

        return results[: self.MAX_RESULTS]

    async def _search_imports(
        self, query: str, path: Path, ctx: ToolContext, language: Optional[str]
    ) -> List[Symbol]:
        """Search for import statements mentioning a symbol."""
        results = []
        query_lower = query.lower()

        for file_path in self._find_code_files(path, language):
            lang = self._get_language(file_path)
            if not lang:
                continue

            import_pattern = self.PATTERNS.get(lang, {}).get("import")
            if not import_pattern:
                continue

            try:
                content = file_path.read_text(errors="replace")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        if re.match(import_pattern, line.strip()):
                            rel_path = file_path.relative_to(ctx.working_directory)
                            results.append(
                                Symbol(
                                    name=query,
                                    kind="import",
                                    file=str(rel_path),
                                    line=line_num,
                                    signature=line.strip()[:100],
                                )
                            )

            except Exception:
                continue

        return results[: self.MAX_RESULTS]

    def _find_code_files(self, path: Path, language: Optional[str]) -> List[Path]:
        """Find code files in a directory."""
        files = []

        if language:
            # Filter by language
            exts = [ext for ext, lang in self.EXTENSIONS.items() if lang == language]
        else:
            exts = list(self.EXTENSIONS.keys())

        if path.is_file():
            if path.suffix in exts:
                return [path]
            return []

        for ext in exts:
            for file_path in path.rglob(f"*{ext}"):
                # Skip common ignore patterns
                parts = file_path.parts
                if any(
                    p in ["node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"]
                    for p in parts
                ):
                    continue
                files.append(file_path)

        return files

    def _get_language(self, path: Path) -> Optional[str]:
        """Get language from file extension."""
        return self.EXTENSIONS.get(path.suffix.lower())

    def _format_results(self, results: List[Symbol], query: str, kind: str) -> ToolResult:
        """Format search results."""
        if not results:
            return ToolResult(
                success=True, output=f"No {kind}s found for '{query}'", metadata={"count": 0}
            )

        output_lines = []
        for sym in results:
            output_lines.append(f"{sym.file}:{sym.line} [{sym.kind}] {sym.name}")
            if sym.signature:
                output_lines.append(f"  {sym.signature}")

        output = "\n".join(output_lines)

        if len(results) >= self.MAX_RESULTS:
            output += f"\n\n[Showing first {self.MAX_RESULTS} results]"

        return ToolResult(success=True, output=output, metadata={"count": len(results)})
