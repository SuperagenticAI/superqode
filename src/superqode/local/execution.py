"""Cancellable, process-safe local inference slots and prompt-free measurements.

Slots cover model generation, never tool execution. Kernel locks are released
on process death; stale measurement rows are reported as interrupted.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4


_current = ContextVar("local_inference_turn", default=None)


def annotate(**values):
    turn = _current.get()
    if turn is not None:
        allowed = {
            "context",
            "context_source",
            "output_limit",
            "sdk_prompt_tokens",
            "server_load_s",
            "server_prefill_s",
            "server_decode_s",
        }
        turn.data.update({key: value for key, value in values.items() if key in allowed})


def memory_health():
    """Cheap OS memory observations. Missing values stay unknown, not zero."""
    value = {"total_gb": None, "available_gb": None, "swap_used_gb": None, "source": "unavailable"}
    try:
        import psutil

        memory, swap = psutil.virtual_memory(), psutil.swap_memory()
        return {
            "total_gb": round(memory.total / 1024**3, 1),
            "available_gb": round(memory.available / 1024**3, 1),
            "swap_used_gb": round(swap.used / 1024**3, 2),
            "source": "OS memory counters",
        }
    except ImportError:
        pass
    if sys.platform == "darwin":
        import subprocess
        import re

        try:
            total = subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"], timeout=1, text=True
            )
            stats = subprocess.check_output(["/usr/bin/vm_stat"], timeout=1, text=True)
            page = int(re.search(r"page size of (\d+)", stats).group(1))
            counts = {
                name: int(count) for name, count in re.findall(r"(Pages [^:]+):\s+(\d+)", stats)
            }
            available = (
                sum(
                    counts.get(name, 0)
                    for name in ("Pages free", "Pages inactive", "Pages speculative")
                )
                * page
            )
            swap = subprocess.check_output(
                ["/usr/sbin/sysctl", "vm.swapusage"], timeout=1, text=True
            )
            used = re.search(r"used = ([\d.]+)([KMG])", swap)
            value.update(
                total_gb=round(int(total) / 1024**3, 1),
                available_gb=round(available / 1024**3, 1),
                swap_used_gb=round(
                    float(used[1]) * {"K": 1 / 1024**2, "M": 1 / 1024, "G": 1}[used[2]], 2
                )
                if used
                else None,
                source="macOS counters; available memory is approximate",
            )
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            pass
    return value


def directory():
    root = (
        Path(os.environ.get("SUPERQODE_STATE_DIR") or Path.home() / ".superqode")
        / "local-execution"
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise ValueError("Local execution storage must not be a symbolic link")
    return root


def enabled():
    return os.name == "posix" and (
        sys.platform == "darwin" or bool(os.environ.get("SUPERQODE_STATE_DIR"))
    )


@contextmanager
def database():
    path = directory() / "measurements.sqlite3"
    if path.is_symlink():
        raise ValueError("Local measurement database must not be a symbolic link")
    db = sqlite3.connect(path, timeout=5)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, concurrency INTEGER NOT NULL)"
    )
    db.execute("INSERT OR IGNORE INTO settings VALUES(1,1)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS measurements(id TEXT PRIMARY KEY,pid INTEGER,created REAL,updated REAL,status TEXT,data TEXT)"
    )
    try:
        yield db
        db.commit()
    finally:
        db.close()


def configure(concurrency):
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise ValueError("Choose one to four simultaneous local generations")
    with database() as db:
        db.execute("UPDATE settings SET concurrency=? WHERE id=1", (concurrency,))
    return {"concurrency": concurrency}


def snapshot():
    if not enabled():
        return {"enabled": False, "concurrency": 1, "requests": []}
    with database() as db:
        rows = list(
            db.execute("SELECT * FROM measurements WHERE status IN ('queued','generating')")
        )
        for row in rows:
            if not lease_alive(row["id"]):
                db.execute(
                    "UPDATE measurements SET status='interrupted',updated=? WHERE id=?",
                    (time.time(), row["id"]),
                )
        rows = list(db.execute("SELECT * FROM measurements ORDER BY created DESC LIMIT 40"))
        limit = db.execute("SELECT concurrency FROM settings WHERE id=1").fetchone()[0]
    return {
        "enabled": True,
        "concurrency": limit,
        "health": memory_health(),
        "requests": [
            {
                **json.loads(row["data"]),
                "id": row["id"],
                "status": row["status"],
                "created": row["created"],
            }
            for row in rows
        ],
    }


def lease_alive(identity):
    import fcntl

    path = directory() / ("request-" + identity + ".lock")
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return False
    finally:
        os.close(fd)


def comparison_records(trace):
    if not enabled():
        return []
    with database() as db:
        rows = db.execute(
            "SELECT data,status FROM measurements WHERE json_extract(data,'$.comparison_trace')=? ORDER BY created LIMIT 200",
            (trace,),
        ).fetchall()
    return [{**json.loads(r["data"]), "status": r["status"]} for r in rows]


class LocalTurn:
    def __init__(self, provider, model):
        self.provider, self.model = provider, model
        self.id = uuid4().hex
        self.fd = None
        self.request_fd = None
        self.started = None
        self.queued = time.monotonic()
        self.terminal = False
        self.data = {
            "provider": provider,
            "model": model,
            "queue_s": None,
            "first_output_s": None,
            "first_text_s": None,
            "generation_s": None,
            "input_tokens": None,
            "output_tokens": None,
        }
        trace = os.environ.get("SUPERQODE_LOCAL_COMPARISON_TRACE", "")
        if trace:
            self.data["comparison_trace"] = trace[:100]
        self.active = enabled()

    def save(self, status):
        with database() as db:
            now = time.time()
            db.execute(
                "INSERT INTO measurements VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated=excluded.updated,data=excluded.data",
                (self.id, os.getpid(), now, now, status, json.dumps(self.data)),
            )

    def queued_lease(self):
        import fcntl

        path = directory() / ("request-" + self.id + ".lock")
        self.request_fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self.request_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.save("queued")

    def try_slot(self):
        import fcntl

        with database() as db:
            slots = db.execute("SELECT concurrency FROM settings WHERE id=1").fetchone()[0]
        for slot in range(slots):
            fd = os.open(
                directory() / f"slot-{slot}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            self.fd = fd
            self.started = time.monotonic()
            self.data["queue_s"] = self.started - self.queued
            self.save("generating")
            return True
        return False

    def __enter__(self):
        self.sync_token = _current.set(self)
        if not self.active:
            return self
        try:
            self.queued_lease()
            while not self.try_slot():
                time.sleep(0.05)
        except BaseException:
            _current.reset(self.sync_token)
            self.close("cancelled")
            raise
        return self

    def __exit__(self, kind, value, traceback):
        _current.reset(self.sync_token)
        self.close(
            "completed" if self.terminal else "cancelled" if kind is KeyboardInterrupt else "failed"
        )

    async def __aenter__(self):
        if not self.active:
            return self
        try:
            self.queued_lease()
            while not self.try_slot():
                await asyncio.sleep(0.05)
        except BaseException:
            self.close("cancelled")
            raise
        return self

    async def run(self, awaitable):
        token = _current.set(self)
        try:
            return await awaitable
        finally:
            _current.reset(token)

    async def next(self, source):
        # An async generator may be consumed by different tasks between yields.
        # Never retain a ContextVar token across those yields.
        return await self.run(anext(source))

    def observe(self, *, text=False, thinking=False, tools=False, terminal=False, usage=None):
        self.terminal = self.terminal or terminal
        if not self.active or self.started is None:
            return
        changed = False
        elapsed = time.monotonic() - self.started
        if (text or thinking or tools) and self.data["first_output_s"] is None:
            self.data["first_output_s"] = elapsed
            changed = True
        if text and self.data["first_text_s"] is None:
            self.data["first_text_s"] = elapsed
            changed = True
        if usage is not None:
            changed |= (
                self.data["input_tokens"] != usage.prompt_tokens
                or self.data["output_tokens"] != usage.completion_tokens
            )
            self.data.update(
                input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens
            )
        if self.terminal and self.data["generation_s"] is None:
            self.data["generation_s"] = elapsed
            changed = True
        if changed:
            self.save("completed" if self.terminal else "generating")
        if self.terminal:
            # Completion can be consumed before the iterator is resumed or
            # closed. Tool execution and delegated model calls must not wait
            # for that consumer to ask for EOF. Late usage still updates this
            # completed record, without extending generation time.
            self.release_locks()

    def close(self, status):
        if not self.active:
            return
        try:
            if self.started is not None and self.data["generation_s"] is None:
                self.data["generation_s"] = time.monotonic() - self.started
            self.save(status)
            with database() as db:
                db.execute(
                    "DELETE FROM measurements WHERE status NOT IN ('queued','generating') AND id NOT IN (SELECT id FROM measurements ORDER BY created DESC LIMIT 200)"
                )
        finally:
            self.release_locks()

    def release_locks(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.request_fd is not None:
            os.close(self.request_fd)
            self.request_fd = None
            try:
                (directory() / ("request-" + self.id + ".lock")).unlink()
            except FileNotFoundError:
                pass

    async def __aexit__(self, kind, value, traceback):
        self.close(
            "completed"
            if self.terminal
            else "cancelled"
            if kind in {asyncio.CancelledError, GeneratorExit}
            else "failed"
        )


def is_local(provider):
    from superqode.providers.registry import PROVIDERS, ProviderCategory

    spec = PROVIDERS.get(provider)
    return bool(
        spec and spec.category == ProviderCategory.LOCAL and spec.deployment_mode != "cloud"
    )
