"""Real native-bridge process contract, using a fake helper without Apple hardware."""

import asyncio
import json
import os

import pytest

from superqode.local import apple
from superqode.providers.gateway.base import Message, ToolDefinition


pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Apple native helper contract uses a POSIX fixture executable"
)


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    helper = tmp_path / "SuperQodeAppleModel"
    record = tmp_path / "input.json"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        + f"""
import json,os,sys,time
if '--status' in sys.argv:
 print(json.dumps({{'available':True,'state':'ready','guidance':'Ready','model':'system-on-device','context':4096}}));sys.exit(0)
request=json.loads(sys.stdin.readline())
record={{'request':request,'pid':os.getpid(),'leaked':any(k in os.environ for k in ['GITHUB_TOKEN','OPENAI_API_KEY','LOCAL_RUNTIME_API_KEY'])}}
open({str(record)!r},'w').write(json.dumps(record))
print(json.dumps({{'event':'text','text':'Hello '}}),flush=True)
if any(m.get('content')=='wait' for m in request['messages']): time.sleep(30)
if any(m.get('content')=='incomplete' for m in request['messages']):sys.exit(0)
print(json.dumps({{'event':'text','text':'Apple'}}),flush=True)
print(json.dumps({{'event':'done','finish_reason':'stop'}}),flush=True)
"""
    )
    helper.chmod(0o755)
    monkeypatch.setenv("SUPERQODE_APPLE_HELPER", str(helper))
    monkeypatch.setenv("GITHUB_TOKEN", "private-github-key")
    monkeypatch.setenv("OPENAI_API_KEY", "private-cloud-key")
    monkeypatch.setenv("LOCAL_RUNTIME_API_KEY", "private-local-key")
    return record


@pytest.mark.asyncio
async def test_apple_bridge_streams_and_does_not_inherit_tokens(bridge):
    chunks = [chunk async for chunk in apple.stream([Message("user", "Hello")], max_tokens=32)]
    assert "".join(c.content for c in chunks) == "Hello Apple"
    assert chunks[-1].finish_reason == "stop"
    assert all(c.usage is None for c in chunks), "Unknown Apple token usage must stay unknown"
    record = json.loads(bridge.read_text())
    assert record["leaked"] is False
    assert record["request"]["max_tokens"] == 32


@pytest.mark.asyncio
async def test_cancel_apple_stream_terminates_the_helper(bridge):
    chunks = apple.stream([Message("user", "wait")])
    try:
        first = await asyncio.wait_for(anext(chunks), 3)
        assert first.content == "Hello "
        pid = json.loads(bridge.read_text())["pid"]
        await chunks.aclose()
        if os.name == "posix":
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        await chunks.aclose()


@pytest.mark.asyncio
async def test_incomplete_apple_output_is_not_completed_or_replayed(bridge):
    chunks = apple.stream([Message("user", "incomplete")])
    assert (await anext(chunks)).content == "Hello "
    with pytest.raises(ValueError, match="without completion"):
        await anext(chunks)


@pytest.mark.asyncio
async def test_apple_rejects_unsupported_schemas_and_images_before_starting_a_process(bridge):
    with pytest.raises(ValueError, match="schema"):
        _ = [
            c
            async for c in apple.stream(
                [Message("user", "Hello")], tools=[ToolDefinition("write", "write", {})]
            )
        ]
    with pytest.raises(ValueError, match="text conversations"):
        _ = [
            c
            async for c in apple.stream(
                [Message("user", [{"type": "image_url", "image_url": {"url": "x"}}])]
            )
        ]
    assert not bridge.exists()


def test_status_reports_unsupported_platform_without_loading_a_model(bridge, monkeypatch):
    monkeypatch.setattr(apple.platform, "system", lambda: "Linux")
    assert apple.status()["available"] is False
    assert not bridge.exists()
    monkeypatch.setattr(apple.platform, "system", lambda: "Darwin")
    assert apple.status()["available"] is True
    assert not bridge.exists(), "Availability checks must not make generation requests"


@pytest.mark.asyncio
async def test_explicit_native_utility_route_never_falls_back_to_the_cloud(monkeypatch):
    from superqode.agent.utility_model import utility_completion

    calls = []

    class Gateway:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("Apple unavailable")

    monkeypatch.setenv("SUPERQODE_UTILITY_PROVIDER", "apple-foundation/system-on-device")
    with pytest.raises(RuntimeError, match="Apple unavailable"):
        await utility_completion(
            Gateway(), "openai", "cloud-model", "instructions", "private utility input"
        )
    assert len(calls) == 1
    assert calls[0]["provider"] == "apple-foundation"


def test_native_setup_blocks_coding_and_utility_enable_on_unavailable_device(desktop, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr(
        apple, "status", lambda: {"available": False, "guidance": "Enable Apple Intelligence"}
    )
    with pytest.raises(ValueError, match="Enable Apple"):
        service.dispatch("local.apple.utility", {"enabled": True})
    with pytest.raises(ValueError, match="Enable Apple"):
        service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "provider": "apple-foundation",
                "model": apple.MODEL,
                "harness": "core",
                "prompt": "Edit code",
            },
        )


from test_desktop_service import desktop  # noqa: E402,F401
