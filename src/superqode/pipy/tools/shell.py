"""The bash tool.

Ported from ``packages/coding-agent/src/core/tools/bash.ts`` and
``output-accumulator.ts`` of earendil-works/pi (MIT).

Commands run with the permissions of the process, matching pi. Output streams
to the model as it arrives, is truncated from the tail, and spills to a temp
file when it exceeds the budget so nothing is silently lost.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

from ..messages import TextContent
from ..signals import AbortSignal, is_aborted
from ..types import JSONObject
from .base import AgentTool, AgentToolResult, ToolUpdateCallback
from .paths import json_schema
from .truncate import DEFAULT_MAX_BYTES, TruncationResult, format_size, truncate_tail

#: Minimum gap between streamed output updates, so a chatty command does not
#: flood the event stream.
UPDATE_THROTTLE_SECONDS = 0.1


class OutputAccumulator:
    """Collects command output, spilling the full text to a temp file."""

    def __init__(self, prefix: str = "pipy-bash") -> None:
        self._chunks: list[bytes] = []
        self._prefix = prefix
        self._temp_path: Path | None = None

    def append(self, data: bytes) -> None:
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")

    def snapshot(
        self, *, persist_if_truncated: bool = False
    ) -> tuple[TruncationResult, str | None]:
        content = self.text
        truncation = truncate_tail(content)
        path: str | None = None
        if truncation.truncated and persist_if_truncated:
            path = str(self._persist(content))
        return truncation, path

    def _persist(self, content: str) -> Path:
        if self._temp_path is None:
            handle = tempfile.NamedTemporaryFile(
                prefix=f"{self._prefix}-", suffix=".txt", delete=False, mode="w", encoding="utf-8"
            )
            handle.close()
            self._temp_path = Path(handle.name)
        self._temp_path.write_text(content, encoding="utf-8")
        return self._temp_path


BASH_DESCRIPTION = (
    "Execute a bash command in the current working directory. Returns stdout and "
    f"stderr. Output is truncated to last 2000 lines or {DEFAULT_MAX_BYTES // 1024}KB "
    "(whichever is hit first). If truncated, full output is saved to a temp file. "
    "Optionally provide a timeout in seconds."
)


def _format_output(
    truncation: TruncationResult,
    full_output_path: str | None,
    empty_text: str = "(no output)",
) -> str:
    text = truncation.content or empty_text
    if not truncation.truncated:
        return text
    start = truncation.total_lines - truncation.output_lines + 1
    end = truncation.total_lines
    if truncation.last_line_partial:
        text += (
            f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end}. "
            f"Full output: {full_output_path}]"
        )
    elif truncation.truncated_by == "lines":
        text += (
            f"\n\n[Showing lines {start}-{end} of {truncation.total_lines}. "
            f"Full output: {full_output_path}]"
        )
    else:
        text += (
            f"\n\n[Showing lines {start}-{end} of {truncation.total_lines} "
            f"({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {full_output_path}]"
        )
    return text


def _append_status(text: str, status: str) -> str:
    return f"{text}\n\n{status}" if text else status


def create_bash_tool(
    cwd: str | Path,
    *,
    shell: str = "/bin/bash",
    session_env: dict[str, str] | None = None,
) -> AgentTool:
    async def execute(
        tool_call_id: str,
        args: JSONObject,
        signal: AbortSignal | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        command = str(args["command"])
        timeout = args.get("timeout")
        timeout_seconds = float(timeout) if timeout is not None else None

        output = OutputAccumulator()
        last_update = 0.0

        def emit_update() -> None:
            nonlocal last_update
            if on_update is None:
                return
            now = time.monotonic()
            if now - last_update < UPDATE_THROTTLE_SECONDS:
                return
            last_update = now
            truncation, path = output.snapshot(persist_if_truncated=True)
            on_update(
                AgentToolResult(
                    content=[TextContent(text=truncation.content)],
                    details={"full_output_path": path} if path else None,
                )
            )

        if on_update is not None:
            on_update(AgentToolResult(content=[], details=None))

        env = {**os.environ, **(session_env or {})}
        process = await asyncio.create_subprocess_exec(
            shell,
            "-c",
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        async def pump() -> None:
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    break
                output.append(chunk)
                emit_update()

        async def watch_abort() -> None:
            # The signal is cooperative, so poll it rather than requiring the
            # caller to wire a callback into the subprocess.
            while process.returncode is None:
                if is_aborted(signal):
                    process.kill()
                    return
                await asyncio.sleep(0.05)

        pump_task = asyncio.ensure_future(pump())
        abort_task = asyncio.ensure_future(watch_abort())
        timed_out = False
        try:
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            except TimeoutError:
                timed_out = True
                process.kill()
                await process.wait()
            await pump_task
        finally:
            abort_task.cancel()

        truncation, full_output_path = output.snapshot(persist_if_truncated=True)
        text = _format_output(truncation, full_output_path)
        details: JSONObject = {"exit_code": process.returncode}
        if full_output_path:
            details["full_output_path"] = full_output_path

        if is_aborted(signal):
            raise RuntimeError(_append_status(text, "Command aborted"))
        if timed_out:
            raise RuntimeError(
                _append_status(text, f"Command timed out after {timeout_seconds:g} seconds")
            )
        if process.returncode not in (0, None):
            # pi raises here so the loop turns a failed command into an error
            # tool result, which is what makes a model actually read the output.
            raise RuntimeError(
                _append_status(text, f"Command exited with code {process.returncode}")
            )

        return AgentToolResult(content=[TextContent(text=text)], details=details)

    return AgentTool(
        name="bash",
        label="bash",
        description=BASH_DESCRIPTION,
        parameters=json_schema(
            {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (optional, no default timeout)",
                },
            },
            ["command"],
        ),
        execute_fn=execute,
        prompt_snippet="Execute bash commands (ls, grep, find, etc.)",
    )


__all__ = ["BASH_DESCRIPTION", "OutputAccumulator", "create_bash_tool"]
