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
        "Hello",
        "Hello!",
        "hi",
        "Hello there",
        "Hi there",
        "Hey there",
        "Hello, how are you?",
        "What is a compiler?",
        "Who wrote Hamlet?",
        # Model identity must skip tools (substring "code" in "coding" used to force tools).
        "which coding model are you using",
        "Which coding model is this?",
        "what model are you using?",
        "what model are you",
        "who are you",
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
        "which file should I edit",
        "what code uses auth",
        "hello please refactor the auth module",
    ],
)
def test_code_prompts_are_not_simple(prompt):
    assert is_simple(prompt) is False


def test_fast_chat_path_applies_to_grok_subscription():
    """Grok subscription is cloud — must still use fast chat for Hello."""
    from superqode.agent.loop import AgentConfig, AgentLoop
    from superqode.tools.base import ToolRegistry

    loop = AgentLoop(
        gateway=object(),  # unused for path decision
        tools=ToolRegistry.empty(),
        config=AgentConfig(provider="grok-cli", model="grok-build"),
    )
    assert loop._use_fast_chat_path("Hello") is True
    assert loop._use_fast_chat_path("Hello there") is True
    assert loop._use_fast_chat_path("which coding model are you using") is True
    assert loop._use_fast_chat_path("refactor the auth module") is False
    assert loop._use_fast_chat_path("hello please refactor the auth module") is False
