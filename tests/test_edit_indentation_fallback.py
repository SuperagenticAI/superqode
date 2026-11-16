"""Tests for indentation handling in the fuzzy edit fallbacks.

read_file numbers its output ('N: content'); smaller models sometimes copy the
space after the prefix into both old_text and new_text. The whitespace-tolerant
fallbacks still match, and the replacement must land on the file's real indent.
"""

from superqode.agent.edit_strategies import replace_with_strategies

FILE = 'def add(a, b):\n    """Return the sum of a and b."""\n    return a - b\n'


def test_extra_indent_from_read_output_is_rebased():
    # 5 leading spaces: one copied from the "3: " separator plus the real 4.
    old = "     return a - b"
    new = "     return a + b"
    result, count = replace_with_strategies(FILE, old, new)
    assert count == 1
    assert result == 'def add(a, b):\n    """Return the sum of a and b."""\n    return a + b\n'


def test_multiline_replacement_keeps_relative_indent():
    content = "if ready:\n    run()\n"
    old = "     run()"
    new = "     run()\n     report()"
    result, count = replace_with_strategies(content, old, new)
    assert count == 1
    assert result == "if ready:\n    run()\n    report()\n"


def test_explicit_indent_change_is_preserved():
    content = "if ready:\n    run()\n"
    result, count = replace_with_strategies(content, "    run()", "        run()")
    assert count == 1
    assert result == "if ready:\n        run()\n"


def test_line_number_prefix_fallback_does_not_reindent():
    content = "def add(a, b):\n    return a + b\n"
    old = "2:     return a + b"
    new = "    return a * b"
    result, count = replace_with_strategies(content, old, new)
    assert count == 1
    assert result == "def add(a, b):\n    return a * b\n"
