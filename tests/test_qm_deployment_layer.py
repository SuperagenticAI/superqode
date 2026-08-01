from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
LAYER = ROOT / "examples" / "qm-deployment-layer" / "sandbox"
TOOL_DIR = LAYER / "tools" / "superqode"


def test_qm_tool_descriptor_matches_contract_v1_invariants():
    descriptor = json.loads((TOOL_DIR / "tool.json").read_text())

    assert descriptor["id"] == TOOL_DIR.name
    assert descriptor["install"]["binary"] == descriptor["id"]
    assert descriptor["label"]
    assert descriptor["advertise"]
    assert all(item and "*" not in item for item in descriptor["egress"])
    assert all(rule["decision"] in {"deny", "require_approval"} for rule in descriptor["approvals"])
    for rule in descriptor["approvals"]:
        if "pattern" in rule:
            assert rule["pattern"].startswith(r"\bsuperqode\b")


def test_qm_skill_has_required_frontmatter():
    skill = (LAYER / "skills" / "superqode-harness" / "SKILL.md").read_text()

    assert skill.startswith("---\n")
    frontmatter = skill.split("---", 2)[1]
    assert "name: superqode-harness" in frontmatter
    assert "description:" in frontmatter


def test_qm_superqode_wrapper_delegates_without_exposing_credentials(tmp_path: Path):
    fake = tmp_path / "fake-superqode"
    fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    fake.chmod(0o755)
    wrapper = TOOL_DIR / "superqode"
    env = os.environ.copy()
    env["SUPERQODE_EXECUTABLE"] = str(fake)

    completed = subprocess.run(
        [str(wrapper), "harness", "validate", "--spec", "harness.yaml"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        "harness",
        "validate",
        "--spec",
        "harness.yaml",
    ]
