"""Workers exit quickly after their result without skipping shutdown work."""

import subprocess
import sys

import pytest

FIXTURE = """
import atexit, sys, threading, time
from pathlib import Path
from superqode.desktop_service.process_exit import run_and_exit

root = Path(sys.argv[1])
mode = sys.argv[2]


def main():
    atexit.register(lambda: (root / "atexit").write_text("ran"))

    def slow():
        time.sleep(0.2)
        (root / "thread").write_text("joined")

    threading.Thread(target=slow).start()
    print("wire", flush=True)
    if mode == "code":
        raise SystemExit(3)
    if mode == "error":
        raise RuntimeError("boom")
    if mode == "message":
        raise SystemExit("bad request")


run_and_exit(main)
"""


@pytest.mark.parametrize(
    ("mode", "code", "stderr"),
    [
        ("ok", 0, ""),
        ("code", 3, ""),
        ("error", 1, "RuntimeError: boom"),
        ("message", 1, "bad request"),
    ],
)
def test_fast_exit_keeps_threads_atexit_and_exit_code(tmp_path, mode, code, stderr):
    script = tmp_path / "worker_fixture.py"
    script.write_text(FIXTURE)
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path), mode],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == code, completed.stderr
    assert completed.stdout.strip() == "wire"
    assert (tmp_path / "atexit").read_text() == "ran"
    assert (tmp_path / "thread").read_text() == "joined"
    assert stderr in completed.stderr
