"""Tests for 5-dimension Merge Risk assessment, built-in Factory skills, and Visual Proof."""

from types import SimpleNamespace

import pytest
import yaml

from superqode.factory.definition import validate_definition
from superqode.factory.merge_risk import assess_merge_risk
from superqode.factory.skill_templates import (
    list_skill_templates,
    render_skill_template,
    scaffold_skill,
)
from superqode.factory.skills import parse_skill
from superqode.factory.templates import factory_template
from superqode.factory.visual_proof import build_handoff_markdown, collect_visual_proof


def test_merge_risk_scores_isolated_tested_change_low():
    diff = """diff --git a/src/superqode/helper.py b/src/superqode/helper.py
+++ b/src/superqode/helper.py
+def add(a, b):
+    return a + b
diff --git a/tests/test_helper.py b/tests/test_helper.py
+++ b/tests/test_helper.py
+def test_add():
+    assert add(1, 2) == 3
"""
    risk = assess_merge_risk(
        goal="Add helper arithmetic function",
        diff_text=diff,
        verification={"state": "passed"},
    )
    assert risk["advisory"] is True
    assert risk["overall"] == "low"
    assert [c["id"] for c in risk["categories"]] == [
        "alignment",
        "impact",
        "verification",
        "rollback",
        "error_detection",
    ]
    assert "Merge Risk Assessment (**LOW**)" in risk["markdown"]


def test_merge_risk_flags_sensitive_paths_schema_swallowed_errors_and_missing_ui_proof():
    diff = """diff --git a/src/auth/permissions.py b/src/auth/permissions.py
+++ b/src/auth/permissions.py
+try:
+    check()
+except Exception: pass
+try:
+    other()
+except ValueError: pass
diff --git a/db/migrations/001_schema.sql b/db/migrations/001_schema.sql
+++ b/db/migrations/001_schema.sql
+ALTER TABLE users ADD COLUMN role TEXT;
diff --git a/apps/macos/Sources/SuperQode/SidebarView.swift b/apps/macos/Sources/SuperQode/SidebarView.swift
+++ b/apps/macos/Sources/SuperQode/SidebarView.swift
+Text("Updated")
"""
    risk = assess_merge_risk(
        goal="Update sidebar label",
        diff_text=diff,
        verification={"state": "passed"},
        visual_proof={"items": [], "summary": ""},
    )
    by_id = {c["id"]: c for c in risk["categories"]}
    assert risk["overall"] == "high"
    assert by_id["impact"]["risk"] == "high"
    assert by_id["rollback"]["risk"] == "high"
    assert by_id["error_detection"]["risk"] == "high"
    assert by_id["verification"]["risk"] == "medium"
    assert risk["gaps"]


def test_builtin_factory_skills_parse_and_bind_cleanly(tmp_path):
    catalog = list_skill_templates()
    assert {item["id"] for item in catalog} == {"merge-risk", "ui-verification"}

    for skill_id, preset in (
        ("merge-risk", ""),
        ("ui-verification", "web"),
        ("ui-verification", "macos"),
        ("ui-verification", "cli"),
    ):
        rel, content = render_skill_template(skill_id, preset=preset)
        meta, body = parse_skill(content)
        assert meta["name"] == skill_id
        assert body
        assert rel.endswith("SKILL.md")

    base_yaml = yaml.safe_dump(factory_template("triage-spec-build"), sort_keys=False)
    res1 = scaffold_skill(tmp_path, "merge-risk", yaml_text=base_yaml)
    assert res1["created"] is True
    assert (tmp_path / "skills/merge-risk/SKILL.md").is_file()
    res2 = scaffold_skill(tmp_path, "ui-verification", preset="macos", yaml_text=res1["yaml"])
    assert res2["created"] is True
    assert (tmp_path / "skills/ui-verification/SKILL.md").is_file()
    data = yaml.safe_load(res2["yaml"])
    validate_definition(data)
    assert "skill-merge-risk" in data["data_context"]["files"]
    assert "skill-ui-verification" in data["data_context"]["files"]
    assert set(data["inference"]["harnesses"]["coder"]["skills"]) == {
        "skill-merge-risk",
        "skill-ui-verification",
    }

    with pytest.raises(ValueError, match="Unknown built-in"):
        render_skill_template("does-not-exist")


def test_collect_visual_proof_ignores_symlinks_and_formats_handoff_markdown(tmp_path):
    proof_dir = tmp_path / ".superqode" / "factory-proof" / "wo-1"
    proof_dir.mkdir(parents=True)
    shot = proof_dir / "01-result.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    ignored = proof_dir / "notes.txt"
    ignored.write_text("not media", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\noutside")
    (proof_dir / "02-link.png").symlink_to(outside)

    order = SimpleNamespace(
        work_order_id="wo-1",
        artifacts=[
            SimpleNamespace(
                content="Implemented menu.\n\n## Visual proof\n\nWalked View menu -> Expand All Folders.\n"
            )
        ],
    )
    proof = collect_visual_proof(tmp_path, order)
    assert [item["name"] for item in proof["items"]] == ["01-result.png"]
    assert "Expand All Folders" in proof["summary"]

    risk = assess_merge_risk(
        goal="Add Expand All Folders",
        files=["apps/macos/Sources/SuperQode/SidebarView.swift"],
        verification={"state": "passed"},
        visual_proof=proof,
    )
    assert {c["id"]: c["risk"] for c in risk["categories"]}["verification"] == "low"

    md = build_handoff_markdown(
        goal="Add Expand All Folders",
        status="completed",
        supergauge_verdict="ship",
        merge_risk=risk,
        visual_proof=proof,
    )
    assert "# Factory Handoff: Add Expand All Folders" in md
    assert "## Merge Risk Assessment" in md
    assert "## Visual proof" in md
    assert "01-result.png" in md
