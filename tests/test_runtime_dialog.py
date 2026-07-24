"""Tests for the RuntimeDialog selection logic.

The dialog uses prompt_toolkit for interactive input; we test the pure logic
paths (resolution + validation) by invoking helpers directly.
"""

from __future__ import annotations

import pytest

from superqode.dialogs.runtime import RuntimeDialog
from superqode.runtime import list_runtimes


def test_dialog_lists_current_runtimes():
    dialog = RuntimeDialog(active="builtin")
    names = {info.name for info in dialog.runtimes}
    assert names == {
        "builtin",
        "adk",
        "openai-agents",
        "codex-sdk",
        "copilot-sdk",
        "claude-agent-sdk",
        "antigravity-sdk",
        "antigravity-cli",
        "antigravity-managed",
        "pydanticai",
    }


def test_resolve_numeric_answer():
    dialog = RuntimeDialog(active="builtin")
    runtimes = list_runtimes()
    # Numeric answer "1" maps to the first runtime
    first = dialog._resolve_answer("1")
    assert first is not None
    assert first.name == runtimes[0].name


def test_resolve_name_answer_case_insensitive():
    dialog = RuntimeDialog(active="builtin")
    info = dialog._resolve_answer("BUILTIN")
    assert info is not None
    assert info.name == "builtin"


def test_resolve_unknown_answer_returns_none():
    dialog = RuntimeDialog(active="builtin")
    assert dialog._resolve_answer("nope") is None
    assert dialog._resolve_answer("99") is None
    assert dialog._resolve_answer("") is None


def test_active_runtime_defaults_to_resolver():
    """When constructed without `active`, the dialog reads resolve_runtime_name()."""
    dialog = RuntimeDialog()
    assert dialog.active in {"builtin", "adk", "openai-agents", "codex-sdk", "pydanticai"}
