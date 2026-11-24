"""Keep the reviewed mobile inventory honest as Mac navigation evolves."""

import json
from pathlib import Path
import re
import runpy


def test_mobile_inventory_covers_current_mac_navigation_and_tools():
    root = Path(__file__).resolve().parents[1]
    audit = runpy.run_path(str(root / "apps/ios/scripts/audit-parity.py"))
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
    assert sections == covered, f"Review every Mac section explicitly: {sections ^ covered}"
    assert {name for item in entries for name in item["mac_tools"]} == tools
    assert len({item["id"] for item in entries}) == len(entries), "Duplicate feature IDs"
    for item in entries:
        assert item["parity"] in audit["LABELS"], item["id"]
        assert item.get("workflow") in workflow_names | {None}, item["id"]
        assert item["macRoute"] and item["detail"], item["id"]
        assert item["parity"] != "mac_only" or not item.get("workflow"), item["id"]
    assert (root / "apps/ios/PARITY.md").read_text() == audit["document"](entries, sections, tools)
    assert any(item["parity"] == "mac_only" for item in entries)
    assert next(item for item in entries if item["id"] == "factory_studio")["workflow"] == "Factory"
    assert next(item for item in entries if item["id"] == "pro")["parity"] == "preview"
