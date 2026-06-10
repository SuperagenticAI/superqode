"""Tests for BashTool output spill (full output preserved on truncation)."""

import pytest

from superqode.tools import output_spill
from superqode.tools.base import ToolContext
from superqode.tools.shell_tools import BashTool


@pytest.fixture(autouse=True)
def _isolated_spill_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(output_spill.SPILL_DIR_ENV, str(tmp_path / "spill"))
    monkeypatch.setattr(output_spill, "_cleanup_done", False)
    yield


def _ctx(tmp_path, **kwargs) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path, **kwargs)


@pytest.mark.asyncio
async def test_buffered_small_output_untouched(tmp_path):
    result = await BashTool().execute({"command": "echo hello"}, _ctx(tmp_path))
    assert result.success
    assert "hello" in result.output
    assert "spilled_to" not in result.metadata


@pytest.mark.asyncio
async def test_buffered_oversized_output_spills(tmp_path):
    ctx = _ctx(tmp_path, max_output_bytes=2000)
    result = await BashTool().execute(
        {"command": "seq 1 20000"}, ctx
    )
    assert result.success
    assert "Full output saved to:" in result.output
    spilled = result.metadata.get("spilled_to")
    assert spilled
    full = open(spilled).read()
    assert "1\n" in full and "20000" in full  # both ends preserved on disk
    # Preview keeps head and tail.
    assert "1" in result.output and "20000" in result.output
    assert len(result.output.encode()) < 6000


@pytest.mark.asyncio
async def test_streaming_oversized_output_spills_and_completes(tmp_path):
    chunks = []

    async def on_output(text):
        chunks.append(text)

    ctx = _ctx(tmp_path, max_output_bytes=2000, on_output=on_output)
    result = await BashTool().execute({"command": "seq 1 20000"}, ctx)
    assert result.success  # process drained to EOF, no deadlock/timeout
    assert result.metadata.get("spilled_to")
    full = open(result.metadata["spilled_to"]).read()
    assert "20000" in full
    # Live stream stayed bounded near the cap.
    assert sum(len(c) for c in chunks) <= 2100
