"""Isolated transport, policy and catalog contracts for Strands."""

from dataclasses import replace
from pathlib import Path
import asyncio
import os
import sys

import pytest

from superqode.harness.backends import strands
from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.registry import create_harness_backend, backend_capabilities
from superqode.harness.catalog import resolve_harness
from superqode.harness.spec import PermissionRuleSpec, HarnessFlavor
from superqode.harness.templates import strands_template
from superqode.tools.base import ToolRegistry


@pytest.fixture
def request_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(
        strands,
        "_worker_command",
        lambda: [sys.executable, "-u", str(Path(__file__).parent / "fixtures/strands_worker.py")],
    )

    def make(prompt="success", **config):
        spec = strands_template()
        spec = replace(spec, runtime=replace(spec.runtime, config={"session": False, **config}))
        return HarnessBackendRequest(
            spec=spec, prompt=prompt, provider="ollama", model="fixture", working_directory=tmp_path
        )

    return make


def test_discovery_is_optional_and_keeps_venv_symlink(tmp_path, monkeypatch):
    link = tmp_path / "python"
    link.symlink_to(sys.executable)
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", str(link))
    assert strands.strands_python() == link
    assert strands.strands_installation_status()[0]
    assert resolve_harness("strands", root=tmp_path).available
    assert create_harness_backend("strands").name == "strands"
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", str(tmp_path / "missing"))
    assert not resolve_harness("strands", root=tmp_path).available
    assert backend_capabilities("strands").availability == "missing"


@pytest.mark.asyncio
async def test_process_result_stream_usage_and_unknown_cost(request_factory):
    result = await strands.StrandsHarnessBackend().run(request_factory())
    assert result.response.content == "fixture response"
    assert result.response.total_tokens == 14
    assert result.response.cost_usd is None
    assert [e.type for e in result.metadata["events"]] == [
        "model_request",
        "model_delta",
        "model_result",
        "end",
    ]


@pytest.mark.parametrize(
    "prompt", ["partial", "garbage", "duplicate", "bad_exit", "bad_usage", "limited"]
)
@pytest.mark.asyncio
async def test_incomplete_or_invalid_process_never_succeeds(request_factory, prompt):
    with pytest.raises((RuntimeError, ValueError)):
        await strands.StrandsHarnessBackend().run(request_factory(prompt))


@pytest.mark.asyncio
async def test_tool_roundtrip_respects_default_denial_then_explicit_write(
    request_factory, tmp_path
):
    request = request_factory("tool")
    denied = await strands.StrandsHarnessBackend().run(request)
    assert not (tmp_path / "fixture.txt").exists()
    assert "denied" in denied.response.content
    request = replace(
        request,
        spec=replace(
            request.spec, execution_policy=replace(request.spec.execution_policy, allow_write=True)
        ),
    )
    allowed = await strands.StrandsHarnessBackend().run(request)
    assert allowed.response.content == "written"
    assert (tmp_path / "fixture.txt").read_text() == "written"


@pytest.mark.parametrize("action", ["ask", "deny"])
@pytest.mark.asyncio
async def test_rules_block_before_tool_side_effects(request_factory, tmp_path, action):
    request = request_factory("tool")
    policy = replace(
        request.spec.execution_policy,
        allow_write=True,
        permission_rules=(PermissionRuleSpec(tool="write", action=action),),
    )
    result = await strands.StrandsHarnessBackend().run(
        replace(request, spec=replace(request.spec, execution_policy=policy))
    )
    assert not (tmp_path / "fixture.txt").exists()
    assert "approval" in result.response.content


@pytest.mark.asyncio
async def test_readonly_profile_cannot_be_overridden_by_allow_rule(request_factory, tmp_path):
    request = request_factory()
    policy = replace(
        request.spec.execution_policy,
        allow_write=True,
        permission_rules=(PermissionRuleSpec(tool="write", action="allow"),),
    )
    request = replace(
        request, sandbox_backend="read-only", spec=replace(request.spec, execution_policy=policy)
    )
    result = await strands.execute_tool(
        request, ToolRegistry.core(), "write", {"path": "fixture.txt", "content": "bad"}
    )
    assert not result.success
    assert not (tmp_path / "fixture.txt").exists()


@pytest.mark.asyncio
async def test_path_escape_invalid_arguments_and_compound_shell_blocked(request_factory, tmp_path):
    request = request_factory()
    policy = replace(request.spec.execution_policy, allow_shell=True, allowed_commands=("echo",))
    request = replace(request, spec=replace(request.spec, execution_policy=policy))
    for name, args in [
        ("read", {"path": "../secret"}),
        ("read", {"path": 42}),
        ("bash", {"command": "echo ok; touch fixture.txt"}),
        ("bash", {"command": "touch fixture.txt"}),
    ]:
        result = await strands.execute_tool(request, ToolRegistry.core(), name, args)
        assert not result.success
    assert not (tmp_path / "fixture.txt").exists()


@pytest.mark.asyncio
async def test_file_tools_cannot_follow_project_symlinks_outside(request_factory, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_text("private fixture")
    (tmp_path / "escape.txt").symlink_to(outside)
    request = request_factory()
    request = replace(
        request,
        spec=replace(
            request.spec,
            execution_policy=replace(
                request.spec.execution_policy,
                allow_write=True,
            ),
        ),
    )
    try:
        for name, arguments in [
            ("read", {"path": "escape.txt"}),
            ("write", {"path": "escape.txt", "content": "changed"}),
            ("edit", {"path": "escape.txt", "old_text": "private", "new_text": "changed"}),
        ]:
            result = await strands.execute_tool(request, ToolRegistry.core(), name, arguments)
            assert not result.success
            assert "outside the project" in result.error
        assert outside.read_text() == "private fixture"
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_timeout_and_cancel_reap_owned_worker(request_factory, monkeypatch):
    processes = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(TimeoutError):
        await strands.StrandsHarnessBackend().run(request_factory("hang", timeout_seconds=0.05))
    backend = strands.StrandsHarnessBackend()
    ready = asyncio.Event()

    async def run():
        async for event in backend.stream(request_factory("hang")):
            if event.type == "model_request":
                ready.set()

    task = asyncio.create_task(run())
    await asyncio.wait_for(ready.wait(), 3)
    await backend.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(processes) == 2
    assert all(p.returncode is not None for p in processes)


@pytest.mark.parametrize(
    "config",
    [
        {"max_turns": 0},
        {"max_turns": True},
        {"timeout_seconds": float("nan")},
        {"wall_timeout_seconds": float("nan")},
        {"wall_timeout_seconds": True},
        {"wall_timeout_seconds": 0},
        {"mcp_servers": {}},
        {"session": "yes"},
    ],
)
def test_invalid_configuration_rejected_before_launch(request_factory, config):
    with pytest.raises(ValueError):
        strands._settings(request_factory(**config))


def test_model_route_and_iteration_caps_are_explicit(request_factory):
    request = request_factory(max_turns=20)
    assert (
        strands._model(replace(request, provider="google", model="gemini-model"))
        == "google/gemini-model"
    )
    for provider, model in [("codex", "model"), ("openai", "anthropic/model"), ("ollama", "")]:
        with pytest.raises(ValueError):
            strands._model(replace(request, provider=provider, model=model))
    request = replace(request, metadata={"agent_max_iterations": 2, "agent_max_tokens": 100})
    assert strands._settings(request)["max_turns"] == 2
    assert strands._settings(request)["output_tokens"] == 100


def test_no_tool_does_not_inherit_agent_tools(request_factory):
    request = request_factory()
    request = replace(
        request,
        spec=replace(request.spec, flavor=HarnessFlavor.NO_TOOL),
        metadata={"agent_tools": ["bash"]},
    )
    assert strands._tools(request).list() == []


def test_metadata_cannot_widen_declared_tool_set(request_factory):
    request = request_factory()
    agent = replace(request.spec.agents[0], tools=("read",))
    request = replace(
        request, spec=replace(request.spec, agents=(agent,)), metadata={"agent_tools": ["write"]}
    )
    with pytest.raises(ValueError, match="cannot widen"):
        strands._tools(request)


@pytest.mark.asyncio
async def test_cancel_during_host_shell_reaps_command(request_factory, monkeypatch):
    processes = []
    started = asyncio.Event()
    from superqode.tools.shell_tools import BashTool

    original = BashTool._spawn

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(BashTool, "_spawn", staticmethod(spawn))
    request = request_factory()
    request = replace(
        request,
        spec=replace(
            request.spec,
            execution_policy=replace(
                request.spec.execution_policy, allow_shell=True, allowed_commands=("sleep",)
            ),
        ),
    )
    task = asyncio.create_task(
        strands.execute_tool(request, ToolRegistry.core(), "bash", {"command": "sleep 60"})
    )
    await asyncio.wait_for(started.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes and all(p.returncode is not None for p in processes)


@pytest.mark.asyncio
async def test_slow_event_consumer_is_not_cancelled_by_worker_timeout(request_factory):
    backend = strands.StrandsHarnessBackend()
    events = []
    async for event in backend.stream(request_factory(timeout_seconds=0.2)):
        events.append(event.type)
        if event.type == "model_request":
            await asyncio.sleep(0.35)
    assert events[-2:] == ["model_result", "end"]
    assert not asyncio.current_task().cancelling()


@pytest.mark.asyncio
async def test_wall_timeout_reaps_worker_while_consumer_is_suspended(request_factory, monkeypatch):
    processes = []
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    stream = strands.StrandsHarnessBackend().stream(
        request_factory("hang", timeout_seconds=5, wall_timeout_seconds=0.2)
    )
    try:
        assert (await anext(stream)).type == "model_request"
        await asyncio.wait_for(processes[0].wait(), 3)
        assert processes[0].returncode is not None
        assert not asyncio.current_task().cancelling()
        with pytest.raises(TimeoutError, match="wall-clock"):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_wall_timeout_cancels_active_host_operation():
    stopped = asyncio.Event()

    async def operation():
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    with pytest.raises(TimeoutError, match="wall-clock"):
        await strands._ActiveBudget(5, 0.02).wait(operation())
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_missing_runtime_has_packaged_setup_hint(request_factory, monkeypatch):
    monkeypatch.setattr(strands, "_worker_command", lambda: ["/missing/strands/python"])
    with pytest.raises(RuntimeError, match="superqode harness strands setup"):
        await strands.StrandsHarnessBackend().run(request_factory())


def test_readonly_advertises_only_executable_tools(request_factory):
    request = request_factory()
    assert [t.name for t in strands._tools(request).list()] == ["read"]
    request = replace(
        request,
        spec=replace(
            request.spec,
            execution_policy=replace(
                request.spec.execution_policy, allow_write=True, allow_shell=True
            ),
        ),
    )
    assert {t.name for t in strands._tools(request).list()} == {"read", "write", "edit", "bash"}
    assert [
        t.name for t in strands._tools(replace(request, sandbox_backend="read-only")).list()
    ] == ["read"]


@pytest.mark.asyncio
async def test_saved_api_key_reaches_child_without_other_credentials(
    request_factory, tmp_path, monkeypatch
):
    from superqode import auth

    storage = auth.LocalAuthStorage(tmp_path / "auth.json")
    storage.set("openai", auth.ApiAuth(key="saved-openai-fixture"))
    monkeypatch.setattr(auth, "_storage", storage)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-anthropic-fixture")
    monkeypatch.setenv("GITHUB_TOKEN", "unrelated-github-fixture")
    request = replace(request_factory("environment"), provider="openai")
    result = await strands.StrandsHarnessBackend().run(request)
    import json

    assert json.loads(result.response.content) == {
        "selected_key": True,
        "other_key": False,
        "github_token": False,
    }
    assert "saved-openai-fixture" not in str(result.metadata)
    assert "OPENAI_API_KEY" not in os.environ
