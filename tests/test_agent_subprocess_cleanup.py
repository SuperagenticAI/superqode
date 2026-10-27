import asyncio
import sys

import pytest

from superqode.acp.client import ACPClient


@pytest.mark.asyncio
async def test_stop_closes_input_before_waiting_for_a_shell_child(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text('import sys; print("ready", flush=True); sys.stdin.read()')
    process = await asyncio.create_subprocess_exec(
        "sh",
        "-c",
        '"$1" "$2"; :',
        "agent-shell",
        sys.executable,
        str(script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    assert await process.stdout.readline() == b"ready\n"
    client = ACPClient(project_root=tmp_path, command="unused")
    client._process = process
    await asyncio.wait_for(client.stop(), timeout=2)
    assert process.returncode is not None
    assert process.stdin.is_closing()
    assert await process.stdout.read() == b""


@pytest.mark.asyncio
async def test_stop_reaps_a_child_that_ignores_termination(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready", flush=True); time.sleep(60)',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    assert await process.stdout.readline() == b"ready\n"
    client = ACPClient(project_root=tmp_path, command="unused")
    client._process = process
    await asyncio.wait_for(client.stop(), timeout=8)
    assert process.returncode is not None
    assert await process.stdout.read() == b""
