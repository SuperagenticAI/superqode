"""Content identities and a single-writer journal for refinement jobs."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    os.replace(temporary, path)


def read_json(path: Path):
    return json.loads(path.read_text())


def verify_digest(value, field, description):
    if digest({key: item for key, item in value.items() if key != field}) != value.get(field):
        raise ValueError(f"Saved {description} changed")


def verify_manifest(value):
    identity = {key: item for key, item in value.items() if key not in {"identity", "plan"}}
    if digest(identity) != value.get("identity"):
        raise ValueError("Saved refinement manifest changed")


@contextmanager
def job_lock(root: Path):
    """Nonblocking writer lock, including recovery from a dead local process."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".running"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            try:
                pid = int(path.read_text())
                os.kill(pid, 0)
            except ProcessLookupError:
                path.unlink(missing_ok=True)
                continue
            except (ValueError, OSError):
                pass
            raise ValueError("This refinement job already has an active writer")
    else:
        raise ValueError("Could not acquire refinement job lock")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


class RefinementStore:
    def __init__(self, root: Path, callback=None):
        self.root = root
        self.callback = callback

    def event(self, kind, **data):
        record = {"type": kind, "timestamp": time.time(), "data": data}
        with (self.root / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        if self.callback:
            self.callback(record)
        return record

    def result(self, value):
        value["result_digest"] = digest(value)
        write_json(self.root / "result.json", value)


def inspect_refinement(path: str | Path):
    root = Path(path).expanduser().resolve()
    manifest = read_json(root / "manifest.json")
    result = (
        read_json(root / "result.json")
        if (root / "result.json").exists()
        else {"status": "interrupted"}
    )
    stages = [read_json(p) for p in sorted((root / "stages").glob("*/record.json"))]
    return {
        "path": str(root),
        "manifest": manifest,
        "result": result,
        "stages": stages,
        "running": (root / ".running").exists(),
    }


def cancel_refinement(path: str | Path):
    root = Path(path).expanduser().resolve()
    if not (root / "manifest.json").is_file():
        raise ValueError("No refinement manifest exists here")
    (root / "cancel.request").touch()
