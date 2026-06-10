"""Tests for ReadFileTool context-economy behavior (caps, numbering, binary)."""

import pytest

from superqode.tools.base import ToolContext
from superqode.tools.file_tools import ReadFileTool


def _ctx(tmp_path, **kwargs) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path, **kwargs)


@pytest.mark.asyncio
async def test_lines_are_numbered(tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n")
    result = await ReadFileTool().execute({"path": "a.py"}, _ctx(tmp_path))
    assert result.success
    assert result.output.splitlines()[:3] == ["1: alpha", "2: beta", "3: gamma"]


@pytest.mark.asyncio
async def test_start_end_line_range(tmp_path):
    (tmp_path / "a.txt").write_text("\n".join(f"L{i}" for i in range(1, 11)))
    result = await ReadFileTool().execute(
        {"path": "a.txt", "start_line": 4, "end_line": 6}, _ctx(tmp_path)
    )
    assert result.success
    assert result.output.splitlines()[:3] == ["4: L4", "5: L5", "6: L6"]


@pytest.mark.asyncio
async def test_offset_limit_aliases(tmp_path):
    (tmp_path / "a.txt").write_text("\n".join(f"L{i}" for i in range(1, 11)))
    result = await ReadFileTool().execute(
        {"file_path": "a.txt", "offset": 5, "limit": 2}, _ctx(tmp_path)
    )
    assert result.success
    lines = [ln for ln in result.output.splitlines() if ln and not ln.startswith("[")]
    assert lines == ["5: L5", "6: L6"]


@pytest.mark.asyncio
async def test_default_line_cap_and_continuation_hint(tmp_path):
    total = ReadFileTool.DEFAULT_MAX_LINES + 100
    (tmp_path / "big.txt").write_text("\n".join("x" for _ in range(total)))
    result = await ReadFileTool().execute({"path": "big.txt"}, _ctx(tmp_path))
    assert result.success
    assert result.metadata["truncated"] is True
    assert result.metadata["end_line"] == ReadFileTool.DEFAULT_MAX_LINES
    assert f"start_line={ReadFileTool.DEFAULT_MAX_LINES + 1}" in result.output
    assert f"{total:,} total lines" in result.output


@pytest.mark.asyncio
async def test_byte_cap_from_context(tmp_path):
    (tmp_path / "big.txt").write_text("\n".join("y" * 80 for _ in range(200)))
    result = await ReadFileTool().execute(
        {"path": "big.txt"}, _ctx(tmp_path, max_output_bytes=1000)
    )
    assert result.success
    assert result.metadata["truncated"] is True
    assert len(result.output.encode()) < 2000  # cap + notice, far below file size


@pytest.mark.asyncio
async def test_long_lines_clamped(tmp_path):
    (tmp_path / "min.js").write_text("z" * 10_000 + "\nshort\n")
    result = await ReadFileTool().execute({"path": "min.js"}, _ctx(tmp_path))
    assert result.success
    first = result.output.splitlines()[0]
    assert len(first) < 2100
    assert "[line truncated]" in first


@pytest.mark.asyncio
async def test_empty_file(tmp_path):
    (tmp_path / "empty.txt").write_text("")
    result = await ReadFileTool().execute({"path": "empty.txt"}, _ctx(tmp_path))
    assert result.success
    assert "empty" in result.output.lower()


@pytest.mark.asyncio
async def test_start_past_eof_errors(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    result = await ReadFileTool().execute({"path": "a.txt", "start_line": 50}, _ctx(tmp_path))
    assert result.success is False
    assert "past the end" in (result.error or "")


@pytest.mark.asyncio
async def test_binary_file_rejected(tmp_path):
    (tmp_path / "blob.dat").write_bytes(b"\x00\x01\x02\x03" * 100)
    result = await ReadFileTool().execute({"path": "blob.dat"}, _ctx(tmp_path))
    assert result.success is False
    assert "binary" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_image_file_rejected_by_extension(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    result = await ReadFileTool().execute({"path": "pic.png"}, _ctx(tmp_path))
    assert result.success is False
    assert "image" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_read_tool_is_read_only():
    assert ReadFileTool.read_only is True
