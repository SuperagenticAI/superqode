"""Tests for view_image and multimodal message handling in the loop."""

import pytest

from superqode.agent.loop import (
    AgentLoop,
    AgentMessage,
    _content_for_counting,
    _message_to_tuple,
)
from superqode.tools.base import ToolContext, ToolResult
from superqode.tools.image_tools import MAX_IMAGE_BYTES, ViewImageTool


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path)


def _write_png(tmp_path, name="shot.png", extra=100):
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * extra)
    return path


@pytest.mark.asyncio
async def test_view_image_returns_data_url(tmp_path):
    _write_png(tmp_path)
    result = await ViewImageTool().execute({"path": "shot.png"}, _ctx(tmp_path))
    assert result.success, result.error
    assert result.metadata["image_mime"] == "image/png"
    assert result.metadata["image_data_url"].startswith("data:image/png;base64,")
    assert "shot.png" in result.output


@pytest.mark.asyncio
async def test_view_image_rejects_unsupported_and_missing(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF")
    bad = await ViewImageTool().execute({"path": "doc.pdf"}, _ctx(tmp_path))
    assert bad.success is False
    assert "Unsupported" in (bad.error or "")

    missing = await ViewImageTool().execute({"path": "nope.png"}, _ctx(tmp_path))
    assert missing.success is False


@pytest.mark.asyncio
async def test_view_image_rejects_oversized(tmp_path):
    path = tmp_path / "big.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_IMAGE_BYTES + 1))
    result = await ViewImageTool().execute({"path": "big.png"}, _ctx(tmp_path))
    assert result.success is False
    assert "limit" in (result.error or "")


def test_image_followup_message_built_from_metadata():
    result = ToolResult(
        success=True,
        output="attached",
        metadata={"image_data_url": "data:image/png;base64,AAAA", "image_path": "shot.png"},
    )
    msg = AgentLoop._image_followup_message(result)
    assert msg is not None
    assert msg.role == "user"
    assert isinstance(msg.content, list)
    assert msg.content[1]["image_url"]["url"].startswith("data:image/png")

    # No image metadata, or failed tool => no follow-up.
    assert AgentLoop._image_followup_message(ToolResult(success=True, output="x")) is None
    failed = ToolResult(success=False, output="", metadata={"image_data_url": "d"})
    assert AgentLoop._image_followup_message(failed) is None


def test_content_for_counting_charges_flat_per_image():
    content = [
        {"type": "text", "text": "[Attached image: shot.png]"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 5_000_000}},
    ]
    counted = _content_for_counting(content)
    # Flat ~4000-char charge instead of megabytes of base64.
    assert len(counted) < 10_000
    assert "[Attached image: shot.png]" in counted
    assert _content_for_counting("plain") == "plain"


def test_message_to_tuple_hashable_with_list_content():
    msg = AgentMessage(
        role="user",
        content=[{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": "d"}}],
    )
    key = _message_to_tuple(msg)
    hash(key)  # must not raise


def test_strip_image_parts_for_summarization():
    msg = AgentMessage(
        role="user",
        content=[
            {"type": "text", "text": "[Attached image: shot.png]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    )
    stripped = AgentLoop._strip_image_parts(msg)
    assert isinstance(stripped.content, str)
    assert "shot.png" in stripped.content
    assert "image attachment omitted" in stripped.content
    assert "base64" not in stripped.content

    plain = AgentMessage(role="user", content="hello")
    assert AgentLoop._strip_image_parts(plain) is plain


def test_view_image_is_read_only():
    assert ViewImageTool.read_only is True
