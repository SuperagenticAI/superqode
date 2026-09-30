"""Release-policy cases copied from SuperGauge conformance/fixtures."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from superqode.commands.gauge import gauge
from superqode.gauge.levels import highest_level

CASES = json.loads((Path(__file__).parent / "fixtures/gauge-release-policy.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_record_level_and_release_policy(case, tmp_path):
    assert highest_level(case["record"]) == case["level"]
    path = tmp_path / "record.json"
    path.write_text(json.dumps(case["record"]))
    runner = CliRunner()
    validation = runner.invoke(gauge, ["gate", str(path), "--level", "L2", "--quiet"])
    assert validation.exit_code == (0 if case["level"] == "L2" else 1)
    release = runner.invoke(
        gauge, ["gate", str(path), "--level", "L1", "--require-ship", "--quiet"]
    )
    assert release.exit_code == (0 if case["release_permitted"] else 1)
