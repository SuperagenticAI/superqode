"""Contract tests for semantic subcalls.

`llm_query` is what separates a recursive language model from a coding agent
that happens to write Python: context stays in the environment as data, and the
model asks bounded questions about it instead of pushing it all through one
conversation. These tests pin the two properties that make that work, host-owned
limits and answers that stay out of the transcript.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from superqode.pipy.messages import AssistantMessage, TextContent, Usage, UsageCost
from superqode.pipy.provider_events import AssistantDoneEvent, AssistantErrorEvent
from superqode.pipy.stream import Model
from superqode.rlm.kernel import PersistentPythonKernel
from superqode.rlm.subcalls import (
    RLMResponse,
    SubcallExecutor,
    SubcallLimitError,
    SubcallPolicy,
)

MODEL = Model(id="fake-rlm", provider="fake", api="fake-api")


class ScriptedStream:
    """A stream function driven by a per-prompt handler."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.prompts: list[str] = []
        self.live = 0
        self.peak = 0

    def __call__(self, model: Model, context: Any, options: Any) -> Any:
        return self._stream(model, context)

    async def _stream(self, model: Model, context: Any) -> Any:
        prompt = context.messages[0].text
        self.prompts.append(prompt)
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            text = self.handler(prompt)
            if asyncio.iscoroutine(text):
                text = await text
        finally:
            self.live -= 1
        if isinstance(text, Exception):
            yield AssistantErrorEvent(
                reason="error",
                error=AssistantMessage(content=[], stop_reason="error", error_message=str(text)),
            )
            return
        yield AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(
                content=[TextContent(text=str(text))],
                usage=Usage(input=10, output=5, cost=UsageCost(total=0.001)),
            ),
        )


def _executor(handler: Any, **policy) -> SubcallExecutor:
    return SubcallExecutor(
        model=MODEL,
        stream_fn=ScriptedStream(handler),
        policy=SubcallPolicy(**policy) if policy else SubcallPolicy(),
    )


async def test_a_query_returns_a_handle_rather_than_a_wall_of_text():
    """The whole point is keeping a long answer out of the transcript."""
    executor = _executor(lambda prompt: "detail " * 500)

    response = await executor.query("what does this do", context="some source")

    assert isinstance(response, RLMResponse)
    assert len(response) == len("detail " * 500)
    assert "detail" in response.text
    # `repr` is what a returned value contributes to the conversation.
    assert len(repr(response)) < 200
    assert "chars=3500" in repr(response)


async def test_a_batch_preserves_input_order_despite_concurrency():
    async def handler(prompt: str) -> str:
        # The first prompt finishes last, so ordering cannot come from timing.
        await asyncio.sleep(0.05 if prompt.startswith("one") else 0.0)
        return prompt.split()[0]

    executor = _executor(handler)

    responses = await executor.query_batch(["one a", "two b", "three c"])

    assert [response.text for response in responses] == ["one", "two", "three"]


async def test_concurrency_is_bounded_by_the_policy():
    async def handler(prompt: str) -> str:
        await asyncio.sleep(0.02)
        return prompt

    executor = _executor(handler, max_concurrency=2, max_batch=8)

    await executor.query_batch([f"q{index}" for index in range(6)])

    assert executor.stream_fn.peak <= 2


async def test_the_quota_is_shared_between_single_calls_and_batches():
    """A per-call limit is defeated by calling more often."""
    executor = _executor(lambda prompt: "ok", max_calls=3)

    await executor.query("first")
    await executor.query_batch(["second", "third"])

    with pytest.raises(SubcallLimitError, match="Subcall limit reached"):
        await executor.query("fourth")


async def test_quota_and_usage_survive_a_resident_worker_restart(tmp_path):
    state = tmp_path / "subcalls.json"
    first = SubcallExecutor(
        model=MODEL,
        stream_fn=ScriptedStream(lambda prompt: "ok"),
        policy=SubcallPolicy(max_calls=2),
        state_path=state,
    )
    await first.query("first")

    restored = SubcallExecutor(
        model=MODEL,
        stream_fn=ScriptedStream(lambda prompt: "ok"),
        policy=SubcallPolicy(max_calls=2),
        state_path=state,
    )
    assert restored.snapshot()["usage"]["calls"] == 1
    assert restored.snapshot()["usage"]["total_tokens"] == 15
    await restored.query("second")
    with pytest.raises(SubcallLimitError, match="2 of 2 used"):
        await restored.query("third")


async def test_the_batch_size_limit_is_enforced():
    executor = _executor(lambda prompt: "ok", max_batch=2)

    with pytest.raises(SubcallLimitError, match="batch limit"):
        await executor.query_batch(["a", "b", "c"])


async def test_an_oversized_prompt_comes_back_as_data_with_advice():
    executor = _executor(lambda prompt: "ok", max_prompt_chars=100)

    response = await executor.query("q", context="x" * 500)

    assert response.ok is False
    assert "Chunk the context" in response.error
    assert executor.usage.calls == 1
    assert executor.usage.failures == 1


async def test_one_failed_subcall_does_not_take_down_its_batch():
    def handler(prompt: str) -> Any:
        return RuntimeError("provider exploded") if prompt == "bad" else "fine"

    executor = _executor(handler)

    responses = await executor.query_batch(["good", "bad", "also good"])

    assert [response.ok for response in responses] == [True, False, True]
    assert "provider exploded" in responses[1].error


async def test_a_long_answer_is_truncated_at_the_host_limit():
    executor = _executor(lambda prompt: "y" * 5000, max_response_chars=1000)

    response = await executor.query("q")

    assert len(response.text) == 1000
    assert response.truncated is True
    assert "truncated=True" in repr(response)


async def test_subcall_usage_is_attributed_separately():
    executor = _executor(lambda prompt: "ok")

    await executor.query_batch(["a", "b"])
    snapshot = executor.snapshot()

    assert snapshot["usage"]["calls"] == 2
    assert snapshot["usage"]["input_tokens"] == 20
    assert snapshot["usage"]["output_tokens"] == 10
    assert snapshot["usage"]["cost_usd"] == pytest.approx(0.002)
    assert snapshot["policy"]["max_calls"] == SubcallPolicy().max_calls


async def test_a_model_outside_the_allowlist_is_refused():
    executor = _executor(lambda prompt: "ok", models=("openai/gpt-5.2",))

    with pytest.raises(SubcallLimitError, match="allowlist"):
        await executor.query("q", model="anthropic/claude-opus-5")


async def test_the_timeout_is_reported_as_a_failed_response():
    async def handler(prompt: str) -> str:
        await asyncio.sleep(5)
        return "late"

    executor = _executor(handler, timeout=1.0)

    response = await executor.query("q")

    assert response.ok is False
    assert "timed out" in response.error
    assert executor.usage.calls == 1
    assert executor.usage.failures == 1


def test_the_policy_reads_runtime_config():
    policy = SubcallPolicy.from_config(
        {"subcall_max_calls": 5, "subcall_max_batch": 3, "subcall_models": ["openai/gpt-5.2"]}
    )

    assert policy.max_calls == 5
    assert policy.max_batch == 3
    assert policy.models == ("openai/gpt-5.2",)


async def test_the_kernel_namespace_exposes_llm_query(tmp_path):
    kernel = PersistentPythonKernel(tmp_path)
    kernel.subcalls.bind(
        _executor(lambda prompt: f"answered: {prompt}"), asyncio.get_running_loop()
    )

    result = await kernel.execute(
        "answer = llm_query('what is this', context='some text')\nanswer.text"
    )

    assert result.error is None
    assert "answered:" in result.value_repr


async def test_a_batch_from_the_kernel_namespace_keeps_order(tmp_path):
    kernel = PersistentPythonKernel(tmp_path)
    kernel.subcalls.bind(_executor(lambda prompt: prompt.upper()), asyncio.get_running_loop())

    result = await kernel.execute(
        "answers = llm_query_batched(['a', 'b'])\n[answer.text for answer in answers]"
    )

    assert result.value_repr == "['A', 'B']"


async def test_subcall_names_are_not_checkpointed(tmp_path):
    """They are host-owned callables, not user state to restore."""
    checkpoint = tmp_path / "session.kernel.pkl"
    kernel = PersistentPythonKernel(tmp_path, checkpoint_path=checkpoint)
    kernel.subcalls.bind(_executor(lambda prompt: "ok"), asyncio.get_running_loop())

    await kernel.execute("kept = 1")
    saved = kernel.checkpoint()

    assert "llm_query" not in saved["saved"]
    assert "llm_query" not in saved["skipped"]
    assert saved["saved"] == ["kept"]


async def test_an_unconfigured_kernel_says_subcalls_are_unavailable(tmp_path):
    kernel = PersistentPythonKernel(tmp_path)

    result = await kernel.execute("llm_query('anything')")

    assert "not configured" in str(result.error)
