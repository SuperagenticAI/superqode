"""
Linter Runner - Executes fast linters across supported languages.

Detects languages, respects existing configs, and runs linters in-place without
modifying the repository. Reports findings as structured data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


IGNORE_DIRS = {".git", ".superqode", ".venv", "venv", "node_modules", "__pycache__"}


@dataclass
class LinterRunResult:
    """Result of a single linter execution."""

    tool: str
    language: str
    success: bool
    findings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LinterRunner:
    """Run linters for detected languages in the repository."""

    def __init__(self, project_root: Path, timeout_seconds: int = 300):
        self.project_root = project_root.resolve()
        self.timeout_seconds = timeout_seconds

    async def run(self) -> LinterRunResult:
        """Run all applicable linters and return merged results."""
        results: List[LinterRunResult] = []

        if self._has_extension({".py"}):
            results.append(await self._run_python())
        if self._has_extension({".js", ".jsx", ".ts", ".tsx"}):
            results.append(await self._run_js_ts())
        if self._has_extension({".go"}):
            results.append(await self._run_go())
        if (self.project_root / "Cargo.toml").exists() or self._has_extension({".rs"}):
            results.append(await self._run_rust())
        if self._has_extension({".rb"}):
            results.append(await self._run_ruby())
        if self._has_extension({".swift"}):
            results.append(await self._run_swift())

        merged = LinterRunResult(
            tool="multi",
            language="multi",
            success=True,
        )
        for result in results:
            merged.success = merged.success and result.success
            merged.findings.extend(result.findings)
            merged.errors.extend(result.errors)
        return merged

    def _has_extension(self, extensions: set[str]) -> bool:
        """Check if repository contains files with any of the extensions."""
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for filename in files:
                if Path(filename).suffix in extensions:
                    return True
        return False

    async def _run_python(self) -> LinterRunResult:
        tool = "ruff"
        if not shutil.which(tool):
            return self._missing_tool(tool, "python")

        config_path = self._find_ruff_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_arg = None
            if config_path is None:
                temp_config = Path(temp_dir) / "ruff.toml"
                temp_config.write_text("line-length = 100\n")
                config_arg = temp_config

            args = [tool, "check", ".", "--output-format", "json"]
            if config_path:
                args.extend(["--config", str(config_path)])
            if config_arg:
                args.extend(["--config", str(config_arg)])

            stdout, stderr, code = await self._run_command(args)
            findings = self._parse_ruff_json(stdout, "python")
            return LinterRunResult(
                tool=tool,
                language="python",
                success=code == 0,
                findings=findings,
                errors=self._to_errors(stderr, code),
            )

    async def _run_js_ts(self) -> LinterRunResult:
        eslint_config = self._find_eslint_config()
        if eslint_config and shutil.which("eslint"):
            args = ["eslint", ".", "--format", "json"]
            stdout, stderr, code = await self._run_command(args)
            findings = self._parse_eslint_json(stdout)
            return LinterRunResult(
                tool="eslint",
                language="javascript",
                success=code == 0,
                findings=findings,
                errors=self._to_errors(stderr, code),
            )

        if shutil.which("biome"):
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = self._find_biome_config()
                if config_path is None:
                    temp_config = Path(temp_dir) / "biome.json"
                    temp_config.write_text(
                        json.dumps(
                            {
                                "linter": {"enabled": True},
                                "formatter": {"enabled": False},
                            }
                        )
                    )
                    args = [
                        "biome",
                        "lint",
                        "--reporter",
                        "json",
                        ".",
                        "--config-path",
                        str(temp_config),
                    ]
                else:
                    args = ["biome", "lint", "--reporter", "json", "."]

                stdout, stderr, code = await self._run_command(args)
                findings = self._parse_biome_json(stdout)
                return LinterRunResult(
                    tool="biome",
                    language="javascript",
                    success=code == 0,
                    findings=findings,
                    errors=self._to_errors(stderr, code),
                )

        return self._missing_tool("eslint/biome", "javascript")

    async def _run_go(self) -> LinterRunResult:
        tool = "golangci-lint"
        if shutil.which(tool):
            args = [tool, "run", "--out-format", "json", "./..."]
            stdout, stderr, code = await self._run_command(args)
            findings = self._parse_golangci_json(stdout)
            return LinterRunResult(
                tool=tool,
                language="go",
                success=code == 0,
                findings=findings,
                errors=self._to_errors(stderr, code),
            )

        if shutil.which("go"):
            args = ["go", "vet", "./..."]
            stdout, stderr, code = await self._run_command(args)
            findings = self._parse_go_vet(stderr or stdout)
            return LinterRunResult(
                tool="go vet",
                language="go",
                success=code == 0,
                findings=findings,
                errors=self._to_errors(stderr, code),
            )

        return self._missing_tool("golangci-lint", "go")

    async def _run_rust(self) -> LinterRunResult:
        if not shutil.which("cargo"):
            return self._missing_tool("cargo clippy", "rust")

        args = ["cargo", "clippy", "--message-format=json"]
        stdout, stderr, code = await self._run_command(args)
        findings = self._parse_cargo_clippy(stdout)
        return LinterRunResult(
            tool="cargo clippy",
            language="rust",
            success=code == 0,
            findings=findings,
            errors=self._to_errors(stderr, code),
        )

    async def _run_ruby(self) -> LinterRunResult:
        tool = "rubocop"
        if not shutil.which(tool):
            return self._missing_tool(tool, "ruby")

        args = [tool, "--format", "json"]
        stdout, stderr, code = await self._run_command(args)
        findings = self._parse_rubocop_json(stdout)
        return LinterRunResult(
            tool=tool,
            language="ruby",
            success=code == 0,
            findings=findings,
            errors=self._to_errors(stderr, code),
        )

    async def _run_swift(self) -> LinterRunResult:
        tool = "swiftlint"
        if not shutil.which(tool):
            return self._missing_tool(tool, "swift")

        args = [tool, "lint", "--reporter", "json"]
        stdout, stderr, code = await self._run_command(args)
        findings = self._parse_swiftlint_json(stdout)
        return LinterRunResult(
            tool=tool,
            language="swift",
            success=code == 0,
            findings=findings,
            errors=self._to_errors(stderr, code),
        )

    def _missing_tool(self, tool: str, language: str) -> LinterRunResult:
        return LinterRunResult(
            tool=tool,
            language=language,
            success=True,
            findings=[
                {
                    "id": f"{language}-linter-missing",
                    "severity": "info",
                    "title": f"{language.title()} linter unavailable",
                    "description": f"{tool} is not installed. Install it to enable lint checks.",
                    "file_path": None,
                    "line_number": None,
                    "evidence": f"Missing tool: {tool}",
                    "confidence": 0.5,
                    "category": "tooling",
                }
            ],
        )

    def _find_ruff_config(self) -> Optional[Path]:
        for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
            candidate = self.project_root / name
            if candidate.exists():
                if name == "pyproject.toml":
                    if "[tool.ruff]" in candidate.read_text():
                        return candidate
                else:
                    return candidate
        return None

    def _find_eslint_config(self) -> Optional[Path]:
        eslint_files = [
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.cjs",
            ".eslintrc.json",
            ".eslintrc.yml",
            ".eslintrc.yaml",
            "eslint.config.js",
            "eslint.config.mjs",
            "eslint.config.cjs",
        ]
        for name in eslint_files:
            candidate = self.project_root / name
            if candidate.exists():
                return candidate
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "eslintConfig" in data:
                    return package_json
            except json.JSONDecodeError:
                return None
        return None

    def _find_biome_config(self) -> Optional[Path]:
        for name in ("biome.json", "biome.jsonc", ".biomerc.json"):
            candidate = self.project_root / name
            if candidate.exists():
                return candidate
        return None

    async def _run_command(self, args: List[str]) -> Tuple[str, str, int]:
        """Run a command and return stdout, stderr, exit code."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return "", f"Command not found: {args[0]}", 127

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            return "", f"Timed out running {' '.join(args)}", 124

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        return stdout, stderr, proc.returncode

    def _to_errors(self, stderr: str, code: int) -> List[str]:
        if code == 0 or not stderr:
            return []
        return [stderr.strip()]

    def _parse_ruff_json(self, stdout: str, language: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return []

        findings = []
        for item in data:
            location = item.get("location", {})
            findings.append(
                {
                    "id": item.get("code", "ruff"),
                    "severity": "warning",
                    "title": f"Ruff {item.get('code', '')}".strip(),
                    "description": item.get("message", ""),
                    "file_path": item.get("filename"),
                    "line_number": location.get("row"),
                    "evidence": item.get("message", ""),
                    "confidence": 1.0,
                    "category": f"lint:{language}",
                    "rule_id": item.get("code"),
                    "tool": "ruff",
                }
            )
        return findings

    def _parse_eslint_json(self, stdout: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return []

        findings = []
        for file_entry in data:
            file_path = file_entry.get("filePath")
            for message in file_entry.get("messages", []):
                findings.append(
                    {
                        "id": message.get("ruleId") or "eslint",
                        "severity": "warning" if message.get("severity", 1) == 1 else "critical",
                        "title": f"ESLint {message.get('ruleId', '')}".strip(),
                        "description": message.get("message", ""),
                        "file_path": file_path,
                        "line_number": message.get("line"),
                        "evidence": message.get("message", ""),
                        "confidence": 1.0,
                        "category": "lint:javascript",
                        "rule_id": message.get("ruleId"),
                        "tool": "eslint",
                    }
                )
        return findings

    def _parse_biome_json(self, stdout: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return []

        findings = []
        for diagnostic in data.get("diagnostics", []):
            location = diagnostic.get("location", {})
            findings.append(
                {
                    "id": diagnostic.get("category", "biome"),
                    "severity": "warning"
                    if diagnostic.get("severity") == "warning"
                    else "critical",
                    "title": f"Biome {diagnostic.get('category', '')}".strip(),
                    "description": diagnostic.get("message", ""),
                    "file_path": location.get("path"),
                    "line_number": location.get("span", {}).get("start", {}).get("line"),
                    "evidence": diagnostic.get("message", ""),
                    "confidence": 1.0,
                    "category": "lint:javascript",
                    "rule_id": diagnostic.get("category"),
                    "tool": "biome",
                }
            )
        return findings

    def _parse_golangci_json(self, stdout: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return []

        findings = []
        for issue in data.get("Issues", []):
            pos = issue.get("Pos", {})
            findings.append(
                {
                    "id": issue.get("FromLinter", "golangci-lint"),
                    "severity": "warning",
                    "title": f"GolangCI {issue.get('FromLinter', '')}".strip(),
                    "description": issue.get("Text", ""),
                    "file_path": pos.get("Filename"),
                    "line_number": pos.get("Line"),
                    "evidence": issue.get("Text", ""),
                    "confidence": 1.0,
                    "category": "lint:go",
                    "rule_id": issue.get("FromLinter"),
                    "tool": "golangci-lint",
                }
            )
        return findings

    def _parse_go_vet(self, output: str) -> List[Dict[str, Any]]:
        findings = []
        for line in output.splitlines():
            if ":" not in line:
                continue
            findings.append(
                {
                    "id": "go-vet",
                    "severity": "warning",
                    "title": "go vet issue",
                    "description": line.strip(),
                    "file_path": line.split(":", 1)[0],
                    "line_number": None,
                    "evidence": line.strip(),
                    "confidence": 0.8,
                    "category": "lint:go",
                    "rule_id": "go-vet",
                    "tool": "go vet",
                }
            )
        return findings

    def _parse_cargo_clippy(self, stdout: str) -> List[Dict[str, Any]]:
        findings = []
        for line in stdout.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("reason") != "compiler-message":
                continue
            diag = message.get("message", {})
            level = diag.get("level")
            spans = diag.get("spans", [])
            primary = spans[0] if spans else {}
            findings.append(
                {
                    "id": diag.get("code", {}).get("code", "clippy"),
                    "severity": "critical" if level in {"error", "failure"} else "warning",
                    "title": f"Clippy {diag.get('code', {}).get('code', '')}".strip(),
                    "description": diag.get("message", ""),
                    "file_path": primary.get("file_name"),
                    "line_number": primary.get("line_start"),
                    "evidence": diag.get("message", ""),
                    "confidence": 1.0,
                    "category": "lint:rust",
                    "rule_id": diag.get("code", {}).get("code"),
                    "tool": "cargo clippy",
                }
            )
        return findings

    def _parse_rubocop_json(self, stdout: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return []

        findings = []
        for file_entry in data.get("files", []):
            for offense in file_entry.get("offenses", []):
                location = offense.get("location", {})
                findings.append(
                    {
                        "id": offense.get("cop_name", "rubocop"),
                        "severity": "warning",
                        "title": f"RuboCop {offense.get('cop_name', '')}".strip(),
                        "description": offense.get("message", ""),
                        "file_path": file_entry.get("path"),
                        "line_number": location.get("start_line"),
                        "evidence": offense.get("message", ""),
                        "confidence": 1.0,
                        "category": "lint:ruby",
                        "rule_id": offense.get("cop_name"),
                        "tool": "rubocop",
                    }
                )
        return findings

    def _parse_swiftlint_json(self, stdout: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return []

        findings = []
        for item in data:
            findings.append(
                {
                    "id": item.get("rule_id", "swiftlint"),
                    "severity": "warning" if item.get("severity") == "Warning" else "critical",
                    "title": f"SwiftLint {item.get('rule_id', '')}".strip(),
                    "description": item.get("reason", ""),
                    "file_path": item.get("file"),
                    "line_number": item.get("line"),
                    "evidence": item.get("reason", ""),
                    "confidence": 1.0,
                    "category": "lint:swift",
                    "rule_id": item.get("rule_id"),
                    "tool": "swiftlint",
                }
            )
        return findings
