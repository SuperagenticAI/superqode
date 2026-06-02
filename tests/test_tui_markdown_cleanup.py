from superqode.rendering.markdown import markdown_to_plain_text


def test_markdown_to_plain_text_restores_code_blocks_without_placeholder_leak():
    text = "Before\n```bash\nls -la\n```\nAfter"

    cleaned = markdown_to_plain_text(text)

    assert "CODE_BLOCK_0" not in cleaned
    assert "```bash\nls -la\n```" in cleaned
