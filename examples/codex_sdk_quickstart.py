#!/usr/bin/env python3
"""Drive the OpenAI Codex Python SDK programmatically through SuperQode.

Prereqs:
    pip install superqode[codex-sdk]      # installs the official `openai-codex` SDK
    # plus Codex auth (e.g. `codex login` or an OPENAI_API_KEY), per OpenAI's docs.

Run:
    python examples/codex_sdk_quickstart.py "Add a docstring to main.py"

Shows three usage patterns:
    1. run_codex      — synchronous one-shot
    2. stream_codex   — async stream of typed harness events
    3. codex_session  — multi-turn on a single Codex thread
"""

from __future__ import annotations

import asyncio
import sys

from superqode.codex import codex_session, run_codex, stream_codex


def one_shot(prompt: str) -> None:
    print("\n=== 1. run_codex (one-shot) ===")
    resp = run_codex(prompt, cwd=".", tools=True)
    print("stopped:", resp.stopped_reason, "| tool calls:", resp.tool_calls_made)
    print("response:\n", resp.content)


async def streamed(prompt: str) -> None:
    print("\n=== 2. stream_codex (typed events) ===")
    async for event in stream_codex(prompt, cwd=".", tools=True):
        if event.type == "model_delta":
            print(event.data.get("text", ""), end="", flush=True)
        elif event.type == "tool_result":
            print(f"\n[tool {event.data.get('tool_name')} -> "
                  f"success={event.data.get('success')}]")
        elif event.type == "turn_complete":
            print(f"\n[turn complete: {event.data.get('status')}]")


def multi_turn() -> None:
    print("\n=== 3. codex_session (multi-turn, one thread) ===")
    with codex_session(cwd=".", tools=True) as cx:
        # See which Codex models your account/SDK exposes:
        try:
            print("models:", cx.models())
        except Exception as exc:  # noqa: BLE001
            print("models() unavailable:", exc)
        first = asyncio.run(cx.run("In one sentence, what does this project do?"))
        print("turn 1:", first.content)
        second = asyncio.run(cx.run("Now list its top-level Python packages."))
        print("turn 2:", second.content)


if __name__ == "__main__":
    user_prompt = sys.argv[1] if len(sys.argv) > 1 else "Summarize this repository in one sentence."
    one_shot(user_prompt)
    asyncio.run(streamed(user_prompt))
    multi_turn()
