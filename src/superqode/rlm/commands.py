"""Portable, bounded command jobs. Also staged inside Docker as a stdlib module.

Job receipts survive interpreter restarts. Interrupted jobs with an unverified
outcome retain their workspace lease until explicit reconciliation. A process
group is terminated on timeout/cancellation, not just its shell parent.
"""

import json
import hashlib
from contextlib import contextmanager
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from uuid import uuid4

_LIVE = {}
_LIVE_LOCK = threading.Lock()
_ACTIVE = ("starting", "running", "unknown")


def clean_env(allowlist=(), overrides=None):
    denied = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH|COOKIE)", re.I)
    base = {
        k: v
        for k, v in os.environ.items()
        if (not allowlist or k in allowlist) and not denied.search(k)
    }
    for key, value in dict(overrides or {}).items():
        if denied.search(str(key)):
            raise ValueError("Credential environment variables cannot be passed to commands")
        base[str(key)] = str(value)
    return base


def fingerprint(pid):
    if not pid:
        return ""
    try:
        if os.name == "posix":
            proc = Path(f"/proc/{pid}/stat")
            if proc.exists():
                # The command name can contain spaces or parentheses.
                fields = proc.read_text().rsplit(")", 1)[1].split()
                if fields[0] == "Z":
                    return ""
                return str(pid) + ":" + fields[19]
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=2
            )
            return str(pid) + ":" + result.stdout.strip() if result.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return ""


class CommandHandle:
    def __init__(self, broker, identity):
        self._broker, self.id = broker, identity

    def status(self):
        return self._broker.status(self.id)

    def read(self, *, stream="stdout", start=0, size=4000):
        return self._broker.read(self.id, stream=stream, start=start, size=size)

    def wait(self, timeout=1):
        return self._broker.wait(self.id, timeout=timeout)

    def cancel(self):
        return self._broker.cancel(self.id)

    def __repr__(self):
        state = self.status()
        return f"CommandHandle(id={self.id!r}, state={state['state']!r}, returncode={state['returncode']!r})"


class CommandBroker:
    def __init__(self, cwd, path, *, policy=None, max_output_chars=1000000, agent="root"):
        self.cwd = Path(cwd).resolve()
        self.path = Path(path).resolve()
        self.policy = dict(policy or {})
        self.agent = agent
        self.max_output_chars = max(256, int(max_output_chars))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE, command TEXT, readonly INTEGER,
                state TEXT, pid INTEGER DEFAULT 0, process_identity TEXT DEFAULT '',
                owner INTEGER, owner_identity TEXT, started REAL, returncode INTEGER,
                stdout TEXT DEFAULT '', stderr TEXT DEFAULT '',
                stdout_omitted INTEGER DEFAULT 0, stderr_omitted INTEGER DEFAULT 0,
                reason TEXT DEFAULT '', agent TEXT DEFAULT 'root')""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "signature" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN signature TEXT DEFAULT ''")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _check(self, command):
        if not self.policy.get("allow_shell", True):
            raise PermissionError("Shell execution is disabled by the RLM sandbox policy")
        if isinstance(command, str):
            if not self.policy.get("allow_compound_commands", True) and re.search(
                r"[;&|]|\$\(|`|\n", command
            ):
                raise PermissionError("Compound commands are disabled by the RLM sandbox policy")
            tokens = shlex.split(command)
        else:
            tokens = list(map(str, command))
        if not tokens:
            raise ValueError("Command cannot be empty")
        allowed = self.policy.get("allowed_commands", [])
        if allowed and os.path.basename(tokens[0]) not in allowed:
            raise PermissionError("Command is not in the RLM sandbox allowlist")

    @contextmanager
    def mutation(self):
        """Serialize convenience workspace writes with command admission."""
        self.list()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM jobs WHERE state IN ('starting','running','unknown') LIMIT 1"
            ).fetchone():
                raise RuntimeError(
                    "Workspace command is active or needs reconciliation before a write"
                )
            yield

    def handle(self, identity):
        self.status(identity)
        return CommandHandle(self, identity)

    def start(self, command, *, timeout=120, request_id=None, read_only=False, env=None, bash=True):
        self._check(command)
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("Command timeout must be 0..3600 seconds")
        display = command if isinstance(command, str) else shlex.join(map(str, command))
        if isinstance(command, str) and bash:
            executable = shutil.which("bash")
            if not executable:
                raise RuntimeError("Bash is unavailable in the selected execution environment")
            argv = [executable, "--noprofile", "--norc", "-c", command]
        else:
            argv = command
        environment = clean_env(self.policy.get("env_allowlist", ()), env)
        signature = hashlib.sha256(
            json.dumps(
                {
                    "command": display,
                    "timeout": timeout,
                    "read_only": bool(read_only),
                    "bash": bool(bash),
                    "overrides": dict(env or {}),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        identity = "cmd-" + uuid4().hex[:24]
        request_id = str(request_id or identity)
        # Refresh potentially abandoned leases before checking conflicts.
        self.list()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if self.agent != "root" and previous["agent"] != self.agent:
                    raise PermissionError("Command request belongs to another agent")
                if previous["command"] != display or bool(previous["readonly"]) != bool(read_only):
                    raise ValueError("Command request_id was already used with different inputs")
                if previous["signature"] and previous["signature"] != signature:
                    raise ValueError("Command request_id was already used with different inputs")
                return CommandHandle(self, previous["id"])
            active = db.execute(
                "SELECT readonly FROM jobs WHERE state IN ('starting','running','unknown')"
            ).fetchall()
            if active and (not read_only or any(not row[0] for row in active)):
                raise RuntimeError(
                    "Workspace command is active or needs reconciliation; wait or cancel before another mutation"
                )
            db.execute(
                """INSERT INTO jobs (id,request_id,command,readonly,state,owner,owner_identity,started,agent)
                VALUES (?,?,?,?,'starting',?,?,?,?)""",
                (
                    identity,
                    request_id,
                    display,
                    int(read_only),
                    os.getpid(),
                    fingerprint(os.getpid()),
                    time.time(),
                    self.agent,
                ),
            )
            db.execute("UPDATE jobs SET signature=? WHERE id=?", (signature, identity))
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.cwd,
                env=environment,
                shell=isinstance(argv, str),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except BaseException as exc:
            self._update(identity, state="failed", reason=str(exc), returncode=-1)
            raise
        with _LIVE_LOCK:
            _LIVE[(str(self.path), identity)] = process
        self._update(
            identity, state="running", pid=process.pid, process_identity=fingerprint(process.pid)
        )
        readers = [
            threading.Thread(target=self._capture, args=(identity, name, pipe), daemon=True)
            for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))
        ]
        for reader in readers:
            reader.start()
        threading.Thread(
            target=self._finish, args=(identity, process, readers, timeout), daemon=True
        ).start()
        return CommandHandle(self, identity)

    def _capture(self, identity, stream, pipe):
        import codecs

        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                chunk = pipe.read1(16384)
                text = decoder.decode(chunk, final=not chunk)
                if text:
                    with self._db() as db:
                        row = db.execute(
                            f"SELECT {stream} FROM jobs WHERE id=?", (identity,)
                        ).fetchone()
                        keep = max(0, self.max_output_chars - len(row[0]))
                        db.execute(
                            f"UPDATE jobs SET {stream}={stream} || ?, {stream}_omitted={stream}_omitted+? WHERE id=?",
                            (text[:keep], max(0, len(text) - keep), identity),
                        )
                if not chunk:
                    break
        finally:
            pipe.close()

    def _finish(self, identity, process, readers, timeout):
        state = "complete"
        reason = ""
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill(process.pid, process)
            process.wait()
            state, reason = "timed_out", "Command deadline reached; process group stopped"
        # Stop descendants even if the shell exited while they retained pipes.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for reader in readers:
            reader.join(timeout=5)
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET state=CASE WHEN state='cancelled' THEN state ELSE ? END, returncode=?, reason=CASE WHEN state='cancelled' THEN reason ELSE ? END WHERE id=?",
                (
                    state if process.returncode == 0 or state == "timed_out" else "failed",
                    process.returncode,
                    reason,
                    identity,
                ),
            )
        with _LIVE_LOCK:
            _LIVE.pop((str(self.path), identity), None)

    def _update(self, identity, **values):
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                (*values.values(), identity),
            )

    def status(self, identity):
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (str(identity),)).fetchone()
        if row is None:
            raise ValueError("Unknown command handle")
        if self.agent != "root" and row["agent"] != self.agent:
            raise PermissionError("Command handle belongs to another agent")
        state = row["state"]
        if (
            state in {"starting", "running"}
            and os.name == "posix"
            and fingerprint(row["owner"]) != row["owner_identity"]
        ):
            self._update(
                identity,
                state="unknown",
                reason="Command owner interrupted; verify workspace effects before reconciliation",
            )
            state = "unknown"
        return {
            "id": row["id"],
            "state": state,
            "command": row["command"],
            "read_only": bool(row["readonly"]),
            "returncode": row["returncode"],
            "stdout_chars": len(row["stdout"]),
            "stderr_chars": len(row["stderr"]),
            "stdout_omitted": row["stdout_omitted"],
            "stderr_omitted": row["stderr_omitted"],
            "reason": row["reason"]
            if state == row["state"]
            else "Interrupted owner; outcome unknown",
        }

    def list(self):
        with self._db() as db:
            identifiers = [
                r[0]
                for r in db.execute(
                    """SELECT id FROM jobs WHERE (?='root' OR agent=?) AND
                    (state IN ('starting','running','unknown') OR id IN
                    (SELECT id FROM jobs WHERE ?='root' OR agent=? ORDER BY started DESC LIMIT 100))
                    ORDER BY started DESC""",
                    (self.agent, self.agent, self.agent, self.agent),
                )
            ]
        return [self.status(identity) for identity in identifiers]

    def read(self, identity, *, stream="stdout", start=0, size=4000):
        self.status(identity)
        if stream not in {"stdout", "stderr"}:
            raise ValueError("Command stream must be stdout or stderr")
        start, size = max(0, int(start)), max(1, min(20000, int(size)))
        with self._db() as db:
            row = db.execute(
                f"SELECT {stream},{stream}_omitted FROM jobs WHERE id=?", (identity,)
            ).fetchone()
        return {
            "id": identity,
            "stream": stream,
            "start": start,
            "text": row[0][start : start + size],
            "chars": len(row[0]),
            "more": start + size < len(row[0]),
            "omitted": row[1],
        }

    def wait(self, identity, *, timeout=1):
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 0 <= timeout <= 60:
            raise ValueError("Command wait must be 0..60 seconds")
        deadline = time.monotonic() + timeout
        while True:
            receipt = self.status(identity)
            if (
                receipt["state"] != "running"
                and receipt["state"] != "starting"
                or time.monotonic() >= deadline
            ):
                return receipt
            time.sleep(0.02)

    def _kill(self, pid, process=None):
        try:
            if os.name == "posix":
                os.killpg(pid, signal.SIGKILL)
            elif process is not None:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=5
                )
        except ProcessLookupError:
            pass

    def cancel(self, identity):
        receipt = self.status(identity)
        if receipt["state"] not in _ACTIVE:
            return receipt
        with self._db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
        with _LIVE_LOCK:
            process = _LIVE.get((str(self.path), identity))
        verified = (process is not None and process.poll() is None) or (
            row["process_identity"] and fingerprint(row["pid"]) == row["process_identity"]
        )
        if verified:
            self._kill(row["pid"], process)
            if process is not None:
                process.wait(timeout=5)
        elif process is not None and process.poll() is not None:
            return self.wait(identity, timeout=5)
        elif receipt["state"] == "unknown":
            raise RuntimeError(
                "Interrupted command cannot be safely identified; reconcile its verified outcome explicitly"
            )
        else:
            raise RuntimeError("Command is starting; retry cancellation after admission completes")
        self._update(
            identity,
            state="cancelled",
            reason="Process group cancelled; verify partial workspace writes",
        )
        return self.status(identity)

    def reconcile(self, identity, *, returncode, reason):
        receipt = self.status(identity)
        if receipt["state"] != "unknown" or not str(reason).strip():
            raise ValueError("Reconciliation requires an unknown job and a verification reason")
        with self._db() as db:
            row = db.execute(
                "SELECT pid,process_identity FROM jobs WHERE id=?", (identity,)
            ).fetchone()
        if row[1] and fingerprint(row[0]) == row[1]:
            raise RuntimeError("Cancel the surviving process before reconciling")
        self._update(identity, state="reconciled", returncode=int(returncode), reason=str(reason))
        return self.status(identity)

    def dispatch(self, payload):
        action = payload.get("action", "run")
        identity = str(payload.get("job_id", ""))
        if action in {"run", "start"}:
            handle = self.start(
                str(payload.get("command", "")),
                timeout=payload.get("timeout", 120),
                request_id=payload.get("request_id"),
                read_only=bool(payload.get("read_only", False)),
            )
            return handle.wait(timeout=payload.get("wait", 1) if action == "run" else 0)
        if action == "status":
            return self.status(identity)
        if action == "read":
            return self.read(
                identity,
                stream=payload.get("stream", "stdout"),
                start=payload.get("start", 0),
                size=payload.get("size", 4000),
            )
        if action == "wait":
            return self.wait(identity, timeout=payload.get("wait", 1))
        if action == "cancel":
            return self.cancel(identity)
        if action == "list":
            return self.list()
        if action == "reconcile":
            return self.reconcile(
                identity, returncode=payload.get("returncode", -1), reason=payload.get("reason", "")
            )
        raise ValueError("Unknown command operation")

    def run(self, command, **kwargs):
        return self.start(command, **kwargs)

    def __repr__(self):
        return "CommandBroker(start/run, list, read, wait, cancel; bounded durable output)"
