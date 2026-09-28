"""Generate the publication-safe Harness Hub snapshot used by docs and web."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

from superqode.harness.hub import build_hub_index


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "harness-hub.json"
WEBSITE_OUTPUT_NAME = "superqode-harness-hub.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--website-root",
        type=Path,
        help="also update <root>/src/data/superqode-harness-hub.json",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    payload = build_hub_index(ROOT, public=True)
    rendered = json.dumps(payload, indent=2) + "\n"
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {payload['count']} Hub records to {OUTPUT}")
    if args.website_root is not None:
        website_output = args.website_root.resolve() / "src" / "data" / WEBSITE_OUTPUT_NAME
        if not website_output.parent.is_dir():
            raise SystemExit(f"Website data directory does not exist: {website_output.parent}")
        website_output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {payload['count']} Hub records to {website_output}")


if __name__ == "__main__":
    main()
