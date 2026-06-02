"""Tests for register_plugin_hooks - manifest event_hooks → HookRegistry."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from superqode.agent.hooks import (
    AFTER_TURN_COMPLETE,
    BEFORE_LLM_CALL,
    BEFORE_TOOL_CALL,
    HookRegistry,
    LifecycleContext,
)
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.plugins import (
    PluginHookError,
    PluginManifest,
    register_plugin_hooks,
    validate_plugin_manifest,
)
from superqode.providers.gateway import PassthroughGateway, PlaybackGateway
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Per-test handler module written to a temp dir on sys.path so import-string
# resolution works exactly the way a real plugin would do it.
# ---------------------------------------------------------------------------


HANDLER_MODULE_SOURCE = textwrap.dedent(
    """
    calls = []

    def record_before(ctx, *args, **kwargs):
        calls.append(("before", ctx.iteration))

    async def record_after(ctx, *args, **kwargs):
        calls.append(("after", ctx.iteration))

    def boom(*_args, **_kwargs):
        raise RuntimeError("kapow")
    """
)


@pytest.fixture
def plugin_handler_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a fake handler module to a temp dir, put it on sys.path."""
    pkg_dir = tmp_path / "_sq_test_handlers"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(HANDLER_MODULE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    # Make sure each test gets a fresh module (and a fresh `calls` list).
    sys.modules.pop("_sq_test_handlers", None)
    import _sq_test_handlers  # noqa: F401  (triggered for side effect)

    yield "_sq_test_handlers"
    sys.modules.pop("_sq_test_handlers", None)


# ---------------------------------------------------------------------------
# register_plugin_hooks
# ---------------------------------------------------------------------------


def test_register_plugin_hooks_resolves_colon_syntax(plugin_handler_module):
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {
                "point": BEFORE_LLM_CALL,
                "handler": f"{plugin_handler_module}:record_before",
            }
        ],
    )
    result = register_plugin_hooks(registry, [manifest])
    assert result.errors == []
    assert len(result.registered) == 1
    assert result.registered[0].point == BEFORE_LLM_CALL
    assert registry.list_hooks(BEFORE_LLM_CALL) == ["p1:_sq_test_handlers:record_before"]


def test_register_plugin_hooks_resolves_dotted_syntax(plugin_handler_module):
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {
                "point": BEFORE_LLM_CALL,
                "handler": f"{plugin_handler_module}.record_before",
            }
        ],
    )
    result = register_plugin_hooks(registry, [manifest])
    assert result.errors == []
    assert len(result.registered) == 1


def test_register_plugin_hooks_rejects_unknown_point(plugin_handler_module):
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[{"point": "nonsense", "handler": f"{plugin_handler_module}:record_before"}],
    )
    result = register_plugin_hooks(registry, [manifest])
    assert result.registered == []
    assert len(result.errors) == 1
    assert "unknown hook point" in result.errors[0].message


def test_register_plugin_hooks_isolates_import_error(plugin_handler_module):
    """One bad entry shouldn't block the others."""
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {"point": BEFORE_LLM_CALL, "handler": "does.not.exist:fn"},
            {
                "point": BEFORE_LLM_CALL,
                "handler": f"{plugin_handler_module}:record_before",
            },
        ],
    )
    result = register_plugin_hooks(registry, [manifest])
    assert len(result.registered) == 1
    assert len(result.errors) == 1
    assert result.errors[0].handler == "does.not.exist:fn"


def test_register_plugin_hooks_rejects_non_callable(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "_sq_noncallable"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("_sq_noncallable", None)

    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[{"point": BEFORE_LLM_CALL, "handler": "_sq_noncallable:VALUE"}],
    )
    result = register_plugin_hooks(registry, [manifest])
    assert result.registered == []
    assert "non-callable" in result.errors[0].message


def test_register_plugin_hooks_rejects_non_dict_entry():
    registry = HookRegistry()
    manifest = PluginManifest(id="p1", name="p1", event_hooks=["not-a-dict"])  # type: ignore[arg-type]
    result = register_plugin_hooks(registry, [manifest])
    assert result.registered == []
    assert "must be a dict" in result.errors[0].message


def test_register_plugin_hooks_respects_name_override(plugin_handler_module):
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {
                "point": BEFORE_LLM_CALL,
                "handler": f"{plugin_handler_module}:record_before",
                "name": "audit",
            }
        ],
    )
    register_plugin_hooks(registry, [manifest])
    assert registry.list_hooks(BEFORE_LLM_CALL) == ["audit"]


# ---------------------------------------------------------------------------
# End-to-end through AgentLoop
# ---------------------------------------------------------------------------


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args, ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output="ok")


@pytest.mark.asyncio
async def test_plugin_hooks_fire_during_loop(tmp_path, plugin_handler_module):
    """Register a plugin manifest hook, run the loop, verify it ran."""
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {
                "point": BEFORE_TOOL_CALL,
                "handler": f"{plugin_handler_module}:record_before",
            },
            {
                "point": AFTER_TURN_COMPLETE,
                "handler": f"{plugin_handler_module}:record_after",
            },
        ],
    )
    register_plugin_hooks(registry, [manifest])

    gateway = PlaybackGateway()
    gateway.queue_tool_call("echo", {})
    gateway.queue("done")

    tools = ToolRegistry()
    tools.register(_EchoTool())

    loop = AgentLoop(
        gateway=gateway,
        tools=tools,
        config=AgentConfig(provider="synthetic", model="passthrough", working_directory=tmp_path),
        hooks=registry,
    )
    await loop.run("trigger echo")

    handler_mod = sys.modules[plugin_handler_module]
    # Two turns total → after_turn_complete fires twice; one tool call → one before_tool_call.
    assert ("before", 1) in handler_mod.calls
    assert handler_mod.calls.count(("after", 1)) == 1
    assert handler_mod.calls.count(("after", 2)) == 1


@pytest.mark.asyncio
async def test_misbehaving_plugin_hook_does_not_crash_loop(tmp_path, plugin_handler_module):
    registry = HookRegistry()
    manifest = PluginManifest(
        id="p1",
        name="p1",
        event_hooks=[
            {
                "point": BEFORE_LLM_CALL,
                "handler": f"{plugin_handler_module}:boom",
            }
        ],
    )
    register_plugin_hooks(registry, [manifest])

    loop = AgentLoop(
        gateway=PassthroughGateway(),
        tools=ToolRegistry(),
        config=AgentConfig(provider="synthetic", model="passthrough", working_directory=tmp_path),
        hooks=registry,
    )
    response = await loop.run("hello")
    # Hook errors are caught - loop still completes successfully.
    assert response.stopped_reason == "complete"
    assert response.content == "hello"


# ---------------------------------------------------------------------------
# validate_plugin_manifest
# ---------------------------------------------------------------------------


def test_validate_plugin_manifest_reports_event_hook_issues(tmp_path):
    path = tmp_path / "plugin.json"
    path.write_text(
        """
        {
          "id": "bad",
          "name": "bad",
          "event_hooks": [
            {"point": "wrong", "handler": "foo:bar"},
            {"point": "before_llm_call", "handler": ""},
            {"point": "before_llm_call", "handler": "no_module_path"},
            "not-a-dict"
          ]
        }
        """,
        encoding="utf-8",
    )
    issues = validate_plugin_manifest(path)
    assert any("event_hooks[0].point" in msg for msg in issues)
    assert any("event_hooks[1].handler" in msg for msg in issues)
    assert any("event_hooks[2].handler" in msg for msg in issues)
    assert any("event_hooks[3] must be a dict" in msg for msg in issues)


def test_validate_plugin_manifest_accepts_valid_event_hooks(tmp_path):
    path = tmp_path / "plugin.json"
    path.write_text(
        """
        {
          "id": "good",
          "name": "good",
          "event_hooks": [
            {"point": "before_llm_call", "handler": "mypkg.mymod:fn"},
            {"point": "after_turn_complete", "handler": "mypkg.mymod.fn"}
          ]
        }
        """,
        encoding="utf-8",
    )
    issues = validate_plugin_manifest(path)
    assert issues == []


def test_lifecycle_context_carries_session_info(plugin_handler_module, tmp_path):
    """Sanity: the LifecycleContext object the hook receives is well-formed."""
    captured: list[LifecycleContext] = []

    def grab(ctx: LifecycleContext, *_):
        captured.append(ctx)

    registry = HookRegistry()
    registry.register(BEFORE_LLM_CALL, grab)
    # Run a trivial loop via PassthroughGateway.
    import asyncio

    loop = AgentLoop(
        gateway=PassthroughGateway(),
        tools=ToolRegistry(),
        config=AgentConfig(provider="synthetic", model="passthrough", working_directory=tmp_path),
        hooks=registry,
    )
    asyncio.run(loop.run("hi"))
    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.provider == "synthetic"
    assert ctx.model == "passthrough"
    assert ctx.working_directory == tmp_path
    assert ctx.iteration == 1
