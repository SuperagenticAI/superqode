from pathlib import Path
import sys

import pytest
import yaml

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service.experiments import inspect_suite, reviewed_suite


def write_suite(root):
    path = root / "suite.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "repair",
                        "prompt": "Repair the fixture",
                        "split": "held-out",
                        "evaluator": {
                            "type": "repository",
                            "commands": [{"argv": [sys.executable, "check.py"]}],
                            "files": [{"path": "answer.txt"}],
                        },
                    }
                ]
            }
        )
    )
    return path


def test_native_suite_review_exposes_commands_and_pins_exact_reviewed_content(desktop):
    service, project, root = desktop
    path = write_suite(root)
    params = {"project": project["id"], "tasks": str(path), "live": True}
    inspection = service.dispatch("evals.inspect", params)
    assert inspection["repository_checks"][0]["file_assertions"] == ["answer.txt"]
    assert "check.py" in inspection["repository_checks"][0]["commands"][0]
    with pytest.raises(ValueError, match="Review the repository"):
        reviewed_suite(root, params)
    reviewed = {**params, "tasks_hash": inspection["tasks_hash"]}
    assert reviewed_suite(root, reviewed) == path.read_text()
    path.write_text(path.read_text().replace("check.py", "another-check.py"))
    with pytest.raises(ValueError, match="changed since review"):
        reviewed_suite(root, reviewed)


def test_repository_grader_diagnostics_do_not_execute_the_commands(desktop):
    service, project, root = desktop
    path = write_suite(root)
    (root / "check.py").write_text("raise RuntimeError('must not run during inspection')")
    assert (
        service.dispatch("evals.inspect", {"project": project["id"], "tasks": str(path)})[
            "task_count"
        ]
        == 1
    )
