"""Repeatable local TUI probe; requires no provider credentials or network.

Reports event-loop delay during streamed code, typing, scrolling and resizing.
Times include Textual's headless rendering and are not SSH/network measurements.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import statistics
import tempfile
from time import perf_counter

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog


async def probe(size):
    app = SuperQodeApp()
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        setattr(app, name, lambda *a, **k: None)
    timings = []
    async with app.run_test(size=size) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.replay_history(
            [
                {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Turn {i}\n\n" + "Repeated output. " * 30,
                }
                for i in range(10000)
            ]
        )
        await pilot.pause()
        log.start_agent_session("Fixture", "offline")
        text = "```python\n" + "print('a long streamed code block')\n\n" * 1000 + "```\n\n"

        async def stream():
            started = perf_counter()
            for offset in range(0, len(text), 32):
                tick = perf_counter()
                log.add_response_chunk(text[offset : offset + 32])
                await asyncio.sleep(0)
                timings.append((perf_counter() - tick) * 1000)
            return (perf_counter() - started) * 1000

        producer = asyncio.create_task(stream())
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.focus()
        tick = perf_counter()
        await pilot.press("h", "i")
        typing_ms = (perf_counter() - tick) * 1000
        assert prompt.value == "hi"
        tick = perf_counter()
        log.scroll_home(animate=False)
        await pilot.pause()
        scroll_ms = (perf_counter() - tick) * 1000
        tick = perf_counter()
        await pilot.resize_terminal(size[0] + 10, size[1] + 5)
        await pilot.pause()
        resize_ms = (perf_counter() - tick) * 1000
        stream_ms = await producer
        assert prompt.value == "hi"
        return {
            "size": list(size),
            "history_messages": 10000,
            "rendered_lines": len(log.lines),
            "stream_chars": len(text),
            "stream_ms": round(stream_ms, 2),
            "chunk_and_yield_p50_ms": round(statistics.median(timings), 3),
            "chunk_and_yield_p95_ms": round(sorted(timings)[int(len(timings) * 0.95)], 3),
            "chunk_and_yield_max_ms": round(max(timings), 3),
            "typing_two_keys_ms": round(typing_ms, 2),
            "scroll_with_settle_ms": round(scroll_ms, 2),
            "resize_with_settle_ms": round(resize_ms, 2),
        }


async def main():
    os.environ.pop("SUPERQODE_CONNECT", None)
    os.environ["SUPERQODE_VIM_MODE"] = "0"
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        results = [await probe(size) for size in ((80, 24), (120, 40))]
    print(json.dumps({"kind": "headless local probe", "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
