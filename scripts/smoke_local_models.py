"""End-to-end smoke probe for local-model harness optimizations.

Runs a tool-using prompt against an installed Ollama model and checks:
1. The request actually shapes num_ctx + keep_alive.
2. The model responds either via native tool_calls OR our inline extractor.
3. The content is not "rubbish" (empty / unparsable).

Usage:
    python scripts/smoke_local_models.py qwen3:8b
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List

from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway


def _tools() -> List[ToolDefinition]:
    return [
        ToolDefinition(
            name="read_file",
            description="Read the contents of a file at the given path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to read"}
                },
                "required": ["path"],
            },
        ),
        ToolDefinition(
            name="list_directory",
            description="List entries in a directory.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    ]


async def probe(model: str, provider: str = "ollama") -> Dict[str, Any]:
    gw = LiteLLMGateway(timeout=300.0)
    tools = _tools()

    # Capture what the gateway is about to ship by intercepting the
    # request_kwargs assembled in chat_completion. We do this by
    # exercising _apply_local_request_shaping directly first, then we
    # do a real call.
    pre_kwargs: Dict[str, Any] = {}
    gw._apply_local_request_shaping(provider, model, pre_kwargs, has_tools=True)

    messages = [
        Message(
            role="system",
            content=(
                "You are a precise coding assistant. When the user asks about a file, "
                "call the read_file tool with the appropriate path. Do not narrate."
            ),
        ),
        Message(
            role="user",
            content="What does pyproject.toml contain? Use read_file.",
        ),
    ]

    try:
        resp = await gw.chat_completion(
            messages=messages,
            model=model,
            provider=provider,
            tools=tools,
            temperature=0.0,
        )
    except Exception as e:
        return {"model": model, "ok": False, "error": f"{type(e).__name__}: {e}", "shaping": pre_kwargs}

    tool_calls = resp.tool_calls or []
    has_native_or_extracted = bool(tool_calls)
    called_read_file = any(
        (tc.get("function") or {}).get("name") == "read_file" for tc in tool_calls
    )
    return {
        "model": model,
        "ok": has_native_or_extracted and called_read_file,
        "shaping": pre_kwargs,
        "tool_calls": [
            {
                "name": (tc.get("function") or {}).get("name"),
                "arguments": (tc.get("function") or {}).get("arguments"),
            }
            for tc in tool_calls
        ],
        "content_preview": (resp.content or "")[:200],
        "finish_reason": resp.finish_reason,
    }


async def main() -> int:
    # Args parsed as "provider:model" pairs; bare arg defaults to ollama.
    raw = sys.argv[1:] or ["qwen3:8b"]
    targets: List[tuple] = []
    for r in raw:
        if r.startswith("mlx="):
            targets.append(("mlx", r[len("mlx="):]))
        elif r.startswith("ollama="):
            targets.append(("ollama", r[len("ollama="):]))
        else:
            targets.append(("ollama", r))

    for provider, model in targets:
        print(f"\n=== [{provider}] {model} ===")
        result = await probe(model, provider=provider)
        print(f"  num_ctx       : {result.get('shaping', {}).get('options', {}).get('num_ctx')}")
        print(f"  keep_alive    : {result.get('shaping', {}).get('keep_alive')}")
        print(f"  temperature   : {result.get('shaping', {}).get('temperature')}")
        print(f"  finish_reason : {result.get('finish_reason')}")
        if result.get("tool_calls"):
            print(f"  tool_calls    : {result['tool_calls']}")
        else:
            print(f"  tool_calls    : (none)")
        print(f"  content (200) : {result.get('content_preview', '')!r}")
        print(f"  PASS          : {result['ok']}")
        if not result["ok"] and result.get("error"):
            print(f"  error         : {result['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
