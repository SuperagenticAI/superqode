"""Conditional AGENTS.md fragments reload into the pinned system prompt."""

from __future__ import annotations

from pathlib import Path

from superqode.agent.instructions import (
    glob_match,
    load_instruction_set,
    refresh_pinned_instructions,
    split_instruction_text,
)
from superqode.agent.loop import AgentConfig, AgentLoop, AgentMessage
from superqode.skills import load_project_instructions

MARKED = """\
Always run the tests you touch.

<!-- sq:when paths="billing/**,*.tsx" tools="bash" tasks="docs" -->
Never log card numbers.
<!-- /sq:when -->

Keep commit messages short.
"""


def test_unmarked_text_stays_unconditional():
    parsed = split_instruction_text("Use ruff.\n")
    assert parsed.unconditional == "Use ruff."
    assert parsed.fragments == ()


def test_conditional_block_stays_visible_until_opt_in(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_CONDITIONAL_INSTRUCTIONS", raising=False)
    (tmp_path / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    visible = load_project_instructions(tmp_path)
    assert "Never log card numbers." in visible
    assert "Always run the tests you touch." in visible


def test_conditional_block_leaves_the_always_on_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_CONDITIONAL_INSTRUCTIONS", "1")
    (tmp_path / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    loaded = load_instruction_set(tmp_path, include_globals=False)
    assert "Always run the tests you touch." in loaded.unconditional
    assert "Keep commit messages short." in loaded.unconditional
    assert "Never log card numbers." not in loaded.unconditional
    assert len(loaded.fragments) == 1
    visible = load_project_instructions(tmp_path)
    assert "Never log card numbers." not in visible
    assert "Always run the tests you touch." in visible


def test_unclosed_marker_stays_visible():
    parsed = split_instruction_text('<!-- sq:when paths="billing/**" -->\nKeep this.\n')
    assert "Keep this." in parsed.unconditional
    assert parsed.fragments == ()


def test_path_tool_and_task_globs():
    assert glob_match("billing/**", "billing/invoice.py")
    assert glob_match("billing/**", "src/billing/invoice.py")
    assert glob_match("*.tsx", "src/App.tsx")
    assert not glob_match("*.tsx", "src/app.py")


def test_pin_reloads_and_replaces_the_block(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    messages = [
        AgentMessage(role="system", content="You are SuperQode."),
        AgentMessage(role="user", content="Update the billing invoice."),
        AgentMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "1",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"file_path": "billing/invoice.py"}',
                    },
                }
            ],
        ),
    ]
    pinned = refresh_pinned_instructions(messages, tmp_path, include_globals=False)
    assert "Never log card numbers." in pinned[0].content
    assert pinned[0].content.count("Never log card numbers.") == 1
    assert messages[0].content == "You are SuperQode."

    again = refresh_pinned_instructions(pinned, tmp_path, include_globals=False)
    assert again[0].content.count("Never log card numbers.") == 1

    unrelated = [
        AgentMessage(role="system", content=pinned[0].content),
        AgentMessage(role="user", content="Rename a local variable in src/app.py."),
    ]
    cleared = refresh_pinned_instructions(unrelated, tmp_path, include_globals=False)
    assert "Never log card numbers." not in cleared[0].content
    assert "You are SuperQode." in cleared[0].content


def test_instructions_pin_before_the_model_call(tmp_path: Path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    loop = AgentLoop.__new__(AgentLoop)
    loop.config = AgentConfig(provider="x", model="y", working_directory=tmp_path)
    messages = [
        AgentMessage(role="system", content="base"),
        AgentMessage(role="user", content="Please update the documentation."),
    ]
    monkeypatch.delenv("SUPERQODE_CONDITIONAL_INSTRUCTIONS", raising=False)
    unchanged = loop._refresh_opt_in_instructions(messages)
    assert unchanged is messages
    assert "Never log card numbers." not in unchanged[0].content

    monkeypatch.setenv("SUPERQODE_CONDITIONAL_INSTRUCTIONS", "1")
    pinned = loop._refresh_opt_in_instructions(messages)
    assert "Never log card numbers." in pinned[0].content
    assert messages[0].content == "base"


def test_docs_task_activates_without_a_path(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(MARKED, encoding="utf-8")
    messages = [
        AgentMessage(role="system", content="base"),
        AgentMessage(role="user", content="Please update the documentation."),
    ]
    pinned = refresh_pinned_instructions(messages, tmp_path, include_globals=False)
    assert "Never log card numbers." in pinned[0].content
