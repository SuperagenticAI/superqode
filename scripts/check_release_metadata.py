#!/usr/bin/env python3
"""Validate version metadata, optionally against a release tag."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_metadata_errors(tag: str | None = None) -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["project"]["version"])
    errors: list[str] = []

    expected_entry = "superqode.main:cli_main"
    scripts = pyproject.get("project", {}).get("scripts", {})
    for command in ("superqode", "sq"):
        if scripts.get(command) != expected_entry:
            errors.append(
                f"project script {command!r} is {scripts.get(command)!r}, expected {expected_entry!r}"
            )

    package_text = (ROOT / "src/superqode/__init__.py").read_text(encoding="utf-8")
    package_match = re.search(r'^__version__\s*=\s*"([^"]+)"', package_text, re.MULTILINE)
    package_version = package_match.group(1) if package_match else ""
    if package_version != version:
        errors.append(
            f"src/superqode/__init__.py is {package_version or 'missing'}, expected {version}"
        )

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_versions = [
        str(package.get("version") or "")
        for package in lock.get("package", [])
        if package.get("name") == "superqode"
    ]
    if locked_versions != [version]:
        errors.append(f"uv.lock has SuperQode versions {locked_versions!r}, expected [{version!r}]")

    registry = json.loads(
        (ROOT / "install/acp-registry/superqode/agent.json").read_text(encoding="utf-8")
    )
    if str(registry.get("version") or "") != version:
        errors.append(f"ACP registry version is {registry.get('version')!r}, expected {version}")
    package_pin = str(registry.get("distribution", {}).get("uvx", {}).get("package") or "")
    if package_pin != f"superqode=={version}":
        errors.append(f"ACP registry package is {package_pin!r}, expected superqode=={version}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        errors.append(f"CHANGELOG.md has no release heading for {version}")

    if tag and tag != f"v{version}":
        errors.append(f"release tag is {tag!r}, expected 'v{version}'")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Tag name to compare with project.version")
    args = parser.parse_args()
    errors = release_metadata_errors(args.tag)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release metadata is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
