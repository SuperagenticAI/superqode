"""Native Apple Silicon inference from complete, cached text checkpoints."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import platform
import re
import shutil

from superqode.providers.gateway.base import StreamChunk, Usage

from . import apple_sessions
from .apple import child_environment
from .apple_contract import normalized_temperature, request, tool_calls
from .storage import cache_directory

PROVIDER = "swift-mlx"
STARTER = "mlx-community/Qwen3-0.6B-4bit"
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9][a-zA-Z0-9_.-]*")
_REVISION = re.compile(r"[0-9a-f]{40}")
_LIMIT = 524288


def helper_path() -> str | None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    major = platform.mac_ver()[0].partition(".")[0]
    if not major.isdecimal() or int(major) < 27:
        return None
    path = os.environ.get("SUPERQODE_SWIFT_MLX_HELPER") or shutil.which("SuperQodeSwiftMLX")
    if path and Path(path).is_file() and os.access(path, os.X_OK):
        return str(Path(path).resolve())
    return None


def _read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Swift MLX checkpoint metadata is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid Swift MLX checkpoint metadata")
    return value


def _snapshot(model: str, root: Path) -> tuple[Path, int, int]:
    if not isinstance(model, str) or not _ID.fullmatch(model):
        raise ValueError("Use a cached Swift MLX model ID in organization/model form")
    entry = root / ("models--" + model.replace("/", "--"))
    snapshots = entry / "snapshots"
    if snapshots.is_symlink() or entry.is_symlink() or not snapshots.is_dir():
        raise ValueError(f"Download {model} into the shared model cache first")
    ref = entry / "refs" / "main"
    if ref.is_file():
        with ref.open() as stream:
            commit = stream.read(64).strip()
        candidates = [snapshots / commit] if _REVISION.fullmatch(commit) else []
    else:
        candidates = sorted(snapshots.iterdir(), reverse=True)[:32]
    for path in candidates:
        if not _REVISION.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
            continue
        try:
            config = _read_json(path / "config.json")
            if config.get("model_type") != "qwen3" or not all(
                (path / name).is_file() for name in ("tokenizer.json", "tokenizer_config.json")
            ):
                continue
            index = path / "model.safetensors.index.json"
            if index.exists():
                names = set(_read_json(index)["weight_map"].values())
            else:
                names = {"model.safetensors"}
            if not names or any(
                not isinstance(name, str)
                or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.safetensors", name)
                or not (path / name).is_file()
                for name in names
            ):
                continue
            sizes = [(path / name).stat().st_size for name in names]
            context = config.get("max_position_embeddings")
            if all(sizes) and type(context) is int and context >= 512:
                return path, min(32768, context), sum(sizes)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    raise ValueError(f"{model} needs a complete Qwen3 text checkpoint in the shared model cache")


def status() -> dict:
    helper = helper_path()
    models = []
    if helper:
        root = cache_directory()
        for entry in sorted(root.glob("models--*"))[:200]:
            identity = entry.name.removeprefix("models--").replace("--", "/", 1)
            try:
                model = model_metadata(identity, root)
            except (OSError, ValueError):
                continue
            models.append(model)
    return {"available": bool(helper), "models": models, "starter": STARTER}


def context_limit(model: str, ceiling: int | None = None) -> int:
    from .context_contract import _launch_contract_value

    if ceiling is None:
        _, ceiling, _ = _snapshot(model, cache_directory())
    override = _launch_contract_value(PROVIDER, model, "context", 512, ceiling)
    return override or min(8192, ceiling)


def model_metadata(model: str, root: Path | None = None) -> dict:
    snapshot, ceiling, size = _snapshot(model, root or cache_directory())
    return {
        "id": model,
        "context": context_limit(model, ceiling),
        "size_bytes": size,
        "revision": snapshot.name,
    }


async def stream(
    messages,
    model,
    *,
    tools=None,
    max_tokens=None,
    temperature=None,
    response_format=None,
    requested_context=None,
):
    if response_format not in (None, {"type": "text"}):
        raise ValueError(
            "Swift MLX currently supports text and tools. Choose a structured-output runtime for schemas."
        )
    path = helper_path()
    if not path:
        raise ValueError(
            "Swift MLX needs the native helper on Apple Silicon with macOS 27 or later"
        )
    snapshot, ceiling, size = await asyncio.to_thread(_snapshot, model, cache_directory())
    from .hardware import detect_hardware

    memory = detect_hardware().available_memory_gb
    if memory and size > memory * 0.70 * 1024**3:
        raise ValueError(
            "Swift MLX weights exceed the available memory budget. Choose a smaller model."
        )
    from .context_contract import _launch_contract_value
    from .execution import annotate

    raw, definitions, _ = request(messages, tools, max_tokens, temperature, None)
    for row in raw:
        if row["role"] == "developer":
            row["role"] = "system"
        for call in row.get("tool_calls") or []:
            args = call["function"].get("arguments", {})
            if isinstance(args, str):
                call["function"]["arguments"] = json.loads(args)
    context = context_limit(model, ceiling)
    if type(requested_context) is int and 512 <= requested_context < context:
        context = requested_context
    output = _launch_contract_value(PROVIDER, model, "max_tokens", 1, 4096)
    wire_tools = [{"type": "function", "function": t} for t in definitions]
    payload = {
        "snapshot": str(snapshot),
        "messages": raw,
        "tools": wire_tools,
        "context": context,
        "max_tokens": min(max_tokens or 1024, output or 4096, context // 2),
        "temperature": normalized_temperature(temperature),
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
    if len(encoded) > _LIMIT:
        raise ValueError("Swift MLX conversation exceeds the native request size limit")
    # Only weights survive a request. The helper tokenizes the full conversation
    # each time, so a comparison warmup can reuse weights across gateways.
    key = (path, PROVIDER)

    async def spawn():
        return await asyncio.create_subprocess_exec(
            path,
            "--stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_environment(),
            limit=_LIMIT,
        )

    child = await apple_sessions.acquire(key, spawn)
    complete = False
    try:
        child.stdin.write(encoded)
        await child.stdin.drain()
        while line := await asyncio.wait_for(child.stdout.readline(), timeout=180):
            event = json.loads(line)
            kind = event.get("event")
            if kind == "metadata":
                annotate(
                    context=payload["context"],
                    output_limit=payload["max_tokens"],
                    sdk_prompt_tokens=event["prompt_tokens"],
                    context_source="Swift MLX tokenizer",
                )
            elif kind == "text" and isinstance(event.get("text"), str):
                yield StreamChunk(content=event["text"])
            elif kind == "error":
                if event.get("code") == "context-full":
                    raise ValueError(
                        "Swift MLX context is full. Shorten the conversation or start a new thread."
                    )
                raise ValueError(
                    "Swift MLX " + str(event.get("message", "generation failed"))[:512]
                )
            elif kind == "done":
                calls = tool_calls(event["calls"], definitions) if event["calls"] else None
                reason = event["finish_reason"]
                if reason not in ({"tool_calls"} if calls else {"stop", "length"}):
                    raise ValueError("Invalid Swift MLX completion")
                prompt, generated = event["prompt_tokens"], event["completion_tokens"]
                usage = Usage(
                    prompt_tokens=prompt,
                    completion_tokens=generated,
                    total_tokens=prompt + generated,
                )
                complete = True
                yield StreamChunk(finish_reason=reason, tool_calls=calls, usage=usage)
                return
            else:
                raise ValueError("Invalid Swift MLX bridge event")
        raise ValueError("Swift MLX ended without a completion")
    finally:
        if complete:
            await apple_sessions.release(key, child)
        else:
            await apple_sessions.stop(child)
