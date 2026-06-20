"""User-owned model pack generation."""

from __future__ import annotations

import json

from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import packs
from superqode.local.packs import draft_pack, render_pack_draft


def test_draft_pack_from_model():
    draft = draft_pack(model="MiniMaxAI/MiniMax-M1")

    assert draft.pack.name == "minimax-m1"
    assert "minimaxai/minimax-m1" in draft.pack.match
    assert draft.pack.policy["reasoning"] == "medium"
    assert draft.pack.policy["parallel_tools"] is False
    assert "pack: minimax-m1" in render_pack_draft(draft)


def test_draft_pack_from_smoke_json(tmp_path):
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "model": "my-coder",
                "endpoint": "http://localhost:8000/v1",
                "context_window": 16384,
                "context_source": "/v1/models",
                "checks": [
                    {"name": "read_file_tool", "ok": False},
                    {"name": "context_recall", "ok": False},
                ],
                "warnings": ["Native tool calls look unreliable."],
            }
        ),
        encoding="utf-8",
    )

    draft = draft_pack(from_smoke=smoke)

    assert draft.pack.name == "my-coder"
    assert draft.pack.policy["tool_call_format"] == "prompt"
    assert draft.pack.policy["session_history_limit"] == 8
    assert any("Smoke detected context window" in note for note in draft.pack.notes)


def test_local_pack_init_writes_user_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "USER_PACKS_DIR", tmp_path)

    result = CliRunner().invoke(local, ["pack", "init", "--model", "MiniMaxAI/MiniMax-M1"])

    assert result.exit_code == 0
    target = tmp_path / "minimax-m1.yaml"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "name: minimax-m1" in text
    assert "reasoning: medium" in text


def test_local_pack_init_dry_run_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "USER_PACKS_DIR", tmp_path)

    result = CliRunner().invoke(
        local,
        ["pack", "init", "custom-local", "--model", "vendor/custom-local", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "Dry run only" in result.output
    assert not (tmp_path / "custom-local.yaml").exists()
