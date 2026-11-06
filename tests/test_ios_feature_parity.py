"""Keep the mobile feature inventory honest as Mac navigation evolves."""

from pathlib import Path
import runpy


def test_mobile_inventory_covers_current_mac_navigation_and_tools():
    root = Path(__file__).resolve().parents[1]
    audit = runpy.run_path(str(root / "apps/ios/scripts/audit-parity.py"))
    entries, sections, tools = audit["inventory"]()
    assert (root / "apps/ios/PARITY.md").read_text() == audit["document"](entries, sections, tools)
    assert any(item["parity"] == "mac_only" for item in entries)
    assert next(item for item in entries if item["id"] == "pro")["parity"] == "preview"
