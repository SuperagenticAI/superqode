"""Apple system on-device inference via the bundled native stdio helper."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from superqode.providers.gateway.base import StreamChunk

MODEL = "system-on-device"
GUIDE = "https://support.apple.com/en-us/121115"


def helper_path():
    value = os.environ.get("SUPERQODE_APPLE_HELPER") or shutil.which("SuperQodeAppleModel")
    if not value or not Path(value).is_file() or not os.access(value, os.X_OK):
        raise ValueError(
            "This build has no Apple model bridge. Install the current macOS app, or choose Ollama/MLX. No Python package or API key can install Apple's system model."
        )
    return str(Path(value).resolve())


def status():
    if platform.system() != "Darwin":
        return {
            "available": False,
            "state": "unsupported-system",
            "guidance": "Apple's on-device model requires a supported Mac with macOS 26+ and Apple Intelligence enabled.",
            "docs_url": GUIDE,
            "model": MODEL,
            "supports_tools": False,
        }
    try:
        result = subprocess.run(
            [helper_path(), "--status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            env=child_environment(),
        )
        if len(result.stdout) > 16000:
            raise ValueError("Invalid Apple bridge status")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or type(data.get("available")) is not bool:
            raise ValueError("Invalid Apple bridge status")
        return data
    except Exception:
        return {
            "available": False,
            "state": "bridge-unavailable",
            "guidance": "Apple model availability could not be checked. Update the macOS app, enable Apple Intelligence, then retry. Other local engines remain available.",
            "docs_url": GUIDE,
            "model": MODEL,
            "supports_tools": False,
        }


def child_environment():
    # Native Foundation Models needs no provider tokens or shell credentials.
    allowed = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "__CF_USER_TEXT_ENCODING"}
    return {name: value for name, value in os.environ.items() if name in allowed}


async def stream(messages, model=MODEL, *, tools=None, max_tokens=None, temperature=None):
    if model != MODEL:
        raise ValueError(
            "Choose Apple's system-on-device model; downloaded checkpoints use other engines"
        )
    if tools:
        raise ValueError(
            "Apple's current integration supports Direct Chat and lightweight text tasks. Choose a tool-capable local coding model for coding harnesses."
        )
    if any(
        not isinstance(message.content, str)
        or message.role not in {"system", "developer", "user", "assistant"}
        for message in messages
    ):
        raise ValueError(
            "Apple on-device chat currently accepts text conversations without images or tool results"
        )
    from .context_contract import guard_request

    raw = [{"role": message.role, "content": message.content} for message in messages]
    kept, output = guard_request(raw, None, 4096, min(max_tokens or 512, 2048))
    from .execution import annotate

    annotate(context=4096, context_source="conservative on-device cap", output_limit=output)
    payload = {"messages": [raw[i] for i in kept], "max_tokens": output, "temperature": temperature}
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
    if len(encoded) > 524288:
        raise ValueError("Apple model conversation is too large; start a new thread")
    child = await asyncio.create_subprocess_exec(
        helper_path(),
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=child_environment(),
        limit=524288,
    )
    complete = False
    try:
        child.stdin.write(encoded)
        await child.stdin.drain()
        child.stdin.close()
        while line := await asyncio.wait_for(child.stdout.readline(), timeout=180):
            event = json.loads(line)
            if event.get("event") == "text":
                text = event.get("text")
                if not isinstance(text, str):
                    raise ValueError("Invalid text from Apple model bridge")
                yield StreamChunk(content=text)
            elif event.get("event") == "error":
                raise ValueError(str(event.get("message") or "Apple model failed")[:1000])
            elif event.get("event") == "done":
                complete = True
                yield StreamChunk(finish_reason="stop")
                break
        if not complete:
            raise ValueError("Apple's response ended without completion; it was not replayed")
    finally:
        if child.returncode is None:
            try:
                child.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(child.wait(), 2)
        except asyncio.TimeoutError:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            await child.wait()
