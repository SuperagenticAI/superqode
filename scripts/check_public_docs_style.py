#!/usr/bin/env python3
"""Check public documentation for prohibited punctuation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (ROOT / "README.md", ROOT / "mkdocs.yml", ROOT / "pyproject.toml")
EM_DASH = chr(0x2014)


def iter_public_files() -> list[Path]:
    """Return public documentation and product metadata files."""
    docs = sorted((ROOT / "docs").rglob("*.md"))
    return [*PUBLIC_FILES, *docs]


def public_docs_style_errors() -> list[str]:
    """Return actionable style errors for public documentation."""
    errors: list[str] = []
    for path in iter_public_files():
        if not path.exists():
            errors.append(f"missing public documentation file: {path.relative_to(ROOT)}")
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if EM_DASH in line:
                errors.append(
                    f"{path.relative_to(ROOT)}:{line_number}: replace the em dash "
                    "with standard punctuation"
                )
    return errors


def main() -> int:
    errors = public_docs_style_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Public documentation style check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
