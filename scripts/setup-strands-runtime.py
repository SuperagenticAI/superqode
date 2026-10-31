#!/usr/bin/env python3
"""Explicitly install or check the isolated Strands environment. No model calls."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="Create the isolated environment and install pinned packages",
    )
    parser.add_argument(
        "--python",
        type=Path,
        help="Existing isolated Python interpreter (also accepts SUPERQODE_STRANDS_PYTHON)",
    )
    args = parser.parse_args()
    target = args.python or Path(
        os.environ.get("SUPERQODE_STRANDS_PYTHON")
        or Path.home()
        / ".superqode/runtimes/strands"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    target = target.expanduser().absolute()
    if args.install:
        uv = shutil.which("uv")
        if not uv:
            parser.error("Install uv first, then rerun with --install")
        if target.parent.parent.resolve() == Path(sys.prefix).resolve():
            parser.error("Choose a separate environment, not this Python interpreter")
        if target.exists() and not (target.parent.parent / "pyvenv.cfg").is_file():
            parser.error("Choose an isolated virtual environment, not a system interpreter")
        if not target.exists():
            subprocess.run([uv, "venv", "--python", "3.12", str(target.parent.parent)], check=True)
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(target),
                "strands-harness[anthropic,openai,gemini,ollama]==0.3.3",
                "strands-agents==1.63.0",
            ],
            check=True,
        )
    if not target.is_file():
        parser.error("Isolated Python not found; run with --install")
    worker = (
        Path(__file__).resolve().parents[1] / "src/superqode/harness/backends/strands_worker.py"
    )
    return subprocess.run([str(target), "-I", str(worker), "--check"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
