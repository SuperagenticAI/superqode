from __future__ import annotations

from rich.console import Console

from superqode.rendering.markdown import (
    markdown_to_plain_text,
    normalize_agent_markdown,
    render_agent_markdown,
)
from superqode.app import theme_bridge


def _render_text(markdown: str) -> str:
    console = Console(record=True, width=100, force_terminal=True, color_system=None)
    console.print(render_agent_markdown(markdown))
    return console.export_text()


def test_markdown_table_renders_as_drawn_table_without_raw_pipe_row():
    out = _render_text("| Name | Status |\n| --- | --- |\n| TUI | fixed |")

    assert "Name" in out
    assert "Status" in out
    assert "TUI" in out
    assert "fixed" in out
    assert "| --- | --- |" not in out


def test_markdown_fence_with_table_is_unwrapped():
    text = "```markdown\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```"

    normalized = normalize_agent_markdown(text)
    out = _render_text(text)

    assert normalized.startswith("| A | B |")
    assert "```" not in normalized
    assert "| --- | --- |" not in out
    assert "A" in out and "B" in out and "1" in out and "2" in out


def test_multiline_python_code_block_renders_with_line_numbers_and_count():
    text = "```python\ndef add(a, b):\n    return a + b\n\nresult = add(1, 2)\n```"
    out = _render_text(text)

    assert "python" in out
    assert "lines" in out
    assert "def add" in out


def test_bash_code_block_renders_with_icon():
    text = "```bash\necho 'hello world'\n```"
    out = _render_text(text)

    assert "bash" in out
    assert "echo" in out


def test_agent_code_theme_tracks_selected_tui_theme():
    theme_bridge.apply_theme("nord")
    try:
        rendered = render_agent_markdown("```python\nprint('hi')\n```")
        assert rendered.code_theme == "superqode"
        assert "print" in _render_text("```python\nprint('hi')\n```")
    finally:
        theme_bridge.apply_theme("superqode")


def test_blank_lines_are_collapsed():
    assert normalize_agent_markdown("a\n\n\n\nb") == "a\n\nb"


def test_markdown_to_plain_text_preserves_code_blocks_and_removes_inline_noise():
    text = "**Done** with `x`.\n\n```bash\nls -la\n```"

    plain = markdown_to_plain_text(text)

    assert "**" not in plain
    assert "`x`" not in plain
    assert "Done with x." in plain
    assert "```bash\nls -la\n```" in plain
