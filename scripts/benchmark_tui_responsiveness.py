"""Repeatable local TUI probe; requires no provider credentials or network.

Reports event-loop delay during streamed code, typing, scrolling and resizing.
Times include Textual's headless rendering and are not SSH/network measurements.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
from pathlib import Path
import statistics
import tempfile
from time import perf_counter

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog


# Generous budgets accommodate shared CI hosts while rejecting visible stalls.
# Raw timings are retained as artifacts to guide tighter measured baselines.
PERFORMANCE_BUDGETS_MS = {
    "stream_ms": 2500,
    "chunk_and_yield_p95_ms": 10,
    "chunk_and_yield_max_ms": 1000,
    "event_loop_max_delay_ms": 1000,
    "typing_two_keys_ms": 1500,
    "scroll_with_settle_ms": 750,
    "resize_with_settle_ms": 1500,
    "folded_paste_ms": 1000,
    "block_preview_ms": 1500,
    "folded_draft_typing_ms": 1500,
    "large_submission_render_ms": 1000,
}


def budget_failures(report):
    failures = []
    results = report.get("results") or []
    if sorted(tuple(result.get("size") or ()) for result in results) != [(80, 24), (120, 40)]:
        failures.append("Expected both terminal-size results.")
    for result in results:
        size = result.get("size")
        for metric, limit in PERFORMANCE_BUDGETS_MS.items():
            value = result.get(metric)
            if not isinstance(value, (int, float)) or not 0 <= value <= limit:
                failures.append(f"{size}: {metric}={value!r}; budget {limit} ms")
        lines = result.get("rendered_lines")
        if not isinstance(lines, int) or not 0 < lines < 4000:
            failures.append(f"{size}: rendered history/output exceeded the 4,000-line budget")
    return failures


async def probe(size):
    from superqode.app.draft_recovery import DraftStore

    app = SuperQodeApp()
    app._draft_store = DraftStore(Path.cwd() / f"draft-probe-{size[0]}x{size[1]}")
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
        app._welcome_active = False
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

        loop_delays = []

        async def heartbeat():
            while not producer.done():
                tick = perf_counter()
                await asyncio.sleep(0.005)
                loop_delays.append(max(0, (perf_counter() - tick) * 1000 - 5))

        producer = asyncio.create_task(stream())
        monitor = asyncio.create_task(heartbeat())
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
        await monitor
        assert prompt.value == "hi"
        # Exercise the new composer against the same long-history fixture.
        from textual import events

        prompt.focus()
        pasted = "fixture line\n" * 80000
        tick = perf_counter()
        app.post_message(events.Paste(pasted))
        await pilot.pause()
        paste_ms = (perf_counter() - tick) * 1000
        assert len(prompt.value) < 100
        assert app._expand_composer_blocks(prompt.value) == "hi" + pasted
        tick = perf_counter()
        app.action_preview_composer_block()
        await pilot.pause()
        preview_ms = (perf_counter() - tick) * 1000
        app.screen.action_close()
        await pilot.pause()
        tick = perf_counter()
        await pilot.press("!")
        folded_typing_ms = (perf_counter() - tick) * 1000
        assert app._expand_composer_blocks(prompt.value) == "hi" + pasted + "!"
        tick = perf_counter()
        log.add_user(pasted)
        await pilot.pause()
        submission_ms = (perf_counter() - tick) * 1000
        assert log._messages[-1][1] == pasted
        return {
            "size": list(size),
            "history_messages": 10000,
            "rendered_lines": len(log.lines),
            "stream_chars": len(text),
            "stream_ms": round(stream_ms, 2),
            "event_loop_max_delay_ms": round(max(loop_delays, default=0), 3),
            "chunk_and_yield_p50_ms": round(statistics.median(timings), 3),
            "chunk_and_yield_p95_ms": round(sorted(timings)[int(len(timings) * 0.95)], 3),
            "chunk_and_yield_max_ms": round(max(timings), 3),
            "typing_two_keys_ms": round(typing_ms, 2),
            "scroll_with_settle_ms": round(scroll_ms, 2),
            "resize_with_settle_ms": round(resize_ms, 2),
            "folded_paste_chars": len(pasted),
            "folded_paste_ms": round(paste_ms, 2),
            "block_preview_ms": round(preview_ms, 2),
            "folded_draft_typing_ms": round(folded_typing_ms, 2),
            "large_submission_render_ms": round(submission_ms, 2),
        }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on a responsiveness budget regression"
    )
    parser.add_argument("--output", type=Path, help="Save the JSON measurements")
    args = parser.parse_args()
    output = args.output.resolve() if args.output else None
    original_cwd = Path.cwd()
    os.environ.pop("SUPERQODE_CONNECT", None)
    os.environ["SUPERQODE_VIM_MODE"] = "0"
    try:
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            results = [await probe(size) for size in ((80, 24), (120, 40))]
    finally:
        os.chdir(original_cwd)
    report = {
        "kind": "headless local probe",
        "python": platform.python_version(),
        "platform": platform.system(),
        "budgets_ms": PERFORMANCE_BUDGETS_MS,
        "results": results,
    }
    failures = budget_failures(report)
    report["budget_failures"] = failures
    text = json.dumps(report, indent=2)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if args.check and failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
