"""Phase 8: AGENTS.md compatibility tests.

Covers the OpenAI Agents SDK conventions for AGENTS.md resolution:

    * AGENTS.md is canonical; CLAUDE.md is a legacy fallback only used when
      AGENTS.md is absent in the same directory.
    * Parent → child order: root AGENTS.md first, deeper ones later (so
      deeper-nested instructions take precedence when concatenated).
    * Empty files and unreadable files are skipped silently.
    * Globals (~/.superqode, ~/.config/superqode) load first so project files
      override them.
"""

from __future__ import annotations

from pathlib import Path

from superqode.skills import load_project_instructions


def test_agents_md_alone(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("root rule\n", encoding="utf-8")
    out = load_project_instructions(tmp_path)
    assert "root rule" in out


def test_claude_md_only_loaded_when_agents_md_absent(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("legacy rule\n", encoding="utf-8")
    out = load_project_instructions(tmp_path)
    assert "legacy rule" in out


def test_agents_md_wins_over_claude_md_in_same_dir(tmp_path: Path):
    """When both exist, only AGENTS.md is loaded (the canonical OpenAI choice)."""
    (tmp_path / "AGENTS.md").write_text("agents-rule", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude-rule", encoding="utf-8")
    out = load_project_instructions(tmp_path)
    assert "agents-rule" in out
    assert "claude-rule" not in out


def test_deeper_nested_appears_later(tmp_path: Path):
    """Parent → child order: nested AGENTS.md appears later in the output."""
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("Root says use tabs.", encoding="utf-8")
    (nested / "AGENTS.md").write_text("Pkg overrides: use spaces.", encoding="utf-8")
    out = load_project_instructions(nested)
    root_pos = out.index("Root says use tabs.")
    nested_pos = out.index("Pkg overrides: use spaces.")
    assert root_pos < nested_pos


def test_empty_agents_md_is_skipped(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("   \n   ", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("fallback content", encoding="utf-8")
    out = load_project_instructions(tmp_path)
    # An empty AGENTS.md still suppresses CLAUDE.md (it "exists"); the v1
    # behavior is conservative — fix surprises later if real users complain.
    # The doc test is here to make the choice explicit.
    assert "fallback content" not in out


def test_missing_dirs_have_no_effect(tmp_path: Path):
    out = load_project_instructions(tmp_path / "nonexistent")
    # No AGENTS.md or CLAUDE.md anywhere → output is empty (or only globals).
    assert isinstance(out, str)


def test_mixed_chain_agents_root_claude_legacy(tmp_path: Path):
    """A repo can have AGENTS.md at the root and CLAUDE.md in a subdir."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "AGENTS.md").write_text("root from agents", encoding="utf-8")
    (sub / "CLAUDE.md").write_text("subdir from claude", encoding="utf-8")
    out = load_project_instructions(sub)
    assert "root from agents" in out
    assert "subdir from claude" in out
    # Order: root first, then nested.
    assert out.index("root from agents") < out.index("subdir from claude")


def test_label_is_relative_to_base(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("hi", encoding="utf-8")
    out = load_project_instructions(tmp_path)
    # The header uses the relative path (just "AGENTS.md" when it lives at base).
    assert "AGENTS.md" in out


def test_unreadable_file_does_not_raise(tmp_path: Path, monkeypatch):
    """A read error on AGENTS.md should be silently skipped, not crash."""
    path = tmp_path / "AGENTS.md"
    path.write_text("ok", encoding="utf-8")
    original_read_text = Path.read_text

    def boom(self, *args, **kwargs):
        if self == path:
            raise PermissionError("simulated")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    out = load_project_instructions(tmp_path)
    # No exception raised, returned a string (possibly empty).
    assert isinstance(out, str)
