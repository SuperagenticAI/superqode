"""The published SDK examples run without a model account."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_session_sdk_example(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/pipy/session.py"),
            "--cwd",
            str(tmp_path),
            "--session-root",
            str(tmp_path / "sessions"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Offline SDK example completed" in result.stdout
    assert list((tmp_path / "sessions").rglob("*.jsonl"))


def test_custom_tool_sdk_example():
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples/pipy/custom_tool.py")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Custom tool completed" in result.stdout
