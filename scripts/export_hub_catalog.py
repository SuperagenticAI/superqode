"""Generate the publication-safe Harness Hub snapshot used by docs and web."""

from __future__ import annotations

import json
from pathlib import Path

from superqode.harness.hub import build_hub_index


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "harness-hub.json"


def main() -> None:
    payload = build_hub_index(ROOT, public=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {payload['count']} Hub records to {OUTPUT}")


if __name__ == "__main__":
    main()
