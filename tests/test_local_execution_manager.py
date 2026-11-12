"""Real local-inference coordination, cancellation and crash recovery."""

import asyncio
import json
import os
import subprocess
import sys

import pytest

from superqode.local.execution import LocalTurn, configure, snapshot

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX Mac/Linux model slot contract")


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_STATE_DIR", str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2])
async def test_local_generations_share_the_limit_and_record_queue_time(limit):
    configure(limit)
    active, peak = 0, 0

    async def generate(index):
        nonlocal active, peak
        async with LocalTurn("ollama", f"fixture-{index}") as turn:
            active += 1
            peak = max(peak, active)
            turn.observe(thinking=True)
            await asyncio.sleep(0.03)
            turn.observe(text=True, terminal=True)
            active -= 1

    await asyncio.gather(*(generate(i) for i in range(4)))
    assert peak == limit
    records = snapshot()["requests"]
    assert len(records) == 4 and all(row["status"] == "completed" for row in records)
    assert any(row["queue_s"] > 0.02 for row in records)
    assert all(row["first_text_s"] > row["first_output_s"] for row in records)
    assert all(row["output_tokens"] is None for row in records)


@pytest.mark.asyncio
async def test_cancelled_waiter_and_holder_release_slots():
    async with LocalTurn("mlx", "holder") as first:
        waiting = asyncio.create_task(LocalTurn("mlx", "waiter").__aenter__())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert any(
            row["model"] == "waiter" and row["status"] == "cancelled"
            for row in snapshot()["requests"]
        )
        first.observe(terminal=True)
    async with asyncio.timeout(1):
        async with LocalTurn("mlx", "next") as turn:
            turn.observe(terminal=True)


@pytest.mark.asyncio
async def test_queue_wait_has_a_deadline_and_leaves_no_stale_lease():
    async with LocalTurn("mlx", "holder") as holder:
        with pytest.raises(TimeoutError, match="no model request was sent"):
            async with LocalTurn("mlx", "timeout", queue_timeout=0.05):
                pytest.fail("A waiting request must not enter generation")
        holder.observe(terminal=True)
    async with LocalTurn("mlx", "next", queue_timeout=0.2) as turn:
        turn.observe(terminal=True)


def test_sync_queue_wait_uses_the_same_deadline():
    with LocalTurn("mlx", "holder") as holder:
        with pytest.raises(TimeoutError, match="generation slot"):
            with LocalTurn("mlx", "timeout", queue_timeout=0.05):
                pytest.fail("A waiting request must not enter generation")
        holder.observe(terminal=True)
    with LocalTurn("mlx", "next", queue_timeout=0.2) as turn:
        turn.observe(terminal=True)


@pytest.mark.asyncio
async def test_process_death_releases_kernel_slot_and_reports_interruption():
    code = """
import asyncio
from superqode.local.execution import LocalTurn
async def main():
    async with LocalTurn('ollama', 'crashed-worker'):
        print('acquired', flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=os.environ.copy()
    )
    try:
        assert await asyncio.wait_for(asyncio.to_thread(child.stdout.readline), 5) == "acquired\n"
        child.kill()
        child.wait(timeout=2)
        async with asyncio.timeout(1):
            async with LocalTurn("ollama", "replacement") as turn:
                turn.observe(terminal=True)
        assert any(
            row["model"] == "crashed-worker" and row["status"] == "interrupted"
            for row in snapshot()["requests"]
        )
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        child.stdout.close()


@pytest.mark.parametrize("limit", [0, 5, True, None])
def test_invalid_limits_are_refused(limit):
    with pytest.raises(ValueError):
        configure(limit)


@pytest.mark.asyncio
async def test_timing_records_do_not_store_prompts_or_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-cloud-key")
    async with LocalTurn("local-openai", "fixture") as turn:
        turn.observe(text=True, terminal=True)
    data = json.dumps(snapshot())
    assert "private-cloud-key" not in data
    assert "prompt" not in data and "reply" not in data


@pytest.mark.asyncio
async def test_tool_only_output_has_a_first_output_time_without_fabricating_text():
    from superqode.providers.gateway.base import Usage

    async with LocalTurn("local-openai", "tool-only") as turn:
        turn.observe(tools=True, terminal=True)
        duration = snapshot()["requests"][0]["generation_s"]
        turn.observe(usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5))
        assert snapshot()["requests"][0]["status"] == "completed"
    record = snapshot()["requests"][0]
    assert record["first_output_s"] is not None
    assert record["first_text_s"] is None
    assert record["output_tokens"] == 2
    assert record["generation_s"] == duration, "Consumer cleanup must not extend generation time"
