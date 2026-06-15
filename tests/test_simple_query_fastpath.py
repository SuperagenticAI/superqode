"""Greetings/small talk skip the tool schemas so they stay fast on local models."""

from __future__ import annotations

import pytest

from superqode.agent.loop import _is_simple_conversational_query as is_simple


@pytest.mark.parametrize(
    "prompt",
    [
        "How are you?",
        "how are you",
        "How's it going?",
        "what's up",
        "good morning",
        "thanks!",
        "hello",
        "hi",
        "What is a compiler?",
        "Who wrote Hamlet?",
    ],
)
def test_conversational_prompts_are_simple(prompt):
    assert is_simple(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "Read the README",
        "how do I read a file?",
        "how does this function work",
        "Refactor the auth module",
        "What files are in this project?",
        "edit main.py",
    ],
)
def test_code_prompts_are_not_simple(prompt):
    assert is_simple(prompt) is False
