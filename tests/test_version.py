"""Version metadata consistency tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import superqode


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert superqode.__version__ == pyproject["project"]["version"]
