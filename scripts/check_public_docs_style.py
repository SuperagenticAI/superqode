#!/usr/bin/env python3
"""Check public documentation for prohibited punctuation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (ROOT / "README.md", ROOT / "mkdocs.yml", ROOT / "pyproject.toml")
PROHIBITED_DASHES = {
    chr(0x2013): "en dash",
    chr(0x2014): "em dash",
}
PROHIBITED_FORMULAIC_PHRASES = {
    "why this matters": "replace the formulaic heading with a technical heading",
    "how it works": "replace the generic heading with a specific technical heading",
    "the bottom line": "replace the formulaic phrase with a specific conclusion",
    "game-changing": "replace promotional wording with a measurable description",
    "revolutionary": "replace promotional wording with a technical description",
    "seamlessly": "state the supported integration behavior directly",
    "effortlessly": "state the required operation directly",
    "unlock the power": "describe the capability directly",
    "in today's fast-paced": "remove the generic introductory phrase",
    "whether you're": "replace the generic audience construction with scope",
    "more than just": "describe the additional capability directly",
    "supercharge": "replace promotional wording with a technical description",
}


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
            for character, name in PROHIBITED_DASHES.items():
                if character in line:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: replace the {name} "
                        "with standard punctuation"
                    )
            normalized = line.casefold()
            for phrase, guidance in PROHIBITED_FORMULAIC_PHRASES.items():
                if phrase in normalized:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {guidance}; found {phrase!r}"
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
