#!/usr/bin/env python3
"""Check mobile inventory coverage against actual Mac navigation and tool areas."""

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
IOS = ROOT / "apps/ios"
MAC = ROOT / "apps/macos/Sources/SuperQode"
LABELS = {
    "available": "Available",
    "partial": "Partial",
    "mac_only": "Mac only",
    "preview": "Mac preview",
}


def inventory():
    entries = json.loads((IOS / "SuperQode/FeatureParity.json").read_text())
    source = (MAC / "SuperQodeApp.swift").read_text()
    names = re.search(r"static let names = \[(.*?)\]", source, re.S)
    sections = set(re.findall(r'"([^"]+)"', names[1]))
    tools = (MAC / "ToolsView.swift").read_text()
    categories = re.search(r"private let categories = \[(.*?)\]", tools, re.S)
    tool_names = set(re.findall(r'"([^"]+)"\s*:', categories[1]))
    workflows = (
        (IOS / "SuperQode/CompanionFeatures.swift")
        .read_text()
        .split("struct DeveloperShortcuts")[0]
    )
    workflow_names = set(re.findall(r'\w+ = "([^"]+)"', workflows))
    assert len({item["id"] for item in entries}) == len(entries), "Duplicate feature IDs"
    covered_sections = {name for item in entries for name in item["mac_sections"]}
    covered_tools = {name for item in entries for name in item["mac_tools"]}
    assert sections == covered_sections, (
        f"Mac section coverage differs: {sections ^ covered_sections}"
    )
    assert tool_names == covered_tools, f"Mac tool coverage differs: {tool_names ^ covered_tools}"
    for item in entries:
        assert item["parity"] in LABELS, item["id"]
        assert item.get("workflow") in workflow_names | {None}, item["id"]
        assert item["macRoute"] and item["detail"], item["id"]
        assert item["parity"] != "mac_only" or not item.get("workflow"), item["id"]
    return entries, sections, tool_names


def document(entries, sections, tools):
    lines = [
        "# macOS and iOS feature audit",
        "",
        "Generated from `SuperQode/FeatureParity.json`, the same inventory used by the iOS All features screen.",
        "",
        f"The inventory accounts for all {len(sections)} Mac navigation areas and {len(tools)} typed Tools categories. This is inventory coverage, not a claim of complete mobile functionality.",
        "",
        "## Finding",
        "",
        "Full macOS parity is not implemented. Daily coding, contextual review, explicit approvals, reference files, evaluation and staged optimization are available on the phone. Several are partial: custom evaluation/candidate setup, local-model lifecycle, harness authoring, routing/tuning, queue management, checkpoint restoration, terminal/Git administration and notifications still require additional work.",
        "",
        "The home screen promotes Code, Review, Evaluate and Optimize. Harness Lab opens on Evaluate & improve, with separate evaluation and optimization setup. WorkOrders, queues and checkpoints are discoverable in project tools; every major workflow is searchable in All features with its actual availability.",
        "",
        "## Workflow comparison",
        "",
    ]
    for group in dict.fromkeys(item["group"] for item in entries):
        lines.extend(
            [
                f"### {group}",
                "",
                "| Workflow | Phone parity | Current behavior and gaps | Mac entry point |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in entries:
            if item["group"] == group:
                lines.append(
                    f"| {item['title']} | {LABELS[item['parity']]} | {item['detail']} | {item['macRoute']} |"
                )
        lines.append("")
    lines.extend(
        [
            "## Next implementation priorities",
            "",
            "1. Complete the coding loop: image uploads, file editing, revision-bound queue management and guarded checkpoint restoration. Preserve project scope and explicit device permissions.",
            "2. Complete the harness lifecycle: custom suites and candidate selection, Studio authoring/version history, routing/tuning, evidence export and separately authorized adoption/promotion. A displayed score never authorizes a release.",
            "3. Add scoped Mac administration: local-engine/model lifecycle and installer/readiness feedback, supported subscription sign-in, MCP/skills configuration and external-session import. Provider credentials must not become readable through generic remote RPCs.",
            "4. Add private interactive terminal/Git workflows only with their own reviewed authorization model. Do not expose the existing generic CLI/tool runner just to make every button callable.",
            "5. Design background notifications within the no-hosted-SuperQode-service constraint. Foreground polling is implemented; it is not background push.",
            "",
            "## Verification and release qualification",
            "",
            "Native availability and data projections are exercised with simulator/UI tests and account-free desktop boundary tests. A physical Mac/iPhone still needs private HTTPS, cellular Tailscale access, camera pairing, restart/reconnect, sleep/wake and revocation validation. Signing/distribution require the owner's Apple account. The existing Mac navigation performance gate has produced inconsistent results and remains a release qualification issue.",
            "",
            "No full-parity, universal external-app compatibility, finished Pro feature or bug-free public-release claim is justified by this inventory. Mac-only entries are instructions, not hidden phone implementations.",
            "",
            "## Source evidence",
            "",
            "- [Mac navigation](../macos/Sources/SuperQode/WorkspaceNavigation.swift) and [section names](../macos/Sources/SuperQode/SuperQodeApp.swift).",
            "- [Typed Tools categories](../macos/Sources/SuperQode/ToolsView.swift). These are CLI-backed forms, not separate native phone implementations.",
            "- [Mac evaluation comparison](../macos/Sources/SuperQode/EvaluationComparisonView.swift), [review](../macos/Sources/SuperQode/ReviewWorkspaceView.swift), [queue](../macos/Sources/SuperQode/TaskQueueView.swift), [WorkOrders](../macos/Sources/SuperQode/WorkOrderBoardView.swift) and [checkpoints](../macos/Sources/SuperQode/CheckpointsView.swift).",
            "- [Explicit companion RPC surface](../../src/superqode/desktop_service/remote_rpc.py) and [bounded project projections](../../src/superqode/desktop_service/remote_project.py).",
            "- [Source build and pairing](README.md), [signing and distribution](RELEASE.md).",
            "",
            "Regenerate with `python apps/ios/scripts/audit-parity.py`; validate coverage and document freshness with `python apps/ios/scripts/audit-parity.py --check`.",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    entries, sections, tools = inventory()
    expected = document(entries, sections, tools)
    target = IOS / "PARITY.md"
    if args.check:
        assert target.read_text() == expected, "Regenerate apps/ios/PARITY.md"
    else:
        target.write_text(expected)
    print(
        f"Feature inventory: {len(entries)} workflows cover {len(sections)} Mac areas and {len(tools)} Tools categories"
    )


if __name__ == "__main__":
    main()
