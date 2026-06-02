"""Tests for ``superqode.acp.render``.

These cover the pure helper layer that turns an ACP ``tool_call_update``
into the string we hand to the TUI's ``add_tool_call(output=...)``. No
Textual machinery here — just string in, string out.
"""

from __future__ import annotations

import pytest

from superqode.acp.render import (
    NORMAL_DIFF_MAX_LINES,
    count_line_changes,
    display_title_from_update,
    extract_diff_blocks,
    extract_raw_output_text,
    extract_text_blocks,
    extract_tool_arguments,
    normalize_acp_tool_status,
    render_acp_tool_output,
    render_unified_diff,
    should_suppress_output,
    summarize_diff_blocks,
)


def test_normalize_acp_tool_status_accepts_common_agent_spellings():
    assert normalize_acp_tool_status("done") == "completed"
    assert normalize_acp_tool_status("success") == "completed"
    assert normalize_acp_tool_status("errored") == "failed"
    assert normalize_acp_tool_status("in-progress") == "running"
    assert normalize_acp_tool_status("") == "running"


def test_display_title_and_arguments_from_update_are_tolerant():
    update = {"name": "read_file", "arguments": {"path": "a.py"}}
    assert display_title_from_update(update) == "read_file"
    assert extract_tool_arguments(update) == {"path": "a.py"}


def test_extract_raw_output_text_prefers_stdout_over_dict_dump():
    assert extract_raw_output_text({"stdout": "ok", "metadata": {"x": 1}}) == "ok"
    compact = extract_raw_output_text({"metadata": {"x": 1}})
    assert compact == '{"metadata": {"x": 1}}'


# ---------------------------------------------------------------------------
# extract_diff_blocks
# ---------------------------------------------------------------------------


def test_extract_diff_blocks_handles_single_dict():
    # Some servers send one block instead of a list. The helper
    # silently lifts it so callers don't have to remember to wrap.
    block = {"type": "diff", "path": "a.py", "oldText": "x", "newText": "y"}
    assert extract_diff_blocks(block) == [("a.py", "x", "y")]


def test_extract_diff_blocks_skips_non_diff_types():
    content = [
        {"type": "text", "text": "hello"},
        {"type": "diff", "path": "a.py", "oldText": "x", "newText": "y"},
        {"type": "terminal", "terminalId": "t1"},
    ]
    assert extract_diff_blocks(content) == [("a.py", "x", "y")]


def test_extract_diff_blocks_tolerates_missing_old_text():
    # Edits that *create* a file have no oldText. The helper coerces
    # to "" so downstream diff rendering treats the whole thing as
    # additions.
    content = [{"type": "diff", "path": "new.py", "newText": "hello"}]
    assert extract_diff_blocks(content) == [("new.py", "", "hello")]


def test_extract_diff_blocks_on_none_returns_empty():
    assert extract_diff_blocks(None) == []
    assert extract_diff_blocks("not a list") == []
    assert extract_diff_blocks([{"type": "diff"}]) == [("", "", "")]


# ---------------------------------------------------------------------------
# extract_text_blocks
# ---------------------------------------------------------------------------


def test_extract_text_blocks_concatenates_text_only():
    content = [
        {"type": "text", "text": "alpha "},
        {"type": "diff", "path": "x", "newText": "ignored"},
        {"type": "text", "text": "beta"},
    ]
    assert extract_text_blocks(content) == "alpha beta"


def test_extract_text_blocks_on_dict_lifts():
    assert extract_text_blocks({"type": "text", "text": "hi"}) == "hi"


def test_extract_text_blocks_on_none():
    assert extract_text_blocks(None) == ""


# ---------------------------------------------------------------------------
# count_line_changes
# ---------------------------------------------------------------------------


def test_count_line_changes_pure_addition():
    assert count_line_changes("", "a\nb\nc") == (3, 0)


def test_count_line_changes_pure_deletion():
    assert count_line_changes("a\nb\nc", "") == (0, 3)


def test_count_line_changes_replacement():
    # One line replaced: 1 addition, 1 deletion.
    assert count_line_changes("hello\nworld", "hello\nthere") == (1, 1)


def test_count_line_changes_identical():
    assert count_line_changes("abc", "abc") == (0, 0)


# ---------------------------------------------------------------------------
# render_unified_diff
# ---------------------------------------------------------------------------


def test_render_unified_diff_omits_file_headers():
    # The ``--- a/`` / ``+++ b/`` lines from difflib are noisy when
    # we already show the path in the row header above the output.
    out = render_unified_diff("x\n", "y\n", "f.py")
    assert "--- " not in out
    assert "+++ " not in out
    assert "-x" in out
    assert "+y" in out


def test_render_unified_diff_caps_at_max_lines():
    old = "\n".join(f"line {i}" for i in range(50))
    new = "\n".join(f"changed {i}" for i in range(50))
    out = render_unified_diff(old, new, "big.py", max_lines=5)
    lines = out.splitlines()
    # Marker line is always last; everything before it is kept verbatim.
    assert "more lines" in lines[-1]
    # We should not exceed max_lines + 1 (the marker).
    assert len(lines) <= 6


def test_render_unified_diff_empty_when_unchanged():
    assert render_unified_diff("same", "same", "f.py") == ""


# ---------------------------------------------------------------------------
# summarize_diff_blocks
# ---------------------------------------------------------------------------


def test_summarize_minimal_returns_empty():
    blocks = [("a.py", "x", "y")]
    assert summarize_diff_blocks(blocks, mode="minimal") == ""


def test_summarize_normal_single_block_includes_diff_body():
    blocks = [("a.py", "hello\nworld", "hello\nthere")]
    out = summarize_diff_blocks(blocks, mode="normal")
    # First line is summary; remaining lines carry the actual diff.
    head, *rest = out.splitlines()
    assert "a.py" in head
    assert "+1" in head and "-1" in head
    assert any(line.startswith("-world") for line in rest)
    assert any(line.startswith("+there") for line in rest)


def test_summarize_normal_multi_block_only_summary_lines():
    # Multi-file edits show one summary line per file but skip the
    # body — otherwise a 5-file refactor blows the screen.
    blocks = [
        ("a.py", "x", "y"),
        ("b.py", "p", "q"),
    ]
    out = summarize_diff_blocks(blocks, mode="normal")
    assert "a.py" in out and "b.py" in out
    # No hunk header — we deliberately suppress bodies in multi-file mode.
    assert "@@" not in out


def test_summarize_verbose_includes_all_bodies():
    blocks = [
        ("a.py", "x", "y"),
        ("b.py", "p", "q"),
    ]
    out = summarize_diff_blocks(blocks, mode="verbose")
    # Each file gets a header and a body — separated by blank lines.
    assert "a.py" in out
    assert "b.py" in out
    assert "-x" in out and "+y" in out
    assert "-p" in out and "+q" in out


def test_summarize_empty_blocks_is_empty():
    assert summarize_diff_blocks([], mode="normal") == ""
    assert summarize_diff_blocks([], mode="verbose") == ""


# ---------------------------------------------------------------------------
# should_suppress_output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["read", "execute", "search", "fetch"])
def test_suppress_completed_signal_poor_kinds_in_normal_mode(kind):
    # The one-liner action row already says "read foo.py" / "run pytest";
    # dumping the file contents or stdout is just noise.
    assert should_suppress_output(kind, "completed", "normal") is True


@pytest.mark.parametrize("kind", ["edit", "write", "delete"])
def test_dont_suppress_edits_even_in_normal(kind):
    # Edits are where the user *wants* to see output (diff or
    # confirmation). Never suppress.
    assert should_suppress_output(kind, "completed", "normal") is False


def test_verbose_never_suppresses():
    assert should_suppress_output("read", "completed", "verbose") is False


def test_failed_status_never_suppressed():
    # Errors must always reach the user — that's the whole point of
    # the verbosity scheme having an escape hatch *for the agent*,
    # not the user.
    assert should_suppress_output("read", "failed", "normal") is False


# ---------------------------------------------------------------------------
# render_acp_tool_output (the orchestrator)
# ---------------------------------------------------------------------------


def test_render_prefers_diff_over_raw_output():
    # When both ``content`` (diff) and ``rawOutput`` (legacy) are
    # present, we show the diff — rawOutput for an Edit is usually
    # just the new content duplicated, which the diff already shows.
    content = [{"type": "diff", "path": "a.py", "oldText": "x", "newText": "y"}]
    out = render_acp_tool_output(
        kind="edit",
        status="completed",
        content=content,
        raw_output="duplicate noise",
        mode="normal",
    )
    assert out is not None
    assert "a.py" in out
    assert "duplicate noise" not in out


def test_render_suppresses_read_output_in_normal():
    # A Read returning 200 lines of file contents — in normal mode we
    # want None so the caller skips the output line entirely.
    out = render_acp_tool_output(
        kind="read",
        status="completed",
        content=None,
        raw_output="\n".join(f"line {i}" for i in range(200)),
        mode="normal",
    )
    assert out is None


def test_render_keeps_read_output_in_verbose():
    out = render_acp_tool_output(
        kind="read",
        status="completed",
        content=None,
        raw_output="hello",
        mode="verbose",
    )
    assert out == "hello"


def test_render_falls_back_to_text_content_when_no_diff():
    # When the agent uses content blocks (text type) instead of
    # rawOutput, surface those — they're the spec-canonical channel.
    out = render_acp_tool_output(
        kind="execute",
        status="completed",
        content=[{"type": "text", "text": "exit 0"}],
        raw_output=None,
        mode="verbose",  # execute is suppressed in normal mode
    )
    assert out == "exit 0"


def test_render_returns_none_when_nothing_to_show():
    out = render_acp_tool_output(
        kind="other",
        status="completed",
        content=None,
        raw_output=None,
        mode="normal",
    )
    assert out is None


def test_render_failed_returns_payload_even_if_suppressible_kind():
    # We invoke ``render_acp_tool_output`` with mode="verbose" for
    # failures in app_main.py specifically so this path doesn't
    # accidentally hide error text. Confirm that contract.
    out = render_acp_tool_output(
        kind="read",
        status="failed",
        content=None,
        raw_output="permission denied",
        mode="verbose",
    )
    assert out == "permission denied"


def test_normal_diff_body_respects_max_lines_constant():
    # Sanity: a large diff in normal mode collapses to the cap +
    # marker, not the full hunks.
    old = "\n".join(f"a{i}" for i in range(80))
    new = "\n".join(f"b{i}" for i in range(80))
    out = summarize_diff_blocks([("big.py", old, new)], mode="normal")
    body_lines = out.splitlines()[1:]  # skip the summary header
    assert len(body_lines) <= NORMAL_DIFF_MAX_LINES + 1
