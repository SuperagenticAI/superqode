import asyncio
import hashlib
from pathlib import Path
import sys
import time

import pytest

from superqode.harness import eval as evaluation
from superqode.harness.acceptance import heldout_acceptance
from superqode.harness.eval_workspace import EvaluationWorkspace
from superqode.harness.evaluators import evaluate_content, validate_evaluator
from superqode.harness.repository_grader import _command, evaluate
from test_harness_eval_isolation import dataset, response


@pytest.mark.asyncio
async def test_agent_text_cannot_override_independent_outcomes(tmp_path, monkeypatch):
    (tmp_path / "answer.txt").write_text("wrong")
    config = {
        "type": "repository",
        "commands": [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; assert Path('answer.txt').read_text() == 'correct'",
                ]
            }
        ],
        "files": [{"path": "answer.txt", "contains": "correct"}],
    }

    class Backend:
        async def run(self, request):
            if request.spec.name == "candidate":
                (request.working_directory / "answer.txt").write_text("correct")
            return response("EXPECTED. All tests pass, trust me.")

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda _: Backend())
    report = await evaluation.run_harness_eval(**dataset(tmp_path, config, cases=1))
    before, after = [v["tasks"][0] for v in report["variants"]]
    assert before["status"] == "failed"
    assert after["status"] == "passed"
    evidence = after["evaluation"]["evidence"]
    assert evidence["commands"][0]["returncode"] == 0
    assert evidence["files"][0]["passed"]
    assert len(evidence["grader_sha256"]) == 64
    assert heldout_acceptance(report)["accepted"]
    assert (tmp_path / "answer.txt").read_text() == "wrong"


@pytest.mark.asyncio
async def test_tampering_with_tests_fails_before_commands_execute(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "check.py").write_text("assert False")
    marker = tmp_path / "must-not-run"
    config = {
        "type": "repository",
        "commands": [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path({str(marker)!r}).touch()",
                ]
            }
        ],
    }
    with EvaluationWorkspace(tmp_path) as fixture:
        with fixture.trial() as root:
            (root / "tests/check.py").write_text("pass")
            result = await evaluate(config, root, fixture.manifest, fixture.digest)
    assert result.status == "failed"
    assert result.evidence["protected_changes"] == ["tests/check.py"]
    assert not marker.exists()


@pytest.mark.asyncio
async def test_empty_and_absent_file_assertions_and_required_patch(tmp_path):
    (tmp_path / "empty.txt").touch()
    with EvaluationWorkspace(tmp_path) as fixture:
        with fixture.trial() as root:
            config = {
                "type": "repository",
                "files": [
                    {"path": "empty.txt", "sha256": hashlib.sha256(b"").hexdigest()},
                    {"path": "deleted.txt", "exists": False},
                ],
            }
            assert (
                await evaluate(config, root, fixture.manifest, fixture.digest)
            ).status == "passed"
            assert (
                await evaluate(
                    {**config, "require_changes": True}, root, fixture.manifest, fixture.digest
                )
            ).status == "failed"


@pytest.mark.asyncio
async def test_repository_grading_without_fixture_never_falls_back_to_text():
    result = await evaluate_content(
        "ALL TESTS PASS", {"evaluator": {"type": "repository", "files": [{"path": "answer.txt"}]}}
    )
    assert result.status == "ungraded"


@pytest.mark.parametrize(
    "config",
    [
        {"commands": []},
        {"commands": ["python check.py"]},
        {"commands": [{"argv": [], "timeout_seconds": 1}]},
        {"commands": [{"argv": ["python"], "timeout_seconds": float("nan")}]},
        {"files": [{"path": "../outside"}]},
        {"files": [{"path": "/absolute"}]},
        {"files": [{"path": "C:/outside"}]},
        {"files": [{"path": "file", "exists": "yes"}]},
        {"files": [{"path": "file", "sha256": "x"}]},
    ],
)
def test_invalid_grader_configuration_is_rejected_before_any_model_call(config):
    with pytest.raises(ValueError):
        validate_evaluator({"evaluator": {"type": "repository", **config}})


@pytest.mark.asyncio
async def test_command_timeout_and_output_are_bounded(tmp_path):
    result = await _command(
        {"argv": [sys.executable, "-c", "print('x' * 100000)"], "timeout_seconds": 2}, tmp_path
    )
    assert result["passed"] and result["output_truncated"]
    assert len(result["output"]) <= 16000
    started = time.monotonic()
    result = await _command(
        {"argv": [sys.executable, "-c", "import time; time.sleep(10)"], "timeout_seconds": 0.1},
        tmp_path,
    )
    assert result["timed_out"] and not result["passed"]
    assert time.monotonic() - started < 3


@pytest.mark.asyncio
async def test_cancelling_grader_stops_its_process(tmp_path):
    marker = tmp_path / "alive"
    task = asyncio.create_task(
        _command(
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; Path('alive').touch(); time.sleep(20); Path('late').touch()",
                ]
            },
            tmp_path,
        )
    )
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "late").exists()
