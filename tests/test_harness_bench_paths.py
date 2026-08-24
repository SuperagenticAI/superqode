"""HarnessBench records paths relative to its manifest.

Absolute paths are what the runtime needs and the wrong thing to record. They
pin a scorecard to one machine's directory layout, so a published result
carries the operator's home directory, and the same benchmark run from a
different checkout produces a different fingerprint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.harness.bench import (
    _relativize,
    _relativize_record,
    load_harness_bench_manifest,
)

MANIFEST = """\
schema_version: 1
bench_id: paths
tasks: tasks.yaml
specs: [a.yaml, b.yaml]
provider: google
model: gemini-3.5-flash-lite
working_dir: ../repo
sandbox: local
repetitions: 1
live: false
"""

TASKS = """\
metadata:
  id: paths
tasks:
  - id: one
    prompt: anything
    expect_contains: ["x"]
"""

SPEC = """\
version: 1
name: {name}
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: gemini-3.5-flash-lite
  config:
    provider: google
execution_policy:
  sandbox: local
  allow_read: true
  allow_write: false
agents:
  - id: reader
    role: analysis
    system_prompt: read
    tools: [read_file]
"""


@pytest.fixture
def bench_tree(tmp_path: Path) -> Path:
    bench = tmp_path / "bench"
    bench.mkdir()
    (tmp_path / "repo").mkdir()
    (bench / "tasks.yaml").write_text(TASKS)
    (bench / "a.yaml").write_text(SPEC.format(name="a"))
    (bench / "b.yaml").write_text(SPEC.format(name="b"))
    (bench / "m.yaml").write_text(MANIFEST)
    return bench / "m.yaml"


def test_recorded_paths_are_relative_to_the_manifest(bench_tree: Path):
    manifest = load_harness_bench_manifest(bench_tree)
    recorded = manifest.to_dict()

    assert recorded["tasks"] == "tasks.yaml"
    assert recorded["specs"] == ["a.yaml", "b.yaml"]
    assert recorded["working_dir"] == "../repo"

    serialized = json.dumps(recorded)
    assert "/" not in serialized.replace("../repo", ""), serialized


def test_the_runtime_still_gets_absolute_paths(bench_tree: Path):
    """Recording relative must not change what actually gets opened."""
    manifest = load_harness_bench_manifest(bench_tree)
    assert Path(manifest.tasks).is_absolute()
    assert all(Path(spec).is_absolute() for spec in manifest.specs)
    assert Path(manifest.tasks).is_file()


def test_the_manifest_directory_never_reaches_the_record(bench_tree: Path):
    """It is a loading detail, so including it would put the path back."""
    manifest = load_harness_bench_manifest(bench_tree)
    assert manifest.manifest_dir
    assert "manifest_dir" not in manifest.to_dict()


def test_two_checkouts_of_the_same_benchmark_agree(tmp_path: Path):
    """The fingerprint should describe the benchmark, not where it ran.

    Absolute paths in the record meant the same tasks, specs and model run
    from a different directory produced a different fingerprint, which makes
    two people's results incomparable.
    """
    recorded = []
    for name in ("first", "second"):
        root = tmp_path / name
        bench = root / "bench"
        bench.mkdir(parents=True)
        (root / "repo").mkdir()
        (bench / "tasks.yaml").write_text(TASKS)
        (bench / "a.yaml").write_text(SPEC.format(name="a"))
        (bench / "b.yaml").write_text(SPEC.format(name="b"))
        (bench / "m.yaml").write_text(MANIFEST)
        recorded.append(load_harness_bench_manifest(bench / "m.yaml").to_dict())

    assert recorded[0] == recorded[1]


def test_run_records_are_normalized_too():
    """The manifest is not the only place a path gets written down."""
    root = "/home/someone/bench"
    record = {
        "tasks_file": "/home/someone/bench/tasks.yaml",
        "variants": [
            {"harness": "a", "spec": "/home/someone/bench/a.yaml", "score": 1.0},
            {"harness": "b", "spec": "/home/someone/bench/b.yaml", "score": 1.0},
        ],
    }
    cleaned = _relativize_record(record, root)

    assert cleaned["tasks_file"] == "tasks.yaml"
    assert [v["spec"] for v in cleaned["variants"]] == ["a.yaml", "b.yaml"]
    # Values that are not paths must survive untouched.
    assert [v["score"] for v in cleaned["variants"]] == [1.0, 1.0]
    assert "/home/someone" not in json.dumps(cleaned)


def test_only_path_keys_are_rewritten():
    """A string that merely looks like a path elsewhere is left alone."""
    cleaned = _relativize_record(
        {"note": "/home/someone/bench/a.yaml", "spec": "/home/someone/bench/a.yaml"},
        "/home/someone/bench",
    )
    assert cleaned["note"] == "/home/someone/bench/a.yaml"
    assert cleaned["spec"] == "a.yaml"


def test_relativize_falls_back_when_no_relative_path_exists():
    """Windows across drive letters has no relative form."""
    assert _relativize("relative/already.yaml", "/anywhere").endswith("already.yaml")
    assert _relativize("/a/b/c.yaml", "/a/b") == "c.yaml"
    assert _relativize("/a/x/c.yaml", "/a/b") == "../x/c.yaml"
