"""Local Gemma routes, Gemma on the Gemini API, and vLLM context discovery.

No network or paid calls: every server is an httpx.MockTransport. Template
tests render CodeGem's messages with jinja2 through the official Gemma 4
chat template vendored in tests/fixtures/gemma4 (see SOURCE.md there).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from superqode.codegem import create_tools, resolve_profile
from superqode.codegem.provider import (
    CodeGemStream,
    discover_server_context,
    ollama_messages,
    template_messages,
)
from superqode.pipy.messages import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from superqode.pipy.stream import Context, Model, StreamOptions

jinja2 = pytest.importorskip("jinja2")
from jinja2.sandbox import ImmutableSandboxedEnvironment  # noqa: E402

TEMPLATE = Path(__file__).parent / "fixtures" / "gemma4" / "chat_template.jinja"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    for name in ("OLLAMA_HOST", "LMSTUDIO_HOST", "LLAMACPP_HOST", "VLLM_HOST"):
        monkeypatch.delenv(name, raising=False)


def _render(messages, tools=None, **kwargs):
    def raise_exception(message):
        raise jinja2.exceptions.TemplateError(message)

    env = ImmutableSandboxedEnvironment(
        trim_blocks=True, lstrip_blocks=True, extensions=["jinja2.ext.loopcontrols"]
    )
    env.globals["raise_exception"] = raise_exception
    env.filters["tojson"] = lambda value, **kw: json.dumps(
        value, **{k: v for k, v in kw.items() if k in {"indent", "sort_keys"}}
    )
    template = env.from_string(TEMPLATE.read_text())
    return template.render(
        messages=messages, tools=tools, bos_token="<bos>", add_generation_prompt=True, **kwargs
    )


def _tools():
    return [t for t in create_tools(Path("/tmp")) if t.name == "read"]


def _tool_schemas():
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in _tools()
    ]


def _conversation(model):
    """Two user turns; the second has a parallel batch answered out of order,
    with an image returned by one tool."""
    return Context(
        "You are CodeGem.",
        [
            UserMessage("first task"),
            AssistantMessage(
                model=model.id,
                provider=model.provider,
                stop_reason="toolUse",
                content=[ThinkingContent("old thought"), ToolCall("c0", "read", {"path": "x.py"})],
            ),
            ToolResultMessage("c0", "read", "x"),
            AssistantMessage(
                model=model.id,
                provider=model.provider,
                stop_reason="stop",
                content=[TextContent("ok")],
            ),
            UserMessage("open a.py and b.png"),
            AssistantMessage(
                model=model.id,
                provider=model.provider,
                stop_reason="toolUse",
                content=[
                    ThinkingContent("need both"),
                    ToolCall("c1", "read", {"path": "a.py"}),
                    ToolCall("c2", "read", {"path": "b.png"}),
                ],
            ),
            ToolResultMessage(
                "c2", "read", [TextContent("image"), ImageContent("QUJD", "image/png")]
            ),
            ToolResultMessage("c1", "read", "x=1"),
        ],
        _tools(),
    )


async def _bodies(model, handler, config=None, context=None):
    seen = []

    def record(request):
        seen.append((request.url.path, json.loads(request.content) if request.content else None))
        return handler(request)

    stream = CodeGemStream(config or {}, transport=httpx.MockTransport(record))
    events = [e async for e in stream(model, context or _conversation(model), StreamOptions())]
    assert events[-1].type == "done", getattr(
        getattr(events[-1], "error", None), "error_message", None
    )
    return seen


def _ollama(capabilities):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": capabilities})
        return httpx.Response(200, json={"done": True, "message": {"content": "done"}})

    return handler


def _compatible(request):
    return httpx.Response(
        200, json={"choices": [{"finish_reason": "stop", "message": {"content": "done"}}]}
    )


# Golden request bodies -----------------------------------------------------------

GEMMA4_OLLAMA_MESSAGES = [
    {"role": "system", "content": "You are CodeGem."},
    {"role": "user", "content": "first task"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c0",
                "type": "function",
                "function": {"name": "read", "arguments": {"path": "x.py"}},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c0", "content": "x", "tool_name": "read"},
    {"role": "assistant", "content": "ok"},
    {"role": "user", "content": "open a.py and b.png"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read", "arguments": {"path": "a.py"}},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "read", "arguments": {"path": "b.png"}},
            },
        ],
        "thinking": "need both",
    },
    {"role": "tool", "tool_call_id": "c1", "content": "x=1", "tool_name": "read"},
    {
        "role": "tool",
        "tool_call_id": "c2",
        "content": "image",
        "tool_name": "read",
        "images": ["QUJD"],
    },
]


@pytest.mark.asyncio
async def test_golden_ollama_gemma4_body():
    model = Model("gemma4:e4b", "ollama", context_window=32768)
    seen = await _bodies(model, _ollama(["completion", "tools", "thinking", "vision"]))
    path, body = seen[-1]
    assert path == "/api/chat"
    assert body["messages"] == GEMMA4_OLLAMA_MESSAGES
    assert body["options"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "num_predict": 8192,
        "num_ctx": 32768,
    }
    assert body["think"] is False
    assert [t["function"]["name"] for t in body["tools"]] == ["read"]
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_golden_vllm_gemma4_body_keeps_openai_string_arguments():
    model = Model("google/gemma-4-31B-it", "vllm")
    seen = await _bodies(model, _compatible)
    path, body = seen[-1]
    assert path == "/v1/chat/completions"
    messages = body["messages"]
    # Chat Completions wire: arguments are JSON strings (OpenAI spec).
    assert messages[2]["tool_calls"][0] == {
        "id": "c0",
        "type": "function",
        "function": {"name": "read", "arguments": '{"path": "x.py"}'},
    }
    # Earlier-turn thinking is stripped; the active tool turn keeps it.
    assert "reasoning_content" not in messages[2]
    assert messages[6]["reasoning_content"] == "need both"
    assert [m.get("tool_call_id") for m in messages if m["role"] == "tool"] == ["c0", "c1", "c2"]
    assert messages[-1]["content"] == [
        {"type": "text", "text": "image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]
    assert not any(m["role"] == "user" and "Images returned" in str(m) for m in messages)
    assert {k: body[k] for k in ("temperature", "top_p", "top_k", "max_tokens")} == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "max_tokens": 8192,
    }
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_golden_ollama_gemma3_folds_system_into_first_user_turn():
    model = Model("gemma3:12b", "ollama")

    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        return httpx.Response(
            200,
            json={"done": True, "message": {"content": '{"content": "done", "tool_calls": []}'}},
        )

    context = Context("You are CodeGem.", [UserMessage("hello")], [])
    seen = await _bodies(model, handler, context=context)
    body = seen[-1][1]
    assert body["messages"] == [{"role": "user", "content": "You are CodeGem.\n\nhello"}]
    assert body["options"]["temperature"] == 1.0
    assert body["options"]["top_p"] == 0.95 and body["options"]["top_k"] == 64
    assert "think" not in body


@pytest.mark.asyncio
async def test_user_sampling_replaces_all_gemma_defaults():
    model = Model("gemma3:12b", "ollama")
    context = Context("sys", [UserMessage("hello")], [])
    seen = await _bodies(model, _ollama(["completion"]), {"temperature": 0.3}, context=context)
    options = seen[-1][1]["options"]
    assert options["temperature"] == 0.3
    assert "top_p" not in options and "top_k" not in options


@pytest.mark.asyncio
async def test_explicit_thinking_is_sent_the_same_way_on_each_route():
    ollama = await _bodies(
        Model("gemma4:e4b", "ollama"),
        _ollama(["completion", "tools", "thinking", "vision"]),
        {"thinking": True},
    )
    compatible = await _bodies(Model("gemma-4-e4b", "llamacpp"), _compatible, {"thinking": True})
    assert ollama[-1][1]["think"] is True
    assert compatible[-1][1]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.asyncio
async def test_ollama_omits_think_for_models_without_thinking():
    seen = await _bodies(Model("gemma4:e4b", "ollama"), _ollama(["completion", "tools", "vision"]))
    assert "think" not in seen[-1][1]


def test_missing_and_orphaned_tool_results_are_safe():
    model = Model("gemma4:e4b", "ollama")
    context = Context(
        "",
        [
            UserMessage("go"),
            AssistantMessage(
                model=model.id,
                provider=model.provider,
                stop_reason="toolUse",
                content=[
                    ToolCall("a", "read", {"path": "1"}),
                    ToolCall("b", "read", {"path": "2"}),
                ],
            ),
            ToolResultMessage("zzz", "read", "orphan"),
            ToolResultMessage("b", "read", "two"),
            UserMessage("next"),
        ],
        _tools(),
    )
    wire = ollama_messages(context, native=True, system_role=True)
    tools = [m for m in wire if m["role"] == "tool"]
    # The orphan becomes user text, b keeps its ID, and a gets a synthetic error.
    assert [m["tool_call_id"] for m in tools] == ["a", "b"]
    assert "interrupted" in tools[0]["content"]
    assert any(m["role"] == "user" and "orphan" in m["content"] for m in wire)


def test_tool_images_fall_back_to_a_user_turn_when_disabled():
    model = Model("gemma4:e4b", "vllm")
    wire = ollama_messages(
        _conversation(model), native=True, system_role=True, route="openai", tool_images=False
    )
    assert isinstance(wire[-2]["content"], str) or wire[-2]["role"] == "tool"
    assert wire[-1]["role"] == "user"
    assert wire[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


# Rendering through the official Gemma 4 template ---------------------------------


def test_template_rejects_string_arguments_so_servers_convert_them():
    model = Model("gemma-4-e2b-it", "vllm")
    wire = ollama_messages(_conversation(model), native=True, system_role=True, route="openai")
    with pytest.raises(jinja2.exceptions.TemplateError):
        _render(wire, _tool_schemas())
    rendered = _render(template_messages(wire), _tool_schemas())
    assert "<|tool_call>call:read{" in rendered
    assert 'path:<|"|>a.py<|"|>' in rendered


def test_ollama_route_messages_render_with_object_arguments():
    model = Model("gemma4:e4b", "ollama")
    wire = ollama_messages(_conversation(model), native=True, system_role=True)
    rendered = _render(wire, _tool_schemas())
    assert rendered.startswith("<bos><|turn>system\nYou are CodeGem.")
    assert rendered.count("<|tool_call>call:read{") == 3


def test_render_pairs_results_by_id_and_keeps_tool_images_inside_the_response():
    model = Model("gemma-4-e2b-it", "vllm")
    wire = ollama_messages(_conversation(model), native=True, system_role=True, route="openai")
    rendered = _render(template_messages(wire), _tool_schemas())
    first = rendered.index('<|tool_response>response:read{value:<|"|>x=1')
    second = rendered.index('<|tool_response>response:read{value:<|"|>image', first + 1)
    image = rendered.index("<|image|>")
    # The template emits a tool's image right after that tool's response,
    # inside the same model turn, with no synthetic user turn.
    assert first < second < image
    assert "<|turn>user" not in rendered[second:]
    assert "Images returned by the preceding tools" not in rendered


def test_render_strips_earlier_thinking_and_keeps_active_tool_thinking():
    model = Model("gemma-4-e2b-it", "vllm")
    wire = ollama_messages(_conversation(model), native=True, system_role=True, route="openai")
    rendered = _render(template_messages(wire), _tool_schemas(), enable_thinking=True)
    assert "old thought" not in rendered
    assert "<|channel>thought\nneed both" in rendered
    assert "<|think|>" in rendered


def test_render_thinking_off_by_default():
    rendered = _render([{"role": "user", "content": "hi"}])
    assert "<|think|>" not in rendered


def test_gemma3_messages_have_no_system_role():
    model = Model("gemma3:12b", "ollama")
    context = Context("Be brief.", [UserMessage("hi")], [])
    assert ollama_messages(context, native=False, system_role=False) == [
        {"role": "user", "content": "Be brief.\n\nhi"}
    ]


# vLLM provider and real context size ---------------------------------------------


def test_vllm_is_a_local_gemma_provider():
    profile = resolve_profile("google/gemma-4-31B-it", "vllm")
    assert profile.family == "gemma" and profile.generation == 4 and profile.native_tools


@pytest.mark.asyncio
async def test_vllm_context_from_models_endpoint():
    def handler(request):
        assert str(request.url) == "http://localhost:8000/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "google/gemma-4-31B-it", "max_model_len": 65536}]},
        )

    value = await discover_server_context(
        "vllm", {}, "google/gemma-4-31B-it", transport=httpx.MockTransport(handler)
    )
    assert value == 65536


@pytest.mark.asyncio
async def test_llamacpp_context_from_props():
    def handler(request):
        assert str(request.url) == "http://localhost:8080/props"
        return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 16384}})

    value = await discover_server_context(
        "llamacpp", {}, "gemma", transport=httpx.MockTransport(handler)
    )
    assert value == 16384


@pytest.mark.asyncio
async def test_context_discovery_tolerates_missing_servers():
    def handler(request):
        raise httpx.ConnectError("down")

    assert (
        await discover_server_context("vllm", {}, "m", transport=httpx.MockTransport(handler))
        is None
    )
    assert await discover_server_context("ollama", {}, "m") is None


# Gemma 4 on the Gemini API ----------------------------------------------------------


@pytest.mark.parametrize("model_id", ["gemma-4-31b-it", "gemma-4-26b-a4b-it"])
def test_gemma_api_profile_documents_minimal_and_high(model_id):
    profile = resolve_profile(model_id, "google")
    assert profile.family == "gemma" and profile.thinking_levels == ("minimal", "high")
    assert profile.thinking_level is None


def _gemini_ok(request):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "hi"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        },
    )


@pytest.mark.asyncio
async def test_golden_gemma_api_body():
    model = Model("gemma-4-31b-it", "google")
    context = Context("sys", [UserMessage("hi")], [])
    seen = await _bodies(model, _gemini_ok, {"thinking": True}, context=context)
    path, body = seen[-1]
    assert path == "/v1beta/models/gemma-4-31b-it:streamGenerateContent"
    assert body == {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "systemInstruction": {"parts": [{"text": "sys"}]},
        "generationConfig": {
            "temperature": 1.0,
            "topP": 0.95,
            "topK": 64,
            "thinkingConfig": {"thinkingLevel": "HIGH"},
        },
    }


@pytest.mark.asyncio
async def test_gemma_api_sends_no_thinking_or_output_cap_by_default():
    model = Model("gemma-4-26b-a4b-it", "google")
    context = Context("sys", [UserMessage("hi")], [])
    seen = await _bodies(model, _gemini_ok, {"stream": False}, context=context)
    path, body = seen[-1]
    assert path.endswith(":generateContent")
    assert "thinkingConfig" not in body["generationConfig"]
    assert "maxOutputTokens" not in body["generationConfig"]


@pytest.mark.asyncio
async def test_gemma_api_thinking_off_is_minimal():
    model = Model("gemma-4-31b-it", "google")
    context = Context("sys", [UserMessage("hi")], [])
    seen = await _bodies(model, _gemini_ok, {"thinking": False}, context=context)
    assert seen[-1][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}


def test_gemma_api_rejects_local_tags():
    with pytest.raises(ValueError):
        resolve_profile("gemma4:12b", "google")
