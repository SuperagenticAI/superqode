"""Tests for cross-runtime parallel compare."""

import asyncio

import pytest

from superqode.agent.parallel_compare import (
    CompareSpec,
    parse_compare_specs,
    run_parallel_compare,
)


def test_parse_specs_handles_provider_model_and_bare_model():
    specs = parse_compare_specs(
        ["openai/gpt-4o", "claude-3-5-sonnet", "  ", "anthropic/claude-3-5-sonnet"],
        default_provider="ollama",
    )
    assert specs == [
        CompareSpec("openai", "gpt-4o"),
        CompareSpec("ollama", "claude-3-5-sonnet"),
        CompareSpec("anthropic", "claude-3-5-sonnet"),
    ]


def test_parse_specs_dedupes_and_preserves_order():
    specs = parse_compare_specs(["openai/gpt-4o", "openai/gpt-4o", "openai/o3"])
    assert specs == [CompareSpec("openai", "gpt-4o"), CompareSpec("openai", "o3")]


def test_compare_runs_concurrently_and_preserves_order():
    specs = [CompareSpec("p", "a"), CompareSpec("p", "b"), CompareSpec("p", "c")]

    async def runner(spec, prompt):
        await asyncio.sleep(0.05)
        return f"{spec.model}:{prompt}"

    async def main():
        start = asyncio.get_event_loop().time()
        results = await run_parallel_compare("hi", specs, runner)
        elapsed = asyncio.get_event_loop().time() - start
        return results, elapsed

    results, elapsed = asyncio.run(main())
    assert [r.spec.model for r in results] == ["a", "b", "c"]
    assert [r.text for r in results] == ["a:hi", "b:hi", "c:hi"]
    assert all(r.ok for r in results)
    # Concurrent: total time ~one sleep, not the sum of three.
    assert elapsed < 0.15


def test_compare_captures_per_target_errors_without_failing_batch():
    specs = [CompareSpec("p", "good"), CompareSpec("p", "bad")]

    async def runner(spec, prompt):
        if spec.model == "bad":
            raise RuntimeError("boom")
        return "ok answer"

    results = asyncio.run(run_parallel_compare("q", specs, runner))
    by_model = {r.spec.model: r for r in results}
    assert by_model["good"].ok and by_model["good"].text == "ok answer"
    assert not by_model["bad"].ok
    assert "boom" in by_model["bad"].error


def test_compare_times_out_slow_target():
    specs = [CompareSpec("p", "slow")]

    async def runner(spec, prompt):
        await asyncio.sleep(1.0)
        return "too late"

    results = asyncio.run(run_parallel_compare("q", specs, runner, timeout=0.05))
    assert not results[0].ok
    assert "timed out" in results[0].error


def test_compare_empty_specs_returns_empty():
    async def runner(spec, prompt):  # pragma: no cover - never called
        return ""

    assert asyncio.run(run_parallel_compare("q", [], runner)) == []
