"""Small headless entry point for generated Factory service manifests."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to authorize the pinned WorkOrder's model/tool execution")
    from .operations import run_deployment

    print(json.dumps(run_deployment(args.manifest), indent=2))


if __name__ == "__main__":
    main()
