"""Explicitly install or inspect the private Pydantic Coder environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import PACKAGES, SETUP_HINT, VERSIONS, runtime_python


def find_uv() -> str | None:
    if os.environ.get("SUPERQODE_APP") == "1" and os.environ.get("SUPERQODE_STATE_DIR"):
        from superqode.desktop_service.app_setup import ensure_uv

        return ensure_uv(Path(os.environ["SUPERQODE_STATE_DIR"]) / "bin")
    return shutil.which("uv")


def setup_runtime(interpreter: Path | None = None, *, install: bool = False) -> dict[str, str]:
    target = (interpreter or runtime_python()).expanduser().absolute()
    root = target.parent.parent
    if install:
        if root.resolve() == Path(sys.prefix).resolve() or target.parent.name not in {
            "bin",
            "Scripts",
        }:
            raise ValueError(
                "Choose a separate virtual environment, not the SuperQode interpreter."
            )
        if target.exists() and not (root / "pyvenv.cfg").is_file():
            raise ValueError("Choose an isolated virtual environment, not a system interpreter.")
        uv = find_uv()
        if not uv:
            raise ValueError("Install uv first. " + SETUP_HINT)
        if not target.exists():
            subprocess.run([uv, "venv", "--python", "3.13", str(root)], check=True)
        (root / "superqode-pydantic-coder.json").unlink(missing_ok=True)
        subprocess.run([uv, "pip", "install", "--python", str(target), *PACKAGES], check=True)
    if not target.is_file():
        raise ValueError("Pydantic Coder runtime is missing. " + SETUP_HINT)
    from superqode.harness.strands_setup import BASE_VARIABLES

    try:
        result = subprocess.run(
            [str(target), "-I", str(Path(__file__).with_name("worker.py")), "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            env={name: value for name, value in os.environ.items() if name in BASE_VARIABLES},
        )
        versions = json.loads(result.stdout)
        if result.returncode or versions != VERSIONS:
            raise ValueError("Unexpected runtime versions")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Pydantic Coder runtime check failed. " + SETUP_HINT) from exc
    if install:
        handle, temporary = tempfile.mkstemp(prefix=".coder-receipt-", dir=root)
        try:
            with os.fdopen(handle, "w") as output:
                json.dump(versions, output)
            os.replace(temporary, root / "superqode-pydantic-coder.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    try:
        versions = setup_runtime(args.python, install=args.install)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Pydantic Coder setup failed: {exc}\n")
    print("Pydantic Coder runtime ready: " + json.dumps(versions, sort_keys=True))


if __name__ == "__main__":
    main()
