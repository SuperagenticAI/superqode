#!/usr/bin/env python3
"""Validate the product-surface contract required before the 0.3.0 graduation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]


def candidate_errors(expected_version: str | None = None) -> list[str]:
    from superqode import __version__
    from superqode.governance import default_project_policy
    from superqode.main import cli_main

    errors: list[str] = []
    if expected_version and __version__ != expected_version:
        errors.append(f"package version is {__version__}, expected {expected_version}")

    required_commands = {
        "policy": {"init", "show", "explain"},
        "work": {"worker", "watch", "usage", "policy", "prepare", "merge", "rollback"},
        "harness": {"bench", "bench-verify", "promote", "eval", "audit-candidate"},
    }
    for group_name, expected in required_commands.items():
        group = cli_main.commands.get(group_name)
        if not isinstance(group, click.Group):
            errors.append(f"missing command group: {group_name}")
            continue
        missing = sorted(expected - set(group.commands))
        if missing:
            errors.append(f"{group_name} is missing commands: {', '.join(missing)}")
    harness = cli_main.commands.get("harness")
    promote = harness.commands.get("promote") if isinstance(harness, click.Group) else None
    expected_promote = {"stage", "canary", "activate", "rollback", "status", "select"}
    if not isinstance(promote, click.Group):
        errors.append("missing harness promote group")
    else:
        missing = sorted(expected_promote - set(promote.commands))
        if missing:
            errors.append(f"harness promote is missing: {', '.join(missing)}")

    defaults = default_project_policy().get("guardrails") or {}
    if defaults.get("shell_env") != "filter-secrets":
        errors.append("project policy does not default to secret-filtered shells")
    if defaults.get("network_strict") is not True:
        errors.append("project policy does not default to strict network destinations")
    if defaults.get("block_model_credentials") is not True:
        errors.append("project policy does not block model-supplied credential headers")

    required_docs = (
        "docs/advanced/workorders.md",
        "docs/advanced/contextual-policy.md",
        "docs/advanced/harnessbench.md",
        "docs/advanced/harness-promotion.md",
        "docs/advanced/release-0.2.30.md",
        "docs/cli-reference/work-commands.md",
        "docs/cli-reference/policy-commands.md",
    )
    for relative in required_docs:
        if not (ROOT / relative).is_file():
            errors.append(f"missing release documentation: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", help="Expected package version")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors = candidate_errors(args.version)
    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}")
    else:
        print("0.2.30/0.3.0 candidate surface is complete.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
