"""Smoke tests for developer workflow documentation."""

from pathlib import Path

from click.testing import CliRunner

from superqode.main import cli_main


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


def test_local_agentic_coding_docs_match_cli_surface():
    root = Path(__file__).resolve().parents[1]
    local_doc = (root / "docs" / "advanced" / "local-stack.md").read_text(encoding="utf-8")
    product_plan = (root / "product" / "local-first-strategy.md").read_text(encoding="utf-8")
    runner = CliRunner()

    assert "No implementation yet" not in product_plan
    assert "Local Stack Doctor" in local_doc

    local_help = runner.invoke(cli_main, ["local", "--help"])
    assert local_help.exit_code == 0
    for command in ("doctor", "packs", "bench", "optimize"):
        assert command in local_help.output
        assert f"superqode local {command}" in local_doc
    bench_help = runner.invoke(cli_main, ["local", "bench", "--help"])
    assert bench_help.exit_code == 0
    assert "--agentic" in bench_help.output
    assert "superqode local bench --agentic" in local_doc

    mlx_help = runner.invoke(cli_main, ["providers", "mlx", "--help"])
    assert mlx_help.exit_code == 0
    for action in ("server", "doctor", "list", "models", "setup", "check"):
        assert action in mlx_help.output

    assert "superqode providers mlx server" in local_doc
    assert "superqode providers mlx doctor" in local_doc
