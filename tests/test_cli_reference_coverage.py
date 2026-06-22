"""Documentation coverage checks for the public CLI surface."""

from pathlib import Path

from superqode.main import cli_main


def test_top_level_cli_groups_have_reference_docs():
    """Every public top-level command group should be discoverable from the docs."""

    root = Path(__file__).resolve().parents[1]
    cli_reference = root / "docs" / "cli-reference"
    docs_index = (cli_reference / "index.md").read_text(encoding="utf-8")
    mkdocs = (root / "mkdocs.yml").read_text(encoding="utf-8")

    documented_files = {path.name for path in cli_reference.glob("*.md")}
    filename_aliases = {
        "provider-commands.md": {"providers"},
        "doctor-command.md": {"doctor"},
        "daemon-command.md": {"daemon"},
        "mcp-command.md": {"mcp"},
        "init-commands.md": {"init"},
    }
    intentionally_inline = {
        "help",  # help is built into the CLI and surfaced by Click.
        "tui",  # documented in advanced/tui.md rather than the CLI section.
    }

    documented_groups = set()
    for filename in documented_files:
        if filename == "index.md":
            continue
        if filename.endswith("-commands.md"):
            documented_groups.add(filename[: -len("-commands.md")])
        elif filename.endswith("-command.md"):
            documented_groups.add(filename[: -len("-command.md")])
        documented_groups.update(filename_aliases.get(filename, set()))

    missing = []
    for name in sorted(cli_main.commands):
        if name in intentionally_inline:
            continue
        if name not in documented_groups:
            missing.append(name)
            continue
        expected_refs = [
            f"{name}-commands.md",
            f"{name}-command.md",
            "provider-commands.md" if name == "providers" else "",
        ]
        if not any(ref and ref in docs_index and ref in mkdocs for ref in expected_refs):
            missing.append(name)

    assert missing == []
