#!/usr/bin/env python3
"""Compatibility wrapper; prefer `superqode harness strands setup` / `doctor`."""

from pathlib import Path
import runpy

if __name__ == "__main__":
    # Keep the source helper usable with plain Python before SuperQode is installed.
    module = Path(__file__).resolve().parents[1] / "src/superqode/harness/strands_setup.py"
    runpy.run_path(str(module), run_name="__main__")
