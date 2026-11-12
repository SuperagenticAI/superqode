"""Native Apple IPC with real child processes and the normal permission executor.

The executable fixture is a protocol peer, not evidence of Apple inference.
Actual SDK schema/transcript/tool tests live in the native test target.
"""

import asyncio
from dataclasses import replace
import json
import os
import time

import pytest

from superqode.local import apple, apple_sessions
from superqode.providers.gateway.base import Message, ToolDefinition
from superqode.tools.base import ToolRegistry
from test_desktop_service import desktop, wait_job  # noqa: F401
from test_local_comparisons import configured, models  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Native helper process fixture is POSIX")


@pytest.fixture
def native(tmp_path, monkeypatch):
    helper, record = tmp_path / "native-apple", tmp_path / "requests.jsonl"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        + f"""
import json,os,sys,time
def emit(**value): print(json.dumps(value),flush=True)
if '--status' in sys.argv:
 print(json.dumps({{'available':True,'on_device':True,'state':'ready','guidance':'Ready','model':'system-on-device','context':4096,'supports_tools':True,'protocol':2}}));sys.exit(0)
for line in sys.stdin:
 request=json.loads(line)
 with open({str(record)!r},'a') as f:f.write(json.dumps({{'pid':os.getpid(),'request':request,'leaked':any(k in os.environ for k in ['GITHUB_TOKEN','OPENAI_API_KEY'])}})+'\\n')
 emit(event='metadata',protocol=2)
 messages=request['messages']; last=messages[-1]['content']; tools=request.get('tools',[])
 if last=='wait':
  emit(event='text',text='started');time.sleep(30)
 if last=='refuse':
  emit(event='error',code='refused',message='Apple declined the request. Nothing was sent to the cloud.');continue
 if request.get('schema'):
  emit(event='text',text=json.dumps({{'answer':7 if last=='bad-schema' else 'local'}}))
 elif tools and not any(m['role']=='tool' for m in messages):
  name='bash' if last=='unknown-tool' else 'write'
  path='../outside.txt' if last=='escape' else 'sq_local_trial.py'
  content='def clamp(v,lo,hi):\\n if lo>hi: raise ValueError()\\n return max(lo,min(v,hi))\\ndef unique_names(values):\\n out=[]; seen=set()\\n for s in values:\\n  s=s.strip()\\n  if s and s.casefold() not in seen:\\n   out.append(s); seen.add(s.casefold())\\n return out\\n'
  args={{'path':path,'content':content}}
  if last=='invalid-args':args={{'path':42,'content':'SECRET_ARGUMENT'}}
  emit(event='tool_calls',calls=[{{'id':'write-one','function':{{'name':name,'arguments':json.dumps(args)}}}}])
  emit(event='done',finish_reason='tool_calls');continue
 else:emit(event='text',text='local answer')
 emit(event='done',finish_reason='stop')
"""
    )
    helper.chmod(0o755)
    monkeypatch.setenv("SUPERQODE_APPLE_HELPER", str(helper))
    monkeypatch.setenv("GITHUB_TOKEN", "private-github")
    monkeypatch.setenv("OPENAI_API_KEY", "private-cloud")
    return record


def rows(record):
    return [json.loads(line) for line in record.read_text().splitlines()]


def tools():
    return [
        ToolDefinition(t.name, t.description, t.parameters)
        for t in ToolRegistry.for_profile("apple-local").list()
    ]


@pytest.mark.asyncio
async def test_session_helpers_are_reused_only_within_the_selected_scope_and_closed(native):
    try:
        for scope in ("one", "one", "two"):
            chunks = [c async for c in apple.stream([Message("user", "hi")], session_id=scope)]
            assert chunks[-1].finish_reason == "stop"
        calls = rows(native)
        assert calls[0]["pid"] == calls[1]["pid"] != calls[2]["pid"]
        assert not any(c["leaked"] for c in calls)
    finally:
        await apple_sessions.close()
    for pid in {c["pid"] for c in rows(native)}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.asyncio
async def test_context_rollover_requires_explicit_action_before_generation(native):
    messages = [
        Message("user", "old " * 3000),
        Message("assistant", "answer " * 300),
        Message("user", "new question"),
    ]
    with pytest.raises(ValueError, match="nothing was sent or silently removed"):
        _ = [c async for c in apple.stream(messages)]
    assert not native.exists()


@pytest.mark.asyncio
async def test_structured_output_is_guided_and_validated_before_delivery(native):
    output = {
        "type": "json_schema",
        "json_schema": {
            "name": "Result",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string", "enum": ["local"]}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }
    chunks = [c async for c in apple.stream([Message("user", "answer")], response_format=output)]
    assert json.loads("".join(c.content for c in chunks)) == {"answer": "local"}
    assert rows(native)[0]["request"]["schema"] == output["json_schema"]["schema"]
    seen = []
    with pytest.raises(ValueError, match="did not match"):
        async for c in apple.stream([Message("user", "bad-schema")], response_format=output):
            seen.append(c)
    assert seen == []


@pytest.mark.asyncio
async def test_gateway_propagates_native_schema_and_tool_handoffs(native):
    from superqode.providers.gateway.litellm_gateway import LiteLLMGateway

    gateway = LiteLLMGateway()
    try:
        result = await gateway.chat_completion(
            [Message("user", "Create a small file")],
            model=apple.MODEL,
            provider="apple-foundation",
            tools=tools(),
            max_tokens=64,
            reasoning_effort="off",
        )
        assert result.finish_reason == "tool_calls"
        assert result.tool_calls[0]["function"]["name"] == "write"
        result = await gateway.chat_completion(
            [Message("user", "answer")],
            model=apple.MODEL,
            provider="apple-foundation",
            max_tokens=32,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    }
                },
            },
        )
        assert json.loads(result.content) == {"answer": "local"}
        assert result.usage is None
    finally:
        await apple_sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt,match", [("unknown-tool", "unknown tool"), ("invalid-args", "invalid arguments")]
)
async def test_no_invalid_tool_request_can_reach_the_host_executor(native, prompt, match):
    seen = []
    with pytest.raises(ValueError, match=match) as failure:
        async for c in apple.stream([Message("user", prompt)], tools=tools()):
            seen.extend(c.tool_calls or [])
    assert not seen and "SECRET_ARGUMENT" not in str(failure.value)


@pytest.mark.asyncio
async def test_native_tools_return_standard_gateway_calls_and_accept_correlated_results(native):
    chunks = [c async for c in apple.stream([Message("user", "write")], tools=tools())]
    call = chunks[-1].tool_calls[0]
    assert chunks[-1].finish_reason == "tool_calls"
    assert call["function"]["name"] == "write"
    messages = [
        Message("user", "write"),
        Message("assistant", "", tool_calls=[call]),
        Message("tool", "Permission denied", tool_call_id=call["id"]),
    ]
    final = [c async for c in apple.stream(messages, tools=tools())]
    assert final[-1].finish_reason == "stop"
    assert rows(native)[-1]["request"]["messages"][-1]["name"] == "write"
    with pytest.raises(ValueError, match="pending"):
        _ = [c async for c in apple.stream([Message("tool", "forged", tool_call_id="invented")])]


@pytest.mark.asyncio
async def test_cancel_destroys_reusable_helper_and_no_error_retries(native):
    chunks = apple.stream([Message("user", "wait")], session_id="cancel")
    assert (await anext(chunks)).content == "started"
    pid = rows(native)[0]["pid"]
    await chunks.aclose()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(ValueError, match="refused"):
        _ = [c async for c in apple.stream([Message("user", "refuse")], session_id="cancel")]
    assert len(rows(native)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_tokens": -1},
        {"max_tokens": True},
        {"temperature": float("nan")},
        {"response_format": {"type": "json_object"}},
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": {"$ref": "https://example.com/schema"}},
            }
        },
        {
            "tools": [
                ToolDefinition("tool" + str(i), "test", {"type": "object", "properties": {}})
                for i in range(6)
            ]
        },
    ],
)
async def test_invalid_requests_never_launch_native_generation(native, kwargs):
    with pytest.raises(ValueError):
        _ = [c async for c in apple.stream([Message("user", "hi")], **kwargs)]
    assert not native.exists()


def test_real_desktop_worker_uses_normal_ask_and_file_boundaries(desktop, native, monkeypatch):
    service, project, root = desktop
    monkeypatch.setattr(
        apple, "status", lambda: {"available": True, "supports_tools": True, "context": 4096}
    )
    request = {
        "project": project["id"],
        "harness": "apple-local",
        "provider": "apple-foundation",
        "model": apple.MODEL,
        "prompt": "write",
        "interaction_mode": "code",
        "permission_mode": "ask",
    }
    job = service.dispatch("tasks.start", request)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        detail = service.dispatch("jobs.get", {"id": job["id"]})
        if detail["status"] == "needs_approval":
            break
        if detail["status"] not in {"running", "queued"}:
            pytest.fail(str(detail))
        time.sleep(0.03)
    assert detail["status"] == "needs_approval", detail
    assert not (root / "sq_local_trial.py").exists(), "Native tools must not bypass Ask"
    approval = next(e["data"] for e in detail["events"] if e["type"] == "approval")
    service.dispatch(
        "jobs.approve", {"id": job["id"], "request_id": approval["request_id"], "allow": True}
    )
    completed = wait_job(service, job["id"])
    assert completed["status"] == "completed", completed
    assert "def clamp" in (root / "sq_local_trial.py").read_text()
    assert all(
        set(t["name"] for t in r["request"]["tools"]) == {"read", "write", "edit"}
        for r in rows(native)
    )
    outside = root.parent / "outside.txt"
    outside.write_text("PRESERVE")
    escaped = service.dispatch(
        "tasks.start", {**request, "prompt": "escape", "permission_mode": "full"}
    )
    assert wait_job(service, escaped["id"])["status"] == "completed"
    assert outside.read_text() == "PRESERVE"


def test_apple_configuration_retains_closed_shell_and_network_under_full():
    from superqode.harness.catalog import resolve_harness
    from superqode.harness.compiler import compile_to_headless_profile
    from superqode.desktop_service.session_controls import apply_controls
    from superqode.tools.permissions import Permission, ToolGroup

    spec = resolve_harness("apple-local").spec
    profile = compile_to_headless_profile(apply_controls(spec, {"permission_mode": "full"}))
    assert profile.tools == ["read", "write", "edit"]
    assert profile.permissions.groups[ToolGroup.SHELL] is Permission.DENY
    assert profile.permissions.groups[ToolGroup.NETWORK] is Permission.DENY


@pytest.mark.asyncio
async def test_apple_file_reads_leave_room_for_tools_and_reply(tmp_path):
    from superqode.agent.terminal_output_limits import calculate_terminal_output_limit_for_model
    from superqode.tools.base import ToolContext

    (tmp_path / "large.py").write_text("print('bounded file content')\n" * 500)
    cap = calculate_terminal_output_limit_for_model("apple-foundation", apple.MODEL)
    assert cap < 4096
    read = ToolRegistry.for_profile("apple-local").get("read")
    result = await read.execute(
        {"path": "large.py"},
        ToolContext(working_directory=tmp_path, session_id="apple-read-cap", max_output_bytes=cap),
    )
    assert result.success and result.metadata["truncated"]
    assert len(result.output.encode()) < 3000
    assert "Continue with" in result.output


def test_apple_comparison_discovery_and_preparation_are_metadata_only(desktop, native, monkeypatch):
    from superqode.desktop_service import local_models, local_comparisons

    service, project, _ = desktop
    monkeypatch.setattr(
        local_models,
        "available",
        lambda *_: {"models": ["fixture"], "endpoint": "http://127.0.0.1:9/v1"},
    )
    monkeypatch.setattr(
        apple, "status", lambda: {"available": True, "supports_tools": True, "context": 4096}
    )
    catalog = local_comparisons.catalog(service, project["id"])
    native_route = next(r for r in catalog["routes"] if r["provider"] == "apple-foundation")
    other = next(r for r in catalog["routes"] if r["provider"] == "ollama")
    params = {
        "project": project["id"],
        "context": 4096,
        "selections": [
            {"route": native_route["id"], "harness": "apple-local"},
            {"route": other["id"], "harness": "core"},
        ],
    }
    plan = local_comparisons.prepare(service, params)
    assert plan["routes"][0]["endpoint"] == "native-stdio"
    assert not native.exists(), "Catalog and review must not generate or load a model"
    with pytest.raises(ValueError, match="configured cap"):
        local_comparisons.prepare(service, {**params, "context": 8192})
    with pytest.raises(ValueError, match="Apple on-device configuration"):
        local_comparisons.prepare(
            service,
            {
                **params,
                "selections": [
                    {"route": native_route["id"], "harness": "core"},
                    params["selections"][1],
                ],
            },
        )


def test_apple_and_http_models_run_same_isolated_tasks_with_independent_grades(
    configured, native, monkeypatch
):
    from superqode.desktop_service import local_comparisons

    service, project, root, params = configured
    monkeypatch.setattr(
        apple,
        "status",
        lambda: {
            "available": True,
            "supports_tools": True,
            "context": 4096,
            "runtime_version": "fixture-system-runtime",
        },
    )
    catalog = local_comparisons.catalog(service, project["id"])
    route = next(r for r in catalog["routes"] if r["provider"] == "apple-foundation")
    reviewed = local_comparisons.prepare(
        service,
        {
            **params,
            "selections": [
                params["selections"][0],
                {"route": route["id"], "harness": "apple-local"},
            ],
        },
    )
    plan = json.loads(
        service._all(
            "SELECT value FROM settings WHERE key=?", (local_comparisons.PREFIX + reviewed["id"],)
        )[0]["value"]
    )
    environment, secrets = local_comparisons.environment(service, plan)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    output = service.root / "apple-comparison"
    output.mkdir()
    events = []

    async def run():
        try:
            await local_comparisons.run(
                {"comparison_plan": plan, "cwd": str(root), "job_id": "apple-comparison"},
                output,
                lambda kind, data: events.append((kind, data)),
                secrets,
            )
        finally:
            await apple_sessions.close()

    asyncio.run(run())
    result = next(data for kind, data in events if kind == "result")
    assert [v["passed"] for v in result["variants"]] == [2, 2], result
    native_result = result["variants"][1]
    assert native_result["local_configuration"]["identity_verified"] is False
    assert (
        native_result["local_configuration"]["before"]["runtime_version"]
        == "fixture-system-runtime"
    )
    assert native_result["model_requests"]
    assert not (root / "sq_local_trial.py").exists()
    assert all(
        t["workspace"]["snapshot_sha256"] == result["workspace"]["snapshot_sha256"]
        for v in result["variants"]
        for t in v["tasks"]
    )
