"""Smoke tests for developer workflow documentation."""

from pathlib import Path


def test_developer_workflow_docs_are_linked_and_command_complete():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    docs_index = (root / "docs" / "index.md").read_text(encoding="utf-8")
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")
    workflows = (root / "docs" / "developer-workflows.md").read_text(encoding="utf-8")

    assert "docs/developer-workflows.md" in readme
    assert "developer-workflows.md" in docs_index
    assert "developer-workflows.md" in mkdocs

    required_commands = [
        ":share create",
        ":share export",
        ":share import",
        ":share list",
        ":share revoke",
        ":trust doctor",
        ":trust yes",
        ":plugins add",
        ":plugins doctor",
        ":memory remember",
        ":memory search",
        ":memory search specmem",
        ":codex status",
        ":claude status",
        ":antigravity status",
        "superqode share create",
        "superqode trust status",
        "superqode plugins doctor",
        "superqode memory remember",
        "superqode memory search",
    ]
    for command in required_commands:
        assert command in workflows
