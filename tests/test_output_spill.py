"""Tests for spill-to-disk truncation of oversized tool output."""

import time

import pytest

from superqode.tools import output_spill
from superqode.tools.output_spill import (
    cleanup_spill_dir,
    get_spill_dir,
    spill_output,
    truncate_with_spill,
)


@pytest.fixture(autouse=True)
def _isolated_spill_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(output_spill.SPILL_DIR_ENV, str(tmp_path / "spill"))
    monkeypatch.setattr(output_spill, "_cleanup_done", False)
    yield


def test_small_output_unchanged():
    content, truncated, path = truncate_with_spill("hello", max_bytes=1000)
    assert content == "hello"
    assert truncated is False
    assert path is None


def test_zero_cap_disables_truncation():
    content, truncated, path = truncate_with_spill("x" * 10_000, max_bytes=0)
    assert truncated is False
    assert path is None


def test_oversized_output_spills_full_text():
    text = "\n".join(f"line {i}" for i in range(5000))
    content, truncated, path = truncate_with_spill(text, max_bytes=2000, label="Command output")
    assert truncated is True
    assert path is not None
    assert path.exists()
    assert path.read_text() == text  # nothing lost
    assert "Full output saved to:" in content
    assert str(path) in content
    # Preview is bounded: well under the raw size.
    assert len(content) < len(text) / 2


def test_head_tail_preview_contains_both_ends():
    text = "FIRSTLINE\n" + ("middle\n" * 4000) + "LASTLINE"
    content, truncated, _ = truncate_with_spill(text, max_bytes=2000)
    assert truncated
    assert "FIRSTLINE" in content
    assert "LASTLINE" in content


def test_tail_direction_keeps_end_only():
    text = "FIRSTLINE\n" + ("middle\n" * 4000) + "LASTLINE"
    content, truncated, _ = truncate_with_spill(text, max_bytes=1000, direction="tail")
    assert truncated
    assert "LASTLINE" in content
    assert "FIRSTLINE" not in content


def test_head_direction_keeps_start_only():
    text = "FIRSTLINE\n" + ("middle\n" * 4000) + "LASTLINE"
    content, truncated, _ = truncate_with_spill(text, max_bytes=1000, direction="head")
    assert truncated
    assert "FIRSTLINE" in content
    assert "LASTLINE" not in content


def test_spill_dir_env_override(tmp_path):
    assert str(get_spill_dir()).startswith(str(tmp_path))


def test_cleanup_removes_only_old_spill_files(tmp_path):
    path = spill_output("data")
    assert path is not None and path.exists()
    # Fresh file survives.
    assert cleanup_spill_dir() == 0
    assert path.exists()
    # Aged file is removed.
    removed = cleanup_spill_dir(now=time.time() + output_spill.RETENTION_SECONDS + 60)
    assert removed == 1
    assert not path.exists()


def test_spill_failure_still_truncates(monkeypatch):
    monkeypatch.setattr(output_spill, "spill_output", lambda *a, **k: None)
    text = "x\n" * 5000
    content, truncated, path = truncate_with_spill(text, max_bytes=500)
    assert truncated
    assert path is None
    assert "truncated" in content
