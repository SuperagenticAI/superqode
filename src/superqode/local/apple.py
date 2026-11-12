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


async def stream(
    messages,
    model=MODEL,
    *,
    tools=None,
    max_tokens=None,
    temperature=None,
    response_format=None,
    session_id=None,
):
    if model != MODEL:
        raise ValueError(
            "Choose Apple's system-on-device model; downloaded checkpoints use other engines"
        )
    from .apple_contract import request, tool_calls, normalized_temperature
    from . import apple_sessions
    from .context_contract import guard_request, _launch_contract_value
    from .execution import annotate
    from jsonschema import Draft202012Validator, ValidationError

    raw, definitions, output_schema = request(
        messages, tools, max_tokens, temperature, response_format
    )
    context = _launch_contract_value("apple-foundation", model, "context", 512, 4096) or 4096
    output = min(max_tokens or 512, 2048)
    cap = _launch_contract_value("apple-foundation", model, "max_tokens", 1, 2048)
    if cap:
        output = min(output, cap)
    framing = list(definitions)
    if output_schema:
        framing.append({"response_schema": output_schema})
    kept, output = guard_request(raw, framing or None, context, output)
    if len(kept) != len(raw):
        raise ValueError(
            "Apple's conversation context is full. Start a new thread or shorten the history explicitly; nothing was sent or silently removed"
        )
    annotate(context=context, context_source="conservative on-device cap", output_limit=output)
    payload = {
        "messages": [raw[i] for i in kept],
        "max_tokens": output,
        "temperature": normalized_temperature(temperature),
        "tools": definitions,
        "schema": output_schema,
        "session_id": session_id or "",
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
    if len(encoded) > 524288:
        raise ValueError("Apple model conversation is too large; start a new thread")
    path = helper_path()
    key = (path, session_id) if session_id else None

    async def spawn():
        return await asyncio.create_subprocess_exec(
            path,
            "--stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_environment(),
            limit=524288,
        )

    child = await apple_sessions.acquire(key, spawn)
    complete, reusable, handoff = False, False, None
    structured = []
    try:
        child.stdin.write(encoded)
        await child.stdin.drain()
        while line := await asyncio.wait_for(child.stdout.readline(), timeout=180):
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("Invalid Apple model bridge event")
            kind = event.get("event")
            if kind == "metadata":
                reusable = event.get("protocol") == 2
                if type(event.get("sdk_prompt_tokens")) is int:
                    annotate(
                        sdk_prompt_tokens=event["sdk_prompt_tokens"],
                        context_source="Apple SDK transcript token count; bounded context",
                    )
            elif kind == "text":
                text = event.get("text")
                if not isinstance(text, str) or handoff:
                    raise ValueError("Invalid text from Apple model bridge")
                if output_schema:
                    structured.append(text)
                else:
                    yield StreamChunk(content=text)
            elif kind == "tool_calls":
                if handoff or output_schema:
                    raise ValueError("Invalid Apple tool handoff")
                handoff = tool_calls(event.get("calls"), definitions)
            elif kind == "error":
                code = str(event.get("code") or "generation-failed")
                raise ValueError(
                    str(event.get("message") or "Apple model failed")[:1000]
                    + " ["
                    + code[:64]
                    + "]"
                )
            elif kind == "done":
                reason = event.get("finish_reason")
                if (handoff and reason != "tool_calls") or (
                    not handoff and reason not in {"stop", "length"}
                ):
                    raise ValueError("Invalid Apple model completion")
                if output_schema:
                    if reason == "length":
                        raise ValueError(
                            "Apple's structured output reached its output limit; no partial result was delivered"
                        )
                    text = "".join(structured)
                    try:
                        Draft202012Validator(output_schema).validate(json.loads(text))
                    except (ValueError, ValidationError):
                        raise ValueError(
                            "Apple's structured output did not match the requested schema; no partial result was delivered"
                        ) from None
                    yield StreamChunk(content=text)
                complete = True
                yield StreamChunk(finish_reason=reason, tool_calls=handoff)
                break
        if not complete:
            raise ValueError("Apple's response ended without completion; it was not replayed")
    finally:
        if complete and reusable:
            await apple_sessions.release(key, child)
        else:
            await apple_sessions.stop(child)
