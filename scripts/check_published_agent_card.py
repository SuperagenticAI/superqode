#!/usr/bin/env python3
"""Fail when the published A2A Agent Card disagrees with this build.

The Agent Card is served from a static host that is deployed by hand, while
the A2A server itself is deployed automatically.  Nothing connected the two,
so the published card silently fell behind whenever the interface changed.

This check closes that loop.  It compares the checked-in publication artifact
against the card the discovery origin actually serves, and reports exactly
which fields differ so the manual upload is a known task rather than a
forgotten one.

The card no longer carries the package version, so a normal release does not
move it.  A difference reported here means something a caller depends on has
changed: the interface URL, the capabilities, the auth policy, or the skills.

Usage::

    python scripts/check_published_agent_card.py
    python scripts/check_published_agent_card.py --url https://example.com/card.json
    python scripts/check_published_agent_card.py --warn-only
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://super-agentic.ai/.well-known/agent-card.json"
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "examples" / "a2a" / "agent-card.json"
TIMEOUT_SECONDS = 60


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def icon_problem(card: dict[str, Any]) -> str | None:
    """Return a message when the card's iconUrl does not resolve.

    Host platforms render this in their agent gallery, so a dead URL shows as
    a broken image rather than as no image at all. The field is optional, and
    omitting it is better than pointing it at nothing.
    """
    url = card.get("iconUrl")
    if not url:
        return None
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                return f"iconUrl {url} served {content_type or 'no content type'}, not an image"
    except (urllib.error.URLError, TimeoutError) as error:
        return f"iconUrl {url} is not reachable: {error}"
    return None


def differences(published: Any, local: Any, path: str = "") -> list[str]:
    """Return a readable list of field-level differences."""
    if isinstance(published, dict) and isinstance(local, dict):
        found: list[str] = []
        for key in sorted(set(published) | set(local)):
            where = f"{path}.{key}" if path else key
            if key not in published:
                found.append(f"{where}: missing from the published card")
            elif key not in local:
                found.append(f"{where}: published card has an extra value")
            else:
                found.extend(differences(published[key], local[key], where))
        return found
    if isinstance(published, list) and isinstance(local, list):
        if len(published) != len(local):
            return [f"{path}: published has {len(published)} entries, this build has {len(local)}"]
        found = []
        for index, (left, right) in enumerate(zip(published, local)):
            found.extend(differences(left, right, f"{path}[{index}]"))
        return found
    if published != local:
        return [f"{path}: published {published!r}, this build {local!r}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Discovery URL to check")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Report differences without failing (useful when the host is unreachable)",
    )
    args = parser.parse_args()

    local = json.loads(args.artifact.read_text(encoding="utf-8"))

    icon = icon_problem(local)
    if icon is not None:
        print(icon)
        print("Point iconUrl at an image that exists, or remove the field.")
        if not args.warn_only:
            return 1

    try:
        published = fetch(args.url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"Could not read the published Agent Card at {args.url}: {error}")
        # A cold-starting or unreachable host is not a reason to fail a build.
        return 0

    found = differences(published, local)
    if not found:
        print(f"Published Agent Card at {args.url} matches {args.artifact.name}.")
        return 0

    print(f"Published Agent Card at {args.url} differs from {args.artifact.name}:")
    for line in found:
        print(f"  {line}")
    print()
    print("Regenerate and re-upload the card:")
    print("  superqode serve a2a --public-url <interface-url> --token <value> \\")
    print(f"    --export-agent-card {args.artifact}")
    print(f"Then upload that file to {args.url}.")
    return 0 if args.warn_only else 1


if __name__ == "__main__":
    sys.exit(main())
