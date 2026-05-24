"""Tests for compact TUI tool display helpers."""

from superqode.app.widgets import _diff_stats_from_text, _format_duration, summarize_tool_output
from superqode.tools.display import format_tool_call_compact


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


def test_compact_display_formats_file_tool():
    label = format_tool_call_compact("read_file", {"path": "/repo/src/superqode/app_main.py"})

    assert label == "read_file(.../src/superqode/app_main.py)"


def test_compact_display_formats_search_tool():
    label = format_tool_call_compact("grep", {"pattern": "add_tool_call", "path": "src"})

    assert label == 'grep("add_tool_call", src)'


def test_compact_display_formats_shell_tool_with_timeout():
    label = format_tool_call_compact("bash", {"command": "uv run pytest tests", "timeout": 120})

    assert label == 'bash("uv run pytest tests", timeout=120)'


def test_compact_display_formats_python_repl_multiline():
    label = format_tool_call_compact("python_repl", {"code": "x = 1\nx + 1"})

    assert label == 'python_repl(2 lines: "x = 1")'


def test_compact_display_truncates_long_values():
    label = format_tool_call_compact("repo_search", {"query": "x" * 200}, max_length=40)

    assert label.startswith('repo_search("')
    assert label.endswith("...")
    assert len(label) == 40


def test_tool_display_counts_diff_stats():
    diff = "\n".join(
        [
            "--- a/file.py",
            "+++ b/file.py",
            "@@ -1,2 +1,3 @@",
            " unchanged",
            "-old",
            "+new",
            "+extra",
        ]
    )

    assert _diff_stats_from_text(diff) == (2, 1)


def test_tool_display_formats_duration_badge():
    assert _format_duration(0.01) == "<0.1s"
    assert _format_duration(1.234) == "1.2s"
    assert _format_duration(12.3) == "12s"
