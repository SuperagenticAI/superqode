"""
Shell Tools - Simple Command Execution.

NO command parsing, NO permission trees, NO complex safety checks.
Just run the command and return output.

Safety is handled at a higher level (user confirmation if enabled).
Git operations can be blocked during workspace tracking to maintain immutable repo guarantees.

Performance features:
- Streaming output as command runs (via ctx.on_output callback)
- Non-blocking execution with proper timeout handling
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import Tool, ToolResult, ToolContext
from .output_spill import SPILL_HARD_CAP_BYTES, truncate_with_spill
from .validation import validate_working_dir_parameter


class BashTool(Tool):
    """Execute shell commands.

    Simple, transparent shell execution with streaming output.
    Git operations can be blocked during workspace tracking.

    Performance:
        When ctx.on_output is set, output is streamed in real-time
        as it's produced, instead of waiting for command completion.
    """

    DEFAULT_TIMEOUT = 300  # 5 minutes
    MAX_OUTPUT = 50000  # 50KB - fallback cap when ctx.max_output_bytes is None
    CHUNK_SIZE = 1024  # Read chunks for streaming

    @staticmethod
    def _effective_max_output(ctx: ToolContext, default: int) -> int:
        """Return the per-call byte cap.

        AgentLoop sizes ``ctx.max_output_bytes`` from the model's
        ``max_output_tokens`` (see agent/terminal_output_limits.py). When the
        loop didn't populate it - direct tool calls, legacy callers - we fall
        back to the class default.
        """
        return ctx.max_output_bytes if ctx.max_output_bytes else default

    def __init__(self, git_guard_enabled: bool = True):
        """
        Initialize BashTool.

        Args:
            git_guard_enabled: If True, block git write operations during workspace tracking.
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
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "Start the command as a background session and return its "
                        "session_id immediately; check on it later with the "
                        "shell_session tool (poll/write/kill). Use for servers and "
                        "long builds."
                    ),
                },
            },
            "required": ["command"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = args.get("command", "")
        working_dir = args.get("working_dir")
        timeout = args.get("timeout", self.DEFAULT_TIMEOUT)

        if not command.strip():
            return ToolResult(success=False, output="", error="Empty command")

        # Models trained on the patch-envelope dialect (GPT-5.x, gpt-oss) often invoke
        # `apply_patch <<EOF` as a shell command. Route that to the real
        # apply_patch tool so the patch applies with validation, workspace
        # tracking, and post-edit verification instead of failing on a
        # missing binary.
        from .apply_patch import ApplyPatchTool, extract_heredoc_patch

        heredoc_patch = extract_heredoc_patch(command)
        if heredoc_patch is not None:
            return await ApplyPatchTool().execute({"input": heredoc_patch}, ctx)

        # Background runs are persistent sessions: start one and hand the
        # model a session_id it can poll/write/kill via shell_session.
        if args.get("run_in_background"):
            from .shell_session import ShellSessionTool

            result = await ShellSessionTool().execute(
                {
                    "action": "open",
                    "command": command,
                    "working_dir": working_dir,
                    "yield_ms": 800,
                },
                ctx,
            )
            if result.success:
                sid = result.metadata.get("session_id", "?")
                result.output += (
                    f"\n[Running in background. Check it with shell_session "
                    f'(action="poll", session_id="{sid}").]'
                )
            return result

        # Check Git Guard - block git write operations during workspace tracking
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
                    "automatically tracked and can be reverted. "
                    "Artifacts are preserved in .superqode/artifacts/",
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

    @staticmethod
    async def _spawn(command: str, cwd: Path):
        """Spawn a command, applying the local OS sandbox when one is active.

        When ``SUPERQODE_SANDBOX`` selects a sandbox mode and a backend
        (Seatbelt/bwrap) is available, the command is confined to the workspace;
        otherwise it runs through the shell unchanged.
        """
        try:
            from superqode.sandbox.local_sandbox import build_sandboxed_command

            plan = build_sandboxed_command(command, cwd)
        except Exception:
            plan = None

        from .env_policy import build_shell_env

        env = build_shell_env()
        if plan is not None and plan.applied:
            return await asyncio.create_subprocess_exec(
                *plan.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
        return await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )

    async def _execute_buffered(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute command and buffer all output (original behavior)."""
        process = await self._spawn(command, cwd)

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds",
                metadata={
                    "command": command,
                    "cwd": str(cwd),
                    "timed_out": True,
                    "timeout": timeout,
                },
            )

        # Decode output
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        # Combine output
        output = stdout_str
        if stderr_str:
            output += f"\n[stderr]\n{stderr_str}" if output else stderr_str

        # Bound the output for the model. The full text is spilled to disk so
        # nothing is lost — the model gets a head/tail preview plus the path.
        # Per-call cap so we can size to the active model's context window.
        cap = self._effective_max_output(ctx, self.MAX_OUTPUT)
        output, _truncated, spill_path = self._bound_output(output, cap)

        success = process.returncode == 0
        await ctx.emit_progress(1.0, "Complete" if success else "Failed")

        metadata: Dict[str, Any] = {
            "exit_code": process.returncode,
            "command": command,
            "cwd": str(cwd),
        }
        if spill_path is not None:
            metadata["spilled_to"] = str(spill_path)
        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Exit code: {process.returncode}",
            metadata=metadata,
        )

    @staticmethod
    def _bound_output(output: str, cap: int) -> Tuple[str, bool, Optional[Path]]:
        """Bound output to ``cap`` bytes, spilling the full text to disk."""
        return truncate_with_spill(
            output,
            max_bytes=cap,
            label="Command output",
            prefix="bash",
            direction="head_tail",
        )

    async def _execute_streaming(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute command with streaming output to callback.

        The full output (up to a 5MB hard cap) is retained for the spill
        file even after the live-stream byte cap is reached; the streams are
        always drained to EOF so a chatty process never deadlocks on a full
        pipe. Only the bounded preview is sent to the model.
        """
        process = await self._spawn(command, cwd)

        output_chunks = []  # full output for the spill file (bounded by hard cap)
        emitted_bytes = 0
        total_bytes = 0
        dropped = False
        cap = self._effective_max_output(ctx, self.MAX_OUTPUT)

        async def read_stream(stream, is_stderr: bool = False):
            """Read a stream to EOF, emitting up to ``cap`` bytes live."""
            nonlocal emitted_bytes, total_bytes, dropped

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

                # Prefix stderr
                if is_stderr and text.strip():
                    text = f"[stderr] {text}"

                # Retain for the spill file up to the hard cap; past that the
                # stream is still drained (so the process can exit) but the
                # bytes are dropped.
                if total_bytes < SPILL_HARD_CAP_BYTES:
                    output_chunks.append(text)
                else:
                    dropped = True
                total_bytes += len(text)

                # Live UI stream is bounded by the model-sized cap.
                if emitted_bytes < cap:
                    emit_text = text[: cap - emitted_bytes]
                    emitted_bytes += len(emit_text)
                    await ctx.emit_output(emit_text)

        # Create timeout task
        timed_out = False
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
            timed_out = True

        output = "".join(output_chunks)
        if dropped:
            output += f"\n\n[Process produced more than {SPILL_HARD_CAP_BYTES:,} bytes; the rest was discarded.]"
        output, _truncated, spill_path = self._bound_output(output, cap)

        if timed_out:
            metadata = {
                "command": command,
                "cwd": str(cwd),
                "timed_out": True,
                "timeout": timeout,
                "streamed": True,
            }
            if spill_path is not None:
                metadata["spilled_to"] = str(spill_path)
            return ToolResult(
                success=False,
                output=output,
                error=f"Command timed out after {timeout} seconds",
                metadata=metadata,
            )

        success = process.returncode == 0
        await ctx.emit_progress(1.0, "Complete" if success else "Failed")

        metadata = {
            "exit_code": process.returncode,
            "command": command,
            "cwd": str(cwd),
            "streamed": True,
        }
        if spill_path is not None:
            metadata["spilled_to"] = str(spill_path)
        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Exit code: {process.returncode}",
            metadata=metadata,
        )
