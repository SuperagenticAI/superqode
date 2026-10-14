import asyncio
import os
import shlex
import sys

import pytest

from superqode.codegem.tools import create_tools
from superqode.pipy.signals import AbortController


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group contract")
@pytest.mark.parametrize("close_output", [False, True])
async def test_codegem_stop_covers_process_and_output_lifetimes(tmp_path, close_output):
    tool = next(tool for tool in create_tools(tmp_path) if tool.name == "bash")
    controller = AbortController()
    marker = tmp_path / "survived-stop"
    code = f"import time; from pathlib import Path; time.sleep(0.8); Path({str(marker)!r}).write_text('alive')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} &"
    if close_output:
        command = f"exec >/dev/null 2>&1; {command} wait"
    running = asyncio.create_task(
        tool.execute("stop", {"command": command, "timeout": 3}, controller.signal)
    )
    await asyncio.sleep(0.2)
    controller.abort()
    with pytest.raises(RuntimeError, match="aborted"):
        await asyncio.wait_for(running, timeout=2)
    await asyncio.sleep(0.8)
    assert not marker.exists(), "Descendant survived Stop"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group contract")
@pytest.mark.parametrize("route", ["codegem", "pipy"])
@pytest.mark.parametrize("stop", ["timeout", "task-cancel"])
async def test_process_deadline_and_task_cancel_reap_descendants(tmp_path, route, stop):
    from superqode.pipy.tools.shell import create_bash_tool

    tool = (
        next(tool for tool in create_tools(tmp_path) if tool.name == "bash")
        if route == "codegem"
        else create_bash_tool(tmp_path)
    )
    marker = tmp_path / "survived"
    code = f"import time; from pathlib import Path; time.sleep(0.8); Path({str(marker)!r}).write_text('alive')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)} &"
    running = asyncio.create_task(
        tool.execute("stop", {"command": command, "timeout": 0.15 if stop == "timeout" else 3})
    )
    if stop == "task-cancel":
        await asyncio.sleep(0.15)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    else:
        with pytest.raises((TimeoutError, RuntimeError), match="timed out"):
            await asyncio.wait_for(running, timeout=2)
    await asyncio.sleep(0.8)
    assert not marker.exists()
