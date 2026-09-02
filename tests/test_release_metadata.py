from __future__ import annotations

import importlib.util
from pathlib import Path


def _release_module():
    path = Path(__file__).parents[1] / "scripts" / "check_release_metadata.py"
    spec = importlib.util.spec_from_file_location("check_release_metadata", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_metadata_is_consistent():
    assert _release_module().release_metadata_errors() == []


def test_release_metadata_rejects_wrong_tag():
    errors = _release_module().release_metadata_errors("v999.0.0")
    assert any("release tag" in error for error in errors)


def _notes_module():
    path = Path(__file__).parents[1] / "scripts" / "changelog_notes.py"
    spec = importlib.util.spec_from_file_location("changelog_notes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changelog_notes_take_the_matching_section():
    text = "## [Unreleased]\n\n## [1.2.3] - 2026-09-02\n\n### Fixed\n\n- one\n\n## [1.2.2] - 2026-08-01\n\n- two\n"
    notes = _notes_module().changelog_notes("1.2.3", text)
    assert notes.startswith("### Fixed")
    assert "- one" in notes
    assert "1.2.2" not in notes
    assert _notes_module().changelog_notes("9.9.9", text) == "SuperQode 9.9.9"
