"""Tests for the Python-native Core extension runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from superqode.agent.hooks import BEFORE_TOOL_CALL, LifecycleContext
from superqode.extensions import (
    Extension,
    ExtensionCompatibility,
    ExtensionContext,
    ExtensionRuntime,
    FunctionTool,
    load_extension_runtime,
)
from superqode.project_trust import set_project_trust
from superqode.tools.base import ToolContext, ToolRegistry


def test_public_extension_decorators_build_real_contributions(tmp_path):
    extension = Extension("demo", name="Demo")

    @extension.tool(description="Echo text", read_only=True)
    def echo(text: str, count: int = 1) -> str:
        return text * count

    @extension.before_tool
    def observe(_ctx, _name, _arguments):
        return None

    @extension.context
    def instructions(context: ExtensionContext) -> str:
        return f"Work in {context.root.name}."

    @extension.command("hello", aliases=("hi",))
    def hello(args: str, context: ExtensionContext) -> str:
        return f"{args}@{context.root.name}"

    runtime = ExtensionRuntime(tmp_path, [extension])
    registry = ToolRegistry.core()
    runtime.apply_tools(registry)

    tool = registry.get("echo")
    assert isinstance(tool, FunctionTool)
    assert tool.parameters == {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer", "default": 1},
        },
        "required": ["text"],
    }
    result = asyncio.run(
        tool.execute(
            {"text": "a", "count": 3},
            ToolContext(session_id="s", working_directory=tmp_path),
        )
    )
    assert result.success is True
    assert result.output == "aaa"
    assert runtime.context_text(ExtensionContext(root=tmp_path)) == (
        f"# Extension: Demo\n\nWork in {tmp_path.name}."
    )
    assert asyncio.run(runtime.invoke_command("hi", "world")) == f"world@{tmp_path.name}"
    assert runtime.build_hooks().list_hooks(BEFORE_TOOL_CALL)


def test_extension_cannot_replace_core_tool_without_explicit_opt_in(tmp_path):
    extension = Extension("collision")

    @extension.tool(name="read")
    def replacement(path: str) -> str:
        return path

    registry = ToolRegistry.core()
    original = registry.get("read")
    runtime = ExtensionRuntime(tmp_path, [extension])
    runtime.apply_tools(registry)

    assert registry.get("read") is original
    assert runtime.errors[0].capability == "tools"
    assert "already exists" in runtime.errors[0].message


def test_extension_permission_rules_execute_in_hook_registry(tmp_path):
    extension = Extension("guard")
    extension.permission(tool="bash", pattern="git push *", action="deny")
    runtime = ExtensionRuntime(tmp_path, [extension])
    hooks = runtime.build_hooks()
    context = LifecycleContext(
        session_id="s",
        provider="test",
        model="model",
        working_directory=tmp_path,
    )

    outcome = asyncio.run(
        hooks.fire_decision(
            "permission_request", context, "bash", {"command": "git push origin main"}
        )
    )

    assert outcome.denied is True
    assert outcome.decided_by == "extension:guard:permissions"


def test_project_manifest_is_trust_gated_then_activates(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    plugin_dir = tmp_path / ".superqode" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "context.md").write_text("Use the project rules.", encoding="utf-8")
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "context_injectors": [{"path": "context.md"}],
            }
        ),
        encoding="utf-8",
    )

    untrusted = load_extension_runtime(tmp_path, include_entry_points=False, include_manifests=True)
    assert untrusted.extensions == []
    assert untrusted.skipped == ["demo: project is untrusted"]

    set_project_trust(tmp_path, True)
    trusted = load_extension_runtime(tmp_path, include_entry_points=False, include_manifests=True)
    assert [extension.id for extension in trusted.extensions] == ["demo"]
    assert "Use the project rules." in trusted.context_text(ExtensionContext(root=tmp_path))


def test_manifest_tool_hook_command_and_context_are_runtime_capabilities(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    set_project_trust(tmp_path, True)
    plugin_dir = tmp_path / ".superqode" / "plugins" / "manifest-demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin_code.py").write_text(
        """
from superqode.tools.base import Tool, ToolResult

events = []

class GreetingTool(Tool):
    @property
    def name(self): return "greeting"
    @property
    def description(self): return "Return a greeting"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, args, ctx): return ToolResult(success=True, output="hello")

def audit(ctx, name="", arguments=None):
    events.append(name)

def status(args, context):
    return {"args": args, "root": context.root.name}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "context.md").write_text("Manifest context", encoding="utf-8")
    (plugin_dir / "review.md").write_text(
        "---\nname: review\ndescription: Review a change\n---\nCheck tests and correctness.\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "manifest-demo",
                "tools": [{"name": "greeting", "path": "plugin_code.py"}],
                "commands": [
                    {
                        "name": "manifest-status",
                        "path": "plugin_code.py",
                        "target": "status",
                    }
                ],
                "skills": ["review.md"],
                "event_hooks": [
                    {
                        "point": "before_tool_call",
                        "handler": "plugin_code:audit",
                    }
                ],
                "context_injectors": [{"path": "context.md"}],
            }
        ),
        encoding="utf-8",
    )

    runtime = load_extension_runtime(tmp_path, include_entry_points=False)
    registry = ToolRegistry.core()
    runtime.apply_tools(registry)

    assert registry.get("greeting") is not None
    skill_tool = registry.get("skill")
    assert skill_tool is not None
    skill_result = asyncio.run(
        skill_tool.execute(
            {"action": "invoke", "name": "review", "context": "diff"},
            ToolContext(session_id="s", working_directory=tmp_path),
        )
    )
    assert skill_result.success is True
    assert "Check tests and correctness." in skill_result.output
    assert "Manifest context" in runtime.context_text(ExtensionContext(root=tmp_path))
    assert asyncio.run(runtime.invoke_command("manifest-status", "ok")) == {
        "args": "ok",
        "root": tmp_path.name,
    }
    assert runtime.build_hooks().list_hooks(BEFORE_TOOL_CALL)


def test_pure_mode_core_activates_trusted_manifest_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    set_project_trust(tmp_path, True)
    plugin_dir = tmp_path / ".superqode" / "plugins" / "core-tool"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "tool.py").write_text(
        """
from superqode.tools.base import Tool, ToolResult

class ExtraTool(Tool):
    @property
    def name(self): return "extra"
    @property
    def description(self): return "An optional extension tool"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, args, ctx): return ToolResult(success=True, output="ok")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "core-tool",
                "tools": [{"name": "extra", "path": "tool.py"}],
            }
        ),
        encoding="utf-8",
    )

    from superqode.pure_mode import PureMode

    pure = PureMode()

    assert pure.session.harness_name == "core"
    assert [tool.name for tool in pure.tools.list()] == ["read", "write", "edit", "bash", "extra"]

    from superqode.plugins import disable_plugin, enable_plugin

    disable_plugin("core-tool", tmp_path)
    pure.reload_extensions()
    assert [tool.name for tool in pure.tools.list()] == ["read", "write", "edit", "bash"]

    enable_plugin("core-tool", tmp_path)
    pure.reload_extensions()
    assert [tool.name for tool in pure.tools.list()] == ["read", "write", "edit", "bash", "extra"]


def test_pure_mode_untrusted_project_keeps_exact_four_tool_core(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    plugin_dir = tmp_path / ".superqode" / "plugins" / "ignored"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"id": "ignored", "context_injectors": []}), encoding="utf-8"
    )

    from superqode.pure_mode import PureMode

    pure = PureMode()

    assert [tool.name for tool in pure.tools.list()] == ["read", "write", "edit", "bash"]
    assert pure._extension_runtime.skipped == ["ignored: project is untrusted"]


def test_headless_core_activates_extension_tools_context_and_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_TRUST_STORE", str(tmp_path / "trust.json"))
    set_project_trust(tmp_path, True)
    plugin_dir = tmp_path / ".superqode" / "plugins" / "headless"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "tool.py").write_text(
        """
from superqode.tools.base import Tool, ToolResult

class HeadlessExtraTool(Tool):
    @property
    def name(self): return "headless_extra"
    @property
    def description(self): return "Headless extension tool"
    @property
    def parameters(self): return {"type": "object", "properties": {}}
    async def execute(self, args, ctx): return ToolResult(success=True, output="ok")

def before(ctx, name="", arguments=None): return None
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "context.md").write_text("Headless extension context.", encoding="utf-8")
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "headless",
                "tools": [{"name": "headless_extra", "path": "tool.py"}],
                "context_injectors": [{"path": "context.md"}],
                "event_hooks": [{"point": "before_tool_call", "handler": "tool:before"}],
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    class Runtime:
        async def run(self, prompt):
            from superqode.agent.loop import AgentResponse

            return AgentResponse(
                content="done",
                messages=[],
                tool_calls_made=0,
                iterations=1,
                stopped_reason="complete",
            )

    def create_runtime(_name, **kwargs):
        captured.update(kwargs)
        return Runtime()

    monkeypatch.setattr("superqode.headless.create_runtime", create_runtime)

    from superqode.headless import run_headless

    response = asyncio.run(run_headless("work", "test", "model", working_directory=tmp_path))

    assert response.content == "done"
    assert captured["tools"].get("headless_extra") is not None
    assert "Headless extension context." in captured["config"].custom_system_prompt
    assert captured["hooks"].list_hooks(BEFORE_TOOL_CALL)


def test_incompatible_extension_is_isolated(monkeypatch, tmp_path):
    incompatible = Extension(
        "future",
        compatibility=ExtensionCompatibility(api_version=999),
    )

    class EntryPoint:
        name = "future"

        @staticmethod
        def load():
            return incompatible

    monkeypatch.setattr("superqode.extensions._extension_entry_points", lambda: [EntryPoint()])
    runtime = load_extension_runtime(tmp_path, include_entry_points=True, include_manifests=False)

    assert runtime.extensions == []
    assert runtime.errors[0].extension_id == "future"
    assert "incompatible" in runtime.errors[0].message


def test_context_sources_are_bounded_and_fail_independently(tmp_path):
    broken = Extension("broken")

    @broken.context
    def fail(_context):
        raise RuntimeError("bad context")

    healthy = Extension("healthy")

    @healthy.context
    def content(_context):
        return "abcdefghij"

    runtime = ExtensionRuntime(tmp_path, [broken, healthy])

    text = runtime.context_text(ExtensionContext(root=tmp_path), max_chars=4)

    assert text == "# Extension: healthy\n\nabcd"
    assert runtime.errors[0].extension_id == "broken"
    assert runtime.errors[0].capability == "context"


@pytest.mark.parametrize(
    ("requirement", "compatible"),
    [(">=0.2.0,<1.0", True), (">99.0", False)],
)
def test_requires_superqode_compatibility(requirement, compatible, monkeypatch, tmp_path):
    extension = Extension(
        "versioned",
        compatibility=ExtensionCompatibility(requires_superqode=requirement),
    )

    class EntryPoint:
        name = "versioned"

        @staticmethod
        def load():
            return extension

    monkeypatch.setattr("superqode.extensions._extension_entry_points", lambda: [EntryPoint()])
    runtime = load_extension_runtime(tmp_path, include_entry_points=True, include_manifests=False)

    assert bool(runtime.extensions) is compatible
    assert bool(runtime.errors) is not compatible
