"""Local migration dry-run planning."""

from __future__ import annotations

from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local.migrate import plan_local_migration, render_migration_report


def test_plan_local_migration_inventory(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "Use web_search only when available. Prefer OpenAI tools.\n",
        encoding="utf-8",
    )
    skills_dir = tmp_path / ".agents" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "review.md").write_text(
        "---\nname: review\ndescription: Review\n---\nRun shell checks carefully.\n",
        encoding="utf-8",
    )
    (tmp_path / "harness.yaml").write_text(
        "version: 1\nname: local\nmodel_policy:\n  primary: minimax/minimax-m1\n  pack: minimax\n",
        encoding="utf-8",
    )

    report = plan_local_migration(
        tmp_path,
        endpoint="http://localhost:8000/v1",
        model="MiniMaxAI/MiniMax-M1",
    )

    assert report.detected_pack == "minimax"
    assert [item.path for item in report.prompts] == ["AGENTS.md"]
    assert [item.path for item in report.skills] == [".agents/skills/review.md"]
    assert [item.path for item in report.harnesses] == ["harness.yaml"]
    assert any("web-search" in note for note in report.prompts[0].notes)
    assert any("shell approval" in note for note in report.skills[0].notes)
    assert report.harness_hint["primary"] == "openai_compatible/MiniMaxAI/MiniMax-M1"
    assert report.harness_hint["pack"] == "minimax"
    assert "harness you own" in render_migration_report(report)
    assert "pack: minimax" in render_migration_report(report)
    assert any("--pack minimax" in step for step in report.next_steps)


def test_local_migrate_cli_json(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Local rules.\n", encoding="utf-8")

    result = CliRunner().invoke(
        local,
        [
            "migrate",
            "--repo",
            str(tmp_path),
            "--model",
            "MiniMaxAI/MiniMax-M1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"detected_pack": "minimax"' in result.output
    assert '"pack": "minimax"' in result.output
    assert '"path": "AGENTS.md"' in result.output
