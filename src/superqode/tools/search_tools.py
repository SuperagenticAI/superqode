"""
Search Tools - Code Search with ripgrep/grep.

Provides multiple search strategies:
- GrepTool: Text pattern search (ripgrep/grep)
- GlobTool: File pattern matching
- CodeSearchTool: Semantic code search (symbols, definitions, references)
"""

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import Tool, ToolResult, ToolContext
from .validation import get_configured_search_roots, validate_path_in_search_scope


def _external_search_allowed() -> bool:
    """Opt-in to searching absolute paths outside the workspace (default off)."""
    return os.environ.get("SUPERQODE_ALLOW_EXTERNAL_SEARCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_within(target: Path, bases: List[Path]) -> bool:
    t = target.resolve()
    for base in bases:
        try:
            t.relative_to(Path(base).resolve())
            return True
        except ValueError:
            continue
    return False


def _dedupe_roots(roots: List[Path]) -> List[Path]:
    out: List[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(Path(r).resolve())
        if key not in seen:
            seen.add(key)
            out.append(Path(r).resolve())
    return out


def resolve_search_targets(
    path_arg: Optional[str], all_repos: bool, ctx: ToolContext
) -> Tuple[List[Path], Optional[str], bool]:
    """Resolve a search request into concrete root directories/files.

    Returns ``(targets, error, multi)``:
      - ``all_repos`` → the cwd plus every registered workspace/search root.
      - an absolute ``path`` inside scope → honored silently; outside scope it is
        honored only when ``SUPERQODE_ALLOW_EXTERNAL_SEARCH`` is set, else a
        helpful error pointing at ``:workspace add``.
      - a relative ``path`` → validated to stay within cwd/registered roots.
    ``multi`` is True when results should be labeled by repo.
    """
    roots = list(getattr(ctx, "search_roots", None) or get_configured_search_roots())
    cwd = Path(ctx.working_directory).resolve()

    if all_repos:
        targets = _dedupe_roots([cwd, *roots])
        return targets, None, len(targets) > 1

    raw = (path_arg or ".").strip()
    expanded = Path(os.path.expanduser(raw))

    if expanded.is_absolute():
        resolved = expanded.resolve()
        if not resolved.exists():
            return [], f"Path does not exist: {resolved}", False
        if _is_within(resolved, [cwd, *roots]) or _external_search_allowed():
            return [resolved], None, False
        return (
            [],
            (
                f"Path {resolved} is outside the search workspace. Register it with "
                f"`:workspace add {resolved}` (or set SUPERQODE_ALLOW_EXTERNAL_SEARCH=1) "
                "to allow searching it."
            ),
            False,
        )

    try:
        validated = validate_path_in_search_scope(raw, ctx.working_directory, roots)
        return [validated], None, False
    except ValueError as exc:
        return [], str(exc), False


def _label_match_path(file_text: str, targets: List[Path], cwd: Path, multi: bool) -> str:
    """Render a match's path: ``repo/relpath`` across repos, else cwd-relative."""
    fp = Path(file_text)
    if not fp.is_absolute():
        fp = cwd / fp
    fp = fp.resolve()
    for root in targets:
        try:
            rel = fp.relative_to(Path(root).resolve())
            return f"{root.name}/{rel}" if multi else str(rel)
        except ValueError:
            continue
    try:
        return str(fp.relative_to(cwd))
    except ValueError:
        return str(fp)


try:
    from superqode.file_explorer import PathFilter
except ImportError:
    PathFilter = None


class GrepTool(Tool):
    """Search for text patterns in files using ripgrep or grep."""

    read_only = True

    MAX_RESULTS = 100

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file CONTENTS by regular expression, powered by ripgrep. "
            "Full regex syntax is supported (e.g. 'log.*Error', 'def\\s+\\w+'). "
            "Filter files with `include` (e.g. '*.py', '*.{ts,tsx}') and narrow scope "
            "with `path`. Returns `file:line: matching content`; respects .gitignore.\n"
            "- Use this to find WHERE a pattern occurs across the codebase. "
            "To find files by NAME, use the glob tool instead.\n"
            "- For open-ended exploration needing several rounds of grep/glob, delegate "
            "to a subagent/Task tool rather than many manual calls.\n"
            "- You can call multiple search tools in one turn — batch speculative "
            "searches that are likely useful."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Search pattern (regex supported)"},
                "path": {
                    "type": "string",
                    "description": (
                        "Directory or file to search (default: current directory). "
                        "An absolute path is honored if it is inside the workspace "
                        "(see :workspace add)."
                    ),
                },
                "all_repos": {
                    "type": "boolean",
                    "description": (
                        "Search across ALL registered workspace repos in one pass "
                        "(matches are labeled 'repo/path'). Default: false."
                    ),
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
        all_repos = bool(args.get("all_repos", False))

        if not pattern:
            return ToolResult(success=False, output="", error="Pattern is required")

        targets, err, multi = resolve_search_targets(path, all_repos, ctx)
        if err:
            return ToolResult(success=False, output="", error=err)
        if not targets:
            return ToolResult(success=True, output="No matches found", metadata={"matches": 0})

        # Prefer ripgrep with structured --json output; fall back to grep.
        # Both spawn the binary directly (argv, no shell) so regex patterns with
        # shell metacharacters are passed verbatim and can't be misinterpreted.
        rg_path = shutil.which("rg")
        try:
            if rg_path:
                return await self._run_rg_json(
                    rg_path, pattern, targets, include, case_sensitive, ctx, multi
                )
            return await self._run_grep(pattern, targets, include, case_sensitive, ctx, multi)
        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error="Search timed out")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    @staticmethod
    def _rel_to(path_text: str, root: Path) -> str:
        try:
            return str(Path(path_text).resolve().relative_to(Path(root).resolve()))
        except Exception:
            return path_text

    def _format_matches(
        self,
        matches: List[Tuple[str, int, str]],
        truncated: bool,
        partial: bool,
        multi: bool = False,
        repo_count: int = 1,
    ):
        """Render grep matches into the concise, model-friendly file:line: text form."""
        scope = f" across {repo_count} repos" if multi else ""
        if not matches:
            out = f"No matches found{scope}"
            if partial:
                out += "\n(Some paths were inaccessible and skipped)"
            return ToolResult(success=True, output=out, metadata={"matches": 0})
        lines = [f"Found {len(matches)} match(es){scope}:", ""]
        lines.extend(f"{rel}:{lineno}: {text}" for rel, lineno, text in matches)
        if truncated:
            lines += [
                "",
                f"(Results truncated to the first {self.MAX_RESULTS} matches — "
                "narrow with a more specific `path` or `include` pattern.)",
            ]
        if partial:
            lines += ["", "(Some paths were inaccessible and skipped)"]
        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={
                "matches": len(matches),
                "truncated": truncated,
                "partial": partial,
                "repos": repo_count,
            },
        )

    @staticmethod
    def _build_rg_args(
        rg_path: str, pattern: str, paths: List[Path], include, case_sensitive: bool
    ) -> List[str]:
        # --no-config ignores the user's rgrc so behavior is deterministic;
        # ripgrep already respects .gitignore and skips hidden files / .git.
        # NB: there is no --git-ignore flag; passing it makes rg exit 2.
        # ripgrep is multi-threaded and accepts many roots in one invocation, so
        # fanning out across repos is a single fast pass.
        args = [rg_path, "--no-config", "--json"]
        if not case_sensitive:
            args.append("-i")
        if include:
            args += ["--glob", include]
        args.append("--")
        args.append(pattern)
        args += [str(p) for p in paths]
        return args

    async def _run_rg_json(
        self,
        rg_path: str,
        pattern: str,
        targets: List[Path],
        include,
        case_sensitive: bool,
        ctx,
        multi: bool,
    ) -> ToolResult:
        args = self._build_rg_args(rg_path, pattern, targets, include, case_sensitive)
        cwd = Path(ctx.working_directory).resolve()

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ctx.working_directory),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        code = proc.returncode
        err = stderr.decode("utf-8", errors="replace")

        # Invalid regex: rg exits 2 with a parse error on stderr.
        if code == 2 and ("regex parse error" in err or "error parsing regex" in err):
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid grep pattern {pattern!r}: {err.strip()}",
            )
        # Exit codes: 0 = matches, 1 = no matches, 2 = some paths skipped (partial).
        if code not in (0, 1, 2):
            return ToolResult(
                success=False, output="", error=err.strip() or f"ripgrep failed (exit {code})"
            )
        partial = code == 2

        matches: List[Tuple[str, int, str]] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("type") != "match":
                continue
            data = record.get("data", {})
            file_text = (data.get("path") or {}).get("text", "")
            line_no = data.get("line_number") or 0
            text = ((data.get("lines") or {}).get("text", "") or "").rstrip("\n")
            if len(text) > 400:
                text = text[:400] + "…"
            matches.append((_label_match_path(file_text, targets, cwd, multi), line_no, text))

        truncated = len(matches) > self.MAX_RESULTS
        if truncated:
            matches = matches[: self.MAX_RESULTS]
        return self._format_matches(matches, truncated, partial, multi, len(targets))

    async def _run_grep(
        self,
        pattern: str,
        targets: List[Path],
        include,
        case_sensitive: bool,
        ctx,
        multi: bool,
    ) -> ToolResult:
        """Fallback when ripgrep is unavailable. Still argv-based (no shell)."""
        args = ["grep", "-rn"]
        if not case_sensitive:
            args.append("-i")
        if include:
            args += ["--include", include]
        args.append("--")
        args.append(pattern)
        args += [str(p) for p in targets]
        cwd = Path(ctx.working_directory).resolve()

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ctx.working_directory),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        code = proc.returncode
        if code and code >= 2:
            err = stderr.decode("utf-8", errors="replace").strip()
            return ToolResult(success=False, output="", error=err or f"grep failed (exit {code})")

        rows = [ln for ln in stdout.decode("utf-8", errors="replace").splitlines() if ln]
        truncated = len(rows) > self.MAX_RESULTS
        matches: List[Tuple[str, int, str]] = []
        for ln in rows[: self.MAX_RESULTS]:
            # grep -rn output: path:line:content
            parts = ln.split(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                matches.append(
                    (_label_match_path(parts[0], targets, cwd, multi), int(parts[1]), parts[2])
                )
            else:
                matches.append((ln, 0, ""))
        return self._format_matches(matches, truncated, False, multi, len(targets))


class GlobTool(Tool):
    """Find files matching a pattern."""

    read_only = True

    MAX_RESULTS = 200

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files by NAME using glob patterns (e.g. '**/*.py', 'src/**/*.ts'). "
            "Returns matching file paths; respects .gitignore.\n"
            "- Use this to locate files by name/pattern. To search file CONTENTS, "
            "use the grep tool instead.\n"
            "- For open-ended exploration needing several rounds of glob/grep, delegate "
            "to a subagent/Task tool. You can also batch multiple searches in one turn."
        )

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
                    "description": (
                        "Base directory to search from (default: current directory). "
                        "An absolute path is honored if inside the workspace."
                    ),
                },
                "all_repos": {
                    "type": "boolean",
                    "description": (
                        "Search across ALL registered workspace repos (results labeled "
                        "'repo/path'). Default: false."
                    ),
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        all_repos = bool(args.get("all_repos", False))

        if not pattern:
            return ToolResult(success=False, output="", error="Pattern is required")

        targets, err, multi = resolve_search_targets(path, all_repos, ctx)
        if err:
            return ToolResult(success=False, output="", error=err)
        if not targets:
            return ToolResult(
                success=True, output="No files found matching pattern", metadata={"matches": 0}
            )

        # Fast path: ripgrep --files natively honors .gitignore and is far faster
        # than pathlib on large trees. Fall back to pathlib if rg is missing/fails.
        rg_path = shutil.which("rg")
        if rg_path:
            try:
                result = await self._run_rg_files(rg_path, pattern, targets, ctx, multi)
                if result is not None:
                    return result
            except Exception:
                pass  # fall through to the pathlib implementation

        # pathlib fallback handles a single root only; use the first target.
        base_path = targets[0]
        try:
            # Use pathlib glob
            matches = list(base_path.glob(pattern))

            # Create path filter to respect .gitignore
            path_filter = None
            if PathFilter:
                try:
                    path_filter = PathFilter.from_git_root(base_path)
                except Exception:
                    pass

            # Filter out hidden files and gitignored patterns
            filtered = []
            for m in matches:
                parts = m.relative_to(base_path).parts
                # Skip hidden files and common ignore directories
                if any(
                    p.startswith(".") or p in ("node_modules", "__pycache__", "venv") for p in parts
                ):
                    continue
                # Use PathFilter to check gitignore
                if path_filter and path_filter.match(m):
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

    async def _run_rg_files(
        self, rg_path: str, pattern: str, targets: List[Path], ctx, multi: bool
    ) -> Optional[ToolResult]:
        """List files matching a glob via `rg --files` across one or more roots."""
        args = [rg_path, "--no-config", "--files", "--glob", pattern]
        args += [str(p) for p in targets]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ctx.working_directory),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        code = proc.returncode
        # 0 = listed, 1 = nothing matched. Anything else: let pathlib try instead.
        if code not in (0, 1):
            return None

        cwd = Path(ctx.working_directory).resolve()
        rows = sorted(
            _label_match_path(ln, targets, cwd, multi)
            for ln in stdout.decode("utf-8", errors="replace").splitlines()
            if ln
        )
        truncated = len(rows) > self.MAX_RESULTS
        shown = rows[: self.MAX_RESULTS]
        scope = f" across {len(targets)} repos" if multi else ""
        if not shown:
            return ToolResult(
                success=True,
                output=f"No files found matching pattern{scope}",
                metadata={"matches": 0},
            )
        header = f"Found {len(shown)} file(s){scope}:\n" if multi else ""
        output = header + "\n".join(shown)
        if truncated:
            output += (
                f"\n\n(Showing first {self.MAX_RESULTS} files — narrow the pattern to see more.)"
            )
        return ToolResult(
            success=True,
            output=output,
            metadata={"matches": len(shown), "truncated": truncated, "repos": len(targets)},
        )

    @staticmethod
    def _rel_to(path_text: str, root: Path) -> str:
        try:
            return str(Path(path_text).resolve().relative_to(Path(root).resolve()))
        except Exception:
            return path_text


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

    read_only = True

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
            search_path = validate_path_in_search_scope(
                path, ctx.working_directory, getattr(ctx, "search_roots", None)
            )
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


class RepoSearchTool(Tool):
    """High-level repository search for files, content, and symbols."""

    read_only = True

    MAX_FILES = 20
    MAX_CONTENT_MATCHES = 40
    MAX_SYMBOL_LINES = 20

    @property
    def name(self) -> str:
        return "repo_search"

    @property
    def description(self) -> str:
        return (
            "Search the repository in one compact pass. Returns ranked file path matches, "
            "content matches, and code symbol matches. Prefer this for broad codebase exploration."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text, symbol, or filename to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search from (default: repository root)",
                },
                "include": {
                    "type": "string",
                    "description": "Optional file glob to include, for example '*.py' or 'src/**/*.ts'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per section (default: 20)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query", "")).strip()
        path = args.get("path", ".")
        include = args.get("include")
        limit = int(args.get("limit") or self.MAX_FILES)
        limit = max(1, min(limit, 100))

        if not query:
            return ToolResult(success=False, output="", error="Query is required")

        try:
            search_path = validate_path_in_search_scope(
                path, ctx.working_directory, getattr(ctx, "search_roots", None)
            )
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        file_matches = await self._search_files(query, search_path, ctx, include, limit)
        content_matches = await self._search_content(query, search_path, ctx, include, limit)
        symbol_result = await CodeSearchTool().execute(
            {"query": query, "kind": "symbol", "path": str(search_path)}, ctx
        )

        output_sections = []
        if file_matches:
            output_sections.append("Files:\n" + "\n".join(file_matches))
        if content_matches:
            output_sections.append("Content:\n" + "\n".join(content_matches))
        if symbol_result.success and symbol_result.metadata.get("count", 0):
            symbol_lines = symbol_result.output.splitlines()[: min(limit, self.MAX_SYMBOL_LINES)]
            output_sections.append("Symbols:\n" + "\n".join(symbol_lines))

        if not output_sections:
            return ToolResult(
                success=True,
                output=f"No repository matches found for '{query}'",
                metadata={"files": 0, "content": 0, "symbols": 0},
            )

        return ToolResult(
            success=True,
            output="\n\n".join(output_sections),
            metadata={
                "files": len(file_matches),
                "content": len(content_matches),
                "symbols": symbol_result.metadata.get("count", 0) if symbol_result.success else 0,
            },
        )

    async def _search_files(
        self,
        query: str,
        path: Path,
        ctx: ToolContext,
        include: Optional[str],
        limit: int,
    ) -> List[str]:
        rg_path = shutil.which("rg")
        files: List[str] = []
        if rg_path:
            command = [rg_path, "--files", str(path)]
            if include:
                command.extend(["-g", include])
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            files = stdout.decode("utf-8", errors="replace").splitlines()
        else:
            glob_pattern = include or "**/*"
            files = [str(item) for item in path.glob(glob_pattern) if item.is_file()]

        ranked = []
        for file_name in files:
            display = self._relative_display(file_name, ctx.working_directory)
            score = self._path_score(query, display)
            if score > 0:
                ranked.append((score, display))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [file_name for _, file_name in ranked[:limit]]

    async def _search_content(
        self,
        query: str,
        path: Path,
        ctx: ToolContext,
        include: Optional[str],
        limit: int,
    ) -> List[str]:
        rg_path = shutil.which("rg")
        if rg_path:
            command = [
                rg_path,
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "-i",
                "-F",
                query,
                str(path),
            ]
            if include:
                command[1:1] = ["-g", include]

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            lines = stdout.decode("utf-8", errors="replace").splitlines()
            return [
                self._relative_match_line(line, ctx.working_directory) for line in lines[:limit]
            ]

        # Fallback: use grep or pure-Python search
        grep_path = shutil.which("grep")
        if grep_path:
            command = [grep_path, "-rni", "--include", include or "*", "-F", query, str(path)]
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            lines = stdout.decode("utf-8", errors="replace").splitlines()
            return [
                self._relative_match_line(line, ctx.working_directory) for line in lines[:limit]
            ]

        # Pure-Python fallback
        results: List[str] = []
        query_lower = query.lower()
        glob_pattern = include or "**/*"
        for file_path in path.rglob("*") if not include else path.glob(glob_pattern):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(errors="replace")
                for line_num, line in enumerate(content.splitlines(), 1):
                    if query_lower in line.lower():
                        display = self._relative_display(str(file_path), ctx.working_directory)
                        results.append(f"{display}:{line_num}:{line.rstrip()}")
                        if len(results) >= limit:
                            return results
            except Exception:
                continue
        return results

    def _path_score(self, query: str, path: str) -> int:
        query_lower = query.lower()
        path_lower = path.lower()
        basename = Path(path_lower).name
        if query_lower in basename:
            return 100 + len(query_lower)
        if query_lower in path_lower:
            return 50 + len(query_lower)

        cursor = 0
        score = 0
        for char in query_lower:
            found = path_lower.find(char, cursor)
            if found == -1:
                return 0
            score += 1
            cursor = found + 1
        return score

    def _relative_display(self, file_name: str, root: Path) -> str:
        path = Path(file_name)
        try:
            if path.is_absolute():
                return str(path.relative_to(root))
        except ValueError:
            pass
        return file_name

    def _relative_match_line(self, line: str, root: Path) -> str:
        file_name, separator, rest = line.partition(":")
        if not separator:
            return line
        return f"{self._relative_display(file_name, root)}:{rest}"


class LocalCodeSearchTool(Tool):
    """Fast offline code-search broker over local roots.

    This is intentionally an orchestration layer over local filesystem search.
    It gives local/airplane agents one high-signal tool while keeping the first
    implementation small: path ranking, literal content matches, and
    regex-symbol extraction. Persistent indexes can replace these internals
    later without changing the tool contract.
    """

    read_only = True

    MAX_LIMIT = 100

    @property
    def name(self) -> str:
        return "local_code_search"

    @property
    def description(self) -> str:
        return (
            "Fast local-only code search broker. Searches file paths, content, and code "
            "symbols across the current repo or all registered local repos. Prefer this "
            "in Airplane Mode and for broad offline code exploration."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text, symbol, filename, or concept to search for locally",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search from (default: current repo)",
                },
                "all_repos": {
                    "type": "boolean",
                    "description": "Search the working repo plus registered read-only search roots",
                },
                "include": {
                    "type": "string",
                    "description": "Optional file glob, for example '*.py' or 'src/**/*.ts'",
                },
                "mode": {
                    "type": "string",
                    "enum": ["all", "path", "content", "symbol"],
                    "description": "Which local search lanes to run (default: all)",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language for symbol search (python, javascript, typescript, go, rust)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per lane (default: 20)",
                },
                "backend": {
                    "type": "string",
                    "enum": ["auto", "index", "live"],
                    "description": "Search backend: auto uses the local SQLite index when available, live uses filesystem search",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(success=False, output="", error="Query is required")

        mode = str(args.get("mode") or "all").strip().lower()
        if mode not in {"all", "path", "content", "symbol"}:
            return ToolResult(success=False, output="", error="mode must be one of: all, path, content, symbol")
        include = args.get("include")
        language = args.get("language")
        limit = max(1, min(int(args.get("limit") or 20), self.MAX_LIMIT))
        backend = str(args.get("backend") or "auto").strip().lower()
        if backend not in {"auto", "index", "live"}:
            return ToolResult(success=False, output="", error="backend must be one of: auto, index, live")
        targets, error, multi = resolve_search_targets(
            args.get("path"), bool(args.get("all_repos")), ctx
        )
        if error:
            return ToolResult(success=False, output="", error=error)

        if backend in {"auto", "index"}:
            indexed = self._try_index_search(
                query=query,
                targets=targets,
                ctx=ctx,
                mode=mode,
                include=include,
                language=language,
                limit=limit,
                multi=multi,
            )
            if indexed is not None:
                return indexed
            if backend == "index":
                return ToolResult(
                    success=False,
                    output="",
                    error="Local code index is unavailable or does not cover the requested roots. Run `superqode local airplane index` or use backend='live'.",
                )

        sections: list[str] = []
        metadata: dict[str, Any] = {
            "backend": "ripgrep+regex-symbols" if shutil.which("rg") else "python-fallback",
            "repos": len(targets),
            "mode": mode,
            "path": 0,
            "content": 0,
            "symbol": 0,
        }

        if mode in {"all", "path"}:
            paths = await self._search_paths(query, targets, ctx, include, limit, multi)
            metadata["path"] = len(paths)
            if paths:
                sections.append("Files:\n" + "\n".join(paths))

        if mode in {"all", "content"}:
            content = await self._search_content(query, targets, ctx, include, limit, multi)
            metadata["content"] = len(content)
            if content:
                sections.append("Content:\n" + "\n".join(content))

        if mode in {"all", "symbol"}:
            symbols = await self._search_symbols(query, targets, ctx, language, include, limit, multi)
            metadata["symbol"] = len(symbols)
            if symbols:
                sections.append("Symbols:\n" + "\n".join(symbols))

        if not sections:
            roots = ", ".join(root.name for root in targets)
            return ToolResult(
                success=True,
                output=f"No local code matches found for '{query}' in {roots or 'workspace'}",
                metadata=metadata,
            )

        header = (
            f"Local code search results for '{query}' "
            f"({len(targets)} root{'s' if len(targets) != 1 else ''}; {metadata['backend']})"
        )
        return ToolResult(
            success=True,
            output=header + "\n\n" + "\n\n".join(sections),
            metadata=metadata,
        )

    def _try_index_search(
        self,
        *,
        query: str,
        targets: List[Path],
        ctx: ToolContext,
        mode: str,
        include: Optional[str],
        language: Optional[str],
        limit: int,
        multi: bool,
    ) -> Optional[ToolResult]:
        try:
            from superqode.local.code_index import search_code_index

            report = search_code_index(
                workspace_root=ctx.working_directory,
                roots=targets,
                query=query,
                mode=mode,
                include=include,
                language=language,
                limit=limit,
            )
        except Exception:
            return None
        if not report.covered:
            return None
        return self._format_index_report(report, targets, ctx.working_directory, multi, mode)

    def _format_index_report(
        self,
        report: Any,
        targets: List[Path],
        cwd: Path,
        multi: bool,
        mode: str,
    ) -> ToolResult:
        sections: list[str] = []
        if report.files:
            sections.append(
                "Files:\n"
                + "\n".join(
                    f"{self._index_display(item.root_path, item.rel_path, targets, cwd, multi)}  [{item.preview}]"
                    for item in report.files
                )
            )
        if report.content:
            lines: list[str] = []
            for item in report.content:
                display = self._index_display(item.root_path, item.rel_path, targets, cwd, multi)
                line = f":{item.line}" if item.line is not None else ""
                lines.append(f"{display}{line}:{item.preview}")
            sections.append("Content:\n" + "\n".join(lines))
        if report.symbols:
            lines = []
            for item in report.symbols:
                display = self._index_display(item.root_path, item.rel_path, targets, cwd, multi)
                lines.append(
                    f"{display}:{item.line} [{item.kind}] {item.name}\n  {item.preview}"
                )
            sections.append("Symbols:\n" + "\n".join(lines))

        metadata = {
            "backend": "sqlite-fts5",
            "index_path": report.index_path,
            "repos": len(targets),
            "mode": mode,
            "path": len(report.files),
            "content": len(report.content),
            "symbol": len(report.symbols),
        }
        if not sections:
            roots = ", ".join(root.name for root in targets)
            return ToolResult(
                success=True,
                output=f"No indexed local code matches found for '{report.query}' in {roots or 'workspace'}",
                metadata=metadata,
            )

        header = (
            f"Indexed local code search results for '{report.query}' "
            f"({len(targets)} root{'s' if len(targets) != 1 else ''}; sqlite-fts5)"
        )
        return ToolResult(success=True, output=header + "\n\n" + "\n\n".join(sections), metadata=metadata)

    def _index_display(
        self, root_path: str, rel_path: str, targets: List[Path], cwd: Path, multi: bool
    ) -> str:
        return _label_match_path(str(Path(root_path) / rel_path), targets, cwd, multi)

    async def _search_paths(
        self,
        query: str,
        targets: List[Path],
        ctx: ToolContext,
        include: Optional[str],
        limit: int,
        multi: bool,
    ) -> List[str]:
        files: list[str] = []
        rg_path = shutil.which("rg")
        if rg_path:
            command = [rg_path, "--no-config", "--files"]
            if include:
                command.extend(["--glob", include])
            command.extend(str(target) for target in targets)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            files = stdout.decode("utf-8", errors="replace").splitlines()
        else:
            for target in targets:
                glob_pattern = include or "**/*"
                iterator = target.glob(glob_pattern) if target.is_dir() else [target]
                files.extend(str(path) for path in iterator if path.is_file())

        ranked: list[tuple[int, str]] = []
        for file_name in files:
            display = _label_match_path(file_name, targets, ctx.working_directory, multi)
            score = RepoSearchTool()._path_score(query, display)
            if score > 0:
                ranked.append((score, display))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [f"{display}  [score {score}]" for score, display in ranked[:limit]]

    async def _search_content(
        self,
        query: str,
        targets: List[Path],
        ctx: ToolContext,
        include: Optional[str],
        limit: int,
        multi: bool,
    ) -> List[str]:
        rg_path = shutil.which("rg")
        if rg_path:
            command = [
                rg_path,
                "--no-config",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "-i",
                "-F",
            ]
            if include:
                command.extend(["--glob", include])
            command.extend(["--", query])
            command.extend(str(target) for target in targets)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.working_directory),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            lines = stdout.decode("utf-8", errors="replace").splitlines()
            return [
                self._label_content_line(line, targets, ctx.working_directory, multi)
                for line in lines[:limit]
            ]

        results: list[str] = []
        query_lower = query.lower()
        for path in self._iter_candidate_files(targets, include, None):
            try:
                for line_num, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                    if query_lower in line.lower():
                        display = _label_match_path(str(path), targets, ctx.working_directory, multi)
                        results.append(f"{display}:{line_num}:{line.rstrip()}")
                        if len(results) >= limit:
                            return results
            except Exception:
                continue
        return results

    async def _search_symbols(
        self,
        query: str,
        targets: List[Path],
        ctx: ToolContext,
        language: Optional[str],
        include: Optional[str],
        limit: int,
        multi: bool,
    ) -> List[str]:
        query_pattern = re.compile(re.escape(query), re.IGNORECASE)
        out: list[str] = []
        for file_path in self._iter_candidate_files(targets, include, language):
            lang = CodeSearchTool()._get_language(file_path)
            if not lang:
                continue
            for item in self._symbols_in_file(file_path, lang):
                name = item["name"]
                if not query_pattern.search(name):
                    continue
                display = _label_match_path(str(file_path), targets, ctx.working_directory, multi)
                out.append(
                    f"{display}:{item['line']} [{item['kind']}] {name}\n  {item['signature']}"
                )
                if len(out) >= limit:
                    return out
        return out

    def _iter_candidate_files(
        self, targets: List[Path], include: Optional[str], language: Optional[str]
    ) -> List[Path]:
        code = CodeSearchTool()
        allowed_exts = {
            ext for ext, lang in code.EXTENSIONS.items() if language is None or lang == language
        }
        files: list[Path] = []
        for target in targets:
            if target.is_file():
                candidates = [target]
            else:
                candidates = list(target.glob(include or "**/*"))
            for path in candidates:
                if not path.is_file() or path.suffix.lower() not in allowed_exts:
                    continue
                try:
                    rel_parts = path.relative_to(target).parts
                except ValueError:
                    rel_parts = path.parts
                if any(
                    part
                    in {"node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"}
                    for part in rel_parts
                ):
                    continue
                files.append(path)
        return files

    def _symbols_in_file(self, file_path: Path, language: str) -> List[dict[str, Any]]:
        patterns = CodeSearchTool.PATTERNS.get(language, {})
        symbols: list[dict[str, Any]] = []
        try:
            lines = file_path.read_text(errors="replace").splitlines()
        except Exception:
            return []
        for line_num, line in enumerate(lines, 1):
            for kind_name, pattern in patterns.items():
                match = re.match(pattern, line)
                if not match:
                    continue
                groups = match.groups()
                raw = groups[-1] if groups else ""
                names = [item.strip() for item in raw.split(",")] if "," in raw else [raw]
                for name in names:
                    if name:
                        symbols.append(
                            {
                                "name": name,
                                "kind": kind_name,
                                "line": line_num,
                                "signature": line.strip()[:120],
                            }
                        )
        return symbols

    def _label_content_line(
        self, line: str, targets: List[Path], cwd: Path, multi: bool
    ) -> str:
        file_name, sep, rest = line.partition(":")
        if not sep:
            return line
        return f"{_label_match_path(file_name, targets, cwd, multi)}:{rest}"
