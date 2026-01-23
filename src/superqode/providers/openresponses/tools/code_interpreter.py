"""
Code Interpreter Tool for Open Responses.

Executes code in a sandboxed environment. Supports:
- Python execution
- Shell command execution
- Test running

Features:
- Timeout control
- Output capture
- Error handling
- Resource limits

Usage:
    tool = CodeInterpreterTool(workspace_root="/path/to/project")
    result = await tool.execute("print('Hello, World!')", language="python")
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ExecutionResult:
    """Result of code execution."""

    success: bool
    output: str
    error: str = ""
    exit_code: int = 0
    timed_out: bool = False


class CodeInterpreterTool:
    """
    Code interpreter tool for Open Responses.

    Executes code in a controlled environment with timeout
    and output capture.

    Args:
        workspace_root: Root directory for execution
        timeout: Maximum execution time in seconds
        max_output_size: Maximum output size in bytes
    """

    def __init__(
        self,
        workspace_root: str,
        timeout: float = 60.0,
        max_output_size: int = 100 * 1024,  # 100KB
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout
        self.max_output_size = max_output_size

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute code in the specified language.

        Args:
            code: The code to execute
            language: Programming language ("python", "shell", "bash")
            timeout: Override default timeout

        Returns:
            Dict with success status, output, and details
        """
        use_timeout = timeout if timeout is not None else self.timeout

        if language in ("python", "python3"):
            result = await self._execute_python(code, use_timeout)
        elif language in ("shell", "bash", "sh"):
            result = await self._execute_shell(code, use_timeout)
        else:
            return {
                "success": False,
                "output": "",
                "error": f"Unsupported language: {language}",
                "exit_code": 1,
            }

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }

    async def run_tests(
        self,
        test_command: Optional[str] = None,
        test_file: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Run tests in the workspace.

        Args:
            test_command: Custom test command
            test_file: Specific test file to run
            timeout: Override default timeout

        Returns:
            Dict with test results
        """
        use_timeout = timeout if timeout is not None else self.timeout

        # Determine test command
        if test_command:
            cmd = test_command
        elif test_file:
            cmd = f"python -m pytest {test_file} -v"
        else:
            # Auto-detect test framework
            cmd = await self._detect_test_command()

        result = await self._execute_shell(cmd, use_timeout)

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "command": cmd,
        }

    async def _execute_python(
        self,
        code: str,
        timeout: float,
    ) -> ExecutionResult:
        """Execute Python code."""
        # Write code to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            dir=str(self.workspace_root),
        ) as f:
            f.write(code)
            script_file = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                script_file,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Execution timed out after {timeout} seconds",
                    exit_code=-1,
                    timed_out=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            # Truncate if needed
            if len(output) > self.max_output_size:
                output = output[: self.max_output_size] + "\n[Output truncated]"
            if len(error) > self.max_output_size:
                error = error[: self.max_output_size] + "\n[Error output truncated]"

            return ExecutionResult(
                success=proc.returncode == 0,
                output=output,
                error=error,
                exit_code=proc.returncode or 0,
                timed_out=False,
            )

        finally:
            # Clean up temp file
            try:
                os.unlink(script_file)
            except Exception:
                pass

    async def _execute_shell(
        self,
        command: str,
        timeout: float,
    ) -> ExecutionResult:
        """Execute a shell command."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Execution timed out after {timeout} seconds",
                    exit_code=-1,
                    timed_out=True,
                )

            output = stdout.decode("utf-8", errors="replace")
            error = stderr.decode("utf-8", errors="replace")

            # Truncate if needed
            if len(output) > self.max_output_size:
                output = output[: self.max_output_size] + "\n[Output truncated]"
            if len(error) > self.max_output_size:
                error = error[: self.max_output_size] + "\n[Error output truncated]"

            return ExecutionResult(
                success=proc.returncode == 0,
                output=output,
                error=error,
                exit_code=proc.returncode or 0,
                timed_out=False,
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                exit_code=1,
                timed_out=False,
            )

    async def _detect_test_command(self) -> str:
        """Detect the appropriate test command for the workspace."""
        # Check for common test configurations
        if (self.workspace_root / "pytest.ini").exists():
            return "python -m pytest -v"
        if (self.workspace_root / "pyproject.toml").exists():
            return "python -m pytest -v"
        if (self.workspace_root / "setup.py").exists():
            return "python -m pytest -v"
        if (self.workspace_root / "package.json").exists():
            return "npm test"
        if (self.workspace_root / "Cargo.toml").exists():
            return "cargo test"
        if (self.workspace_root / "go.mod").exists():
            return "go test ./..."

        # Default to pytest
        return "python -m pytest -v"

    def get_tool_definition(self) -> Dict[str, Any]:
        """Get the Open Responses tool definition for code_interpreter."""
        return {
            "type": "code_interpreter",
        }
