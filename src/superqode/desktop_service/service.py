"""Desktop commands over a local pipe; private companion access is opt-in."""

from __future__ import annotations

import hashlib
import difflib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from .redaction import redact
from .routes import acp_routes, resolve_acp_route

MAX_TEXT = 1_000_000
ACTIVE = {"running", "needs_approval", "queued", "cancelling"}


def private_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "This folder is not a Git repository")
    return result.stdout[:MAX_TEXT]


def record_stderr(stream, path, secrets):
    try:
        with stream, path.open("w") as log:
            for line in stream:
                log.write(redact(line, secrets))
                log.flush()
    except (OSError, ValueError):
        pass


class DesktopService:
    def __init__(self, root: str | Path):
        self.root = private_root(root)
        # Child processes use the state folder, never the home folder, as their
        # fallback working directory (see superqode.agents.client).
        os.environ.setdefault("SUPERQODE_STATE_DIR", str(self.root))
        from .app_setup import activate_bundled_extras, publish_cli

        activate_bundled_extras(self.root)
        if os.environ.get("SUPERQODE_APP") == "1":
            publish_cli(self.root)
        from .ownership import Lease

        self._engine_lease = Lease(self.root / "engine.lock")
        self._engine_lease.record(pid=os.getpid())
        self._project_leases = {}
        self._reapers = {}
        self.lock = threading.RLock()
        # Projects with a Git commit, push or branch switch in progress.
        self._ship_projects: set[str] = set()
        self._external_scan_lock = threading.Lock()
        self.db = sqlite3.connect(self.root / "desktop.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, path TEXT UNIQUE, opened REAL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, project TEXT, kind TEXT, title TEXT, status TEXT,
              request TEXT, result TEXT, created REAL, updated REAL);
            CREATE INDEX IF NOT EXISTS jobs_project_kind ON jobs(project,kind,updated);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS remote_routes(id TEXT PRIMARY KEY, project TEXT, route TEXT);
            CREATE TABLE IF NOT EXISTS custom_acp_agents(id TEXT PRIMARY KEY, project TEXT, definition TEXT);
            CREATE TABLE IF NOT EXISTS acp_install_receipts(reference TEXT, digest TEXT, updated REAL, PRIMARY KEY(reference,digest));
            CREATE TABLE IF NOT EXISTS thread_runs(job TEXT PRIMARY KEY, project TEXT, conversation TEXT);
            CREATE INDEX IF NOT EXISTS thread_runs_project ON thread_runs(project,conversation);
            CREATE TABLE IF NOT EXISTS thread_metadata(
              project TEXT, conversation TEXT, title TEXT, pinned INTEGER, archived INTEGER, updated REAL,
              PRIMARY KEY(project,conversation));
            CREATE TABLE IF NOT EXISTS thread_forks(
              id TEXT PRIMARY KEY,source_project TEXT,source_run TEXT,source_thread TEXT,project TEXT,
              path TEXT,branch TEXT,base_commit TEXT,title TEXT,context TEXT,created REAL,state TEXT,
              plan_digest TEXT,issue TEXT);
            CREATE INDEX IF NOT EXISTS thread_forks_project ON thread_forks(project);
            CREATE TABLE IF NOT EXISTS desktop_notifications(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE,job TEXT,project TEXT,status TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS external_session_sources(
              id TEXT PRIMARY KEY,path TEXT UNIQUE,device INTEGER,inode INTEGER,created REAL,
              scanned REAL,report TEXT,provider TEXT);
            CREATE TABLE IF NOT EXISTS external_sessions(
              id TEXT,source TEXT,relative TEXT,metadata TEXT,stamp TEXT,updated REAL,PRIMARY KEY(id,source));
            CREATE INDEX IF NOT EXISTS external_sessions_source ON external_sessions(source);
            CREATE TABLE IF NOT EXISTS local_model_plans(id TEXT PRIMARY KEY,plan TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS studio_reviews(id TEXT PRIMARY KEY,project TEXT,payload TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS studio_check_plans(id TEXT PRIMARY KEY,project TEXT,payload TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS local_model_bindings(project TEXT,harness TEXT,provider TEXT,model TEXT,endpoint TEXT,PRIMARY KEY(project,harness,provider,model));
            """
        )
        from .run_stats import ensure_timing_table

        ensure_timing_table(self.db)
        self.db.execute(
            "UPDATE jobs SET status='interrupted' WHERE status IN ('running','needs_approval','queued','cancelling')"
        )
        self.db.commit()
        self._conversation_roots: dict[str, dict] = {}
        from .thread_branches import reconcile

        reconcile(self)
        self.processes: dict[str, subprocess.Popen] = {}
        self._threads: set[threading.Thread] = set()
        self._closing = False
        self._closed = False
        self.pending: dict[str, str] = {}
        self.credentials: dict[str, str] = {}
        self.remote_connections: dict[str, dict] = {}
        self.vendor_keys: dict[str, str] = {}
        from .authentication import AuthenticationActions

        self.authentication = AuthenticationActions()
        from .task_queue import TaskQueues

        self.task_queues = TaskQueues(self)
        for row in self._all("SELECT id FROM jobs WHERE kind='task' AND status='interrupted'"):
            self._notify(row["id"], "interrupted")
        from .remote_access import RemoteAccess

        self.companion = RemoteAccess(self)
        if self.companion.config.get("enabled"):
            self._background(self.companion.resume)

    def _all(self, query, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(query, args).fetchall()]

    def _background(self, target, *args):
        def execute():
            try:
                target(*args)
            finally:
                with self.lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(target=execute, daemon=True)
        with self.lock:
            self._threads.add(thread)
            try:
                thread.start()
            except BaseException:
                self._threads.discard(thread)
                raise
        return thread

    def job_summaries(self, identity=None, *, include_metadata=True, identities=None):
        """Keep individual run records, with a stable conversation identity for recent rows."""
        columns = (
            "id,project,kind,title,status,created,updated,"
            "json_extract(request,'$.harness') AS harness,"
            "json_extract(request,'$.remote_origin.device') AS phone_origin,"
            "json_extract(request,'$._fork_origin') AS fork_origin"
        )
        rows = (
            (
                self._all(
                    f"SELECT {columns} FROM jobs WHERE id IN ("
                    + ",".join("?" for _ in identities)
                    + ")",
                    identities,
                )
                if identities
                else []
            )
            if identities is not None
            else (
                self._all(f"SELECT {columns} FROM jobs WHERE id=?", (identity,))
                if identity is not None
                else self._all(
                    f"SELECT {columns} FROM jobs WHERE id IN (SELECT id FROM jobs ORDER BY updated DESC LIMIT 100) OR status IN ('running','needs_approval','queued','cancelling') ORDER BY updated DESC"
                )
            )
        )
        nodes = {row["id"]: row for row in rows}
        # Parent links and original titles are immutable. Resolve new runs once,
        # rather than decoding every stored prompt on each GUI status poll.
        if len(self._conversation_roots) > 10_000:
            self._conversation_roots.clear()
        roots = self._conversation_roots
        for row in rows:
            current = row
            chain = []
            seen = set()
            while current["id"] not in roots:
                identity = current["id"]
                if identity in seen:
                    current = row
                    break
                seen.add(identity)
                chain.append(identity)
                records = self._all("SELECT request FROM jobs WHERE id=?", (identity,))
                request = json.loads(records[0]["request"] or "{}") if records else {}
                parent_id = (
                    request.get("parent_id")
                    if current["kind"] == "task"
                    else request.get("source_job")
                    if current["kind"] == "compaction"
                    else None
                )
                if not parent_id:
                    break
                if parent_id not in nodes:
                    found = self._all(f"SELECT {columns} FROM jobs WHERE id=?", (parent_id,))
                    if found:
                        nodes[parent_id] = found[0]
                parent = nodes.get(parent_id)
                if not parent or parent["project"] != row["project"] or parent["kind"] != "task":
                    break
                current = parent
            root = roots.get(current["id"], {key: current[key] for key in ("id", "title")})
            for identity in chain:
                roots[identity] = root
        result = []
        identities = list({roots.get(row["id"], row)["id"] for row in rows})
        metadata = (
            {
                (r["project"], r["conversation"]): r
                for r in self._all(
                    "SELECT * FROM thread_metadata WHERE conversation IN ("
                    + ",".join("?" for _ in identities)
                    + ")",
                    identities,
                )
            }
            if identities and include_metadata
            else {}
        )
        used = {}
        if include_metadata:
            from .threads import index_runs
            from .identities import thread_harnesses

            with self.lock:
                for project in {row["project"] for row in rows}:
                    index_runs(self, project)
                used = thread_harnesses(self, identities)
        for row in rows:
            root = roots.get(row["id"], row)
            summary = {key: value for key, value in row.items() if key != "request"}
            summary["phone_origin"] = row["phone_origin"] or ""
            summary["fork_origin"] = json.loads(row["fork_origin"]) if row["fork_origin"] else None
            summary.update(conversation_id=root["id"], conversation_title=root["title"])
            saved = metadata.get((row["project"], root["id"]), {})
            if saved.get("title"):
                summary["conversation_title"] = saved["title"]
            summary.update(pinned=bool(saved.get("pinned")), archived=bool(saved.get("archived")))
            if row["kind"] == "task" and include_metadata:
                summary["harnesses_used"] = used.get((row["project"], root["id"]), [])
                summary["harness"] = row["harness"] or "core"
            result.append(summary)
        return result

    def _write(self, query, args=()):
        with self.lock:
            self.db.execute(query, args)
            self.db.commit()

    def project(self, project_id: str) -> Path:
        rows = self._all("SELECT path FROM projects WHERE id=?", (project_id,))
        if not rows:
            raise ValueError("Open a project first")
        path = Path(rows[0]["path"]).resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Project folder is no longer available")
        return path

    def open_project(self, path: str):
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Choose a project folder")
        project_id = hashlib.sha256(str(root).encode()).hexdigest()[:20]
        self._write(
            "INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET opened=excluded.opened",
            (project_id, str(root), time.time()),
        )
        forks = self._all(
            "SELECT title,branch,source_project FROM thread_forks WHERE path=?", (str(root),)
        )
        return {
            "id": project_id,
            "path": str(root),
            "name": forks[0]["title"] if forks else root.name,
            **(
                {"branch": forks[0]["branch"], "source_project": forks[0]["source_project"]}
                if forks
                else {}
            ),
        }

    def append(self, job_id: str, event: dict):
        # Wall-clock time the engine recorded the event, for timestamps in the app.
        at = time.time()
        if isinstance(event, dict) and "at" not in event:
            event = {**event, "at": at}
        raw = json.dumps(event, default=str, ensure_ascii=False)
        if len(raw) > 64_000:
            if event.get("type") == "approval":
                data = event.get("data", {})
                tool = data.get("tool", {})
                description = json.dumps(tool, default=str, ensure_ascii=False)
                event = {
                    "type": "approval",
                    "data": {
                        "request_id": data.get("request_id"),
                        "preview_truncated": True,
                        "tool": {
                            "title": str(tool.get("title", "Permission request"))[:300]
                            if isinstance(tool, dict)
                            else "Permission request",
                            "preview": description[:16_000],
                            "request_sha256": hashlib.sha256(description.encode()).hexdigest(),
                        },
                    },
                }
            else:
                event = {"type": "output", "data": {"text": raw[:63_000], "truncated": True}}
            event["at"] = at
            raw = json.dumps(event, ensure_ascii=False)
        self._write("INSERT INTO events(job,payload) VALUES(?,?)", (job_id, raw))

    def _status(self, job_id, status):
        self._write("UPDATE jobs SET status=?,updated=? WHERE id=?", (status, time.time(), job_id))
        self._mark_finished(job_id, status)
        self._notify(job_id, status)

    def _mark_started(self, job_id, at):
        self._write(
            "INSERT OR IGNORE INTO job_timing(job,started,finished) VALUES(?,?,NULL)",
            (job_id, at),
        )

    def _mark_finished(self, job_id, status):
        from .run_stats import TERMINAL_STATUSES

        if status not in TERMINAL_STATUSES:
            return
        self._write(
            "INSERT INTO job_timing(job,started,finished) VALUES(?,NULL,?) "
            "ON CONFLICT(job) DO UPDATE SET finished=COALESCE(job_timing.finished,excluded.finished)",
            (job_id, time.time()),
        )

    def _notify(self, job_id, status):
        if status not in {"needs_approval", "completed", "failed", "interrupted"}:
            return
        rows = self._all("SELECT project,kind FROM jobs WHERE id=?", (job_id,))
        if not rows or rows[0]["kind"] != "task":
            return
        request = self.pending.get(job_id, "") if status == "needs_approval" else ""
        key = hashlib.sha256((job_id + status + str(request)).encode()).hexdigest()
        self._write(
            "INSERT OR IGNORE INTO desktop_notifications(event_key,job,project,status,created) VALUES(?,?,?,?,?)",
            (key, job_id, rows[0]["project"], status, time.time()),
        )

    def _seal_checkpoint(self, job_id):
        try:
            job = self.dispatch("jobs.get", {"id": job_id})
            baseline = next(
                (
                    event["data"].get("id")
                    for event in reversed(job["events"])
                    if event["type"] == "checkpoint" and event["data"].get("phase") == "baseline"
                ),
                None,
            )
            if baseline:
                from .checkpoints import manager_for

                manager = manager_for(self.project(job["project"]))
                task = manager._tasks.get(baseline)
                if task and not task.finished:
                    task.finish([])
                    manager.seal_task(task)
        except (ValueError, OSError):
            pass

    def _watch(self, job_id, process, secrets=(), logger=None):
        from .run_stats import UsageCollector

        result = None
        error = None
        usage = UsageCollector()
        try:
            for line in process.stdout:
                try:
                    event = redact(json.loads(line), secrets)
                except ValueError:
                    self.append(
                        job_id, {"type": "output", "data": {"text": redact(line[:4000], secrets)}}
                    )
                    continue
                self.append(job_id, event)
                usage.observe(event)
                if event.get("type") == "approval":
                    with self.lock:
                        self.pending[job_id] = event["data"]["request_id"]
                    self._status(job_id, "needs_approval")
                elif event.get("type") == "result":
                    result = event.get("data")
                elif event.get("type") == "error":
                    error = event.get("data", {}).get("message", "Execution failed")
            code = process.wait()
            reaped = self._reapers.get(job_id)
            if reaped:
                reaped.wait()
            if logger:
                logger.join(timeout=2)
            self._seal_checkpoint(job_id)
            current = self._all("SELECT status FROM jobs WHERE id=?", (job_id,))[0]["status"]
            if current == "cancelled":
                return
            if current == "cancelling" and result is None:
                error = (
                    error or "Remote cancellation ended without acknowledgement; check the server."
                )
            if not isinstance(result, dict):
                error = error or "Worker exited without a valid terminal result"
                result = None
            status = "failed" if code or error else "completed"
            if isinstance(result, dict) and result.get("status") == "cancelled":
                status = "cancelled"
            if isinstance(result, dict) and result.get("regressed"):
                status = "regressed"
            if isinstance(result, dict) and result.get("status") in {"failed", "error"}:
                status = "failed"
            # Keep the reported usage with the run so history can show it later.
            summary = usage.result(result)
            if isinstance(result, dict) and summary:
                result = {**result, "usage_summary": summary}
            with self.lock:
                self.processes.pop(job_id, None)
                self._write(
                    "UPDATE jobs SET status=?,result=?,updated=? WHERE id=?",
                    (
                        status,
                        json.dumps(
                            result
                            if result is not None
                            else {"error": error or "No result recorded"}
                        ),
                        time.time(),
                        job_id,
                    ),
                )
                lease = self._project_leases.pop(job_id, None)
                if lease:
                    lease.close()
                self._mark_finished(job_id, status)
                self._notify(job_id, status)
        except Exception as exc:
            self.append(job_id, {"type": "error", "data": {"message": redact(str(exc), secrets)}})
            self._status(job_id, "failed")
        finally:
            self._seal_checkpoint(job_id)
            with self.lock:
                self.processes.pop(job_id, None)
                self.pending.pop(job_id, None)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
            reaped = self._reapers.pop(job_id, None)
            if reaped:
                reaped.wait()
            lease = self._project_leases.pop(job_id, None)
            if lease:
                lease.close()
            self.task_queues.finished(job_id)

    def start(self, project_id: str, kind: str, params: dict):
        if kind not in {
            "task",
            "evaluation",
            "optimization",
            "check",
            "tool",
            "compaction",
            "tuning",
            "local",
            "studio",
        }:
            raise ValueError("Unknown job type")
        with self.lock:
            if self._closing:
                raise ValueError("The desktop engine is shutting down")
            root = self.project(project_id)
            if project_id in self._ship_projects:
                raise ValueError(
                    "A Git commit or push is in progress for this project. Start the run when it finishes."
                )
            if kind in {"evaluation", "optimization"}:
                from .experiments import reviewed_suite

                params = {**params, "_suite_content": reviewed_suite(root, params)}
            if kind != "local" and self._all(
                "SELECT id FROM jobs WHERE kind='local' AND status IN ('running','queued','needs_approval','cancelling') AND json_extract(request,'$.local_plan.action') IN ('serve','stop','install')"
            ):
                raise ValueError(
                    "Wait for inference-server setup to finish before starting other work"
                )
            job_id = uuid.uuid4().hex
            key = str(params.get("command_id") or job_id)
            for old in self._all("SELECT id,request FROM jobs WHERE project=?", (project_id,)):
                if json.loads(old["request"]).get("command_id") == key:
                    return {"id": old["id"]}
            # A stopped process may still be reaping; keep its project writer lease.
            if any(
                row["id"] in self.processes
                for row in self._all("SELECT id FROM jobs WHERE project=?", (project_id,))
            ):
                raise ValueError("Finish or stop the active project run before starting another")
            # A single workspace writer prevents simultaneous experiments and edits.
            if self._all(
                "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
                (project_id,),
            ):
                raise ValueError("Finish or stop the active project run before starting another")
            if len(self.processes) >= 4:
                raise ValueError("Four runs are already active")
            params = {
                **params,
                "command_id": key,
                "cwd": str(root),
                "kind": kind,
                "state_root": str(self.root),
                "job_id": job_id,
            }
            tool_plan = None
            if kind == "tool":
                from .tools import tool_arguments

                tool_plan = tool_arguments(
                    str(params.get("action") or ""), params.get("values") or {}
                )
                params["values"] = tool_plan["recorded_values"]
            params.pop("session_id", None)
            params.pop("_remote_previous", None)
            params.pop("_desktop_route", None)
            params.pop("_desktop_connection", None)
            params.pop("_local_harness", None)
            params.pop("image_snapshots", None)
            params.pop("_chat_history", None)
            params.pop("_handoff_context", None)
            params.pop("_continuity", None)
            params.pop("expected_digest", None)
            params.pop("_thread_harness", None)
            params.pop("_fork_origin", None)
            fork = self._all(
                "SELECT * FROM thread_forks WHERE project=? AND state='ready'", (project_id,)
            )
            if fork:
                from .thread_branches import validate, public

                validate(self, fork[0])
                params["_fork_origin"] = public(fork[0])
            if kind == "compaction":
                source = self.dispatch("jobs.get", {"id": params["source_job"]})
                if (
                    source["project"] != project_id
                    or source["kind"] != "task"
                    or source["status"] != "completed"
                    or not (source.get("result") or {}).get("native_continuity")
                    or source["request"].get("interaction_mode") == "chat"
                ):
                    raise ValueError("Choose a completed built-in coding conversation to compact")
                from superqode.harness.catalog import resolve_harness

                if (
                    resolve_harness(
                        "core"
                        if source["request"].get("_local_harness")
                        else source["request"]["harness"],
                        root=root,
                    ).spec.runtime.backend
                    != "builtin"
                ):
                    raise ValueError(
                        "This harness owns its context; use its advertised native command"
                    )
                params.update(
                    {key: source["request"][key] for key in ("harness", "provider", "model")}
                )
                if source["request"].get("_local_harness"):
                    from .local_harnesses import apply_route

                    apply_route(self, project_id, params)
                params["session_id"] = source["result"]["session_id"]
                params["expected_digest"] = source["result"]["harness_digest"]
                if len(str(params.get("instructions") or "")) > 4000:
                    raise ValueError("Use compaction instructions up to 4,000 characters")
            if kind == "task":
                reference = str(params.get("harness") or "core")
                if reference.startswith("local-harness:"):
                    from .local_harnesses import apply_route

                    apply_route(self, project_id, params)
                elif reference.startswith("connection:"):
                    from .connect_workflow import profile_route

                    connection = profile_route(root, reference.removeprefix("connection:"))
                    if not connection["available"]:
                        raise ValueError(
                            connection["issue"] or "Set up this vendor connection first"
                        )
                    params[
                        "_desktop_route"
                        if connection.get("desktop_kind") == "acp"
                        else "_desktop_connection"
                    ] = connection
                    params["provider"] = "agent"
                elif reference.startswith("vendor-key:"):
                    from .configuration import vendor_key_route

                    route = vendor_key_route(root, reference.removeprefix("vendor-key:"))
                    if not route["available"]:
                        raise ValueError("Install this vendor's coding agent first")
                    if route["entry_id"] not in self.vendor_keys and not any(
                        os.environ.get(k) for k in route["env_vars"]
                    ):
                        raise ValueError("Connect this vendor API key before coding")
                    params[
                        "_desktop_route"
                        if route["desktop_kind"] == "acp"
                        else "_desktop_connection"
                    ] = route
                    params["provider"] = "agent"
                elif reference.startswith("attach:"):
                    from .connect_workflow import attachment_route, attachment_environment

                    attachment = attachment_route(root, reference.removeprefix("attach:"))
                    if not attachment["available"]:
                        raise ValueError(attachment["issue"] or "Install this ACP harness first")
                    attachment_environment(
                        attachment, str(params.get("provider") or ""), self.credentials
                    )
                    params[
                        "_desktop_connection"
                        if attachment.get("kind") == "runtime"
                        else "_desktop_route"
                    ] = attachment
                elif reference.startswith("remote:"):
                    connection = self.remote_connections.get(reference)
                    if not connection or connection["project"] != project_id:
                        raise ValueError("Reconnect this protocol server from Connect")
                    params["_desktop_connection"] = connection["route"]
                    params["provider"] = "agent"
                elif reference.startswith("acp:") or any(
                    route["id"] == reference for route in acp_routes(root)
                ):
                    params["_desktop_route"] = self.resolve_desktop_acp(project_id, root, reference)
                    params["provider"] = "agent"
                else:
                    from superqode.harness.catalog import resolve_harness

                    resolved = resolve_harness(reference, root=root)
                    params["_thread_harness"] = {
                        "name": resolved.display_name,
                        "runtime": resolved.spec.runtime.backend,
                    }
            if kind == "task" and params.get("parent_id"):
                from .conversations import prepare_continuation

                prepare_continuation(self, params, project_id, root)
                if self._all(
                    "SELECT conversation FROM thread_metadata WHERE project=? AND conversation=? AND archived=1",
                    (project_id, params["_continuity"]["conversation_id"]),
                ):
                    raise ValueError("Restore this archived thread before continuing it")
            if kind == "task":
                from .session_controls import accept, enforces_session_controls

                accept(params)
                external = bool(params.get("_desktop_route") or params.get("_desktop_connection"))
                runtime = (params.get("_thread_harness") or {}).get("runtime")
                enforced = (not external) and enforces_session_controls(runtime)
                if params.get("interaction_mode") == "plan" and not enforced:
                    raise ValueError(
                        "Plan mode applies to a SuperQode harness that can enforce it. "
                        "This agent uses its own tools and permissions."
                    )
                if params.get("permission_mode") and not enforced:
                    if params.get("interaction_mode") == "chat":
                        params.pop("permission_mode", None)
                    else:
                        raise ValueError(
                            "Ask, Auto-edit, and Full apply to a SuperQode harness that can "
                            "enforce them. This agent uses its own permissions."
                        )
                if params.get("interaction_mode") == "chat" and external:
                    raise ValueError("Direct chat requires a local or BYOK model connection")
                window = int(params.get("context_window") or 0)
                if window < 0 or window > 10_000_000:
                    raise ValueError("Context window must be 0 (auto) or up to 10,000,000 tokens")
                params["context_window"] = window
                prompt = str(params.get("prompt") or "").strip()
                if not prompt or len(prompt) > 100_000:
                    raise ValueError("Enter a task of up to 100,000 characters")
                if not (params.get("_desktop_route") or params.get("_desktop_connection")) and (
                    not params.get("provider") or not params.get("model")
                ):
                    raise ValueError("Choose a provider and model first")
                if params.get("image_ids"):
                    from .images import resolve_images

                    if params.get("_desktop_connection"):
                        raise ValueError(
                            "This connection does not accept image attachments; choose a vision-capable ACP agent or a supported native harness"
                        )
                    if (
                        not params.get("_desktop_route")
                        and params.get("interaction_mode") != "chat"
                    ):
                        from superqode.harness.catalog import resolve_harness

                        backend = resolve_harness(
                            "core"
                            if params.get("_local_harness")
                            else params.get("harness") or "core",
                            root=root,
                        ).spec.runtime.backend
                        if backend not in {"builtin", "pipy", "codegem"}:
                            raise ValueError(
                                "This harness backend does not accept image attachments"
                            )
                    params["image_snapshots"] = resolve_images(self.root, params["image_ids"])
                title = prompt[:90]
                if params.get("context_files") and params.get("interaction_mode") != "chat":
                    from .context import attach_project_text

                    params["prompt"], params["context_snapshot"] = attach_project_text(
                        root, prompt, params["context_files"]
                    )

            else:
                title = {
                    "tuning": "Routing decision tuning",
                    "evaluation": "Harness evaluation",
                    "optimization": "Harness optimization",
                    "check": "Project check",
                    "compaction": "Compact model context",
                    "tool": tool_plan["title"] if tool_plan else "Advanced workflow",
                    "local": params.get("local_plan", {}).get("title", "Local model setup"),
                    "studio": params.get("studio_plan", {}).get("title", "Harness check"),
                }[kind]
            from .ownership import Lease, project_lease_path

            lease = Lease(project_lease_path(self.root, root))
            self._project_leases[job_id] = lease
            now = time.time()
            try:
                self._write(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        project_id,
                        kind,
                        title,
                        "running",
                        json.dumps(params),
                        None,
                        now,
                        now,
                    ),
                )
                self._mark_started(job_id, now)
            except Exception:
                self._project_leases.pop(job_id, None)
                lease.close()
                raise
            process = None
            try:
                log_path = self.root / f"{job_id}.log"
                remote_config = self.remote_connections.get(str(params.get("harness")), {}).get(
                    "config", {}
                )
                from .connect_workflow import connection_secrets

                remote_secrets = connection_secrets(remote_config)
                secrets = tuple(
                    sorted(
                        set(self.credentials.values()) | {s for s in remote_secrets if s},
                        key=len,
                        reverse=True,
                    )
                )
                from .environment import job_environment, selected_providers
                from superqode.providers.registry import PROVIDERS

                providers = selected_providers(kind, params)
                credential_env = (
                    {}
                    if kind == "check"
                    or (params.get("_desktop_route") or params.get("_desktop_connection"))
                    else self.credential_environment(None if kind == "tool" else providers)
                )
                if str(params.get("harness", "")).startswith("attach:"):
                    from .connect_workflow import attachment_environment

                    credential_env = attachment_environment(
                        params.get("_desktop_route") or params["_desktop_connection"],
                        params["provider"],
                        self.credentials,
                    )
                    secrets = tuple(
                        sorted(set(secrets) | set(credential_env.values()), key=len, reverse=True)
                    )
                if str(params.get("harness", "")).startswith("vendor-key:"):
                    route = params.get("_desktop_route") or params["_desktop_connection"]
                    key = self.vendor_keys.get(route["entry_id"]) or next(
                        (os.environ[k] for k in route["env_vars"] if os.environ.get(k)), ""
                    )
                    credential_env = {name: key for name in route["env_vars"]}
                    secrets = tuple(sorted(set(secrets) | {key}, key=len, reverse=True))
                if (
                    "systemone" in str(params.get("harness") or "")
                    and "systemone" in self.vendor_keys
                    and not (params.get("_desktop_route") or params.get("_desktop_connection"))
                ):
                    credential_env["TYPESAFE_API_KEY"] = self.vendor_keys["systemone"]
                    secrets = tuple(set(secrets) | {self.vendor_keys["systemone"]})
                if tool_plan:
                    secrets = tuple(set(secrets) | set(tool_plan["secrets"]))
                from .local_models import binding as local_binding

                binding = local_binding(
                    self,
                    project_id,
                    params.get("harness", ""),
                    params.get("provider", ""),
                    params.get("model", ""),
                )
                if binding and not params.get("_local_harness"):
                    provider = PROVIDERS.get(params["provider"])
                    if provider and provider.base_url_env:
                        endpoint = binding[0]["endpoint"]
                        credential_env[provider.base_url_env] = (
                            endpoint.removesuffix("/v1") if provider.id == "ollama" else endpoint
                        )
                        if provider.id == "ollama":
                            credential_env["OLLAMA_HOST"] = endpoint.removesuffix("/v1")
                if kind == "check":
                    credential_env = {}
                    remote_config = {}
                allowed = {
                    name
                    for provider in providers
                    if provider in PROVIDERS
                    for name in (PROVIDERS[provider].env_vars or [])
                }
                if kind == "tuning":
                    allowed.add("TYPESAFE_API_KEY")
                if (
                    kind == "local"
                    and params.get("local_plan", {}).get("action") == "download"
                    and params.get("local_plan", {}).get("source") == "hf"
                ):
                    allowed.update({"HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"})
                # External agents retain their own authentication contract. Plain
                # project checks never receive that environment or app keys.
                inherited = (
                    os.environ
                    if kind == "tool"
                    or params.get("_desktop_route")
                    or params.get("_desktop_connection")
                    else job_environment(
                        os.environ, credential_env, check=kind == "check", allowed=allowed
                    )
                )
                if params.get("_local_harness"):
                    from .local_harnesses import worker_environment

                    credential_env = {}
                    inherited = worker_environment(os.environ, params["_local_harness"])
                from superqode.tools.env_policy import is_secret_name
                from .app_setup import engine_pythonpath

                key_vars = set(credential_env) | {
                    name for name in inherited if is_secret_name(name) and name != "SSH_AUTH_SOCK"
                }
                secrets = tuple(
                    sorted(
                        set(secrets)
                        | {inherited[name] for name in key_vars if inherited.get(name)},
                        key=len,
                        reverse=True,
                    )
                )
                process = subprocess.Popen(
                    [sys.executable, "-u", "-m", "superqode.desktop_service.worker"],
                    cwd=root,
                    env={
                        **inherited,
                        **credential_env,
                        "SUPERQODE_DESKTOP_KEY_VARS": json.dumps(sorted(key_vars)),
                        "SUPERQODE_DESKTOP_REMOTE": json.dumps(remote_config),
                        "SUPERQODE_DESKTOP_TOOL_ARGV": json.dumps(
                            tool_plan["argv"] if tool_plan else []
                        ),
                        "SUPERQODE_DESKTOP_TOOL_SECRETS": json.dumps(
                            tool_plan["secrets"] if tool_plan else []
                        ),
                        "PYTHONUNBUFFERED": "1",
                        "PYTHONPATH": engine_pythonpath(self.root),
                        "SUPERQODE_DESKTOP_PARENT_PID": str(os.getpid()),
                        "SUPERQODE_DESKTOP_LEASE_FD": str(lease.fd),
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                    pass_fds=(lease.fd,),
                )
                lease.record(pid=process.pid, job=job_id, project=project_id)
                from .ownership import reap_children

                reaped = threading.Event()
                self._reapers[job_id] = reaped
                self._background(reap_children, process, reaped)
                logger = self._background(record_stderr, process.stderr, log_path, secrets)
                self.processes[job_id] = process
                process.stdin.write(json.dumps(params) + "\n")
                process.stdin.flush()
                self._background(self._watch, job_id, process, secrets, logger)
            except Exception:
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream:
                            stream.close()
                    self.processes.pop(job_id, None)
                self._status(job_id, "failed")
                lease = self._project_leases.pop(job_id, None)
                if lease:
                    lease.close()
                raise
            return {"id": job_id}

    def credential_environment(self, providers=None):
        from .connections import environment

        with self.lock:
            return environment(
                {
                    key: value
                    for key, value in self.credentials.items()
                    if providers is None or key in providers
                }
            )

    def dispatch(self, method: str, params: dict):
        if method.startswith("remote."):
            return self.companion.handle(method, params)
        if method == "engine.status":
            return {
                "mode": "attached",
                "pid": os.getpid(),
                "continuity": "UI loss stops attached workers",
            }
        if method in {
            "files.create",
            "files.write",
            "git.stage",
            "git.stage_file",
            "git.unstage_file",
            "git.commit",
            "checkpoints.restore",
            "checkpoints.undo",
            "checkpoints.redo",
        }:
            # Keep the ownership check and mutation atomic with respect to start().
            with self.lock:
                return self._dispatch(method, params)
        return self._dispatch(method, params)

    def _dispatch(self, method: str, params: dict):
        if method.startswith("ship."):
            from .ship import MUTATIONS, action as ship_action, assert_idle

            project_id = params["project"]
            root = self.project(project_id)
            if method not in MUTATIONS:
                return ship_action(self, root, method, params)
            from .ownership import Lease, project_lease_path

            # Check and hold atomically with respect to start(): while the
            # writer lease is held, no run can start in this project, and a
            # run that already holds it makes the lease attempt fail here.
            with self.lock:
                if project_id in self._ship_projects:
                    raise ValueError("Another Git action is already running for this project")
                assert_idle(self, project_id)
                try:
                    lease = Lease(project_lease_path(self.root, root))
                except ValueError:
                    raise ValueError(
                        "A run or worker still owns this project. Wait for it to stop before committing or pushing."
                    ) from None
                self._ship_projects.add(project_id)
            try:
                return ship_action(self, root, method, params)
            finally:
                with self.lock:
                    self._ship_projects.discard(project_id)
                lease.close()
        if method == "turns.changes":
            from .turn_changes import summary

            return summary(self, self.project(params["project"]), str(params.get("job") or ""))
        if method in {"review.list", "review.diff", "review.feedback", "review.stage"}:
            from .review import action

            with self.lock:
                if method == "review.stage":
                    from .ownership import assert_project_idle

                    assert_project_idle(self, params["project"])
                    jobs = self._all(
                        "SELECT id,status FROM jobs WHERE project=?", (params["project"],)
                    )
                    if any(row["status"] in ACTIVE or row["id"] in self.processes for row in jobs):
                        raise ValueError(
                            "Finish or stop project work before staging reviewed changes"
                        )
                return action(self, self.project(params["project"]), method, params)
        if method in {
            "files.create",
            "files.write",
            "git.stage",
            "git.stage_file",
            "git.unstage_file",
            "git.commit",
        } or method.startswith("checkpoints."):
            with self.lock:
                if any(
                    row["id"] in self.processes
                    for row in self._all(
                        "SELECT id FROM jobs WHERE project=?", (params.get("project"),)
                    )
                ):
                    raise ValueError(
                        "Finish or stop the active project run before changing project files"
                    )
                if method in {
                    "files.create",
                    "files.write",
                    "git.stage",
                    "git.stage_file",
                    "git.unstage_file",
                    "git.commit",
                } or method in {"checkpoints.restore", "checkpoints.undo", "checkpoints.redo"}:
                    from .ownership import assert_project_idle

                    assert_project_idle(self, params["project"])

        if method.startswith("checkpoints."):
            from .checkpoints import action

            with self.lock:
                if self._all(
                    "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','cancelling')",
                    (params["project"],),
                ):
                    raise ValueError(
                        "Finish or stop project work before inspecting or restoring checkpoints"
                    )
                return action(self.project(params["project"]), method, params)
        if method == "workorders.snapshot":
            from superqode.workorders.store import WorkOrderStore
            from superqode.workorders.cockpit import build_cockpit_snapshot

            root = self.project(params["project"])
            path = (root / ".superqode/workorders/store.sqlite3").resolve()
            if not path.is_relative_to(root):
                raise ValueError("WorkOrder storage must stay inside this project")
            if not path.exists():
                return {"items": []}
            store = WorkOrderStore.read_only(path)
            return {
                "items": [
                    build_cockpit_snapshot(store, item.work_order_id)
                    for item in store.list(limit=100)
                ]
            }
        if method == "context.compact":
            return self.start(params["project"], "compaction", params)
        if method == "context.preview":
            from .context import attach_project_text

            root = self.project(params["project"])
            if params.get("interaction_mode") == "chat":
                return {
                    "prompt": str(params.get("prompt") or ""),
                    "files": [],
                    "harness": {},
                    "image_count": len(params.get("image_ids") or []),
                }
            prompt, files = attach_project_text(
                root, str(params.get("prompt") or ""), params.get("context_files") or []
            )
            definition = {}
            if not str(params.get("harness") or "").startswith(
                ("acp:", "connection:", "remote:", "vendor-key:", "attach:", "local-harness:")
            ):
                from superqode.harness.catalog import resolve_harness
                from superqode.harness.loader import harness_spec_to_dict

                definition = harness_spec_to_dict(
                    resolve_harness(params.get("harness") or "core", root=root).spec
                )
            return {
                "prompt": prompt,
                "files": files,
                "harness": definition,
                "image_count": len(params.get("image_ids") or []),
            }
        if method == "images.stage":
            from .images import stage_image

            return stage_image(self.root, str(params["path"]))
        if method.startswith("queue."):
            return self.task_queues.dispatch(method, params)
        if method in {"providers.check", "local.harnesses.status"} and str(
            params.get("harness") or ""
        ).startswith("local-harness:"):
            from .local_harnesses import _profile, preflight

            profile = _profile(self, params["project"], params["harness"])
            plan = preflight(self, profile)
            ready = plan["ready"] and plan.get("digest") == profile["digest"]
            return {
                "ready": ready,
                "state": "local",
                "message": plan.get("reason")
                or (
                    "Local harness preflight passed. No model prompt was sent."
                    if ready
                    else "Local configuration changed. Return to Advanced."
                ),
            }
        if method in {"providers.list", "providers.credentials.set", "providers.check"}:
            from .connections import install, inspect_route, list_connections

            with self.lock:
                if method == "providers.credentials.set":
                    return install(self.credentials, params)
                credentials = dict(self.credentials)
            if method == "providers.check":
                if params.get("project") and params.get("harness"):
                    from .local_models import binding as local_binding

                    binding = local_binding(
                        self,
                        params["project"],
                        params["harness"],
                        params.get("provider", ""),
                        params.get("model", ""),
                    )
                    if binding:
                        from .local_models import available
                        from superqode.local.workbench import PROVIDERS as LOCAL_PROVIDERS

                        engine = next(
                            (
                                key
                                for key, value in LOCAL_PROVIDERS.items()
                                if value == params.get("provider")
                            ),
                            None,
                        )
                        if engine:
                            selected = available(engine)
                            ready = (
                                params.get("model") in selected["models"]
                                and binding[0]["endpoint"] == selected["endpoint"]
                            )
                            return {
                                "ready": ready,
                                "state": "local-model-advertised" if ready else "model-unavailable",
                                "endpoint": binding[0]["endpoint"],
                                "message": "Model checked against the selected loopback endpoint. Test inference and tool use separately."
                                if ready
                                else "The selected local model/server changed. Refresh Local AI.",
                            }
                return inspect_route(credentials, params)
            return list_connections(credentials)
        if method == "hello":
            from superqode import __version__

            return {
                "version": __version__,
                "protocol": 1,
                "state": str(self.root),
                "platform": sys.platform,
            }
        if method == "projects.open":
            return self.open_project(params["path"])
        if method == "projects.list":
            rows = self._all(
                "SELECT * FROM projects WHERE id!='local-model-workspace' ORDER BY opened DESC"
            )
            forks = {
                row["project"]: row
                for row in self._all(
                    "SELECT project,title,branch,source_project FROM thread_forks WHERE state='ready'"
                )
            }
            return [
                {
                    **row,
                    "name": forks[row["id"]]["title"]
                    if row["id"] in forks
                    else Path(row["path"]).name,
                    **(
                        {
                            "branch": forks[row["id"]]["branch"],
                            "source_project": forks[row["id"]]["source_project"],
                        }
                        if row["id"] in forks
                        else {}
                    ),
                }
                for row in rows
            ]
        if method == "settings.get":
            return {r["key"]: json.loads(r["value"]) for r in self._all("SELECT * FROM settings")}
        if method == "settings.set":
            if params["key"] not in {
                "theme",
                "provider",
                "model",
                "harness",
                "drafts",
                "credential_providers",
            }:
                raise ValueError("Unknown preference")
            if params["key"] == "credential_providers":
                from .connections import key_provider

                if not isinstance(params["value"], list) or len(params["value"]) > 100:
                    raise ValueError("Invalid credential provider index")
                for provider in params["value"]:
                    key_provider(str(provider))
            self._write(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                (params["key"], json.dumps(params["value"])),
            )
            return {"ok": True}
        if method == "models.list":
            from superqode.local.inventory import inventory_models
            from superqode.local.hardware import detect_hardware

            return {
                "models": [asdict(m) for m in inventory_models()],
                "hardware": asdict(detect_hardware()),
            }
        if method.startswith("local.harnesses."):
            from . import local_harnesses

            if method == "local.harnesses.catalog":
                return local_harnesses.catalog(self, params["project"])
            if method == "local.harnesses.preflight":
                return local_harnesses.preflight(self, params)
            if method == "local.harnesses.launch":
                return local_harnesses.launch(self, params)
            raise ValueError("Unknown Advanced local harness method")
        if method.startswith("local.models."):
            from . import local_models
            from . import hub_access
            from superqode.local import workbench

            if method.startswith("local.models.quickstart."):
                from . import local_quickstart

                if method == "local.models.quickstart.catalog":
                    return local_quickstart.catalog(self, params["project"])
                if method == "local.models.quickstart.prepare":
                    return local_quickstart.prepare(self, params)
                if method == "local.models.quickstart.start":
                    return local_quickstart.start(self, params)

            if method == "local.models.storage":
                from superqode.local import storage

                return storage.status()
            if method == "local.models.storage.set":
                return local_models.save_storage(self, params)
            if method == "local.models.hub.status":
                return hub_access.status(self)
            if method == "local.models.hub.verify":
                return hub_access.verify(self, params.get("token"))
            if method == "local.models.compatibility":
                return local_models.compatibility(self, params.get("project"))

            if method == "local.models.overview":
                return local_models.overview(self)
            if method == "local.models.ds4":
                return local_models.ds4_configuration(self)
            if method == "local.models.servers":
                return local_models.servers(self)
            if method == "local.models.search":
                return workbench.search(
                    params.get("query", ""),
                    params.get("source", "recommended"),
                    params.get("format", "gguf"),
                    token=hub_access.token(self),
                )
            if method == "local.models.files":
                return workbench.manifest(params["model"], token=hub_access.token(self))
            if method == "local.models.prepare":
                return local_models.prepare(self, params)
            if method == "local.models.start":
                return local_models.start(self, params)
            if method == "local.models.jobs":
                return local_models.jobs(self)
            if method == "local.models.harnesses":
                return local_models.harnesses(self, params["project"])
            if method == "local.models.install":
                return local_models.install(self, params)
            if method == "local.models.install.status":
                return local_models.install_status(self, params)
            if method == "local.models.warm":
                return local_models.warm(self, params)
            if method == "local.models.warm.status":
                return local_models.warm_status(self, params)
            if method == "local.models.installed":
                return local_models.installed(self)
            if method == "local.models.available":
                return local_models.available(params["engine"])
            if method == "local.models.use":
                return local_models.use(self, params)
            if method == "local.models.clear_binding":
                return local_models.clear_binding(self, params)
        if method == "capabilities":
            try:
                optimizer = __import__(
                    "gepa.optimize_anything", fromlist=["OptimizeAnythingConfig"]
                )
                omni = hasattr(optimizer, "OptimizeAnythingConfig") and hasattr(
                    optimizer, "optimize_best_of"
                )
            except ImportError:
                omni = False
            return {
                "omni": omni,
                "metaharness": __import__("shutil").which("metaharness") is not None,
                "task": True,
                "evaluation": True,
                "remote": False,
                "execution": "Local Mac",
                "continuity": "Recorded history; provider resume varies",
            }
        if method == "jobs.list":
            return self.job_summaries()
        if method == "activity.list":
            from .activity import list_activity

            return list_activity(self, params)
        if method.startswith("external."):
            from . import external_sessions

            if method == "external.sources.list":
                return external_sessions.list_sources(self)
            if method == "external.sources.add":
                return external_sessions.add_source(self, params)
            if method == "external.sources.remove":
                return external_sessions.remove_source(self, params["id"])
            if method == "external.sources.scan":
                return external_sessions.scan_source(self, params["id"])
            if method == "external.sessions.list":
                return external_sessions.list_sessions(self, params)
            if method == "external.sessions.preview":
                return external_sessions.preview_session(self, params)
            if method == "external.sessions.reveal":
                return external_sessions.reveal_session(self, params)
        if method == "notifications.poll":
            after = params.get("after", -1)
            if type(after) is not int or after < -1:
                raise ValueError("Use a valid notification cursor")
            attention = self._all(
                "SELECT COUNT(*) AS count FROM jobs WHERE kind='task' AND status='needs_approval'"
            )[0]["count"]
            if after == -1:
                latest = self._all("SELECT COALESCE(MAX(seq),0) AS seq FROM desktop_notifications")[
                    0
                ]["seq"]
                return {"items": [], "cursor": latest, "attention_count": attention}
            rows = self._all(
                "SELECT seq,job,project,status,created FROM desktop_notifications WHERE seq>? ORDER BY seq LIMIT 50",
                (after,),
            )
            return {
                "items": rows,
                "cursor": rows[-1]["seq"] if rows else after,
                "attention_count": attention,
            }
        if method == "threads.list":
            from .threads import list_threads

            return list_threads(self, params)
        if method.startswith("threads.fork."):
            from . import thread_branches

            if method == "threads.fork.preview":
                return thread_branches.preview(self, params)
            if method == "threads.fork.create":
                return thread_branches.create(self, params)
            if method == "threads.fork.list":
                return thread_branches.list_forks(self, params["project"])
            if method == "threads.fork.context":
                row = thread_branches.lookup(self, params["id"])
                thread_branches.validate(self, row)
                return {"text": row["context"], **thread_branches.public(row)}
            if method == "threads.fork.merge.plan":
                return thread_branches.merge_plan(self, params["id"])
            if method == "threads.fork.merge":
                return thread_branches.merge(self, params)
        if method == "threads.update":
            from .threads import update_thread

            return update_thread(self, params)
        if method == "threads.delete":
            from .threads import delete_thread

            return delete_thread(self, params)
        if method == "threads.get":
            from .threads import get_thread

            return get_thread(self, params)
        if method == "conversations.get":
            from .conversations import history

            return history(self, params["id"], params.get("before"))
        if method == "threads.send.preview":
            from .conversations import send_preview

            return send_preview(self, params, self.project(params["project"]))
        if method == "conversations.share":
            from .conversations import share_context

            self.project(params["project"])
            return share_context(self, params["id"], params["project"])
        if method == "jobs.get":
            rows = self._all("SELECT * FROM jobs WHERE id=?", (params["id"],))
            if not rows:
                raise ValueError("Run not found")
            row = rows[0]
            summary = self.job_summaries(params["id"])[0]
            row["conversation_id"] = summary["conversation_id"]
            row["conversation_title"] = summary["conversation_title"]
            row["pinned"] = summary["pinned"]
            row["archived"] = summary["archived"]
            row["harnesses_used"] = summary.get("harnesses_used", [])
            row["harness"] = summary.get("harness")
            row["fork_origin"] = summary.get("fork_origin")
            row["request"] = json.loads(row["request"])
            row["result"] = json.loads(row["result"]) if row["result"] else None
            from .run_stats import timing

            row.update(timing(self, row))
            if row["kind"] in {"evaluation", "optimization"} and row["result"] is not None:
                from .evaluation_review import with_evaluation_comparison

                row["result"] = with_evaluation_comparison(row["result"])
                if row["kind"] == "optimization":
                    from superqode.harness.acceptance import heldout_acceptance

                    gate = heldout_acceptance(row["result"].get("heldout_eval") or {})
                    gate["accepted"] = (
                        gate["accepted"]
                        and row["status"] == "completed"
                        and row["result"].get("accepted") is True
                    )
                    row["result"]["adoption_gate"] = gate
            after = int(params.get("after", 0))
            # Snapshot the page and writer ownership together. Cancellation can
            # become terminal before the stdout watcher drains its final events.
            with self.lock:
                event_rows = self._all(
                    "SELECT seq,payload FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 501",
                    (params["id"], after),
                )
                row["event_stream_open"] = params["id"] in self.processes
            row["has_more_events"] = len(event_rows) > 500
            page_rows = event_rows[:500]
            row["events"] = [{"sequence": r["seq"], **json.loads(r["payload"])} for r in page_rows]
            row["next_sequence"] = page_rows[-1]["seq"] if page_rows else after
            return row
        if method == "jobs.cancel":
            with self.lock:
                process = self.processes.get(params["id"])
                if not process:
                    raise ValueError("Run is no longer active")
                record = self.dispatch("jobs.get", {"id": params["id"]})
                if (
                    record["kind"] == "local"
                    and record["request"].get("local_plan", {}).get("action") == "serve"
                ):
                    from superqode.local.servers import ServerManager

                    manager = ServerManager(registry_dir=self.root / "model-servers")
                    engine = record["request"]["local_plan"]["engine"]
                    handle = manager._load(engine)
                    if (
                        handle
                        and handle.owner_job == params["id"]
                        and handle.process_start
                        and not handle.adopted
                    ):
                        manager.stop(engine)
                remote = record["request"].get("_desktop_connection", {}).get("kind") in {
                    "a2a",
                    "uhp",
                }
                if remote:
                    self._status(params["id"], "cancelling")
                    process.send_signal(signal.SIGTERM)

                    def remote_timeout():
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            self.append(
                                params["id"],
                                {
                                    "type": "error",
                                    "data": {
                                        "message": "Remote cancellation timed out; server execution may continue."
                                    },
                                },
                            )
                            os.killpg(process.pid, signal.SIGKILL)

                    self._background(remote_timeout)
                    return {"ok": True, "state": "cancelling"}
                self._status(params["id"], "cancelled")
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    # macOS reports EPERM when the group has already exited
                    # but is not reaped yet. Either way nothing is left to stop.
                    pass

                def reap():
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass

                self._background(reap)
                return {"ok": True}
        if method == "jobs.steer":
            with self.lock:
                job = self.dispatch("jobs.get", {"id": params["id"]})
                text = str(params.get("text") or "").strip()
                if job["status"] != "running" or not text or len(text) > 32_000:
                    raise ValueError("Steer an active run with up to 32,000 characters")
                capability = next(
                    (
                        event["data"]
                        for event in reversed(job["events"])
                        if event["type"] == "control_capabilities"
                    ),
                    {},
                )
                if not capability.get("steer"):
                    raise ValueError(
                        "This runtime does not advertise live steering; add a queued task instead"
                    )
                process = self.processes.get(params["id"])
                if not process or not process.stdin:
                    raise ValueError("The run has already stopped")
                identity = uuid.uuid4().hex
                process.stdin.write(
                    json.dumps({"operation": "steer", "text": text, "request_id": identity}) + "\n"
                )
                process.stdin.flush()
                return {"request_id": identity, "state": "sent"}
        if method == "jobs.approve":
            with self.lock:
                job_id = params["id"]
                if not params.get("request_id") or self.pending.get(job_id) != params.get(
                    "request_id"
                ):
                    raise ValueError("This approval is stale; refresh the run")
                process = self.processes.get(job_id)
                if not process or not process.stdin:
                    raise ValueError("Run is no longer active")
                process.stdin.write(
                    json.dumps(
                        {
                            "request_id": params["request_id"],
                            "allow": params.get("allow") is True,
                            "scope": "always" if params.get("scope") == "always" else "once",
                        }
                    )
                    + "\n"
                )
                process.stdin.flush()
                self.pending.pop(job_id, None)
                self._status(job_id, "running")
                return {"ok": True}
        if method == "tools.catalog":
            from .tools import command_catalog

            return command_catalog()
        if method == "tools.prepare":
            from .tools import tool_arguments

            plan = tool_arguments(str(params["action"]), params.get("values") or {})
            return {"argv": redact(plan["argv"], plan["secrets"]), "title": plan["title"]}
        if method in {
            "tasks.start",
            "evaluations.start",
            "optimizations.start",
            "checks.start",
            "tools.start",
        }:
            kind = {
                "tasks.start": "task",
                "evaluations.start": "evaluation",
                "optimizations.start": "optimization",
                "checks.start": "check",
                "tools.start": "tool",
            }[method]
            return self.start(params["project"], kind, params)
        if method == "hub.list":
            from superqode.harness.hub import build_hub_index
            from superqode.app.harness_picker import harness_picker_items

            root = self.project(params["project"])
            items = harness_picker_items(
                root, include_all=True, expand_protocol_catalog=True, include_live_registry=False
            )
            return build_hub_index(root, items=items, include_local_paths=True)
        if method == "rlm.overview":
            from .recursive import overview

            return overview()
        if method == "rlm.monty.install":
            from .recursive import monty_install

            return monty_install(self)
        if method == "rlm.monty.status":
            from .recursive import monty_status

            return monty_status(params)
        if method == "rlm.inspect":
            from .recursive import inspect as inspect_session

            return inspect_session(self, params)
        if method == "rlm.command":
            from .recursive import command

            return command(self, params)
        if method == "connect.options":
            from .configuration import options

            return options()
        if method == "connect.harness.configure":
            from .configuration import configured_spec

            return configured_spec(self.project(params["project"]), params)
        if method == "connect.systemone.key":
            key = params.get("key")
            if key is not None and (
                not isinstance(key, str)
                or not key.strip()
                or len(key) > 16000
                or any(ord(c) < 32 for c in key)
            ):
                raise ValueError("Enter a valid TypeSafe API key")
            if key is None:
                self.vendor_keys.pop("systemone", None)
            else:
                self.vendor_keys["systemone"] = key.strip()
            return {"harness": "systemone"}
        if method == "connect.vendor.key":
            from .configuration import vendor_key_route

            entry = str(params["entry"])
            route = vendor_key_route(self.project(params["project"]), entry)
            key = params.get("key")
            if key is None:
                self.vendor_keys.pop(entry, None)
                return {"ok": True}
            if (
                not isinstance(key, str)
                or not key.strip()
                or len(key) > 16000
                or any(ord(c) < 32 for c in key)
            ):
                raise ValueError("Enter a valid vendor key")
            self.vendor_keys[entry] = key.strip()
            return route
        if method == "connect.runtimes":
            from .connect_workflow import runtime_catalog

            return runtime_catalog()
        if method == "connect.harness.draft":
            import yaml
            from superqode.harness.catalog import resolve_harness
            from superqode.harness.loader import harness_spec_to_dict

            spec = resolve_harness(
                str(params.get("harness") or "core"), root=self.project(params["project"])
            ).spec
            data = harness_spec_to_dict(spec)
            if params.get("backend"):
                from superqode.harness.backends.registry import create_harness_backend

                backend = create_harness_backend(str(params["backend"]))
                if not backend.capabilities.supports_coding:
                    raise ValueError("Choose a runtime that supports coding harnesses")
                data["runtime"] = {"backend": backend.name, "config": {}}
            return {"yaml": yaml.safe_dump(data, sort_keys=False)}
        if method == "connect.harness.save":
            from .connect_workflow import save_harness

            with self.lock:
                root = self.project(params["project"])
                from .ownership import assert_project_idle

                assert_project_idle(self, params["project"])
                if self._all(
                    "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
                    (params["project"],),
                ):
                    raise ValueError(
                        "Finish or stop the active project run before creating a harness"
                    )
                return save_harness(
                    root, str(params.get("name") or ""), str(params.get("yaml") or "")
                )
        if method == "connect.menu":
            from .connect_workflow import connection_menu

            return connection_menu(
                self.project(params["project"]), str(params.get("menu") or "root")
            )
        if method == "connect.acp.registry.status":
            from .acp_catalog import registry_status

            return registry_status(self)
        if method == "connect.acp.custom.save":
            from .acp_catalog import custom_agent

            return custom_agent(self, params)
        if method == "connect.acp.custom.remove":
            from .acp_catalog import remove_custom_agent

            return remove_custom_agent(self, params)
        if method == "connect.acp.install.plan":
            from .acp_catalog import install_plan

            return install_plan(self, params["project"], params["reference"])
        if method == "connect.acp.login.plan":
            from .connect_workflow import profile_route
            from superqode.providers.subscription_env import resolve_vendor, subscription_child_env
            from superqode.providers.subscription_login import get_login_spec, login_command

            root = self.project(params["project"])
            route = (
                self.resolve_desktop_acp(params["project"], root, params["reference"])
                if params["reference"].startswith("acp:")
                else profile_route(root, params["reference"].removeprefix("connection:"))
            )
            if params["reference"] == "acp:qwen":
                import shutil

                binary = shutil.which("qwen")
                if not binary:
                    raise ValueError(
                        "Install Qwen Code with npm install -g @qwen-code/qwen-code, then check installation again. https://qwenlm.github.io/qwen-code-docs/"
                    )
                return {
                    "vendor": "qwen-code",
                    "name": "Qwen Code setup",
                    "interactive": True,
                    "argv": [binary],
                    "env": {},
                    "unset_env": [],
                    "instructions": "In Qwen Code, enter /auth and choose your provider, region and plan. Coding Plan, Token Plan and metered API keys use different endpoints. Exit Qwen when setup is complete, then check the connection here. Closing the CLI alone does not verify model access.",
                }
            vendor = route.get("subscription_vendor") or resolve_vendor(
                params["reference"].removeprefix("acp:")
            )
            if not vendor:
                raise ValueError("Use an authentication method advertised by this agent")
            spec = get_login_spec(vendor)
            _, unset = subscription_child_env(vendor)
            return {
                "vendor": spec.id,
                "name": spec.label,
                "interactive": spec.interactive_tty,
                "argv": login_command(spec),
                "env": {},
                "unset_env": unset,
            }
        if method == "execution.recovery":
            from .ownership import recovery_status

            return recovery_status(self, params["project"])
        if method == "execution.recovery.acknowledge":
            self.project(params["project"])
            self._write(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                ("recovery-ack:" + params["project"], json.dumps(time.time())),
            )
            return {"ok": True}
        if method == "connect.auth.start":
            action = str(params.get("action") or "oauth")
            if action == "registry-refresh":
                from .acp_catalog import refresh_registry

                return self.authentication.start(lambda status: refresh_registry(self, status))
            if action == "acp-install":
                from .acp_catalog import install_agent

                return self.authentication.start(
                    lambda status: install_agent(
                        self,
                        params["project"],
                        params["reference"],
                        params["expected_digest"],
                        status,
                    )
                )
            if action in {"probe", "acp-auth", "acp-terminal"}:
                from .connection_probe import probe_route
                from .connect_workflow import profile_route

                root = self.project(params["project"])
                reference = str(params.get("reference") or "")
                route = (
                    self.resolve_desktop_acp(params["project"], root, reference)
                    if reference.startswith("acp:")
                    else profile_route(root, reference.removeprefix("connection:"))
                )
                if action != "probe" and params.get("expected_digest") != route["digest"]:
                    raise ValueError(
                        "The agent launch configuration changed. Check the connection again."
                    )

                async def probe(status):
                    return await probe_route(
                        root,
                        route,
                        status,
                        method_id=params.get("method") if action == "acp-auth" else None,
                        terminal_method=params.get("method") if action == "acp-terminal" else None,
                    )

                return self.authentication.start(probe)
            if action == "install":
                from .configuration import install_agent

                root = self.project(params["project"])

                async def install(status):
                    return await install_agent(root, str(params["reference"]), status)

                return self.authentication.start(install)
            if action == "subscription":
                from superqode.providers.subscription_login import (
                    run_subscription_login,
                    get_login_spec,
                )

                vendor = str(params.get("vendor") or "")
                spec = get_login_spec(vendor)
                if spec.interactive_tty:
                    raise ValueError("This vendor requires an interactive Terminal handoff")

                async def login(status):
                    result = await run_subscription_login(
                        vendor, on_line=status, open_browser=True, force=True
                    )
                    if not result.ok:
                        raise ValueError(result.reason)
                    return {"signed_in": True}

                return self.authentication.start(login)
            from .connect_workflow import discover_protocol, connection_secrets

            config = self.protocol_config(params)
            self.project(params["project"])

            async def authorize(status):
                try:
                    discovery = await discover_protocol(
                        str(params["protocol"]), config, on_status=status
                    )
                    return self.register_protocol(
                        params["project"], str(params["protocol"]), config, discovery
                    )
                except Exception as exc:
                    raise ValueError(redact(str(exc), connection_secrets(config))) from None

            return self.authentication.start(authorize)
        if method == "connect.auth.poll":
            return self.authentication.poll(str(params["id"]))
        if method == "connect.auth.cancel":
            return self.authentication.cancel(str(params["id"]))
        if method == "connect.protocol":
            from .connect_workflow import discover, connection_secrets

            project = params["project"]
            self.project(project)
            kind = str(params.get("protocol"))
            config = self.protocol_config(params)
            try:
                discovery = redact(discover(kind, config), connection_secrets(config))
            except Exception as exc:
                raise ValueError(redact(str(exc), connection_secrets(config))) from None
            return self.register_protocol(project, kind, config, discovery)
        if method == "connect.protocol.select":
            identity = str(params.get("connection") or "")
            connection = self.remote_connections.get(identity)
            if not connection or connection["project"] != params["project"]:
                raise ValueError("Discover this server again")
            route = dict(connection["route"])
            if route["kind"] == "uhp":
                harness = str(params.get("harness") or "")
                item = next((i for i in connection["items"] if i["id"] == harness), None)
                if not item:
                    raise ValueError("Select an advertised server harness")
                # Each selection gets a distinct route; earlier tasks retain their original target.
                identity = "remote:" + uuid.uuid4().hex
                route.update(id=identity, remote_harness=harness, name=item.get("name") or harness)
                self.remote_connections[identity] = {**connection, "route": route}
            transport = {
                "project": connection["project"],
                "kind": route["kind"],
                "url": route["url"],
                "harness": route.get("remote_harness"),
            }
            digest = hashlib.sha256(json.dumps(transport, sort_keys=True).encode()).hexdigest()
            identity = "remote:" + digest[:24]
            route.update(id=identity, digest=digest)
            self.remote_connections[identity] = {**connection, "route": route}
            self._write(
                "INSERT INTO remote_routes VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET route=excluded.route",
                (identity, connection["project"], json.dumps(route)),
            )
            return route
        if method == "routes.list":
            from .connect_workflow import desktop_routes

            routes = desktop_routes(self.project(params["project"]))
            from .acp_catalog import extra_routes

            known = {row["id"]: row for row in routes}
            for row in extra_routes(self, params["project"]):
                if row["id"] in known:
                    known[row["id"]].update(
                        {
                            key: row[key]
                            for key in ("registry_version", "registry_source")
                            if key in row
                        }
                    )
                else:
                    routes.append(row)
            for record in self._all(
                "SELECT id,route FROM remote_routes WHERE project=?", (params["project"],)
            ):
                route = json.loads(record["route"])
                route["available"] = record["id"] in self.remote_connections
                if not route["available"]:
                    route["issue"] = (
                        "Reconnect this server from Connect to restore its authentication."
                    )
                routes.append(route)
            return routes
        if method.startswith("studio."):
            from .studio import handle

            return handle(self, method, params)
        if method in {"creator.propose", "superagent.propose"}:
            from .creator import propose

            return propose(self, params)
        if method in {"creator.save", "superagent.save"}:
            from .creator import commit

            return commit(self, params)
        if method in {"creator.layout", "superagent.layout"}:
            from .creator import layout

            return layout(self, params)
        if method in {"creator.monty", "superagent.monty"}:
            from .creator import run_check

            return run_check(self, params)
        if method == "tasks.isolate.preview":
            from .task_worktree import preview

            return preview(self, params)
        if method == "tasks.isolate.create":
            from .task_worktree import create

            return create(self, params)
        if method == "harnesses.list":
            from superqode.harness.catalog import list_harnesses
            from .session_controls import enforces_session_controls
            from .studio import selection
            from .local_harnesses import selections as local_selections

            return (
                [
                    {
                        "id": h.id,
                        "name": h.display_name,
                        "description": h.description,
                        "runtime": h.runtime,
                        "available": h.available,
                        "issue": h.issue,
                        "digest": h.digest,
                        "path": str(h.path) if h.path else None,
                        "enforces_session_controls": enforces_session_controls(h.runtime),
                    }
                    for h in list_harnesses(self.project(params["project"]))
                ]
                + selection(self, params["project"])
                + local_selections(self, params["project"])
            )
        if method == "harnesses.inspect":
            from superqode.harness.catalog import resolve_harness
            from superqode.harness.loader import harness_spec_to_dict

            from .connect_workflow import desktop_routes

            if str(params["reference"]).startswith("local-harness:"):
                from .local_harnesses import _profile, preflight

                profile = _profile(self, params["project"], params["reference"])
                plan = preflight(self, profile)
                return {
                    "name": "Advanced local harness",
                    "digest": profile["digest"],
                    "connection": plan,
                }
            routes = desktop_routes(self.project(params["project"]))
            route = next((route for route in routes if route["id"] == params["reference"]), None)
            if route:
                return {"name": route["name"], "digest": route["digest"], "connection": route}
            h = resolve_harness(params["reference"], root=self.project(params["project"]))
            return {
                "spec": harness_spec_to_dict(h.spec),
                "digest": h.digest,
                "name": h.display_name,
            }
        if method in {
            "tuning.list",
            "tuning.prepare",
            "tuning.get",
            "tuning.label",
            "tuning.decide",
            "tuning.start",
        }:
            from .tuning import handle

            with self.lock:
                if method not in {"tuning.list", "tuning.get"} and any(
                    row["status"] in ACTIVE or row["id"] in self.processes
                    for row in self._all(
                        "SELECT id,status FROM jobs WHERE project=?", (params["project"],)
                    )
                ):
                    raise ValueError("Finish or stop project work before changing tuning state")
                return handle(self, method, params)
        if method == "evals.inspect":
            from .experiments import inspect_suite

            return inspect_suite(self.project(params["project"]), params)
        if method == "experiments.list":
            project = params["project"]
            self.project(project)
            return self._all(
                "SELECT id,kind,title,status,created,updated FROM jobs "
                "WHERE project=? AND kind IN ('evaluation','optimization') "
                "ORDER BY updated DESC,id DESC LIMIT 100",
                (project,),
            )
        if method == "evals.packs":
            from superqode.harness.eval import list_eval_packs

            return list_eval_packs()
        if method == "git.status":
            root = self.project(params["project"])
            try:
                git(root, "rev-parse", "--verify", "HEAD")
                scope = ["HEAD"]
            except ValueError:
                scope = ["--cached"]
            return {
                "branch": git(root, "branch", "--show-current").strip(),
                "status": git(root, "status", "--short"),
                "diff": git(root, "diff", "--no-ext-diff", "--no-color", *scope),
                "stat": git(root, "diff", "--stat", *scope),
            }
        if method in {"git.stage", "git.stage_file", "git.unstage_file", "git.commit"}:
            root = self.project(params["project"])
            if self._all(
                "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
                (params["project"],),
            ):
                raise ValueError("Finish or stop the active run before changing Git state")
            if method in {"git.stage_file", "git.unstage_file"}:
                target = (root / str(params.get("path") or "")).resolve()
                if (
                    not target.is_relative_to(root)
                    or target.name.startswith(".env")
                    or any(
                        part in {".git", ".ssh", ".aws"} for part in target.relative_to(root).parts
                    )
                ):
                    raise ValueError("Sensitive or out-of-project file cannot be staged here")
                relative = ":(literal)" + str(target.relative_to(root))
                if method == "git.unstage_file":
                    try:
                        git(root, "rev-parse", "--verify", "HEAD")
                    except ValueError:
                        git(root, "rm", "--cached", "--", relative)
                    else:
                        git(root, "restore", "--staged", "--", relative)
                else:
                    if not target.is_file():
                        raise ValueError("Choose a project file")
                    git(root, "add", "--", relative)
                return {"ok": True}
            if method == "git.stage":
                git(root, "add", "--update")
                return {"ok": True}
            message = str(params.get("message") or "").strip()
            if not message or len(message) > 2000:
                raise ValueError("Enter a commit message of up to 2,000 characters")
            return {"output": git(root, "commit", "-m", message)}
        if method == "optimizations.inspect":
            from superqode.harness.acceptance import heldout_acceptance

            job = self.dispatch("jobs.get", {"id": params["id"]})
            result = job.get("result") or {}
            baseline = Path(result.get("baseline_spec_path") or "").resolve()
            candidate = Path(result.get("staged_spec_path") or "").resolve()
            if not baseline.is_relative_to(self.root) or not candidate.is_relative_to(self.root):
                raise ValueError("No staged candidate recorded for this run")
            before = baseline.read_text()
            after = candidate.read_text()
            if max(len(before), len(after)) > MAX_TEXT:
                raise ValueError("Candidate is too large to preview")
            digest = hashlib.sha256(after.encode()).hexdigest()
            return {
                "diff": "".join(
                    difflib.unified_diff(
                        before.splitlines(True),
                        after.splitlines(True),
                        fromfile="baseline.yaml",
                        tofile="candidate.yaml",
                    )
                ),
                "digest": digest,
                "accepted": job["status"] == "completed"
                and result.get("accepted") is True
                and heldout_acceptance(result.get("heldout_eval") or {})["accepted"],
                "unchanged": digest == result.get("staged_sha256"),
            }
        if method == "harnesses.save_candidate":
            job = self.dispatch("jobs.get", {"id": params["id"]})
            preview = self.dispatch("optimizations.inspect", {"id": params["id"]})
            if (
                not preview["accepted"]
                or not preview["unchanged"]
                or params.get("digest") != preview["digest"]
            ):
                raise ValueError("Candidate has not passed its gate or changed after validation")
            from superqode.harness.loader import load_harness_spec

            candidate = Path(job["result"]["staged_spec_path"])
            load_harness_spec(candidate)
            root = self.project(job["project"])
            destination = (root / ".superqode/harness").resolve()
            if not destination.is_relative_to(root):
                raise ValueError("Project harness folder points outside this project")
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / f"optimized-{job['id'][:12]}.yaml"
            with target.open("x") as output:
                output.write(candidate.read_text())
            return {
                "path": str(target),
                "message": "Saved as a new project harness; the original is unchanged",
            }
        if method in {"files.list", "files.read", "files.write", "files.create"}:
            root = self.project(params["project"])
            if method == "files.list":
                return sorted(
                    set(
                        name
                        for name in git(
                            root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
                        ).split("\0")
                        if name
                    )
                )[:5000]
            if method == "files.create":
                relative = str(params.get("path") or "").strip()
                target = (root / relative).resolve()
                if (
                    not relative
                    or Path(relative).is_absolute()
                    or not target.is_relative_to(root)
                    or target == root
                    or any(
                        p in {".git", ".aws", ".ssh"} or p.startswith(".env")
                        for p in target.relative_to(root).parts
                    )
                ):
                    raise ValueError("Choose a non-sensitive file inside this project")
                content = params.get("text", "")
                if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TEXT:
                    raise ValueError("Enter UTF-8 text smaller than 1 MB")
                with self.lock:
                    if self._all(
                        "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
                        (params["project"],),
                    ):
                        raise ValueError(
                            "Finish or stop the active project run before creating files"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("x", encoding="utf-8") as output:
                        output.write(content)
                return {
                    "path": str(target.relative_to(root)),
                    "digest": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            target = (root / params["path"]).resolve(strict=True)
            if not target.is_relative_to(root) or any(
                p in {".git", ".aws", ".ssh"} for p in target.relative_to(root).parts
            ):
                raise ValueError("File is outside the project")
            if target.name.startswith(".env") or target.stat().st_size > MAX_TEXT:
                raise ValueError("Sensitive or oversized file; open it with your editor")
            if method == "files.write":
                content = params.get("text")
                if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TEXT:
                    raise ValueError("Enter UTF-8 text smaller than 1 MB")
                with self.lock:
                    if self._all(
                        "SELECT id FROM jobs WHERE project=? AND status IN ('running','needs_approval','queued','cancelling')",
                        (params["project"],),
                    ):
                        raise ValueError(
                            "Finish or stop the active project run before saving file edits"
                        )
                    expected = params.get("digest")
                    if not expected or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                        raise ValueError(
                            "File changed on disk. Reload and review the changes before saving."
                        )
                    descriptor, temporary = tempfile.mkstemp(
                        prefix=".superqode-edit-", dir=target.parent
                    )
                    try:
                        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                            os.fchmod(output.fileno(), target.stat().st_mode & 0o777)
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                            raise ValueError(
                                "File changed while saving. Reload before trying again."
                            )
                        os.replace(temporary, target)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                return {
                    "path": str(target.relative_to(root)),
                    "digest": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            return {
                "path": str(target.relative_to(root)),
                "text": target.read_text(),
                "digest": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        if method == "artifacts.read":
            root = self.project(params["project"])
            target = Path(params["path"]).expanduser().resolve(strict=True)
            if not (
                target.is_relative_to(root)
                or target.is_relative_to(self.root)
                or params.get("_approved_artifact") is True
            ):
                raise ValueError("Artifact must belong to this project or desktop run store")
            if target.suffix != ".json" or target.stat().st_size > MAX_TEXT:
                raise ValueError("Choose a JSON result smaller than 1 MB")
            from .evaluation_review import review_artifact

            return review_artifact(json.loads(target.read_text()))
        raise ValueError("Unsupported desktop command")

    @staticmethod
    def protocol_config(params):
        from superqode.a2a.connection import parse_header_line

        return {
            "url": str(params.get("url") or ""),
            "token": str(params.get("token") or ""),
            "headers": parse_header_line(str(params.get("headers") or "")),
            "cert": str(params.get("cert") or ""),
            "key": str(params.get("key") or ""),
            "oauth": bool(params.get("oauth")),
            "client_id": str(params.get("client_id") or ""),
            "client_secret": str(params.get("client_secret") or ""),
        }

    def register_protocol(self, project, kind, config, discovery):
        from .connect_workflow import connection_secrets

        discovery = redact(discovery, connection_secrets(config))
        identity = "remote:" + uuid.uuid4().hex
        # Secrets are memory-only and excluded from routes, job requests and preferences.
        route = {
            "id": identity,
            "name": discovery["name"],
            "description": "Remote " + kind.upper(),
            "kind": kind,
            "desktop_kind": "connection",
            "available": True,
            "url": discovery["url"],
            "runtime": kind.upper(),
            "oauth_needs": discovery.get("oauth_needs", []),
        }
        self.remote_connections[identity] = {
            "project": project,
            "config": config,
            "route": route,
            "items": discovery["items"],
        }
        return {**discovery, "connection": identity}

    def resolve_desktop_acp(self, project, root, reference):
        from .acp_catalog import extra_routes

        for route in extra_routes(self, project):
            if route["id"] == reference and (
                route.get("custom") or not any(r["id"] == reference for r in acp_routes(root))
            ):
                if not route["available"]:
                    raise ValueError(route["issue"])
                return route
        return resolve_acp_route(root, reference)

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closing = True
        self.companion.stop()
        with self.lock:
            self.task_queues.enabled.clear()
        self.authentication.begin_close()
        for job_id in list(self.processes):
            try:
                self.dispatch("jobs.cancel", {"id": job_id})
            except ValueError:
                pass
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline and (
            self.processes
            or self._threads
            or any(r["state"] == "running" for r in self.authentication.actions.values())
        ):
            time.sleep(0.05)
        with self.lock:
            if (
                self.processes
                or self._threads
                or any(r["state"] == "running" for r in self.authentication.actions.values())
            ):
                raise RuntimeError(
                    "Desktop workers are still shutting down; retry closing the engine"
                )
            self.db.close()
            for lease in self._project_leases.values():
                lease.close()
            self._project_leases.clear()
            self._engine_lease.close()
            self._closed = True


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    output = sys.stdout
    sys.stdout = sys.stderr
    service = DesktopService(args.state)
    write_lock = threading.Lock()

    def handle(raw):
        request = {}
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or not isinstance(request.get("params", {}), dict):
                raise ValueError("Invalid desktop request")
            result = {
                "id": request.get("id"),
                "result": service.dispatch(request["method"], request.get("params", {})),
            }
        except Exception as exc:
            result = {
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": str(exc)[:2000],
            }
        with write_lock:
            output.write(json.dumps(result, default=str) + "\n")
            output.flush()

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            while raw := sys.stdin.readline(MAX_TEXT + 1):
                if len(raw) > MAX_TEXT:
                    break
                pool.submit(handle, raw)
    finally:
        service.close()


if __name__ == "__main__":
    main()
