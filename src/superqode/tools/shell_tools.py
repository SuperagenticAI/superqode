"""
Shell Tools - Simple Command Execution.

NO command parsing, NO permission trees, NO complex safety checks.
Just run the command and return output.

Safety is handled at a higher level (user confirmation if enabled).
Git operations are blocked during QE sessions to maintain immutable repo guarantee.

Performance features:
- Streaming output as command runs (via ctx.on_output callback)
- Non-blocking execution with proper timeout handling
"""

import asyncio
from pathlib import Path
from typing import Any, Dict

from .base import Tool, ToolResult, ToolContext
from .validation import validate_working_dir_parameter


class BashTool(Tool):
    """Execute shell commands.

    Simple, transparent shell execution with streaming output.
    Git operations are blocked during QE sessions.

    Performance:
        When ctx.on_output is set, output is streamed in real-time
        as it's produced, instead of waiting for command completion.
    """

    DEFAULT_TIMEOUT = 120  # 2 minutes
    MAX_OUTPUT = 50000  # 50KB output limit
    CHUNK_SIZE = 1024  # Read chunks for streaming

    def __init__(self, git_guard_enabled: bool = True):
        """
        Initialize BashTool.

        Args:
            git_guard_enabled: If True, block git write operations during QE.
        """
        self._git_guard_enabled = git_guard_enabled

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command (optional)",
                },
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)"},
            },
            "required": ["command"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = args.get("command", "")
        working_dir = args.get("working_dir")
        timeout = args.get("timeout", self.DEFAULT_TIMEOUT)

        if not command.strip():
            return ToolResult(success=False, output="", error="Empty command")

        # Check Git Guard - block git write operations during QE
        if self._git_guard_enabled:
            try:
                from superqode.workspace.git_guard import get_git_guard, GitOperationBlocked

                guard = get_git_guard()
                if guard.enabled:
                    guard.check_command(command)
            except GitOperationBlocked as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"🛡️ Git operation blocked: {e.reason}\n\n"
                    f"💡 {e.suggestion}\n\n"
                    "SuperQode runs in ephemeral mode - all changes are "
                    "automatically tracked and reverted after QE completes. "
                    "Findings are preserved in .superqode/qe-artifacts/",
                    metadata={"blocked_by": "git_guard", "command": command},
                )
            except ImportError:
                pass  # Git guard not available, continue

        # Validate and resolve working directory - ensures it stays within ctx.working_directory
        try:
            cwd = validate_working_dir_parameter(working_dir, ctx.working_directory)
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        # Emit initial progress
        await ctx.emit_progress(0.0, f"Running: {command[:50]}...")

        try:
            # PERFORMANCE: Use streaming mode if callback is set
            if ctx.on_output:
                return await self._execute_streaming(command, cwd, timeout, ctx)
            else:
                return await self._execute_buffered(command, cwd, timeout, ctx)

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def _execute_buffered(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute command and buffer all output (original behavior)."""
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(
                success=False, output="", error=f"Command timed out after {timeout} seconds"
            )

        # Decode output
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        # Combine output
        output = stdout_str
        if stderr_str:
            output += f"\n[stderr]\n{stderr_str}" if output else stderr_str

        # Truncate if too long
        if len(output) > self.MAX_OUTPUT:
            output = (
                output[: self.MAX_OUTPUT] + f"\n\n[Output truncated at {self.MAX_OUTPUT} bytes]"
            )

        success = process.returncode == 0
        await ctx.emit_progress(1.0, "Complete" if success else "Failed")

        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Exit code: {process.returncode}",
            metadata={"exit_code": process.returncode, "command": command, "cwd": str(cwd)},
        )

    async def _execute_streaming(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute command with streaming output to callback."""
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )

        output_chunks = []
        total_bytes = 0
        truncated = False

        async def read_stream(stream, is_stderr: bool = False):
            """Read from a stream and emit chunks."""
            nonlocal total_bytes, truncated

            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream.read(self.CHUNK_SIZE),
                        timeout=1.0,  # Check timeout every second
                    )
                except asyncio.TimeoutError:
                    continue  # Keep reading

                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")

                # Check size limit
                if total_bytes + len(text) > self.MAX_OUTPUT:
                    remaining = self.MAX_OUTPUT - total_bytes
                    if remaining > 0:
                        text = text[:remaining]
                        output_chunks.append(text)
                        await ctx.emit_output(text)
                    truncated = True
                    break

                total_bytes += len(text)

                # Prefix stderr
                if is_stderr and text.strip():
                    text = f"[stderr] {text}"

                output_chunks.append(text)
                await ctx.emit_output(text)

        # Create timeout task
        try:
            # Read both streams concurrently
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout, is_stderr=False),
                    read_stream(process.stderr, is_stderr=True),
                ),
                timeout=timeout,
            )
            await process.wait()
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(
                success=False,
                output="".join(output_chunks),
                error=f"Command timed out after {timeout} seconds",
            )

        output = "".join(output_chunks)
        if truncated:
            output += f"\n\n[Output truncated at {self.MAX_OUTPUT} bytes]"

        success = process.returncode == 0
        await ctx.emit_progress(1.0, "Complete" if success else "Failed")

        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Exit code: {process.returncode}",
            metadata={
                "exit_code": process.returncode,
                "command": command,
                "cwd": str(cwd),
                "streamed": True,
            },
        )
