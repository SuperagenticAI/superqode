"""Keep the reviewed mobile inventory honest as Mac navigation evolves."""

import json
from pathlib import Path
import re
import runpy

# Mac-only Advanced controls added after the current iOS review submission.
# Do not alter that submitted app or claim it implements this workflow. Every
# other Mac section must still be covered, and this exclusion must be removed
# when a later companion inventory explicitly accounts for it.
MAC_ONLY_SECTIONS = {
    "Local harnesses": "Advanced local harness configuration and launch controls exist only in the Mac UI.",
}


def test_mobile_inventory_covers_current_mac_navigation_and_tools():
    root = Path(__file__).resolve().parents[1]
    audit = runpy.run_path(str(root / "apps/ios/scripts/audit-parity.py"))
    # The frozen auditor assumes all Mac sections existed at mobile submission.
    # Retain its inventory validations with an exact, explained Mac-only delta.
    entries = json.loads((root / "apps/ios/SuperQode/FeatureParity.json").read_text())
    mac = root / "apps/macos/Sources/SuperQode"
    names = re.search(
        r"static let names = \[(.*?)\]", (mac / "SuperQodeApp.swift").read_text(), re.S
    )
    assert names is not None
    sections = set(re.findall(r'"([^"]+)"', names[1]))
    categories = re.search(
        r"private let categories = \[(.*?)\]", (mac / "ToolsView.swift").read_text(), re.S
    )
    assert categories is not None
    tools = set(re.findall(r'"([^"]+)"\s*:', categories[1]))
    workflows = (
        (root / "apps/ios/SuperQode/CompanionFeatures.swift")
        .read_text()
        .split("struct DeveloperShortcuts")[0]
    )
    workflow_names = set(re.findall(r'\w+ = "([^"]+)"', workflows))
    covered = {name for item in entries for name in item["mac_sections"]}
    assert sections - covered == MAC_ONLY_SECTIONS.keys(), (
        "Review every new Mac-only section explicitly"
    )
    assert not covered - sections, "Mobile inventory names a removed Mac section"
    assert all(MAC_ONLY_SECTIONS.values())
    assert {name for item in entries for name in item["mac_tools"]} == tools
    assert len({item["id"] for item in entries}) == len(entries), "Duplicate feature IDs"
    for item in entries:
        assert item["parity"] in audit["LABELS"], item["id"]
        assert item.get("workflow") in workflow_names | {None}, item["id"]
        assert item["macRoute"] and item["detail"], item["id"]
        assert item["parity"] != "mac_only" or not item.get("workflow"), item["id"]
    # Validate the submitted document against precisely its inventoried areas,
    # not against a newly expanded Mac-only feature count.
    assert (root / "apps/ios/PARITY.md").read_text() == audit["document"](entries, covered, tools)
    assert any(item["parity"] == "mac_only" for item in entries)
    assert next(item for item in entries if item["id"] == "pro")["parity"] == "preview"
