from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "check_030_candidate.py"
    spec = importlib.util.spec_from_file_location("check_030_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_030_candidate_surface_contract_is_complete():
    assert _module().candidate_errors() == []
