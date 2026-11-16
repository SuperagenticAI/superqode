from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx
import pytest

from superqode.agent.loop import AgentMessage
from superqode.harness.backends.runtime import _tool_registry_for_spec
from superqode.harness.compiler import compile_to_headless_profile
from superqode.harness.model_policy import resolve_harness_model_policy
from superqode.harness.silicon import project_context, run_checks
from superqode.harness.spec import ChecksSpec, CheckStepSpec
from superqode.harness.templates import silicon_template
from superqode.local import apple, runtimes
from superqode.local.apple_contract import tool_definitions
from superqode.providers.gateway.base import ToolDefinition
from superqode.tools.base import ToolContext, ToolResult
from superqode.tools.permissions import PermissionConfig, PermissionManager
from superqode.tools.silicon import SiliconExecute, SiliconSearch


def test_apple_context_limit_uses_the_reported_capacity(monkeypatch):
    monkeypatch.setenv(
        "SUPERQODE_LOCAL_CONTEXT_CONTRACT",
        '{"provider":"apple-foundation","model":"system-on-device","context":6144}',
    )
    assert apple.context_limit({"context": 8192}) == 6144
    assert apple.context_limit({"context": 4096}) == 4096
    assert apple.context_limit({"context": 0}) == 4096


def test_apple_generation_reuses_status_but_explicit_refresh_checks_again(monkeypatch):
    calls = []
    monkeypatch.setattr(apple, "_capabilities_snapshot", None)
    monkeypatch.setattr(apple.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple, "helper_path", lambda: "/test/AppleModel")
    monkeypatch.setattr(
        apple.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(stdout='{"available": true}'),
    )
    apple.status()
    assert apple.capabilities_for_generation()["available"]
    assert len(calls) == 1
    apple.status()
    assert len(calls) == 2


def test_silicon_default_tools_fit_and_roll_over_completed_tool_results():
    spec = silicon_template()
    registry = _tool_registry_for_spec(
        spec,
        compile_to_headless_profile(spec),
        resolve_harness_model_policy(spec, provider="apple-foundation", model=apple.MODEL),
    )
    tools = [ToolDefinition(t.name, t.description, t.parameters) for t in registry.list()]
    assert {t.name for t in tools} == {"read", "search", "edit", "write"}
    assert len(tool_definitions(tools)) == 4
    call = {"id": "1", "function": {"name": "read", "arguments": '{"path":"app.py"}'}}
    messages = [
        AgentMessage("system", "Keep all trusted instructions."),
        AgentMessage("user", "Fix the parser."),
        AgentMessage("assistant", "", tool_calls=[call]),
        AgentMessage("tool", "result " * 2200, tool_call_id="1"),
    ]
    projection = project_context(messages, tools, 4096)
    assert [m.role for m in projection] == ["system", "user"]
    assert "Fix the parser." in projection[-1].content
    assert "read app.py" in projection[-1].content
    assert "result " * 100 not in projection[-1].content
    short = messages[:2]
    assert project_context(short, tools, 4096) is short
    assert len(messages) == 4


@pytest.mark.asyncio
async def test_mcp_silicon_search_and_execute_resolve_one_allowed_capability(tmp_path):
    capability = SimpleNamespace(
        server_id="docs_local",
        name="lookup",
        description="Look up a page",
        input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    )
    calls = []

    async def execute(server, name, args, *, timeout):
        calls.append((server, name, args, timeout))
        return ToolResult(True, "x" * 8000)

    mcp = SimpleNamespace(silicon_tools=lambda: [capability], execute=execute)
    search, invoke = SiliconSearch(mcp), SiliconExecute(mcp)
    tool_definitions(
        [ToolDefinition(t.name, t.description, t.parameters) for t in (search, invoke)]
    )
    ctx = ToolContext("silicon", tmp_path, permission_manager=PermissionManager())
    discovered = await search.execute({"query": "page", "scope": "mcp"}, ctx)
    assert "docs_local/lookup" in discovered.output
    args = {"capability": "docs_local/lookup", "arguments_json": '{"name":"fixture"}'}
    assert not (await invoke.execute(args, ctx)).success
    assert not calls
    ctx.permission_manager = PermissionManager(
        PermissionConfig(allow_patterns=["mcp_docs_local_lookup"])
    )
    result = await invoke.execute(args, ctx)
    assert result.success and len(result.output) < 2000
    assert calls == [("docs_local", "lookup", {"name": "fixture"}, 25)]


@pytest.mark.asyncio
async def test_configured_check_cannot_fall_back_to_unsandboxed_execution(monkeypatch, tmp_path):
    from superqode.harness import silicon

    def sandbox(argv, cwd, mode, *, allow_network):
        assert argv == ["pytest", "-q"]
        assert not allow_network
        return SimpleNamespace(applied=False)

    monkeypatch.setattr(silicon, "build_sandboxed_argv", sandbox)
    spec = replace(
        silicon_template(),
        checks=ChecksSpec(
            enabled=True, custom_steps=(CheckStepSpec(name="tests", command="pytest -q"),)
        ),
    )
    result = await run_checks(spec, tmp_path)
    assert result == [
        {"name": "tests", "status": "failed", "detail": "Local OS sandbox is unavailable"}
    ]


@pytest.mark.asyncio
async def test_apple_container_check_round_trips_and_fails_closed(monkeypatch, tmp_path):
    import yaml

    from superqode.harness import silicon
    from superqode.harness.loader import harness_spec_to_dict, load_harness_spec
    from superqode.sandbox import apple_container

    pin = "docker.io/library/python@sha256:" + "a" * 64
    spec_file = tmp_path / "harness.yaml"
    raw = harness_spec_to_dict(silicon_template())
    raw["checks"]["enabled"] = True
    raw["checks"]["custom_steps"] = [
        {
            "name": "linux",
            "command": "python3 verify.py",
            "apple_container": {"image": pin, "files": ["verify.py"]},
        }
    ]
    spec_file.write_text(yaml.safe_dump(raw))
    spec = load_harness_spec(spec_file)
    assert harness_spec_to_dict(spec)["checks"]["custom_steps"][0]["apple_container"] == {
        "image": pin,
        "files": ["verify.py"],
    }

    async def missing_image(argv, cwd, timeout, *, image, files):
        assert argv == ["python3", "verify.py"] and cwd == tmp_path
        assert image == pin and files == ("verify.py",)
        raise ValueError("Image missing")

    monkeypatch.setattr(apple_container, "run_check", missing_image)
    monkeypatch.setattr(
        silicon, "build_sandboxed_argv", lambda *a, **kw: pytest.fail("host fallback")
    )
    assert await run_checks(spec, tmp_path) == [
        {
            "name": "linux",
            "status": "failed",
            "detail": "Image missing",
            "backend": "apple-container",
        }
    ]


def test_apple_container_snapshot_rejects_symlinks_and_traversal(tmp_path):
    from superqode.sandbox.apple_container import _copy_file

    root = tmp_path / "repository"
    output = tmp_path / "snapshot"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    (root / "directory").symlink_to(tmp_path, target_is_directory=True)
    (root / "check.py").write_text("print('verified')")
    _copy_file(root, output, "check.py")
    assert (output / "check.py").is_file()
    for path in ("link", "directory/outside.txt", "../outside.txt"):
        with pytest.raises((ValueError, OSError)):
            _copy_file(root, output, path)
    assert [item.name for item in output.iterdir()] == ["check.py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_silicon_verification_sets_terminal_status_in_both_paths(
    monkeypatch, tmp_path, strict
):
    from superqode.harness.backends import runtime
    from superqode.harness.backends.base import HarnessBackendRequest
    from superqode.providers.gateway.base import StreamChunk

    async def failing_check(spec, cwd):
        return [{"name": "Verify", "status": "failed", "detail": "fixture assertion"}]

    async def complete_stream(self, *args, **kwargs):
        yield StreamChunk(content="OK")
        yield StreamChunk(finish_reason="stop")

    monkeypatch.setattr(runtime, "run_checks", failing_check)
    monkeypatch.setattr(runtime.PassthroughGateway, "stream_completion", complete_stream)
    request = HarnessBackendRequest(
        spec=replace(silicon_template(), checks=ChecksSpec(enabled=True, fail_on_error=strict)),
        prompt="Return OK.",
        provider="synthetic",
        model="passthrough",
        working_directory=tmp_path,
    )
    backend = runtime.RuntimeHarnessBackend("builtin")
    result = await backend.run(request)
    assert result.response.stopped_reason == ("error" if strict else "complete")
    events = [event async for event in backend.stream(request)]
    terminal = [event.data for event in events if event.type == "model_result"]
    assert terminal[-1]["stopped_reason"] == result.response.stopped_reason
    assert bool(terminal[-1].get("error")) == strict


@pytest.mark.asyncio
async def test_experimental_code_mode_exposes_only_one_governed_mcp_call(tmp_path, monkeypatch):
    from superqode.tools import monty_tool
    from superqode.tools.silicon import SiliconCodeExecute

    capability = SimpleNamespace(server_id="local", name="lookup")
    calls = []

    async def execute(server, name, args, *, timeout):
        calls.append((server, name, args))
        return ToolResult(True, "fixture data")

    def simulate(_module, _code, *, external_lookup):
        assert set(external_lookup) == {"tool_call"}
        tool_call = external_lookup["tool_call"]
        result = tool_call("local/lookup", {"name": "fixture"})
        assert result["output"] == "fixture data"
        with pytest.raises(ValueError, match="budget exceeded"):
            tool_call("local/lookup", {"name": "second"})
        return result["output"]

    monkeypatch.setattr(monty_tool, "_load_monty", lambda: object())
    monkeypatch.setattr(monty_tool, "run_monty_snippet", simulate)
    runtime = SimpleNamespace(silicon_tools=lambda: [capability], execute=execute)
    tool = SiliconCodeExecute(runtime)
    ctx = ToolContext(
        "silicon",
        tmp_path,
        permission_manager=PermissionManager(PermissionConfig(allow_patterns=["mcp_local_lookup"])),
    )
    result = await tool.execute({"code": "tool_call('local/lookup', {'name': 'fixture'})"}, ctx)
    assert result.success
    assert calls == [("local", "lookup", {"name": "fixture"})]
