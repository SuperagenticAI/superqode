"""Exactly six tools. Reuse PiPy's proven file tools, own bounded processes."""

from __future__ import annotations

import asyncio
import os
import shutil
import signal as process_signal
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from superqode.herdr import child_env
from superqode.pipy.messages import TextContent
from superqode.pipy.signals import is_aborted
from superqode.pipy.tools.base import AgentTool, AgentToolResult
from superqode.pipy.tools.files import create_read_tool, create_write_tool, create_edit_tool
from superqode.pipy.tools.paths import json_schema

TOOL_NAMES = ("read", "write", "edit", "search", "python", "bash")
OUTPUT_BYTES = 16000


async def _process(argv, cwd, args, signal=None, on_update=None):
    """Drain without unbounded RAM; kill the process group on timeout/cancel."""
    timeout = min(300.0, max(0.1, float(args.get("timeout", 60))))
    if is_aborted(signal):
        raise RuntimeError("Command aborted")
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=child_env(
            {
                **os.environ,
                "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            }
        ),
        start_new_session=os.name == "posix",
    )
    retained = bytearray()
    total = 0
    spill = tempfile.NamedTemporaryFile(prefix="codegem-output-", suffix=".txt", delete=False)
    path = Path(spill.name)

    async def pump():
        nonlocal total
        while chunk := await proc.stdout.read(8192):
            spill.write(chunk)
            total += len(chunk)
            retained.extend(chunk)
            del retained[:-OUTPUT_BYTES]

    async def watch():
        while proc.returncode is None:
            if is_aborted(signal):
                raise RuntimeError("Command aborted")
            await asyncio.sleep(0.05)

    def kill():
        try:
            if os.name == "posix":
                os.killpg(proc.pid, process_signal.SIGKILL)
            elif proc.returncode is None:
                proc.kill()
        except ProcessLookupError:
            return
        except PermissionError:
            # Some restricted macOS test runners deny process-group signals.
            # Still terminate the direct child; unrestricted hosts take the
            # process-group path above so grandchildren are killed as well.
            if proc.returncode is None:
                proc.kill()

    reader = asyncio.create_task(pump())
    watcher = asyncio.create_task(watch())
    waiter = asyncio.create_task(proc.wait())
    try:
        done, _ = await asyncio.wait(
            (waiter, watcher), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise TimeoutError(f"Command timed out after {timeout:g}s")
        if watcher in done:
            watcher.result()
        await asyncio.wait_for(reader, timeout=timeout)
    except BaseException:
        kill()
        await proc.wait()
        reader.cancel()
        raise
    finally:
        # Also reap background descendants retaining the output pipe.
        kill()
        for task in (reader, watcher, waiter):
            task.cancel()
        await asyncio.gather(reader, watcher, waiter, return_exceptions=True)
        spill.close()
        if total <= OUTPUT_BYTES:
            path.unlink(missing_ok=True)
    text = retained.decode(errors="replace") or "(no output)"
    if total > OUTPUT_BYTES:
        text += f"\n[Showing last {OUTPUT_BYTES} bytes; full output: {path}]"
    if proc.returncode:
        raise RuntimeError(f"{text}\nCommand exited with code {proc.returncode}")
    return AgentToolResult(content=[TextContent(text)], details={"exit_code": proc.returncode})


def create_tools(cwd: Path, *, config: dict | None = None) -> list[AgentTool]:
    """No MCP, delegation, or hidden model-callable helpers."""
    config = dict(config or {})
    tools = [create_read_tool(cwd), create_write_tool(cwd), create_edit_tool(cwd)]
    for name in ("search", "python", "bash"):
        key = {"search": "pattern", "python": "code", "bash": "command"}[name]
        properties = {
            key: {"type": "string"},
            "timeout": {"type": "number", "minimum": 0.1, "maximum": 300},
        }
        if name == "search":
            properties.update(
                {
                    "path": {"type": "string"},
                    "files": {"type": "boolean"},
                    "semantic": {
                        "type": "boolean",
                        "description": "Use the optional local EmbeddingGemma index instead of ripgrep.",
                    },
                }
            )

        async def execute(
            call_id, args, signal=None, on_update=None, *, tool_name=name, input_key=key
        ):
            if tool_name == "search" and args.get("semantic"):
                from superqode.codegem.retrieval import CodeGemIndex

                embedding_config = dict(config.get("embedding", {}))
                embedding_config.setdefault("provider", "ollama")
                embedding_config.setdefault(
                    "base_url", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434/v1")
                )
                if args.get("path"):
                    embedding_config.setdefault("scope", args["path"])
                index = CodeGemIndex(cwd, embedding_config)

                def report_index_progress(done, total):
                    if on_update:
                        on_update(
                            AgentToolResult(
                                content=[
                                    TextContent(
                                        f"Indexing source for semantic search: {done}/{total} chunks"
                                    )
                                ]
                            )
                        )

                await index.build(on_progress=report_index_progress)
                matches = await index.search(args[input_key], limit=5)
                text = (
                    "\n\n".join(
                        f"{item['path']}:{item['line']} (score {item['score']:.4f})\n{item['text']}"
                        for item in matches
                    )
                    or "No semantic matches"
                )
                return AgentToolResult(content=[TextContent(text)])
            if tool_name == "python":
                argv = [sys.executable, "-u", "-c", args["code"]]
            elif tool_name == "bash":
                shell = shutil.which("bash")
                if not shell:
                    raise RuntimeError("Bash is required for CodeGem's bash tool")
                argv = [shell, "--noprofile", "--norc", "-c", args["command"]]
            else:
                rg = shutil.which("rg")
                if not rg:
                    raise RuntimeError("Install ripgrep (rg) to use CodeGem search")
                if args.get("files"):
                    argv = [rg, "--files", "--glob", args["pattern"], "--", args.get("path", ".")]
                else:
                    argv = [
                        rg,
                        "--line-number",
                        "--no-heading",
                        "--color",
                        "never",
                        "--",
                        args["pattern"],
                        args.get("path", "."),
                    ]
            try:
                return await _process(argv, cwd, args, signal, on_update)
            except RuntimeError as exc:
                if tool_name == "python" and (
                    "IndentationError" in str(exc) or "SyntaxError" in str(exc)
                ):
                    raise RuntimeError(
                        f"{exc}\nCodeGem: fix the Python syntax before retrying. "
                        "For short checks use one line with semicolons, such as "
                        "import math; print(math.sqrt(9)). Run existing pytest tests "
                        "with bash using python -m pytest instead of retyping them."
                    ) from exc
                if tool_name == "search" and str(exc).endswith("Command exited with code 1"):
                    return AgentToolResult(content=[TextContent("No matches")])
                raise

        descriptions = {
            "search": "Search code with ripgrep, or set semantic=true for local EmbeddingGemma code retrieval. Semantic mode creates a local Git-aware index on first use. For large repositories, set path to a source directory to scope the index. Set files=true to find file paths by glob.",
            "python": "Execute Python code with the host Python interpreter in the working directory. Each call is a fresh process; use print for output. Prefer short checks, for example: import math; print(math.sqrt(9)). Preserve Python indentation in multiline code.",
            "bash": "Execute a Bash command in the working directory. Use for builds, tests and shell operations. Default timeout 60 seconds.",
        }
        tools.append(
            AgentTool(
                name=name,
                label=name,
                description=descriptions[name],
                parameters=json_schema(properties, [key]),
                execute_fn=execute,
                execution_mode="sequential",
                replay_safe=name == "search",
            )
        )
    # Mutations and shell commands must preserve model order within a batch.
    return [replace(tool, execution_mode="sequential") for tool in tools]
