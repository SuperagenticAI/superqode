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
