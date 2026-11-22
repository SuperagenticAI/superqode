"""Small, deliberately faulty JSON CLI for live Factory trials (standard library only)."""

import json
import sys


def totals(rows):
    result = {}
    for row in rows:
        result[row["category"]] = row["amount"]
    return result


def active(items):
    return [item for item in items if item.get("active", True)]


def ordered(names):
    return sorted(names)


def main():
    operation, payload = sys.argv[1:]
    handler = {"totals": totals, "active": active, "ordered": ordered}[operation]
    print(json.dumps(handler(json.loads(payload)), sort_keys=True))


if __name__ == "__main__":
    main()
