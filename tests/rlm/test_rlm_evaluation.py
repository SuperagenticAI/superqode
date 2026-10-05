"""Pilot reporting must distinguish execution smoke tests from model quality."""

import json
import os
import shutil

import pytest

from superqode.rlm.evaluation import load_cases, run_pilot


def case(solution="2"):
    return {
        "id": "fix",
        "prompt": "Set value to 2",
        "files": {"target.py": "value = 1"},
        "smoke_solution": {"target.py": f"value = {solution}"},
        "grader": "from target import value; assert value == 2",
    }


@pytest.mark.asyncio
async def test_independent_grader_rejects_incorrect_edit_and_cost_claim(tmp_path):
    report = await run_pilot(
        [case("3")], output=tmp_path / "report", profiles=["python"], repetitions=1
    )
    assert report["profiles"]["python"]["passed"] == 0
    assert report["profiles"]["python"]["cost_per_accepted_task"] is None
    assert "No model quality" in report["claim"]
    attempt = json.loads((tmp_path / "report/attempts.jsonl").read_text())
    assert "AssertionError" in attempt["grader_output"]
    assert attempt["task_sha256"] and attempt["source_sha256"]
    assert attempt["usage"]["total"]["calls"] == 2


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="POSIX Bash required")
async def test_nested_file_edits_work_across_both_tool_surfaces(tmp_path):
    task = case()
    task["smoke_solution"] = {"new/target.py": "value = 2"}
    task["grader"] = (
        "from pathlib import Path; assert Path('new/target.py').read_text() == 'value = 2'"
    )
    report = await run_pilot(
        [task], output=tmp_path / "report", profiles=["python", "hybrid"], repetitions=1
    )
    assert all(v["passed"] == 1 for v in report["profiles"].values())


@pytest.mark.asyncio
async def test_live_pilot_requires_explicit_model_and_limits(tmp_path):
    with pytest.raises(ValueError, match="Live pilots require"):
        await run_pilot([case()], output=tmp_path / "live", live=True)
    assert not (tmp_path / "live").exists()


def test_fixture_paths_cannot_escape(tmp_path):
    task = case()
    task["files"] = {"../outside": "data"}
    source = tmp_path / "tasks.json"
    source.write_text(json.dumps({"tasks": [task]}))
    with pytest.raises(ValueError, match="within"):
        load_cases(source)
