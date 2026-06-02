"""Tests for terminal output limit calculation and BashTool integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.agent.terminal_output_limits import (
    DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT,
    MAX_TERMINAL_OUTPUT_BYTE_LIMIT,
    TERMINAL_BYTES_PER_TOKEN,
    TERMINAL_OUTPUT_TOKEN_HEADROOM_RATIO,
    TERMINAL_OUTPUT_TOKEN_RATIO,
    calculate_terminal_output_limit_for_max_tokens,
    calculate_terminal_output_limit_for_model,
)
from superqode.tools.base import ToolContext
from superqode.tools.shell_tools import BashTool


# ---------------------------------------------------------------------------
# Pure calculator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 0, -1, -100])
def test_no_or_invalid_max_tokens_returns_default(value):
    assert (
        calculate_terminal_output_limit_for_max_tokens(value) == DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT
    )


def test_tiny_max_tokens_clamped_to_default_floor():
    # 100 tokens × 0.83 × 0.8 × 3.3 ≈ 219 bytes - below the default floor.
    assert calculate_terminal_output_limit_for_max_tokens(100) == DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT


def test_large_max_tokens_clamped_to_ceiling():
    # An absurd 10M max_output_tokens must still be capped at the ceiling.
    assert (
        calculate_terminal_output_limit_for_max_tokens(10_000_000) == MAX_TERMINAL_OUTPUT_BYTE_LIMIT
    )


def test_mid_range_matches_formula():
    # 32k output tokens -> meaningful but below the ceiling.
    expected = int(
        32_000
        * TERMINAL_OUTPUT_TOKEN_RATIO
        * (1 - TERMINAL_OUTPUT_TOKEN_HEADROOM_RATIO)
        * TERMINAL_BYTES_PER_TOKEN
    )
    expected = min(expected, MAX_TERMINAL_OUTPUT_BYTE_LIMIT)
    expected = max(expected, DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT)
    assert calculate_terminal_output_limit_for_max_tokens(32_000) == expected


def test_per_model_lookup_returns_default_for_unknown():
    assert (
        calculate_terminal_output_limit_for_model("unknown_provider", "unknown_model")
        == DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT
    )


@pytest.mark.parametrize(
    "provider, model",
    [
        (None, "anything"),
        ("anything", None),
        (None, None),
    ],
)
def test_per_model_lookup_handles_missing_args(provider, model):
    assert (
        calculate_terminal_output_limit_for_model(provider, model)
        == DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT
    )


# ---------------------------------------------------------------------------
# BashTool integration
# ---------------------------------------------------------------------------


def _make_ctx(tmp_path: Path, max_output_bytes: int | None = None) -> ToolContext:
    return ToolContext(
        session_id="t",
        working_directory=tmp_path,
        max_output_bytes=max_output_bytes,
    )


def test_bash_effective_cap_uses_class_default_without_ctx_value(tmp_path):
    ctx = _make_ctx(tmp_path, max_output_bytes=None)
    assert BashTool._effective_max_output(ctx, BashTool.MAX_OUTPUT) == BashTool.MAX_OUTPUT


def test_bash_effective_cap_honors_ctx_value(tmp_path):
    ctx = _make_ctx(tmp_path, max_output_bytes=12_345)
    assert BashTool._effective_max_output(ctx, BashTool.MAX_OUTPUT) == 12_345


@pytest.mark.asyncio
async def test_bash_truncates_to_ctx_cap(tmp_path):
    """End-to-end: a small ctx cap should truncate real bash output."""
    tool = BashTool(git_guard_enabled=False)
    ctx = _make_ctx(tmp_path, max_output_bytes=512)
    # Generate ~3 KB of output - well over our 512 B cap.
    result = await tool.execute(
        {"command": "python3 -c 'print(\"x\" * 3000)'", "timeout": 10},
        ctx,
    )
    assert result.success
    # Truncation notice should appear; total length stays within cap + notice.
    assert "Output truncated at 512 bytes" in result.output
    # The actual content cap is enforced; only the truncation suffix is added on top.
    truncation_marker = "\n\n[Output truncated at 512 bytes]"
    content_before_marker = result.output.split(truncation_marker)[0]
    assert len(content_before_marker) <= 512


@pytest.mark.asyncio
async def test_bash_does_not_truncate_below_cap(tmp_path):
    tool = BashTool(git_guard_enabled=False)
    ctx = _make_ctx(tmp_path, max_output_bytes=10_000)
    result = await tool.execute(
        {"command": "echo hello", "timeout": 10},
        ctx,
    )
    assert result.success
    assert "truncated" not in result.output
    assert "hello" in result.output


def test_agent_loop_populates_max_output_bytes(tmp_path):
    """AgentLoop should size ctx.max_output_bytes from the configured model."""
    # Import inside the test so we don't pay AgentLoop import cost in calculator tests.
    from superqode.agent.loop import AgentConfig, AgentLoop
    from superqode.providers.gateway import PassthroughGateway
    from superqode.tools.base import ToolRegistry

    cfg = AgentConfig(
        provider="anthropic",
        model="claude-sonnet-4-6",  # known to providers/models.py
        working_directory=tmp_path,
    )
    loop = AgentLoop(gateway=PassthroughGateway(), tools=ToolRegistry(), config=cfg)
    ctx = loop._create_tool_context()
    # Known model -> known max_output -> cap > default floor.
    assert ctx.max_output_bytes is not None
    assert ctx.max_output_bytes >= DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT
    assert ctx.max_output_bytes <= MAX_TERMINAL_OUTPUT_BYTE_LIMIT


def test_agent_loop_falls_back_for_unknown_model(tmp_path):
    from superqode.agent.loop import AgentConfig, AgentLoop
    from superqode.providers.gateway import PassthroughGateway
    from superqode.tools.base import ToolRegistry

    cfg = AgentConfig(
        provider="fictional",
        model="nope-1",
        working_directory=tmp_path,
    )
    loop = AgentLoop(gateway=PassthroughGateway(), tools=ToolRegistry(), config=cfg)
    ctx = loop._create_tool_context()
    assert ctx.max_output_bytes == DEFAULT_TERMINAL_OUTPUT_BYTE_LIMIT
