"""Tests for compact workspace change summaries."""

from __future__ import annotations

import subprocess

from superqode.workspace.change_summary import (
    capture_workspace_changes,
    render_change_summary,
    summarize_workspace_changes,
)


def test_change_summary_renders_counts_without_file_list_by_default(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "app.py"
    tracked.write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
    )

    before = capture_workspace_changes(tmp_path)
    tracked.write_text("print('hello')\nprint('world')\n", encoding="utf-8")

    summary = summarize_workspace_changes(tmp_path, before=before)
    rendered = render_change_summary(summary, "summary")

    assert summary.files[0].path == "app.py"
    assert "Changes: 1 file" in rendered
    assert "app.py" not in rendered


def test_change_summary_can_render_file_list(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    before = capture_workspace_changes(tmp_path)
    (tmp_path / "new.txt").write_text("hello\n", encoding="utf-8")

    summary = summarize_workspace_changes(tmp_path, before=before)
    rendered = render_change_summary(summary, "files")

    assert "new.txt" in rendered
