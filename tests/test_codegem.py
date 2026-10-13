from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import replace

import httpx
import pytest

from superqode.codegem import TOOL_NAMES, create_tools, resolve_profile
from superqode.codegem.provider import CodeGemStream, gemini_contents, ollama_messages
from superqode.codegem import retrieval
from superqode.codegem.retrieval import CodeGemIndex, EmbeddingClient
from superqode.harness import resolve_harness
from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.codegem import CodeGemHarnessBackend
from superqode.harness.codegem_adapter import CodeGemHarnessProtocolAdapter
from superqode.harness.protocol import HarnessCreateRequest, HarnessMessage, HarnessSessionRef
from superqode.harness.templates import codegem_template
from superqode.pipy.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    ImageContent,
)
from superqode.pipy.session.codec import decode_message, encode_message
from superqode.pipy.signals import AbortController
from superqode.pipy.stream import Context, Model, StreamOptions
from pathlib import Path


@pytest.mark.parametrize(
    "model,provider,family,native",
    [
        ("gemini-3.1-pro-preview", "google", "gemini", True),
        ("gemini-4-preview", "google", "gemini", True),
        ("gemini-4-argon", "google", "gemini", True),
        ("gemma4:12b-mlx", "ollama", "gemma", True),
        ("gemma4-codegem-26b-q4", "llamacpp", "gemma", True),
        ("hf.co/google/gemma-3-4b-it:Q4", "ollama", "gemma", False),
        ("codegemma:7b", "ollama", "gemma", False),
        ("gemma3n:e4b", "ollama", "gemma", False),
    ],
)
def test_family_profiles(model, provider, family, native):
    profile = resolve_profile(model, provider)
    assert profile.family == family
    assert profile.native_tools == native
    if model.startswith("gemini-4"):
        assert profile.thinking_level is None
        assert profile.thinking is True


@pytest.mark.parametrize(
    "model,provider",
    [
        ("qwen3:8b", "ollama"),
        ("gemini-3-pro", "openai"),
        ("gemma4:12b", "google"),
        ("notgemma4", "ollama"),
    ],
)
def test_other_families_and_unsupported_transports_fail(model, provider):
    with pytest.raises(ValueError):
        resolve_profile(model, provider)


def test_native_catalog_has_exact_six_tools(tmp_path):
    definition = resolve_harness("CodeGem", root=tmp_path)
    assert definition.tools == TOOL_NAMES
    assert definition.available and definition.recommended
    assert definition.continuity == "exact-resume"
    assert [t.name for t in create_tools(tmp_path)] == list(TOOL_NAMES)
    assert all(t.execution_mode == "sequential" for t in create_tools(tmp_path))
    search = next(t for t in create_tools(tmp_path) if t.name == "search")
    assert "semantic" in search.parameters["properties"]


@pytest.mark.parametrize(
    "provider,base",
    [("ollama", "http://localhost:11434/v1"), ("openai", "http://127.0.0.1:8081/v1")],
)
def test_embedding_client_is_loopback_and_selects_supported_dimensions(provider, base):
    client = EmbeddingClient({"provider": provider, "base_url": base, "dimensions": 256})
    assert client.dimensions == 256
    other = "openai" if provider == "ollama" else "ollama"
    assert (
        client.identity
        != EmbeddingClient({"provider": other, "base_url": base, "dimensions": 256}).identity
    )
    with pytest.raises(ValueError, match="loopback"):
        EmbeddingClient({"base_url": "https://embedding.example/v1"})
    with pytest.raises(ValueError, match="dimensions"):
        EmbeddingClient({"dimensions": 300})


@pytest.mark.asyncio
async def test_sentence_transformers_uses_google_code_retrieval_prompt_and_normalizes(monkeypatch):
    seen = []

    def fake_embed(model, texts, config):
        seen.append((model, texts, config["device"]))
        return [[3.0, 4.0, *([0.0] * 126), *([100.0] * 640)] for _ in texts]

    monkeypatch.setattr(retrieval, "_sentence_transformers_embed", fake_embed)
    client = EmbeddingClient(
        {"provider": "sentence-transformers", "dimensions": 128, "device": "cpu"}
    )
    assert client.model == "google/embeddinggemma-2"
    vector = await client.query("find the symbol resolver")
    assert vector[:2] == [0.6, 0.8]
    assert len(vector) == 128
    assert seen == [
        (
            "google/embeddinggemma-2",
            ["task: code retrieval | query: find the symbol resolver"],
            "cpu",
        )
    ]


@pytest.mark.asyncio
async def test_old_ollama_embedding_error_has_a_supported_local_fallback():
    def handler(_request):
        return httpx.Response(400, text="This model requires a newer version of Ollama")

    client = EmbeddingClient(
        {"provider": "ollama", "base_url": "http://127.0.0.1:11434/v1"},
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="sentence-transformers"):
        await client.embed(["test"])


@pytest.mark.asyncio
async def test_semantic_results_do_not_spend_result_window_on_duplicate_files(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "large.py").write_text(
        "def first_match():\n    return 1\n\ndef second_match():\n    return 2\n"
    )
    (source / "other.py").write_text("def other_match():\n    return 3\n")

    class FakeClient:
        identity = "fake-embedding"

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

        async def query(self, text):
            return [1.0, 0.0]

    index = CodeGemIndex(tmp_path, {"scope": "src"}, client=FakeClient())
    await index.build()
    matches = await index.search("find a function", limit=2, hybrid=False)
    assert len(matches) == 2
    assert len({item["path"] for item in matches}) == 2


@pytest.mark.asyncio
async def test_search_tool_routes_semantic_requests_to_the_local_index(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "src" / "session.py"
    source.parent.mkdir()
    source.write_text("def resume_session():\n    return 'restored'\n")

    class FakeClient:
        identity = "embeddinggemma2-test-256"

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

        async def query(self, text):
            return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "EmbeddingClient", lambda _config: FakeClient())
    tools = {tool.name: tool for tool in create_tools(tmp_path, config={"embedding": {}})}
    result = await tools["search"].execute(
        "semantic", {"pattern": "how is the session restored", "semantic": True, "path": "src"}
    )
    assert "src/session.py:1" in result.text
    assert "resume_session" in result.text


@pytest.mark.asyncio
async def test_embeddinggemma_index_reuses_chunks_and_rejects_stale_source(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    outside = tmp_path / "docs" / "other.py"
    outside.parent.mkdir()
    outside.write_text("def locate_cache_elsewhere():\n    return 'other cache'\n")
    scoped = tmp_path / "src" / "main.py"
    scoped.parent.mkdir()
    scoped.write_text("def locate_cache_here():\n    return 'scoped cache'\n")

    class FakeClient:
        identity = "embeddinggemma2-test-256"

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

        async def query(self, text):
            return [1.0, 0.0]

    index = CodeGemIndex(tmp_path, {"scope": "src"}, client=FakeClient())
    progress = []
    built = await index.build(on_progress=lambda done, total: progress.append((done, total)))
    assert built["chunks"] == built["embedded"] == 1
    assert progress == [(1, 1)]
    assert (await index.build())["reused"] == 1
    assert (await index.search("where is cache located"))[0]["path"] == "src/main.py"

    multi_scope = CodeGemIndex(tmp_path, {"scope": ["src", "docs"]}, client=FakeClient())
    assert {row[1] for row in multi_scope.chunks()} == {
        "src/main.py",
        "docs/other.py",
    }
    assert multi_scope.path != index.path

    scoped.write_text("def locate_cache_here():\n    return 'new scoped cache'\n")
    assert await index.search("where is cache located") == []
    with pytest.raises(ValueError, match="inside the project"):
        CodeGemIndex(tmp_path, {"scope": "../outside"}, client=FakeClient())


@pytest.mark.asyncio
async def test_six_tools_execute_with_actual_artifacts(tmp_path):
    tools = {t.name: t for t in create_tools(tmp_path)}
    await tools["write"].execute("w", {"path": "a.py", "content": "value = 1\n"})
    assert "value = 1" in (await tools["read"].execute("r", {"path": "a.py"})).text
    await tools["edit"].execute(
        "e", {"path": "a.py", "edits": [{"oldText": "value = 1", "newText": "value = 2"}]}
    )
    assert "a.py:1:value = 2" in (await tools["search"].execute("s", {"pattern": "value"})).text
    assert "a.py" in (await tools["search"].execute("f", {"pattern": "*.py", "files": True})).text
    assert (
        await tools["python"].execute("p", {"code": "from a import value; print(value)"})
    ).text.strip() == "2"
    assert (
        await tools["bash"].execute(
            "b", {"command": "python -c 'from a import value; print(value)'"}
        )
    ).text.strip() == "2"
    assert (await tools["search"].execute("n", {"pattern": "not_found"})).text == "No matches"
    with pytest.raises(RuntimeError, match="code 3"):
        await tools["python"].execute("bad", {"code": "raise SystemExit(3)"})
    with pytest.raises(RuntimeError, match="one line with semicolons"):
        await tools["python"].execute("indent", {"code": "print(1)\n print(2)"})


@pytest.mark.asyncio
async def test_process_timeout_cancel_and_output_bound(tmp_path):
    python = next(t for t in create_tools(tmp_path) if t.name == "python")
    with pytest.raises(TimeoutError):
        await python.execute("timeout", {"code": "import time; time.sleep(20)", "timeout": 0.1})
    result = await python.execute("large", {"code": "print('x' * 20000)"})
    assert len(result.text) < 17000 and "full output:" in result.text
    controller = AbortController()
    task = asyncio.create_task(
        python.execute("abort", {"code": "import time; time.sleep(20)"}, controller.signal)
    )
    await asyncio.sleep(0.1)
    controller.abort()
    with pytest.raises(RuntimeError, match="aborted"):
        await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_background_pipe_timeout(tmp_path):
    bash = next(t for t in create_tools(tmp_path) if t.name == "bash")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            bash.execute("background", {"command": "sleep 20 &", "timeout": 0.1}), 2
        )


def test_native_signed_content_roundtrip_and_batch_pairing():
    raw = {
        "role": "model",
        "parts": [
            {"text": "Checking", "thoughtSignature": "signed-text"},
            {
                "functionCall": {"name": "read", "args": {"path": "a"}, "id": "call-a"},
                "thoughtSignature": "opaque-a",
            },
            {"functionCall": {"name": "read", "args": {"path": "b"}, "id": "call-b"}},
        ],
    }
    message = AssistantMessage(
        model="gemini-3-pro",
        content=[
            TextContent("Checking"),
            ToolCall("call-a", "read", {"path": "a"}),
            ToolCall("call-b", "read", {"path": "b"}),
        ],
        stop_reason="toolUse",
        provider_content=raw,
    )
    restored = decode_message(encode_message(message))
    messages = [
        restored,
        ToolResultMessage("call-a", "read", "A"),
        ToolResultMessage("call-b", "read", "B", is_error=True),
    ]
    wire = gemini_contents(messages, Model("gemini-3-pro", "google"))
    assert wire[0] == raw
    assert [p["functionResponse"]["id"] for p in wire[1]["parts"]] == ["call-a", "call-b"]
    assert wire[1]["parts"][1]["functionResponse"]["response"] == {"error": "B"}
    wire[0]["parts"][0]["text"] = "mutated"
    assert restored.provider_content == raw
    with pytest.raises(ValueError, match="switching"):
        gemini_contents(messages, Model("gemini-4-pro", "google"))


@pytest.mark.asyncio
async def test_gemini_transport_preserves_exact_signed_parts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    raw = {
        "role": "model",
        "parts": [
            {"functionCall": {"name": "read", "args": {"path": "a"}}, "thoughtSignature": "opaque"}
        ],
    }
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": raw, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3},
            },
        )

    stream = CodeGemStream(transport=httpx.MockTransport(handler))
    model = Model("gemini-3-pro", "google")
    context = Context("instructions", [UserMessage("read a")], create_tools(Path(".")))
    events = [e async for e in stream(model, context, StreamOptions())]
    final = events[-1].message
    assert final.provider_content == raw and final.tool_calls[0].thought_signature == "opaque"
    assert requests[0]["generationConfig"]["temperature"] == 1
    context.messages += [
        decode_message(encode_message(final)),
        ToolResultMessage(final.tool_calls[0].id, "read", "A"),
    ]
    _ = [e async for e in stream(model, context, StreamOptions())]
    assert requests[1]["contents"][1] == raw


@pytest.mark.asyncio
async def test_compatible_native_template_error_falls_back_to_schema_json(tmp_path):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tools"):
            return httpx.Response(
                400,
                json={"error": "Error rendering prompt with jinja template: undefined"},
            )
        response = {"content": "Ready", "tool_calls": []}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(response)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    stream = CodeGemStream(
        {"base_url": "http://127.0.0.1:1234/v1"},
        transport=httpx.MockTransport(handler),
    )
    model = Model("gemma4-codegem-26b-q4", "lmstudio")
    context = Context("instructions", [UserMessage("go")], create_tools(tmp_path))
    events = [e async for e in stream(model, context, StreamOptions())]
    assert events[-1].message.text == "Ready"
    assert requests[0].get("tools")
    assert requests[1]["response_format"]["type"] == "json_schema"
    assert "tools" not in requests[1]

    events = [e async for e in stream(model, context, StreamOptions())]
    assert events[-1].message.text == "Ready"
    assert len(requests) == 3
    assert "tools" not in requests[2]


@pytest.mark.asyncio
async def test_gemini_missing_key_and_truncation_do_not_execute(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("superqode.providers.credentials.provider_api_key", lambda provider: None)
    stream = CodeGemStream(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    context = Context("", [UserMessage("go")])
    events = [e async for e in stream(Model("gemini-3-pro", "google"), context, StreamOptions())]
    assert events[-1].type == "error" and "API_KEY" in events[-1].error.error_message


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.asyncio
async def test_ollama_capability_probe_and_validated_call(tmp_path, native):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"capabilities": ["completion", "tools"] if native else ["completion"]}
            )
        assert ("tools" in body) == native
        if native:
            result = {
                "content": "",
                "tool_calls": [{"function": {"name": "python", "arguments": {"code": "print(2)"}}}],
            }
        else:
            assert body["format"] == "json"
            result = {
                "content": json.dumps(
                    {
                        "content": "",
                        "tool_calls": [{"name": "python", "arguments": {"code": "print(2)"}}],
                    }
                )
            }
        return httpx.Response(
            200, json={"done": True, "message": result, "prompt_eval_count": 15, "eval_count": 5}
        )

    stream = CodeGemStream(transport=httpx.MockTransport(handler))
    events = [
        e
        async for e in stream(
            Model("gemma4:12b", "ollama"),
            Context("", [UserMessage("go")], create_tools(tmp_path)),
            StreamOptions(),
        )
    ]
    assert events[-1].type == "done" and events[-1].message.tool_calls[0].name == "python"
    assert events[-1].message.usage.total_tokens == 20


@pytest.mark.asyncio
async def test_kernel_backend_loop_resume_and_limits(tmp_path, monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["tools"]})
        count += 1
        if count == 1:
            message = {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "write",
                            "arguments": {"path": "done.txt", "content": "done"},
                        }
                    }
                ],
            }
        else:
            message = {"content": "Finished"}
        return httpx.Response(200, json={"done": True, "message": message})

    monkeypatch.setattr(
        "superqode.codegem.provider.CodeGemStream",
        lambda config: CodeGemStream(config, transport=httpx.MockTransport(handler)),
    )
    request = HarnessBackendRequest(
        codegem_template(), "go", "ollama", "gemma4:12b", tmp_path, session_id="same"
    )
    first = await CodeGemHarnessBackend().run(request)
    assert first.response.stopped_reason == "complete"
    assert first.response.tool_calls_made == 1 and (tmp_path / "done.txt").read_text() == "done"
    second = await CodeGemHarnessBackend().run(request)
    assert second.response.content == "Finished"
    assert len(list((tmp_path / ".superqode" / "codegem").rglob("*.jsonl"))) == 1
    limited = replace(
        request,
        spec=replace(request.spec, runtime=replace(request.spec.runtime, config={"max_turns": 1})),
        session_id="limited",
    )
    count = 0
    result = await CodeGemHarnessBackend().run(limited)
    assert result.response.stopped_reason == "error" and "max_turns" in result.response.error


@pytest.mark.asyncio
async def test_execution_policy_denial(tmp_path):
    adapter = CodeGemHarnessProtocolAdapter()
    ref = await adapter.create(
        HarnessCreateRequest(
            "codegem",
            "ollama",
            "gemma4:12b",
            tmp_path,
            metadata={"runtime_config": {"execution_policy": {"allow_shell": False}}},
        )
    )
    coding = adapter._sessions[ref.session_id]
    python = next(t for t in coding.tools if t.name == "python")
    with pytest.raises(PermissionError):
        await python.execute("blocked", {"code": "print(1)"})
    await adapter.close(ref)


@pytest.mark.asyncio
async def test_real_kernel_route_and_protocol_discovery(tmp_path, monkeypatch):
    from superqode.harness import init_harness, MemoryHarnessStore
    from superqode.harness.discovery import load_harness_adapter
    from superqode.harness.drift import detect_drift, DRIFT_OK
    from superqode.harness.diagnostics import _agent_readiness_check

    def handler(request):
        return httpx.Response(200, json={"done": True, "message": {"content": "Ready"}})

    monkeypatch.setattr(
        "superqode.codegem.provider.CodeGemStream",
        lambda config: CodeGemStream(
            {**config, "tool_mode": "native"}, transport=httpx.MockTransport(handler)
        ),
    )
    kernel = await init_harness(codegem_template(), store=MemoryHarnessStore())
    session = await kernel.session("codegem-kernel")
    result = await session.prompt(
        "go", provider="ollama", model="gemma4:12b", working_directory=tmp_path
    )
    assert result.content == "Ready" and result.response.stopped_reason == "complete"
    adapter = load_harness_adapter("codegem")
    assert isinstance(adapter, CodeGemHarnessProtocolAdapter)
    assert adapter.descriptor.capabilities.resume and not adapter.descriptor.capabilities.approvals
    assert (
        next(c for c in detect_drift(codegem_template()).checks if c.name == "tools").status
        == DRIFT_OK
    )
    assert _agent_readiness_check(codegem_template())["status"] != "error"


@pytest.mark.parametrize("finish", ["STOP", "MAX_TOKENS", "MALFORMED_FUNCTION_CALL", "SAFETY"])
@pytest.mark.asyncio
async def test_gemini_finish_reasons_and_native_ids(tmp_path, monkeypatch, finish):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    raw = {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "name": "write",
                    "id": "native-id",
                    "args": {"path": "a", "content": "x"},
                },
                "thoughtSignature": "signature",
            }
        ],
    }
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"candidates": [{"content": raw, "finishReason": finish}]}
        )
    )
    events = [
        e
        async for e in CodeGemStream(transport=transport)(
            Model("gemini-3-pro", "google"),
            Context("", [UserMessage("go")], create_tools(tmp_path)),
            StreamOptions(),
        )
    ]
    if finish == "STOP":
        assert events[-1].message.tool_calls[0].id == "native-id"
    elif finish == "MAX_TOKENS":
        assert events[-1].message.stop_reason == "length"
    else:
        assert events[-1].type == "error"
    assert not (tmp_path / "a").exists()


@pytest.mark.asyncio
async def test_provider_cancellation_is_prompt():
    async def handler(request):
        await asyncio.sleep(30)
        return httpx.Response(200)

    controller = AbortController()
    stream = CodeGemStream({"tool_mode": "native"}, transport=httpx.MockTransport(handler))

    async def collect():
        return [
            e
            async for e in stream(
                Model("gemma4:12b", "ollama"),
                Context("", [UserMessage("go")]),
                StreamOptions(signal=controller.signal),
            )
        ]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.1)
    controller.abort()
    events = await asyncio.wait_for(task, 2)
    assert events[-1].type == "error" and events[-1].error.stop_reason == "aborted"


def test_codegem_model_policy_reports_actual_defaults():
    from superqode.harness.model_policy import resolve_harness_model_policy

    spec = codegem_template()
    gemma = resolve_harness_model_policy(spec, provider="ollama", model="gemma4:12b")
    assert gemma.family == "gemma" and gemma.temperature == 1 and gemma.reasoning == "on"
    gemini = resolve_harness_model_policy(spec, provider="google", model="gemini-3-pro")
    assert gemini.family == "gemini" and gemini.reasoning == "high"


def test_tool_images_are_preserved_in_transport():
    content = {
        "role": "model",
        "parts": [{"functionCall": {"name": "read", "args": {"path": "a.png"}}}],
    }
    assistant = AssistantMessage(
        model="gemini-3-pro",
        content=[ToolCall("a", "read", {"path": "a.png"})],
        provider_content=content,
    )
    result = ToolResultMessage("a", "read", [ImageContent("aW1hZ2U=", "image/png")])
    wire = gemini_contents([assistant, result], Model("gemini-3-pro", "google"))
    assert wire[-1]["parts"][-1] == {"inlineData": {"data": "aW1hZ2U=", "mimeType": "image/png"}}
    wire = ollama_messages(Context("", [assistant, result]), native=True, system_role=True)
    assert wire[-1]["images"] == ["aW1hZ2U="]


def test_truncated_tool_calls_are_not_replayed_as_pending_calls():
    assistant = AssistantMessage(
        model="gemini-3-pro",
        stop_reason="length",
        content=[ToolCall("a", "write", {"path": "a"})],
        provider_content={
            "role": "model",
            "parts": [{"functionCall": {"name": "write", "args": {"path": "a"}}}],
        },
    )
    context = Context("", [UserMessage("go"), assistant, UserMessage("continue")])
    assert all(
        c["role"] == "user"
        for c in gemini_contents(context.messages, Model("gemini-3-pro", "google"))
    )
    assert not any(
        "tool_calls" in m for m in ollama_messages(context, native=True, system_role=True)
    )


def test_interrupted_mutations_get_unknown_outcome_responses():
    raw = {
        "role": "model",
        "parts": [
            {
                "functionCall": {"name": "write", "id": "native", "args": {"path": "a"}},
                "thoughtSignature": "opaque",
            }
        ],
    }
    assistant = AssistantMessage(
        model="gemini-3-pro",
        stop_reason="toolUse",
        content=[ToolCall("native", "write", {"path": "a"})],
        provider_content=raw,
    )
    wire = gemini_contents(
        [UserMessage("go"), assistant, UserMessage("continue")], Model("gemini-3-pro", "google")
    )
    assert wire[1] == raw
    response = wire[2]["parts"][0]["functionResponse"]
    assert response["id"] == "native" and "outcome is unknown" in response["response"]["error"]
    assert wire[2]["parts"][1] == {"text": "continue"}


@pytest.mark.asyncio
async def test_resuming_different_model_is_rejected(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"done": True, "message": {"content": "Done"}})

    monkeypatch.setattr(
        "superqode.codegem.provider.CodeGemStream",
        lambda config: CodeGemStream(
            {"tool_mode": "native"}, transport=httpx.MockTransport(handler)
        ),
    )
    request = HarnessBackendRequest(
        codegem_template(), "go", "ollama", "gemma4:12b", tmp_path, session_id="switch"
    )
    await CodeGemHarnessBackend().run(request)
    with pytest.raises(ValueError, match="changing the model"):
        await CodeGemHarnessBackend().run(replace(request, model="gemma4:31b"))


@pytest.mark.asyncio
@pytest.mark.parametrize("context_window,expected", [(None, 32768), (4096, 4096), (65536, 65536)])
async def test_local_context_and_output_are_bounded_for_imported_models(
    tmp_path, context_window, expected
):
    config = {} if context_window is None else {"context_window": context_window}
    adapter = CodeGemHarnessProtocolAdapter()
    ref = await adapter.create(
        HarnessCreateRequest(
            "codegem",
            "ollama",
            "gemma4-imported-q4",
            tmp_path,
            metadata={"runtime_config": config},
        )
    )
    coding = adapter._sessions[ref.session_id]
    assert coding.options.model.context_window == expected
    assert coding.options.stream_fn.config["max_output_tokens"] == min(8192, expected // 4)
    assert coding.options.compaction_settings.reserve_tokens <= expected // 4
    assert coding.options.compaction_settings.keep_recent_tokens <= expected // 4
    await adapter.close(ref)


def test_incompatible_model_cannot_replace_connected_codegem_session(tmp_path, monkeypatch):
    from superqode.pure_mode import PureMode

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "codegem")
    pure = PureMode()
    pure.connect("ollama", "gemma4:12b")
    with pytest.raises(ValueError, match="only Gemini and Gemma"):
        pure.connect("ollama", "qwen3:8b")
    assert pure.session.connected and pure.session.model == "gemma4:12b"
    pure.disconnect()


@pytest.mark.asyncio
async def test_compatible_tool_results_keep_ids_when_completion_order_changes(tmp_path):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Done"},
                    }
                ]
            },
        )

    model = Model("gemma4:12b", "llamacpp")
    context = Context(
        "instructions",
        [
            UserMessage("Inspect both files"),
            AssistantMessage(
                model=model.id,
                provider=model.provider,
                stop_reason="toolUse",
                content=[
                    ToolCall("first", "read", {"path": "a.py"}),
                    ToolCall("second", "read", {"path": "b.py"}),
                ],
            ),
            ToolResultMessage("second", "read", "b"),
            ToolResultMessage("first", "read", "a"),
        ],
        create_tools(tmp_path),
    )
    events = [
        e
        async for e in CodeGemStream(transport=httpx.MockTransport(handler))(
            model, context, StreamOptions()
        )
    ]
    assert events[-1].message.text == "Done"
    results = [m for m in requests[0]["messages"] if m["role"] == "tool"]
    assert [(m["tool_call_id"], m["content"]) for m in results] == [("second", "b"), ("first", "a")]


@pytest.mark.asyncio
async def test_semantic_file_scope_and_replaced_symlinks(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "source.py"
    source.write_text("def answer():\n    return 42\n")

    class Client:
        identity = "test"

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

        async def query(self, text):
            return [1.0, 0.0]

    index = CodeGemIndex(tmp_path, {"scope": "source.py"}, client=Client())
    assert (await index.build())["chunks"] == 1
    assert (await index.search("answer"))[0]["path"] == "source.py"
    target = tmp_path / "target.py"
    target.write_text(source.read_text())
    source.unlink()
    source.symlink_to(target)
    assert await index.search("answer") == []

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    directory = project / "src"
    directory.mkdir()
    (directory / "outside.py").write_text("def private_context():\n    return 123\n")
    subprocess.run(["git", "add", "src/outside.py"], cwd=project, check=True)
    outside = tmp_path / "outside"
    directory.rename(outside)
    directory.symlink_to(outside, target_is_directory=True)
    assert CodeGemIndex(project, client=Client()).chunks() == []


@pytest.mark.asyncio
async def test_metal_embedding_does_not_block_terminal_event_loop(monkeypatch):
    import threading

    release = threading.Event()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    threads = []

    def embed(model, texts, config):
        threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=5)
        return [[1.0, *([0.0] * 127)]]

    monkeypatch.setattr(retrieval, "_sentence_transformers_embed", embed)
    client = EmbeddingClient(
        {"provider": "sentence-transformers", "device": "mps", "dimensions": 128}
    )
    task = asyncio.create_task(client.query("resume"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not task.done()
        assert len(threads) == 1 and threads[0] != threading.get_ident()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_cancel_by_public_session_id_interrupts_provider_request(tmp_path, monkeypatch):
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.sleep(60)
        return httpx.Response(200, json={"done": True, "message": {"content": "Done"}})

    monkeypatch.setattr(
        "superqode.codegem.provider.CodeGemStream",
        lambda config: CodeGemStream(
            {**config, "tool_mode": "native"},
            transport=httpx.MockTransport(handler),
        ),
    )
    backend = CodeGemHarnessBackend()
    task = asyncio.create_task(
        backend.run(
            HarnessBackendRequest(
                codegem_template(),
                "go",
                "ollama",
                "gemma4:12b",
                tmp_path,
                session_id="public/id",
            )
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    try:
        await backend.cancel("another-session")
        assert not task.done()
        await backend.cancel("public/id")
        result = await asyncio.wait_for(task, 2)
        assert result.response.stopped_reason == "error"
        assert "aborted" in result.response.error.lower()
        assert backend._active_ref is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_composer_images_reach_codegem_through_pure_mode(tmp_path, monkeypatch, streaming):
    from superqode.pure_mode import PureMode

    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"done": True, "message": {"content": "Image reviewed"}})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "codegem")
    monkeypatch.setattr(
        "superqode.codegem.provider.CodeGemStream",
        lambda config: CodeGemStream(
            {**config, "tool_mode": "native"},
            transport=httpx.MockTransport(handler),
        ),
    )
    pure = PureMode()
    pure.connect("ollama", "gemma4:12b-mlx")
    image = ImageContent("aW1hZ2U=", "image/png")
    if streaming:
        text = "".join([chunk async for chunk in pure.run_streaming("Review", images=[image])])
    else:
        text = (await pure.run("Review", images=[image])).content
    assert text == "Image reviewed"
    assert requests[0]["messages"][-1]["images"] == [image.data]
    pure.disconnect()


@pytest.mark.asyncio
async def test_gemini4_usage_estimate_includes_thinking_and_discounted_cache():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Done"}],
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1000,
                    "cachedContentTokenCount": 200,
                    "candidatesTokenCount": 100,
                    "thoughtsTokenCount": 50,
                    "totalTokenCount": 1150,
                },
            },
        )

    events = [
        e
        async for e in CodeGemStream(transport=httpx.MockTransport(handler))(
            Model("gemini-4-argon", "google"),
            Context("instructions", [UserMessage("go")]),
            StreamOptions(api_key="fixture"),
        )
    ]
    usage = events[-1].message.usage
    assert usage.cost.input == pytest.approx(0.0016)
    assert usage.cost.output == pytest.approx(0.0015)
    assert usage.cost.cache_read == pytest.approx(0.00002)
    assert usage.cost.total == pytest.approx(0.00312)
