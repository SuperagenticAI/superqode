"""Tests for compact TUI tool display helpers."""

from superqode.app.widgets import summarize_tool_output


def test_repo_search_output_is_summarized():
    output = """Files:
src/superqode/main.py
src/superqode/tools/search_tools.py

Content:
src/superqode/main.py:12:repo_search

Symbols:
src/superqode/tools/search_tools.py:1 [class] RepoSearchTool
"""

    summary = summarize_tool_output("repo_search", "success", output)

    assert summary == "files 2, content 1, symbols 1"


def test_verbose_tool_output_is_preserved():
    output = "line 1\nline 2"

    assert summarize_tool_output("bash", "success", output, "verbose") == output


def test_normal_read_output_hides_file_body():
    output = "first line\nsecond line\nthird line"

    assert summarize_tool_output("read_file", "success", output) == "read 3 lines"


def test_minimal_success_output_is_hidden():
    assert summarize_tool_output("grep", "success", "a\nb", "minimal") == ""
