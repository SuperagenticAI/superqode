#!/usr/bin/env python3
"""Build/install dependency probes without changing the project's environment.

Use Python 3.12+ to run this script. It deliberately installs dependencies without
the project so a candidate interpreter beyond requires-python can be audited.
Resolution alone cannot establish compatibility with native extensions.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.15", help="Interpreter version or executable")
    parser.add_argument("--uv", default="uv", help="uv executable to test")
    parser.add_argument(
        "--extra", action="append", default=[], choices=sorted(project["optional-dependencies"])
    )
    parser.add_argument("--locked", action="store_true", help="Probe existing uv.lock pins")
    parser.add_argument("--wheels-only", action="store_true", help="Disallow source builds")
    parser.add_argument("--output", type=Path, help="Save the JSON report")
    args = parser.parse_args()
    uv = shutil.which(args.uv)
    if uv is None:
        parser.error(f"uv executable not found: {args.uv}")

    report = {
        "python_request": args.python,
        "project_requires_python": project["requires-python"],
        "scope": "dependency installation only; project runtime tests are separate",
        "extras": sorted(set(args.extra)),
        "locked": args.locked,
        "wheels_only": args.wheels_only,
        "steps": [],
    }

    def run(label: str, command: list[str]) -> bool:
        print(f"Checking {label}...", file=sys.stderr, flush=True)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        report["steps"].append(
            {
                "name": label,
                "exit_code": result.returncode,
                "output": (result.stdout + result.stderr)[-8000:],
            }
        )
        return result.returncode == 0

    with tempfile.TemporaryDirectory(prefix="superqode-python-probe-") as directory:
        work = Path(directory)
        environment = work / "venv"
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        requirements = work / "requirements.txt"
        ok = run("uv version", [uv, "--version"])
        if ok:
            ok = run(
                "create environment",
                [uv, "venv", "--no-project", "--python", args.python, str(environment)],
            )
        if ok:
            ok = run("interpreter", [str(python), "-c", "import sys; print(sys.version)"])
        if ok and args.locked:
            command = [
                uv,
                "export",
                "--frozen",
                "--no-emit-project",
                "--no-default-groups",
                "--no-hashes",
                "--no-header",
                "--no-annotate",
                "--output-file",
                str(requirements),
            ]
            for extra in report["extras"]:
                command.extend(["--extra", extra])
            ok = run("export locked dependencies", command)
        elif ok:
            dependencies = list(project["dependencies"])
            for extra in report["extras"]:
                dependencies.extend(project["optional-dependencies"][extra])
            requirements.write_text("\n".join(dependencies) + "\n", encoding="utf-8")
        if ok:
            command = [uv, "pip", "install", "--python", str(python), "-r", str(requirements)]
            if args.wheels_only:
                command.extend(["--only-binary", ":all:"])
            ok = run("install dependencies", command)
        if ok:
            ok = run("dependency consistency", [uv, "pip", "check", "--python", str(python)])

    report["success"] = ok
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
