from pathlib import Path

import pytest

from superqode.harness import inspect_harness_backend, load_harness_spec


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "harnesses"


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.yaml")))
def test_harness_examples_load_and_match_backend(path: Path):
    spec = load_harness_spec(path)

    assert spec.name
    assert spec.runtime.backend
    assert spec.agents
    assert spec.metadata.get("example")

    inspection = inspect_harness_backend(spec.runtime.backend, spec)
    assert inspection.ok, [issue.to_dict() for issue in inspection.issues]
