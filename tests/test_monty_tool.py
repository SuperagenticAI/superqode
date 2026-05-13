import ast
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.tools.base import ToolContext, ToolRegistry
from superqode.tools.monty_tool import MontyPythonReplTool, reset_monty_repl


class FakeCollectString:
    def __init__(self):
        self.output = ""


class FakeMountDir:
    def __init__(self, virtual_path, host_path, *, mode="overlay", write_bytes_limit=None):
        self.virtual_path = virtual_path
        self.host_path = Path(host_path)
        self.mode = mode
        self.write_bytes_limit = write_bytes_limit


class FakeMontyRepl:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.namespace = {}
        self.mounts = []

    def feed_run(self, code, *, print_callback=None, mount=None):
        if "open(" in code and mount is None:
            raise PermissionError("filesystem access blocked")
        if mount is not None:
            self.mounts.append(mount)

        tree = ast.parse(code)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
                if prefix.body:
                    exec(compile(prefix, "fake_monty.py", "exec"), self.namespace)
                value = eval(
                    compile(ast.Expression(tree.body[-1].value), "fake_monty.py", "eval"),
                    self.namespace,
                )
            else:
                exec(compile(tree, "fake_monty.py", "exec"), self.namespace)
                value = None
        if print_callback is not None:
            print_callback.output += stdout.getvalue()
        return value


def fake_monty_module():
    return SimpleNamespace(
        __version__="fake",
        CollectString=FakeCollectString,
        MontyRepl=FakeMontyRepl,
        MountDir=FakeMountDir,
    )


@pytest.fixture
def tool_context(tmp_path):
    return ToolContext(session_id="test-monty", working_directory=tmp_path)


def test_full_registry_includes_python_repl_when_monty_available(monkeypatch):
    monkeypatch.setattr("superqode.tools.monty_tool.is_monty_available", lambda: True)

    registry = ToolRegistry.full()

    assert registry.get("python_repl") is not None


@pytest.mark.asyncio
async def test_python_repl_reports_missing_dependency(monkeypatch, tool_context):
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", lambda: None)

    result = await MontyPythonReplTool().execute({"code": "1 + 1"}, tool_context)

    assert not result.success
    assert result.metadata["missing_dependency"] == "pydantic-monty"
    assert "superqode[monty]" in result.error


@pytest.mark.asyncio
async def test_python_repl_executes_and_preserves_session_state(monkeypatch, tool_context):
    reset_monty_repl()
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", fake_monty_module)
    tool = MontyPythonReplTool()

    first = await tool.execute({"code": "x = 40\nx + 2", "reset": True}, tool_context)
    second = await tool.execute({"code": "x + 3"}, tool_context)

    assert first.success
    assert first.output == "42"
    assert second.success
    assert second.output == "43"


@pytest.mark.asyncio
async def test_python_repl_blocks_filesystem_by_default(monkeypatch, tool_context):
    reset_monty_repl()
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", fake_monty_module)

    result = await MontyPythonReplTool().execute(
        {"code": "open('/tmp/example').read()"}, tool_context
    )

    assert not result.success
    assert "filesystem access blocked" in result.error


@pytest.mark.asyncio
async def test_python_repl_can_mount_workspace(monkeypatch, tool_context):
    reset_monty_repl()
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", fake_monty_module)

    result = await MontyPythonReplTool().execute(
        {
            "code": "'mounted'",
            "allow_filesystem": True,
            "mount_mode": "read-only",
            "reset": True,
        },
        tool_context,
    )

    assert result.success
    assert result.output == "'mounted'"
    assert result.metadata["filesystem"] == "mounted"
    assert result.metadata["mount_mode"] == "read-only"
