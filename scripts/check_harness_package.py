#!/usr/bin/env python3
"""Build, install, run, check, and uninstall the minimal harness package."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples" / "harness-packages" / "hello-harness"


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _capture(command: list[str], *, cwd: Path) -> str:
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def main() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to run the harness package check")
    with tempfile.TemporaryDirectory(prefix="superqode-harness-package-") as temporary:
        temp = Path(temporary)
        dist = temp / "dist"
        workspace = temp / "workspace"
        dist.mkdir()
        workspace.mkdir()
        _run([uv, "build", "--wheel", "--out-dir", str(dist), str(ROOT)])
        _run([uv, "build", "--wheel", "--out-dir", str(dist), str(PACKAGE)])
        superqode_wheel = next(
            path for path in dist.glob("superqode-*.whl") if "hello_harness" not in path.name
        )
        harness_wheel = next(dist.glob("superqode_hello_harness-*.whl"))
        venv = temp / "venv"
        _run([uv, "venv", str(venv)])
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        executable = venv / ("Scripts/superqode.exe" if os.name == "nt" else "bin/superqode")
        _run([uv, "pip", "install", "--python", str(python), str(superqode_wheel)])
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(harness_wheel),
            ]
        )
        listed = json.loads(_capture([str(executable), "harness", "list", "--json"], cwd=workspace))
        if not any(row["id"] == "hello" and row["kind"] == "python" for row in listed):
            raise AssertionError("installed hello harness was not discovered")
        run = json.loads(
            _capture(
                [
                    str(executable),
                    "harness",
                    "run",
                    "hello",
                    "package-check",
                    "--provider",
                    "test",
                    "--model",
                    "model",
                    "--store",
                    "memory",
                    "--json",
                ],
                cwd=workspace,
            )
        )
        if run["content"] != "hello from hello: package-check":
            raise AssertionError(f"unexpected package response: {run}")
        report = json.loads(
            _capture(
                [
                    str(executable),
                    "harness",
                    "protocol",
                    "conformance",
                    "hello",
                    "--json",
                ],
                cwd=workspace,
            )
        )
        if not report["passed"]:
            raise AssertionError(f"installed harness failed conformance: {report}")
        _run(
            [
                uv,
                "pip",
                "uninstall",
                "--python",
                str(python),
                "superqode-hello-harness",
            ]
        )
        after = json.loads(_capture([str(executable), "harness", "list", "--json"], cwd=workspace))
        if any(row["id"] == "hello" for row in after):
            raise AssertionError("uninstalled hello harness is still discoverable")
    print("Harness package lifecycle check passed.")


if __name__ == "__main__":
    main()
