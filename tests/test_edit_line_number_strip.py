"""Tests for the line-number-prefix fallback in edit matching.

read_file numbers its output ('N: content'); smaller models sometimes paste
those prefixes into old_string. The fallback replacer strips them.
"""

import pytest

from superqode.agent.edit_strategies import replace_with_strategies

FILE = "def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n"


def test_exact_match_still_first():
    new, count = replace_with_strategies(FILE, "return a + b", "return a * b")
    assert count == 1
    assert "a * b" in new


def test_line_number_prefixes_stripped():
    old = "1: def add(a, b):\n2:     return a + b"
    new, count = replace_with_strategies(FILE, old, "def add(a, b):\n    return a - b")
    assert count == 1
    assert "a - b" in new


def test_pipe_style_prefixes_stripped():
    old = "1| def add(a, b):\n2|     return a + b"
    new, count = replace_with_strategies(FILE, old, "def add(a, b):\n    return a - b")
    assert count == 1
    assert "a - b" in new


def test_unprefixed_content_with_digit_words_not_mangled():
    content = "value = 5\n5: a label line\nother = 2\n"
    # Only one of three lines looks prefixed - stripping must not kick in
    # for a plain exact match that already works.
    new, count = replace_with_strategies(content, "value = 5", "value = 6")
    assert count == 1
    assert "value = 6" in new


def test_not_found_still_raises():
    with pytest.raises(ValueError):
        replace_with_strategies(FILE, "9: nonexistent line", "x")
