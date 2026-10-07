"""Exercise contamination, source preservation and immutable recovery identities."""

from pathlib import Path
from types import SimpleNamespace
import subprocess
import asyncio

import pytest

from superqode.harness import eval as evaluation
from superqode.harness.bench import HarnessBenchManifest, run_harness_bench
from superqode.harness.eval_workspace import snapshot_eval_workspace


def fixture_tree(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "input.txt").write_text("original")
    specs = []
    for name in ("baseline", "candidate"):
        path = tmp_path / f"{name}.yaml"
        path.write_text(f"name: {name}\n")
        specs.append(path)
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text("tasks:\n  - id: one\n    prompt: inspect\n  - id: two\n    prompt: inspect\n")
    return project, specs, tasks


def fake_execution(monkeypatch, visits):
    async def initialize(spec, **kwargs):
        return SimpleNamespace(calls=0)

    async def execute(**kwargs):
        directory = Path(kwargs["working_dir"])
        kernel = kwargs["kernel"]
        kernel.calls += 1
        visits.append((directory, kwargs["spec"].name, kwargs["task"]["id"]))
        assert kernel.calls == 1
        assert (directory / "input.txt").read_text() == "original"
        assert not (directory / "marker").exists()
        assert Path(kwargs["spec"].context.session_storage).is_relative_to(directory)
        (directory / "input.txt").write_text("changed")
        (directory / "marker").write_text("private to this case")
        return {
            "id": kwargs["task"]["id"],
            "status": "passed",
            "score": 1,
            "duration_seconds": 0,
            "usage": {},
        }

    monkeypatch.setattr(evaluation, "init_harness", initialize)
    monkeypatch.setattr(evaluation, "_run_eval_task", execute)


async def test_every_task_variant_and_repetition_has_a_fresh_workspace(monkeypatch, tmp_path):
    project, specs, tasks = fixture_tree(tmp_path)
    visits = []
    fake_execution(monkeypatch, visits)
    manifest = HarnessBenchManifest(
        "isolation",
        str(tasks),
        tuple(map(str, specs)),
        "test",
        "test-model",
        working_dir=str(project),
        repetitions=2,
        live=True,
        manifest_dir=str(tmp_path),
    )
    output = project / "results"
    await run_harness_bench(manifest, output_dir=output)
    assert len(visits) == 8
    assert len({directory for directory, _, _ in visits}) == 8
    assert all(not directory.exists() for directory, _, _ in visits)
    assert (project / "input.txt").read_text() == "original"
    assert not (project / "marker").exists()
    import json

    raw = [json.loads(path.read_text()) for path in sorted((output / "raw").glob("*.json"))]
    digests = {
        case["workspace_fixture"]["fixture_digest"]
        for run in raw
        for variant in run["result"]["variants"]
        for case in variant["tasks"]
    }
    assert len(digests) == 1
    assert (
        raw[0]["result"]["variants"][0]["tasks"][0]["execution"]["requested_backend"] == "builtin"
    )
    assert "superqode-eval-case-" not in json.dumps(raw)


async def test_benchmark_freezes_source_once_even_if_source_changes(monkeypatch, tmp_path):
    project, specs, tasks = fixture_tree(tmp_path)
    seen = []

    async def runner(**kwargs):
        directory = Path(kwargs["working_dir"])
        assert not (directory / "results").exists()
        seen.append((directory / "input.txt").read_text())
        (directory / "input.txt").write_text("candidate mutation")
        (project / "input.txt").write_text("concurrent developer edit")
        return {"status": "passed", "task_count": 1, "variants": []}

    manifest = HarnessBenchManifest(
        "frozen",
        str(tasks),
        tuple(map(str, specs)),
        "test",
        "model",
        working_dir=str(project),
        repetitions=2,
        live=True,
    )
    await run_harness_bench(manifest, output_dir=project / "results", eval_runner=runner)
    assert seen == ["original", "original"]
    assert (project / "input.txt").read_text() == "concurrent developer edit"


async def test_real_kernel_marks_evaluation_backend_requests_disposable(monkeypatch, tmp_path):
    from superqode.agent.loop import AgentResponse
    from superqode.harness.backends.base import HarnessBackendResult

    project, specs, tasks = fixture_tree(tmp_path)
    requests = []

    class Backend:
        async def run(self, request):
            requests.append(request)
            assert request.metadata["_evaluation_disposable"] is True
            assert request.working_directory != project
            assert (request.working_directory / "input.txt").read_text() == "original"
            return HarnessBackendResult(
                AgentResponse("fixture done", [], 0, 1, "complete"), "builtin", "builtin"
            )

    monkeypatch.setattr("superqode.harness.kernel.create_harness_backend", lambda name: Backend())
    result = await evaluation.run_harness_eval(
        spec_paths=specs,
        tasks_path=tasks,
        provider="test",
        model="model",
        working_dir=project,
        live=True,
    )
    assert len(requests) == 4
    assert result["status"] == "passed"


async def test_failure_cleans_up_case_without_changing_source(monkeypatch, tmp_path):
    project, specs, tasks = fixture_tree(tmp_path)
    directories = []

    async def initialize(*args, **kwargs):
        return object()

    async def fail(**kwargs):
        directory = Path(kwargs["working_dir"])
        directories.append(directory)
        (directory / "input.txt").write_text("before failure")
        raise RuntimeError("injected failure")

    monkeypatch.setattr(evaluation, "init_harness", initialize)
    monkeypatch.setattr(evaluation, "_run_eval_task", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        await evaluation.run_harness_eval(
            spec_paths=specs,
            tasks_path=tasks,
            provider="test",
            model="model",
            working_dir=project,
            live=True,
        )
    assert directories and all(not path.exists() for path in directories)
    assert (project / "input.txt").read_text() == "original"


async def test_cancelled_evaluation_removes_disposable_workspace(monkeypatch, tmp_path):
    project, specs, tasks = fixture_tree(tmp_path)
    entered = asyncio.Event()
    directories = []

    async def initialize(*args, **kwargs):
        return object()

    async def wait(**kwargs):
        directory = Path(kwargs["working_dir"])
        directories.append(directory)
        (directory / "input.txt").write_text("unfinished candidate")
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(evaluation, "init_harness", initialize)
    monkeypatch.setattr(evaluation, "_run_eval_task", wait)
    run = asyncio.create_task(
        evaluation.run_harness_eval(
            spec_paths=specs,
            tasks_path=tasks,
            provider="test",
            model="model",
            working_dir=project,
            live=True,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert directories and all(not directory.exists() for directory in directories)
    assert (project / "input.txt").read_text() == "original"


async def test_recovery_reuses_identical_cases_but_not_changed_fixtures(monkeypatch, tmp_path):
    project, specs, tasks = fixture_tree(tmp_path)
    visits = []
    fake_execution(monkeypatch, visits)
    options = dict(
        spec_paths=specs[:1],
        tasks_path=tasks,
        provider="test",
        model="model",
        working_dir=project,
        live=True,
        recovery_store=project / "recovery.sqlite",
    )
    first = await evaluation.run_harness_eval(**options)
    second = await evaluation.run_harness_eval(**options)
    assert len(visits) == 2
    assert (
        first["variants"][0]["recovery_work_order"] == second["variants"][0]["recovery_work_order"]
    )
    assert all(case["recovery"] == "reused" for case in second["variants"][0]["tasks"])
    (project / "new-input.txt").write_text("new fixture")
    third = await evaluation.run_harness_eval(**options)
    assert len(visits) == 4
    assert (
        third["variants"][0]["recovery_work_order"] != first["variants"][0]["recovery_work_order"]
    )


def git(root, *args):
    return (
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", *args],
            cwd=root,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )


def test_git_fixture_preserves_dirty_binary_mode_and_independent_history(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    git(project, "init", "--quiet", "--template=")
    git(project, "config", "user.name", "Fixture")
    git(project, "config", "user.email", "fixture@example.invalid")
    (project / "file.bin").write_bytes(b"\x00original")
    (project / "deleted.txt").write_text("deleted later")
    (project / ".gitignore").write_text("ignored.txt\n")
    git(project, "add", ".")
    git(project, "commit", "--quiet", "-m", "base")
    head = git(project, "rev-parse", "HEAD")
    (project / "file.bin").write_bytes(b"\x00dirty")
    (project / "file.bin").chmod(0o755)
    (project / "deleted.txt").unlink()
    (project / "untracked.txt").write_text("included")
    (project / "ignored.txt").write_text("excluded")
    (project / "link.bin").symlink_to(project / "file.bin")
    before = git(project, "status", "--porcelain")
    with snapshot_eval_workspace(project) as snapshot:
        assert snapshot.base_commit == head
        with snapshot.case() as case:
            assert (case / "file.bin").read_bytes() == b"\x00dirty"
            assert (case / "file.bin").stat().st_mode & 0o777 == 0o755
            assert not (case / "deleted.txt").exists()
            assert (case / "untracked.txt").read_text() == "included"
            assert not (case / "ignored.txt").exists()
            assert (case / "link.bin").resolve() == case / "file.bin"
            assert git(case, "remote") == ""
            (case / "untracked.txt").write_text("changed only here")
            git(case, "add", "-A")
            git(
                case,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "private candidate",
            )
            assert git(case, "rev-parse", "HEAD") != head
    assert git(project, "rev-parse", "HEAD") == head
    assert git(project, "status", "--porcelain") == before


def test_external_symlinks_are_rejected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.txt").write_text("must not write")
    (project / "escape.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(ValueError, match="symlink escapes"):
        with snapshot_eval_workspace(project):
            pass


def test_looping_symlinks_are_rejected(tmp_path):
    (tmp_path / "loop").symlink_to("loop")
    with pytest.raises(ValueError, match="symlink escapes or loops"):
        with snapshot_eval_workspace(tmp_path):
            pass


@pytest.mark.parametrize("override", ["GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"])
def test_git_overrides_cannot_mutate_source_staging(tmp_path, monkeypatch, override):
    git(tmp_path, "init", "--quiet", "--template=")
    git(tmp_path, "config", "user.name", "Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "input.txt").write_text("base")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "--quiet", "-m", "base")
    (tmp_path / "input.txt").write_text("staged developer edit")
    git(tmp_path, "add", "input.txt")
    index = tmp_path / ".git/index"
    index_before = index.read_bytes()
    values = {
        "GIT_INDEX_FILE": index,
        "GIT_DIR": tmp_path / ".git",
        "GIT_WORK_TREE": tmp_path,
    }
    monkeypatch.setenv(override, str(values[override]))
    with pytest.raises(ValueError, match=override):
        with snapshot_eval_workspace(tmp_path):
            pytest.fail("Unsafe evaluation fixture was created")
    assert index.read_bytes() == index_before
    assert (tmp_path / "input.txt").read_text() == "staged developer edit"


def test_git_override_introduced_after_snapshot_blocks_case(tmp_path, monkeypatch):
    (tmp_path / "input.txt").write_text("original")
    with snapshot_eval_workspace(tmp_path) as snapshot:
        monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "private-index"))
        with pytest.raises(ValueError, match="GIT_INDEX_FILE"):
            with snapshot.case():
                pytest.fail("Unsafe evaluation case was created")
    assert not (tmp_path / "private-index").exists()


def test_policy_is_retained_but_runtime_ledgers_and_dependencies_are_excluded(tmp_path):
    (tmp_path / ".superqode").mkdir()
    (tmp_path / ".superqode/policy.yaml").write_text("rules: []")
    (tmp_path / ".superqode/session.json").write_text("private runtime state")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/dependency").write_text("omit")
    with snapshot_eval_workspace(tmp_path) as first:
        with first.case() as case:
            assert (case / ".superqode/policy.yaml").read_text() == "rules: []"
            assert not (case / ".superqode/session.json").exists()
            assert not (case / ".venv").exists()
        digest = first.digest
    (tmp_path / ".superqode/policy.yaml").write_text("rules: [deny]")
    with snapshot_eval_workspace(tmp_path) as second:
        assert second.digest != digest
