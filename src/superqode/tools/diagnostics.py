"""
Diagnostics Tool - Expose LSP errors as a tool.

Provides code diagnostics (errors, warnings, hints) for files
by leveraging Language Server Protocol integration.

Features:
- Get errors/warnings for specific files
- Filter by severity
- Support file patterns
- Run linters directly if LSP unavailable
"""

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from .base import Tool, ToolResult, ToolContext


class Severity(Enum):
    """Diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HINT = "hint"


class DiagnosticsTool(Tool):
    """
    Get code diagnostics (errors, warnings) for files.

    Uses LSP when available, falls back to running linters directly.

    Supports:
    - Python: pyright, ruff, mypy
    - TypeScript/JavaScript: tsc, eslint
    - Go: go vet
    - Rust: cargo check
    """

    # Linter commands by language
    LINTERS = {
        "python": [
            ("ruff", ["ruff", "check", "--output-format=text"]),
            ("pyright", ["pyright", "--outputjson"]),
        ],
        "typescript": [
            ("tsc", ["tsc", "--noEmit", "--pretty", "false"]),
            ("eslint", ["eslint", "--format", "unix"]),
        ],
        "javascript": [
            ("eslint", ["eslint", "--format", "unix"]),
        ],
        "go": [
            ("go", ["go", "vet"]),
        ],
        "rust": [
            ("cargo", ["cargo", "check", "--message-format=short"]),
        ],
    }

    # File extensions to language
    EXTENSIONS = {
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
    }

    @property
    def name(self) -> str:
        return "diagnostics"

    @property
    def description(self) -> str:
        return "Get code diagnostics (errors, warnings) for files. Runs linters and type checkers."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to check"},
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning", "info", "all"],
                    "description": "Minimum severity to report (default: error)",
                },
                "linter": {
                    "type": "string",
                    "description": "Specific linter to use (e.g., 'ruff', 'eslint')",
                },
            },
            "required": ["path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path", ".")
        severity = args.get("severity", "error")
        specific_linter = args.get("linter")

        target_path = Path(path)
        if not target_path.is_absolute():
            target_path = ctx.working_directory / target_path

        if not target_path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        try:
            # Try LSP first
            lsp_result = await self._try_lsp_diagnostics(target_path, ctx)
            if lsp_result:
                return self._format_lsp_result(lsp_result, severity)

            # Fall back to running linters directly
            if target_path.is_file():
                language = self._get_language(target_path)
                if not language:
                    return ToolResult(
                        success=True,
                        output="No diagnostics available for this file type",
                        metadata={"language": None},
                    )

                return await self._run_linter(target_path, language, ctx, specific_linter)
            else:
                # Directory - find files and check them
                return await self._check_directory(target_path, ctx, severity, specific_linter)

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Diagnostics error: {str(e)}")

    def _get_language(self, path: Path) -> Optional[str]:
        """Get language from file extension."""
        return self.EXTENSIONS.get(path.suffix.lower())

    async def _try_lsp_diagnostics(self, path: Path, ctx: ToolContext) -> Optional[List[Dict]]:
        """Try to get diagnostics from LSP client."""
        try:
            from superqode.lsp.client import LSPClient, LSPConfig

            # Check if LSP client is available
            client = LSPClient(ctx.working_directory, LSPConfig())

            if path.is_file():
                language = self._get_language(path)
                if language:
                    await client.start_server(language)
                    await client.open_file(str(path.relative_to(ctx.working_directory)))
                    # Wait for diagnostics
                    await asyncio.sleep(1.0)
                    diagnostics = await client.get_diagnostics(str(path))
                    await client.shutdown()

                    if diagnostics:
                        return [
                            {
                                "file": str(path),
                                "line": d.range.start.line + 1,
                                "column": d.range.start.character + 1,
                                "severity": d.severity_name,
                                "message": d.message,
                                "source": d.source or "lsp",
                            }
                            for d in diagnostics
                        ]

            await client.shutdown()
            return None

        except ImportError:
            return None
        except Exception:
            return None

    def _format_lsp_result(self, diagnostics: List[Dict], severity_filter: str) -> ToolResult:
        """Format LSP diagnostics as result."""
        # Filter by severity
        severity_order = ["error", "warning", "info", "hint"]
        if severity_filter != "all":
            min_idx = (
                severity_order.index(severity_filter) if severity_filter in severity_order else 0
            )
            diagnostics = [
                d
                for d in diagnostics
                if severity_order.index(d.get("severity", "error")) <= min_idx
            ]

        if not diagnostics:
            return ToolResult(success=True, output="No diagnostics found", metadata={"count": 0})

        # Format output
        output_lines = []
        for d in diagnostics:
            output_lines.append(
                f"{d['file']}:{d['line']}:{d['column']}: {d['severity']}: {d['message']}"
            )

        return ToolResult(
            success=True, output="\n".join(output_lines), metadata={"count": len(diagnostics)}
        )

    async def _run_linter(
        self, path: Path, language: str, ctx: ToolContext, specific_linter: Optional[str] = None
    ) -> ToolResult:
        """Run a linter directly."""
        linters = self.LINTERS.get(language, [])

        if specific_linter:
            linters = [(name, cmd) for name, cmd in linters if name == specific_linter]
            if not linters:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Linter '{specific_linter}' not available for {language}",
                )

        for linter_name, cmd_template in linters:
            # Check if linter is available
            if not shutil.which(cmd_template[0]):
                continue

            # Build command
            cmd = cmd_template + [str(path)]

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(ctx.working_directory),
                )

                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

                output = stdout.decode("utf-8", errors="replace")
                if stderr:
                    output += stderr.decode("utf-8", errors="replace")

                # Parse output
                output = output.strip()

                if not output:
                    return ToolResult(
                        success=True,
                        output="No diagnostics found",
                        metadata={"linter": linter_name, "count": 0},
                    )

                # Count issues (rough heuristic)
                issue_count = len([line for line in output.split("\n") if line.strip()])

                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"linter": linter_name, "count": issue_count},
                )

            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

        return ToolResult(
            success=True,
            output=f"No linters available for {language}",
            metadata={"language": language},
        )

    async def _check_directory(
        self, path: Path, ctx: ToolContext, severity: str, specific_linter: Optional[str]
    ) -> ToolResult:
        """Check all supported files in a directory."""
        results = []
        files_checked = 0

        # Find files
        for ext, language in self.EXTENSIONS.items():
            for file_path in path.rglob(f"*{ext}"):
                # Skip common ignore patterns
                parts = file_path.parts
                if any(
                    p in ["node_modules", "__pycache__", ".git", "venv", ".venv"] for p in parts
                ):
                    continue

                result = await self._run_linter(file_path, language, ctx, specific_linter)
                files_checked += 1

                if result.output and result.output != "No diagnostics found":
                    results.append(result.output)

        if not results:
            return ToolResult(
                success=True,
                output=f"No diagnostics found ({files_checked} files checked)",
                metadata={"files_checked": files_checked, "count": 0},
            )

        output = "\n\n".join(results)
        return ToolResult(success=True, output=output, metadata={"files_checked": files_checked})
