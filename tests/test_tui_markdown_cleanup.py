from superqode.app_main import SuperQodeApp


def test_strip_markdown_restores_code_blocks_without_placeholder_leak():
    text = "Before\n```bash\nls -la\n```\nAfter"

    cleaned = SuperQodeApp._strip_markdown(object(), text)

    assert "CODE_BLOCK_0" not in cleaned
    assert "```bash\nls -la\n```" in cleaned
