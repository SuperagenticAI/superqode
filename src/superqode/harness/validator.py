"""
Patch Harness Validator - OSS command-based harness.

Runs user-provided commands from superqode.yaml (BYOH).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import time

from .config import HarnessConfig, ValidationCategory


@dataclass
class HarnessFinding:
    """A finding from the harness validation."""

    tool: str
    category: ValidationCategory
    file: Optional[Path]
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    severity: str = "error"

    def to_dict(self) -> Dict[str, object]:
        return {
            "tool": self.tool,
            "category": self.category.value,
            "file": str(self.file) if self.file else None,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
        }


@dataclass
class HarnessResult:
    """Result of running the harness on a patch."""

    success: bool
    findings: List[HarnessFinding] = field(default_factory=list)
    tools_run: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    files_validated: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> Dict[str, object]:
        return {
            "success": self.success,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "tools_run": self.tools_run,
            "duration_seconds": self.duration_seconds,
            "files_validated": self.files_validated,
            "findings": [f.to_dict() for f in self.findings],
        }


class PatchHarness:
    """Command-based harness runner for OSS."""

    def __init__(
        self,
        project_root: Path,
        config: Optional[HarnessConfig] = None,
    ):
        from .config import load_harness_config

        self.project_root = project_root.resolve()
        self.config = config or load_harness_config(project_root)

    async def validate_changes(
        self,
        _changes: Dict[Path, str],
        timeout_override: Optional[int] = None,
    ) -> HarnessResult:
        if not self.config.enabled:
            return HarnessResult(success=True)

        if not self.config.custom_steps:
            return HarnessResult(success=True)

        start_time = time.monotonic()
        findings: List[HarnessFinding] = []
        tools_run: List[str] = []

        for step in self.config.custom_steps:
            if not step.enabled:
                continue

            tools_run.append(step.name)
            timeout = timeout_override or step.timeout_seconds
            try:
                result = subprocess.run(
                    step.command,
                    cwd=self.project_root,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.returncode != 0:
                    stderr = result.stderr.strip()
                    message = stderr or result.stdout.strip() or "Command failed"
                    findings.append(
                        HarnessFinding(
                            tool=step.name,
                            category=ValidationCategory.FUNCTIONAL,
                            file=None,
                            message=message,
                            severity="error",
                        )
                    )
            except subprocess.TimeoutExpired:
                findings.append(
                    HarnessFinding(
                        tool=step.name,
                        category=ValidationCategory.FUNCTIONAL,
                        file=None,
                        message=f"Command timed out after {timeout}s",
                        severity="warning",
                    )
                )

        duration = time.monotonic() - start_time
        success = all(f.severity != "error" for f in findings)

        return HarnessResult(
            success=success,
            findings=findings,
            tools_run=tools_run,
            duration_seconds=duration,
            files_validated=0,
        )
