"""CodeGem Gemini reliability: retries, thinking levels, long decode, finish reasons."""

from __future__ import annotations

import json

import httpx
import pytest

from superqode.codegem import create_tools, resolve_profile
from superqode.codegem.profiles import gemini_thinking_level
from superqode.codegem.provider import CodeGemStream, _retry_delay_from
from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.codegem import CodeGemHarnessBackend
from superqode.harness.templates import codegem_template
from superqode.pipy.messages import UserMessage
from superqode.pipy.stream import Context, Model, StreamOptions

OK = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "done"}]}, "finishReason": "STOP"}
    ],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2, "totalTokenCount": 12},
}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")


def _stream(responses, config=None, seen=None):
    queue = list(responses)

    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    stream = CodeGemStream(
        {"retry_initial_delay": 0.0, **(config or {})}, transport=httpx.MockTransport(handler)
    )
    return stream, queue


async def _run(stream, model="gemini-3.8-flash", tools=None):
    return [
        e
        async for e in stream(
            Model(model, "google"), Context("", [UserMessage("go")], tools or []), StreamOptions()
        )
    ]


# 1. Retry with backoff ---------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 503, 504])
@pytest.mark.asyncio
async def test_transient_status_is_retried(status):
    stream, queue = _stream([httpx.Response(status, json={}), httpx.Response(200, json=OK)])
    events = await _run(stream)
    assert events[-1].type == "done" and events[-1].message.text == "done"
    assert not queue


@pytest.mark.asyncio
async def test_transient_network_error_is_retried():
    stream, queue = _stream([httpx.ConnectError("reset"), httpx.Response(200, json=OK)])
    assert (await _run(stream))[-1].type == "done"


@pytest.mark.asyncio
async def test_non_retryable_status_fails_once():
    for status in (400, 499):
        stream, queue = _stream([httpx.Response(status, json={}), httpx.Response(200, json=OK)])
        events = await _run(stream)
        assert events[-1].type == "error" and len(queue) == 1


@pytest.mark.asyncio
async def test_attempts_are_bounded_and_reported(caplog):
    stream, queue = _stream([httpx.Response(503, json={})] * 5, {"max_attempts": 3})
    with caplog.at_level("WARNING", logger="superqode.codegem"):
        events = await _run(stream)
    assert events[-1].type == "error"
    assert "(after 3 attempts)" in events[-1].error.error_message
    assert len(queue) == 2
    assert "attempt 2/3" in caplog.text and "attempt 3/3" in caplog.text


def test_retry_info_and_retry_after_are_honoured():
    info = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}
                ]
            }
        },
    )
    assert _retry_delay_from(info) == 7.0
    assert _retry_delay_from(httpx.Response(503, headers={"Retry-After": "3"})) == 3.0
    assert _retry_delay_from(httpx.Response(503)) is None


@pytest.mark.asyncio
async def test_server_delay_is_used_and_long_delay_is_final(monkeypatch):
    waits = []

    async def fake_sleep(self, seconds, signal):
        waits.append(seconds)

    monkeypatch.setattr(CodeGemStream, "_sleep", fake_sleep)
    delayed = httpx.Response(429, headers={"Retry-After": "2"})
    stream, _ = _stream([delayed, httpx.Response(200, json=OK)])
    assert (await _run(stream))[-1].type == "done" and waits == [2.0]
    quota = httpx.Response(429, headers={"Retry-After": "3600"})
    stream, queue = _stream([quota, httpx.Response(200, json=OK)])
    assert (await _run(stream))[-1].type == "error" and len(queue) == 1


@pytest.mark.asyncio
async def test_local_servers_are_not_retried():
    stream, queue = _stream([httpx.Response(503, json={}), httpx.Response(200, json={})])
    events = [
        e
        async for e in stream(
            Model("gemma4:12b", "ollama"), Context("", [UserMessage("go")]), StreamOptions()
        )
    ]
    assert events[-1].type == "error" and len(queue) == 1


# 2. Thinking levels -------------------------------------------------------------


@pytest.mark.parametrize(
    "model,default",
    [
        ("gemini-4-hydrogen", "high"),
        ("gemini-4-neon", "high"),
        ("gemini-4-argon", "medium"),
        ("gemini-3.8-flash", "medium"),
        ("gemini-3.6-flash", "medium"),
        ("gemini-3.5-flash-lite", "minimal"),
        ("gemini-3.1-pro-preview", "high"),
        ("gemini-3.1-pro-preview-customtools", "high"),
        ("gemini-3-flash-preview", "high"),
    ],
)
def test_documented_thinking_defaults(model, default):
    assert resolve_profile(model, "google").thinking_level == default


@pytest.mark.asyncio
async def test_no_thinking_level_is_forced():
    seen = []
    stream, _ = _stream([httpx.Response(200, json=OK)], seen=seen)
    await _run(stream, "gemini-3.5-flash-lite")
    assert "thinkingConfig" not in seen[0]["generationConfig"]


@pytest.mark.asyncio
async def test_explicit_thinking_config_wins():
    seen = []
    stream, _ = _stream(
        [httpx.Response(200, json=OK)], {"thinking_config": {"thinkingLevel": "LOW"}}, seen
    )
    await _run(stream)
    assert seen[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW",
        "includeThoughts": True,
    }

    opt_out = []
    stream_off, _ = _stream(
        [httpx.Response(200, json=OK)],
        {"thinking_config": {"thinkingLevel": "LOW", "includeThoughts": False}},
        opt_out,
    )
    await _run(stream_off)
    assert opt_out[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW",
        "includeThoughts": False,
    }


@pytest.mark.parametrize(
    "model,level",
    [
        ("gemini-4-argon", "low"),
        ("gemini-4-argon", "medium"),
        ("gemini-4-argon", "high"),
        ("gemini-4-hydrogen", "xhigh"),
        ("gemini-4-neon", "low"),
        ("gemini-4-neon", "medium"),
        ("gemini-4-neon", "high"),
        ("gemini-4-neon", "xhigh"),
    ],
)
def test_gemini_accepts_documented_thinking_level(model, level):
    profile = resolve_profile(model, "google")
    assert gemini_thinking_level(model, profile, level) == level.upper()


@pytest.mark.parametrize("model", ["gemini-4-argon", "gemini-3.8-flash", "gemini-3.1-pro-preview"])
def test_minimal_is_rejected_where_unsupported(model):
    with pytest.raises(ValueError, match="'minimal' is not supported.*low, medium, high"):
        gemini_thinking_level(model, resolve_profile(model, "google"), "minimal")


def test_minimal_is_allowed_where_documented():
    profile = resolve_profile("gemini-3.6-flash", "google")
    assert gemini_thinking_level("gemini-3.6-flash", profile, "minimal") == "MINIMAL"


async def _backend_config(tmp_path, model, reasoning):
    spec = codegem_template()
    spec = spec.__class__(
        **{
            **spec.__dict__,
            "model_policy": spec.model_policy.__class__(
                **{**spec.model_policy.__dict__, "reasoning": reasoning}
            ),
        }
    )
    backend = CodeGemHarnessBackend()
    captured = {}

    async def resume(ref):
        captured.update(ref.metadata["runtime_config"])
        raise RuntimeError("stop")

    backend.adapter.resume = resume
    request = HarnessBackendRequest(
        spec=spec, prompt="go", provider="google", model=model, working_directory=tmp_path
    )
    with pytest.raises(RuntimeError, match="stop"):
        async for _ in backend._events(request):
            pass
    return captured


@pytest.mark.asyncio
async def test_backend_maps_argon_reasoning(tmp_path):
    config = await _backend_config(tmp_path, "gemini-4-argon", "high")
    assert config["thinking_config"] == {"thinkingLevel": "HIGH"}


@pytest.mark.asyncio
async def test_backend_rejects_unsupported_level(tmp_path):
    with pytest.raises(ValueError, match="not supported for gemini-4-argon"):
        await _backend_config(tmp_path, "gemini-4-argon", "minimal")


# 3. Argon readiness ------------------------------------------------------------


@pytest.mark.asyncio
async def test_argon_timeout_and_output_defaults(monkeypatch):
    timeouts = []
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    seen = []
    stream, _ = _stream([httpx.Response(200, json=OK)] * 2, seen=seen)
    await _run(stream, "gemini-4-argon")
    await _run(stream, "gemini-3.8-flash")
    plain, _ = _stream([httpx.Response(200, json=OK)], {"stream": False}, seen=seen)
    await _run(plain, "gemini-4-argon")
    assert timeouts[0].read >= 1200 and timeouts[0].connect <= 30.0
    assert timeouts[1].read == 180
    # Streaming default 64K for Gemini 4, non-streaming REST 32K.
    assert seen[0]["generationConfig"]["maxOutputTokens"] == 65536
    assert seen[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "MEDIUM",
        "includeThoughts": True,
    }
    assert seen[1]["generationConfig"]["maxOutputTokens"] == 32768
    assert seen[2]["generationConfig"]["maxOutputTokens"] == 32768
    assert seen[2]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MEDIUM"}


@pytest.mark.asyncio
async def test_neon_timeout_output_and_thinking_defaults(monkeypatch):
    timeouts = []
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    seen = []
    stream, _ = _stream([httpx.Response(200, json=OK), httpx.Response(200, json=OK)], seen=seen)
    await _run(stream, "gemini-4-neon")
    await _run(stream, "gemini-4-neon")
    # Connection client is reused across turns instead of opening a fresh client each turn.
    assert len(timeouts) == 1
    assert timeouts[0].read >= 1200
    assert timeouts[0].connect <= 30.0
    assert timeouts[0].write <= 60.0
    assert seen[0]["generationConfig"]["maxOutputTokens"] == 65536
    assert seen[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "HIGH",
        "includeThoughts": True,
    }
    await stream.aclose()


@pytest.mark.asyncio
async def test_backend_maps_neon_xhigh_and_rejects_minimal(tmp_path):
    config = await _backend_config(tmp_path, "gemini-4-neon", "xhigh")
    assert config["thinking_config"] == {"thinkingLevel": "XHIGH"}
    with pytest.raises(ValueError, match="not supported for gemini-4-neon"):
        await _backend_config(tmp_path, "gemini-4-neon", "minimal")


def _hop(parts, reason, token=None, thoughts=0):
    candidate = {"content": {"role": "model", "parts": parts}, "finishReason": reason}
    if token:
        candidate["continuationToken"] = token
    return httpx.Response(
        200,
        json={
            "candidates": [candidate],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 5,
                "thoughtsTokenCount": thoughts,
                "totalTokenCount": 105 + thoughts,
            },
        },
    )


@pytest.mark.asyncio
async def test_continuation_hops_join_into_one_signed_turn(tmp_path):
    seen = []
    call = {
        "functionCall": {"name": "read", "id": "c1", "args": {"path": "a"}},
        "thoughtSignature": "sig-B",
    }
    stream, queue = _stream(
        [
            _hop([{"text": "", "thoughtSignature": "sig-A"}], "CONTINUATION", "tok-1", 32768),
            _hop([{"text": "Reading"}, call], "STOP"),
        ],
        seen=seen,
    )
    events = await _run(stream, "gemini-4-argon", create_tools(tmp_path))
    message = events[-1].message
    assert events[-1].type == "done" and not queue
    assert "continuationToken" not in seen[0] and seen[1]["continuationToken"] == "tok-1"
    assert seen[0]["contents"] == seen[1]["contents"]
    assert seen[0]["generationConfig"] == seen[1]["generationConfig"]
    assert message.provider_content["parts"] == [
        {"text": "", "thoughtSignature": "sig-A"},
        {"text": "Reading"},
        call,
    ]
    assert message.tool_calls[0].id == "c1" and message.tool_calls[0].thought_signature == "sig-B"
    assert message.usage.input == 200 and message.usage.reasoning == 32768
    assert message.usage.total_tokens == 100 + 10 + 32768


@pytest.mark.asyncio
async def test_max_tokens_with_token_resumes_with_higher_limit():
    seen = []
    stream, _ = _stream(
        [_hop([{"text": "part 1 "}], "MAX_TOKENS", "tok-9"), _hop([{"text": "part 2"}], "STOP")],
        seen=seen,
    )
    events = await _run(stream, "gemini-4-argon")
    assert events[-1].type == "done" and events[-1].message.stop_reason == "stop"
    assert events[-1].message.text == "part 1 part 2"
    assert seen[1]["continuationToken"] == "tok-9"
    assert seen[1]["generationConfig"]["maxOutputTokens"] == 131072


@pytest.mark.asyncio
async def test_max_tokens_at_ceiling_reports_length():
    stream, queue = _stream(
        [_hop([{"text": "cut"}], "MAX_TOKENS", "tok"), httpx.Response(200, json=OK)],
        {"max_output_tokens": 65536, "max_output_tokens_ceiling": 65536},
    )
    events = await _run(stream, "gemini-4-argon")
    assert events[-1].message.stop_reason == "length" and len(queue) == 1


# 4. Finish reasons and parts ---------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        _hop([{"text": "{bad"}], "MALFORMED_FUNCTION_CALL"),
        httpx.Response(200, json={"candidates": []}),
        _hop([], "STOP"),
    ],
)
@pytest.mark.asyncio
async def test_malformed_or_empty_gets_one_retry(first):
    stream, queue = _stream([first, httpx.Response(200, json=OK)])
    assert (await _run(stream))[-1].type == "done" and not queue


@pytest.mark.asyncio
async def test_malformed_twice_is_an_error():
    bad = _hop([], "MALFORMED_FUNCTION_CALL")
    stream, queue = _stream([bad, bad, httpx.Response(200, json=OK)])
    events = await _run(stream)
    assert events[-1].type == "error" and "malformed function call (after one retry)" in (
        events[-1].error.error_message
    )
    assert len(queue) == 1


@pytest.mark.parametrize(
    "reason,text",
    [
        ("SAFETY", "safety reasons"),
        ("RECITATION", "recited existing content"),
        ("BLOCKLIST", "blocklisted term"),
    ],
)
@pytest.mark.asyncio
async def test_blocked_finish_reasons_are_readable(reason, text):
    body = {
        "candidates": [
            {
                "finishReason": reason,
                "safetyRatings": [
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "probability": "HIGH"}
                ],
            }
        ]
    }
    stream, queue = _stream([httpx.Response(200, json=body), httpx.Response(200, json=OK)])
    events = await _run(stream)
    message = events[-1].error.error_message
    assert events[-1].type == "error" and text in message and f"({reason})" in message
    assert len(queue) == 1
    if reason == "SAFETY":
        assert "dangerous_content" in message


@pytest.mark.asyncio
async def test_blocked_prompt_is_readable_and_not_retried():
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    stream, queue = _stream([httpx.Response(200, json=body), httpx.Response(200, json=OK)])
    events = await _run(stream)
    assert "blocked the prompt (SAFETY)" in events[-1].error.error_message and len(queue) == 1


@pytest.mark.asyncio
async def test_unknown_parts_are_skipped_and_signatures_stay_exact(tmp_path):
    parts = [
        {"executableCode": {"language": "PYTHON", "code": "1"}, "thoughtSignature": "sig-X"},
        {"futurePart": {"x": 1}},
        {"thoughtSignature": "sig-bare"},
        {"text": "answer", "thoughtSignature": "sig-T"},
    ]
    stream, _ = _stream([_hop(parts, "STOP")])
    events = await _run(stream)
    message = events[-1].message
    assert events[-1].type == "done" and message.text == "answer"
    assert message.provider_content["parts"] == parts


# 5. Sampling, thinkingBudget and retired IDs ------------------------------------


@pytest.mark.asyncio
async def test_argon_omits_sampling_and_warns_once(caplog):
    import superqode.codegem.provider as provider

    provider._warned.clear()
    config = {"temperature": 0.3, "top_p": 0.9, "top_k": 10, "candidate_count": 2}
    for _ in range(2):
        seen = []
        stream, _ = _stream([httpx.Response(200, json=OK)], config, seen)
        await _run(stream, model="gemini-4-argon")
        gen = seen[0]["generationConfig"]
        assert not {"temperature", "topP", "topK", "candidateCount"} & gen.keys()
    warnings = [r for r in caplog.records if "sampling parameters are ignored" in r.message]
    assert len(warnings) == 1
    assert "temperature, top_p, top_k, candidate_count" in warnings[0].message


@pytest.mark.asyncio
async def test_gemini3_keeps_temperature():
    seen = []
    stream, _ = _stream([httpx.Response(200, json=OK)], {"temperature": 0.4}, seen)
    await _run(stream)
    assert seen[0]["generationConfig"]["temperature"] == 0.4


@pytest.mark.asyncio
async def test_local_gemma_keeps_sampling():
    bodies = []

    def handler(request):
        if request.url.path.endswith("/show"):
            return httpx.Response(200, json={})
        bodies.append(json.loads(request.content))
        return httpx.Response(500, json={})

    stream = CodeGemStream({"top_p": 0.8, "top_k": 20}, transport=httpx.MockTransport(handler))
    async for _ in stream(
        Model("gemma4:31b", "ollama"), Context("", [UserMessage("go")], []), StreamOptions()
    ):
        pass
    text = json.dumps(bodies[0])
    assert '"top_p": 0.8' in text and '"top_k": 20' in text


@pytest.mark.asyncio
async def test_budget_and_level_keeps_level_and_warns(caplog):
    import superqode.codegem.provider as provider

    provider._warned.clear()
    seen = []
    raw = {"thinkingLevel": "LOW", "thinkingBudget": 1024}
    stream, _ = _stream([httpx.Response(200, json=OK)], {"thinking_config": raw}, seen)
    await _run(stream)
    assert seen[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW",
        "includeThoughts": True,
    }
    assert any("keeping thinkingLevel" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_gemini4_never_sends_budget():
    seen = []
    stream, _ = _stream(
        [httpx.Response(200, json=OK)], {"thinking_config": {"thinkingBudget": 512}}, seen
    )
    await _run(stream, model="gemini-4-argon")
    assert seen[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "MEDIUM",
        "includeThoughts": True,
    }


@pytest.mark.asyncio
async def test_budget_alone_still_allowed_for_gemini3():
    seen = []
    stream, _ = _stream(
        [httpx.Response(200, json=OK)], {"thinking_config": {"thinkingBudget": 512}}, seen
    )
    await _run(stream)
    assert seen[0]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 512}


@pytest.mark.parametrize(
    ("old", "new"),
    [("gemini-3.7-flash", "gemini-3.8-flash"), ("gemini-3.5-flash", "gemini-3.6-flash")],
)
@pytest.mark.asyncio
async def test_retired_ids_are_mapped(old, new, caplog):
    from superqode.providers.model_specs import normalize_model_for_provider
    from superqode.providers.models import LATEST_GOOGLE_MODEL_IDS

    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json=OK)

    stream = CodeGemStream({}, transport=httpx.MockTransport(handler))
    await _run(stream, model=old)
    assert f"/models/{new}:" in urls[0]
    assert normalize_model_for_provider("google", old) == new
    assert (
        normalize_model_for_provider("google", "gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    )
    assert old not in LATEST_GOOGLE_MODEL_IDS


def test_codegem_preferred_routes_and_carbon_profile():
    from superqode.codegem.profiles import is_codegem_preferred

    assert resolve_profile("gemini-4-carbon", "google").thinking_level == "medium"
    assert is_codegem_preferred("gemini-4-neon", "google") is True
    assert is_codegem_preferred("gemini-3.8-flash", "google") is True
    assert is_codegem_preferred("gemma-4-31b-it", "google") is True
    assert is_codegem_preferred("gemma4:26b", "ollama") is True
    assert is_codegem_preferred("google/gemma-4-31B-it", "vllm") is True
    assert is_codegem_preferred("gpt-5.4", "openai") is False
    assert is_codegem_preferred("claude-sonnet-4-6", "anthropic") is False
    assert is_codegem_preferred("qwen3:32b", "ollama") is False


def test_pipy_adapter_usage_reports_thinking_and_cached_tokens():
    from superqode.harness.pipy_adapter import _usage_dict
    from superqode.pipy.messages import Usage, UsageCost

    usage = Usage(
        input=5000,
        output=300,
        cache_read=4200,
        reasoning=900,
        total_tokens=6200,
        cost=UsageCost(total=0.015),
    )
    assert _usage_dict(usage) == {
        "input_tokens": 5000,
        "output_tokens": 300,
        "thinking_tokens": 900,
        "cached_tokens": 4200,
        "total_tokens": 6200,
        "cost_usd": 0.015,
    }


def test_pure_mode_set_reasoning_effort_validates_and_updates_codegem(tmp_path):
    from superqode.pure_mode import PureMode

    pm = PureMode()
    pm.select_harness("codegem")
    pm.session.provider = "google"
    pm.session.model = "gemini-4-neon"

    assert pm.set_reasoning_effort("medium") == "medium"
    assert pm._harness_spec.model_policy.reasoning == "medium"
    assert pm.reasoning_effort == "medium"

    assert pm.set_reasoning_effort("xhigh") == "xhigh"
    assert pm._harness_spec.model_policy.reasoning == "xhigh"

    with pytest.raises(ValueError, match="not supported for gemini-4-neon"):
        pm.set_reasoning_effort("minimal")

    assert pm.set_reasoning_effort("auto") is None
    assert pm._harness_spec.model_policy.reasoning is None


@pytest.mark.asyncio
async def test_codegem_process_streams_live_updates_and_search_falls_back_without_rg(
    tmp_path, monkeypatch
):
    (tmp_path / "demo.py").write_text("alpha = 1\nbeta = 2\n", encoding="utf-8")
    tools = {t.name: t for t in create_tools(tmp_path)}

    updates = []
    result = await tools["python"].execute(
        "p1",
        {"code": "import sys; print('line-one', flush=True); print('line-two', flush=True)"},
        on_update=lambda partial: updates.append(partial.text),
    )
    assert "line-one" in result.text and "line-two" in result.text
    assert updates and "line-one" in "".join(updates)

    monkeypatch.setattr("shutil.which", lambda name: None if name == "rg" else "/usr/bin/" + name)
    text_hits = await tools["search"].execute("s1", {"pattern": "beta"})
    assert "demo.py:2:beta = 2" in text_hits.text
    file_hits = await tools["search"].execute("s2", {"pattern": "*.py", "files": True})
    assert "demo.py" in file_hits.text


@pytest.mark.asyncio
async def test_codegem_compaction_uses_low_reasoning_and_larger_gemini4_window(tmp_path):
    from superqode.harness.codegem_adapter import CodeGemHarnessProtocolAdapter
    from superqode.harness.protocol import HarnessCreateRequest
    from superqode.pipy.compaction import _run_summary

    adapter = CodeGemHarnessProtocolAdapter()
    request = HarnessCreateRequest(
        harness_id="codegem",
        session_id="cg-neon-compaction",
        provider="google",
        model="gemini-4-neon",
        working_directory=tmp_path,
        metadata={},
    )
    session = await adapter._open(request, tmp_path)
    assert session.options.compaction_settings.reserve_tokens == 65536
    assert session.options.compaction_settings.keep_recent_tokens == 32768
    await session.abort()

    seen = []
    stream, _ = _stream(
        [httpx.Response(200, json=OK)],
        {"thinking_config": {"thinkingLevel": "HIGH"}},
        seen=seen,
    )
    summary, _ = await _run_summary(
        model=Model("gemini-4-neon", "google", supports_reasoning=True),
        stream_fn=stream,
        system_prompt="Summarize",
        messages=[UserMessage("long history")],
        instruction="Summarize now",
        signal=None,
        error_code="compaction_failed",
    )
    assert summary == "done"
    assert seen[0]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "LOW"
    await stream.aclose()
