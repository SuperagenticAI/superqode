#!/usr/bin/env python3
"""Print the CHANGELOG section for a version or git tag."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def changelog_notes(version: str, text: str) -> str:
    heading = f"## [{version}]"
    start = text.find(heading)
    if start == -1:
        return f"SuperQode {version}"
    start = text.find("\n", start) + 1
    nxt = text.find("\n## [", start)
    body = text[start : nxt if nxt != -1 else None].strip()
    return body or f"SuperQode {version}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Tag or version, for example v0.2.117")
    args = parser.parse_args()
    version = str(args.tag).removeprefix("v")
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    print(changelog_notes(version, text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
