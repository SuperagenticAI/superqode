import asyncio
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from superqode.agent.loop import AgentResponse
from superqode.harness import eval as evaluation
from superqode.harness.backends.base import HarnessBackendResult
from superqode.harness.eval_workspace import EvaluationWorkspace
from superqode.harness.loader import harness_spec_to_dict
from superqode.harness.templates import coding_template


def response(text="EXPECTED"):
    return HarnessBackendResult(
        response=AgentResponse(
            content=text,
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        ),
        backend="fixture",
        runtime="fixture",
    )


def dataset(tmp_path, evaluator=None, cases=2):
    paths = []
    for name in ("baseline", "candidate"):
        path = tmp_path / (name + ".yaml")
        path.write_text(yaml.safe_dump(harness_spec_to_dict(coding_template(name=name))))
        paths.append(path)
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": str(i),
                        "prompt": "fix fixture",
                        "split": "held-out",
                        "expect_contains": "EXPECTED",
                        **({"evaluator": evaluator} if evaluator else {}),
                    }
                    for i in range(cases)
                ]
            }
        )
    )
    return dict(
        spec_paths=paths,
        tasks_path=tasks,
        provider="synthetic",
        model="passthrough",
        working_dir=tmp_path,
        live=True,
        eval_split="held-out",
    )


@pytest.mark.asyncio
async def test_every_case_and_variant_has_same_pristine_inputs_and_fresh_kernel(
    tmp_path, monkeypatch
):
    (tmp_path / "source.txt").write_text("dirty local edit")
    observed, instances, paths = [], [], []

    class Backend:
        async def run(self, request):
            root = request.working_directory
            observed.append(((root / "source.txt").read_text(), (root / "leak.txt").exists()))
            paths.append(root)
            (root / "source.txt").write_text("changed by agent")
            (root / "leak.txt").write_text("must not reach another trial")
            return response()

    def factory(_):
        backend = Backend()
        instances.append(backend)
        return backend

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", factory)
    report = await evaluation.run_harness_eval(**dataset(tmp_path))
    assert observed == [("dirty local edit", False)] * 4
    assert len(instances) == 4
    assert len(set(paths)) == 4 and all(not p.exists() for p in paths)
    assert (tmp_path / "source.txt").read_text() == "dirty local edit"
    assert not (tmp_path / "leak.txt").exists()
    for variant in report["variants"]:
        for row in variant["tasks"]:
            assert row["status"] == "passed"
            assert row["workspace"]["snapshot_sha256"] == report["workspace"]["snapshot_sha256"]
            assert row["workspace"]["changed_files"] == ["leak.txt", "source.txt"]


def test_git_fixture_includes_dirty_untracked_deletions_but_not_ignored_files(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("original")
    (tmp_path / "deleted.txt").write_text("delete me")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("dirty")
    (tmp_path / "deleted.txt").unlink()
    (tmp_path / "untracked.txt").write_text("keep")
    (tmp_path / "ignored.txt").write_text("do not copy")
    with EvaluationWorkspace(tmp_path) as workspace:
        with workspace.trial() as root:
            assert (root / "tracked.txt").read_text() == "dirty"
            assert (root / "untracked.txt").read_text() == "keep"
            assert not (root / "deleted.txt").exists()
            assert not (root / "ignored.txt").exists()
            assert (root / ".git").is_dir()
            assert subprocess.check_output(["git", "status", "--porcelain"], cwd=root) == b""
            assert (
                subprocess.check_output(["git", "log", "--format=%s", "-1"], cwd=root).strip()
                == b"Evaluation fixture"
            )


@pytest.mark.asyncio
async def test_cancellation_cleans_trial_without_touching_source(tmp_path, monkeypatch):
    entered = asyncio.Event()
    roots = []

    class Backend:
        async def run(self, request):
            roots.append(request.working_directory)
            (request.working_directory / "partial.txt").write_text("partial")
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda _: Backend())
    task = asyncio.create_task(evaluation.run_harness_eval(**dataset(tmp_path)))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert roots and all(not root.exists() for root in roots)
    assert not (tmp_path / "partial.txt").exists()


def test_external_link_is_rejected_without_reading_its_target(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("outside")
    try:
        (fixture / "link").symlink_to(secret)
    except OSError:
        pytest.skip("Symbolic links unavailable")
    with pytest.raises(ValueError, match="link leaves"):
        with EvaluationWorkspace(fixture):
            pass


def test_missing_git_still_supports_plain_fixture(tmp_path, monkeypatch):
    (tmp_path / "input.txt").write_text("fixture")

    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("superqode.harness.eval_workspace.subprocess.run", missing)
    with EvaluationWorkspace(tmp_path) as workspace:
        with workspace.trial() as root:
            assert (root / "input.txt").read_text() == "fixture"
