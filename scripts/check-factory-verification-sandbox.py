"""Exercise native verification isolation using only repository-owned fixtures.

Run from the repository with its development Python. No models, downloads,
personal files or external network hosts are involved.
"""

from pathlib import Path
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from superqode.factory.probes import run_python_probe


def main():
    storage = ROOT / ".superqode/validation/native-verification"
    storage.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(dir=storage, prefix="probe-") as name:
        stage = Path(name)
        candidate, scratch = stage / "candidate", stage / "scratch"
        candidate.mkdir()
        scratch.mkdir()
        (candidate / "app.py").write_text("print(43)\n")
        secret = stage / "protected-evaluator.txt"
        secret.write_text("synthetic acceptance data")
        read = f"open({str(secret)!r}).read()"
        write = "open('app.py','w').write('changed')"
        link = f"__import__('os').link({str(secret)!r},{str(scratch / 'linked')!r})"
        cases = [
            ("python-output", "print(43)", "43\n"),
            (
                "candidate-read-only",
                f"try:\n {write}\n print('unexpected')\nexcept PermissionError:\n print('denied')",
                "denied\n",
            ),
            (
                "evaluator-unreadable",
                f"try:\n {read}\n print('unexpected')\nexcept PermissionError:\n print('denied')",
                "denied\n",
            ),
            (
                "hardlink-denied",
                f"try:\n {link}\n print('unexpected')\nexcept PermissionError:\n print('denied')",
                "denied\n",
            ),
            (
                "network-denied",
                "import socket,errno\ntry:\n socket.socket().connect(('127.0.0.1',9))\n print('unexpected')\nexcept OSError as e:\n print('denied' if e.errno in (errno.EPERM,errno.EACCES) else 'unexpected')",
                "denied\n",
            ),
            (
                "scratch-write",
                f"open({str(scratch / 'allowed')!r},'w').write('ok');print('ok')",
                "ok\n",
            ),
        ]
        for label, code, expected in cases:
            result = run_python_probe(
                ["python", "-c", code],
                candidate=candidate,
                scratch=scratch,
                stdin="",
                deadline=time.monotonic() + 10,
            )
            results.append(
                {
                    "check": label,
                    "passed": result.get("kind") == "completed"
                    and result.get("returncode") == 0
                    and result.get("stdout") == expected,
                    **result,
                }
            )
        assert (candidate / "app.py").read_text() == "print(43)\n"
    print(
        json.dumps({"passed": all(row["passed"] for row in results), "checks": results}, indent=2)
    )
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
