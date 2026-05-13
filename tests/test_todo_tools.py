"""Tests for session todo tools."""

from __future__ import annotations

import json

import pytest

from superqode.tools.base import ToolContext
from superqode.tools.todo_tools import TodoReadTool, TodoWriteTool, _todo_store


@pytest.mark.asyncio
async def test_todo_tools_persist_by_session(tmp_path):
    ctx = ToolContext(session_id="session-1", working_directory=tmp_path)
    write = TodoWriteTool()
    read = TodoReadTool()

    result = await write.execute(
        {
            "todos": [
                {
                    "id": "1",
                    "content": "Wire DS4 tool support",
                    "status": "completed",
                    "priority": "high",
                }
            ]
        },
        ctx,
    )

    assert result.success
    path = tmp_path / ".superqode" / "todos" / "session-1.json"
    assert path.exists()

    _todo_store.clear()
    read_result = await read.execute({}, ctx)

    assert read_result.success
    assert json.loads(read_result.output)[0]["content"] == "Wire DS4 tool support"
    assert read_result.metadata["persisted"] is True
