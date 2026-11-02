"""OS-backed engine and project writer leases; never replay interrupted work."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


class Lease:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise ValueError(
                "Another engine or worker still owns this workspace. Wait for it to stop before retrying."
            ) from None

    def record(self, **data):
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, json.dumps(data).encode())
        os.fsync(self.fd)

    def close(self):
        if getattr(self, "fd", None) is not None:
            os.close(self.fd)
            self.fd = None

    def __del__(self):
        self.close()


def project_lease_path(state, root):
    # Lease the resolved working directory within the desktop engine state.
    # It is app state, never a tracked project file or Git worktree mutation.
    key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()
    return Path(state) / "writers" / (key + ".lock")


def watch_parent(parent_pid):
    """The worker session belongs to the engine that launched it."""
    if os.getppid() != parent_pid:
        raise RuntimeError("The owner engine exited before execution started")

    def watch():
        while os.getppid() == parent_pid:
            time.sleep(0.2)
        if os.getpgrp() == os.getpid():
            if not os.environ.get("SUPERQODE_DESKTOP_LEASE_FD"):
                os.killpg(os.getpgrp(), signal.SIGKILL)
                return
            lease_fd = int(os.environ["SUPERQODE_DESKTOP_LEASE_FD"])
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import os,signal,sys,time; p=int(sys.argv[1]); "
                    "os.killpg(p,signal.SIGTERM); time.sleep(0.3); "
                    "\ntry: os.killpg(p,signal.SIGKILL)\nexcept ProcessLookupError: pass",
                    str(os.getpgrp()),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(lease_fd,),
            )

    threading.Thread(target=watch, daemon=True).start()


def reap_children(process, finished):
    """Close pipes held by attached children after the worker leader exits."""
    try:
        process.wait()
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        time.sleep(0.3)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    finally:
        finished.set()


def assert_project_idle(service, project):
    lease = Lease(project_lease_path(service.root, service.project(project)))
    lease.close()


def recovery_status(service, project):
    path = project_lease_path(service.root, service.project(project))
    blocked = False
    try:
        lease = Lease(path)
        lease.close()
    except ValueError:
        blocked = not any(
            row["id"] in service.processes
            for row in service._all("SELECT id FROM jobs WHERE project=?", (project,))
        )
    key = "recovery-ack:" + project
    saved = service._all("SELECT value FROM settings WHERE key=?", (key,))
    since = float(json.loads(saved[0]["value"])) if saved else 0
    rows = service._all(
        "SELECT id,title,updated FROM jobs WHERE project=? AND status='interrupted' AND updated>? ORDER BY updated DESC LIMIT 10",
        (project, since),
    )
    return {
        "blocked": blocked,
        "interrupted": rows,
        "message": "A previous worker still owns this project. Wait for it to stop before starting work or editing files."
        if blocked
        else "Interrupted work was preserved. Review its changes before continuing; no task was replayed."
        if rows
        else "",
    }
