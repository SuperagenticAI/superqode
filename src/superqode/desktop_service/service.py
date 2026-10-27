"""Desktop commands over an inherited JSON-lines pipe; no network listener."""

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
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "desktop.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, path TEXT UNIQUE, opened REAL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, project TEXT, kind TEXT, title TEXT, status TEXT,
              request TEXT, result TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS remote_routes(id TEXT PRIMARY KEY, project TEXT, route TEXT);
            """
        )
        self.db.execute(
            "UPDATE jobs SET status='interrupted' WHERE status IN ('running','needs_approval','queued','cancelling')"
        )
        self.db.commit()
        self._conversation_roots: dict[str, dict] = {}
        self.processes: dict[str, subprocess.Popen] = {}
        self.pending: dict[str, str] = {}
        self.credentials: dict[str, str] = {}
        self.remote_connections: dict[str, dict] = {}
        self.vendor_keys: dict[str, str] = {}
        from .authentication import AuthenticationActions

        self.authentication = AuthenticationActions()
        from .task_queue import TaskQueues

        self.task_queues = TaskQueues(self)

    def _all(self, query, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(query, args).fetchall()]

    def job_summaries(self, identity=None):
        """Keep individual run records, with a stable conversation identity for recent rows."""
        columns = "id,project,kind,title,status,created,updated"
        rows = (
            self._all(f"SELECT {columns} FROM jobs WHERE id=?", (identity,))
            if identity is not None
            else self._all(f"SELECT {columns} FROM jobs ORDER BY updated DESC LIMIT 100")
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
        for row in rows:
            root = roots.get(row["id"], row)
            summary = {key: value for key, value in row.items() if key != "request"}
            summary.update(conversation_id=root["id"], conversation_title=root["title"])
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
        return {"id": project_id, "path": str(root), "name": root.name}

    def append(self, job_id: str, event: dict):
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
            raw = json.dumps(event, ensure_ascii=False)
        self._write("INSERT INTO events(job,payload) VALUES(?,?)", (job_id, raw))

    def _status(self, job_id, status):
        self._write("UPDATE jobs SET status=?,updated=? WHERE id=?", (status, time.time(), job_id))

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
        result = None
        error = None
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
                if event.get("type") == "approval":
                    with self.lock:
                        self.pending[job_id] = event["data"]["request_id"]
                    self._status(job_id, "needs_approval")
                elif event.get("type") == "result":
                    result = event.get("data")
                elif event.get("type") == "error":
                    error = event.get("data", {}).get("message", "Execution failed")
            code = process.wait()
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
            status = "failed" if code or error else "completed"
            if isinstance(result, dict) and result.get("status") == "cancelled":
                status = "cancelled"
            if isinstance(result, dict) and result.get("regressed"):
                status = "regressed"
            if isinstance(result, dict) and result.get("status") in {"failed", "error"}:
                status = "failed"
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
            self.task_queues.finished(job_id)

    def start(self, project_id: str, kind: str, params: dict):
        root = self.project(project_id)
        if kind not in {"task", "evaluation", "optimization", "check", "tool", "compaction"}:
            raise ValueError("Unknown job type")
        with self.lock:
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
            params.pop("image_snapshots", None)
            params.pop("_chat_history", None)
            params.pop("_handoff_context", None)
            params.pop("_continuity", None)
            params.pop("expected_digest", None)
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
                    resolve_harness(source["request"]["harness"], root=root).spec.runtime.backend
                    != "builtin"
                ):
                    raise ValueError(
                        "This harness owns its context; use its advertised native command"
                    )
                params.update(
                    {key: source["request"][key] for key in ("harness", "provider", "model")}
                )
                params["session_id"] = source["result"]["session_id"]
                params["expected_digest"] = source["result"]["harness_digest"]
                if len(str(params.get("instructions") or "")) > 4000:
                    raise ValueError("Use compaction instructions up to 4,000 characters")
            if kind == "task":
                reference = str(params.get("harness") or "core")
                if reference.startswith("connection:"):
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
                    params["_desktop_route"] = resolve_acp_route(root, reference)
                    params["provider"] = "agent"
                else:
                    from superqode.harness.catalog import resolve_harness

                    resolve_harness(reference, root=root)
            if kind == "task" and params.get("parent_id"):
                from .conversations import prepare_continuation

                prepare_continuation(self, params, project_id, root)
            if kind == "task":
                if params.get("interaction_mode") == "chat" and (
                    params.get("_desktop_route") or params.get("_desktop_connection")
                ):
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
                            params.get("harness") or "core", root=root
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
                    "evaluation": "Harness evaluation",
                    "optimization": "Harness optimization",
                    "check": "Project check",
                    "compaction": "Compact model context",
                    "tool": tool_plan["title"] if tool_plan else "Advanced workflow",
                }[kind]
            now = time.time()
            self._write(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, project_id, kind, title, "running", json.dumps(params), None, now, now),
            )
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
                if kind == "check":
                    credential_env = {}
                    remote_config = {}
                allowed = {
                    name
                    for provider in providers
                    if provider in PROVIDERS
                    for name in (PROVIDERS[provider].env_vars or [])
                }
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
                from superqode.tools.env_policy import is_secret_name

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
                        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                logger = threading.Thread(
                    target=record_stderr, args=(process.stderr, log_path, secrets), daemon=True
                )
                logger.start()
                self.processes[job_id] = process
                process.stdin.write(json.dumps(params) + "\n")
                process.stdin.flush()
                threading.Thread(
                    target=self._watch, args=(job_id, process, secrets, logger), daemon=True
                ).start()
            except Exception:
                self._status(job_id, "failed")
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
        if method in {"review.list", "review.diff", "review.feedback", "review.stage"}:
            from .review import action

            with self.lock:
                if method == "review.stage":
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
                ("acp:", "connection:", "remote:", "vendor-key:", "attach:")
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
        if method in {"providers.list", "providers.credentials.set", "providers.check"}:
            from .connections import install, inspect_route, list_connections

            with self.lock:
                if method == "providers.credentials.set":
                    return install(self.credentials, params)
                credentials = dict(self.credentials)
            if method == "providers.check":
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
            return self._all("SELECT * FROM projects ORDER BY opened DESC")
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
        if method == "conversations.get":
            from .conversations import history

            return history(self, params["id"], params.get("before"))
        if method == "jobs.get":
            rows = self._all("SELECT * FROM jobs WHERE id=?", (params["id"],))
            if not rows:
                raise ValueError("Run not found")
            row = rows[0]
            summary = self.job_summaries(params["id"])[0]
            row["conversation_id"] = summary["conversation_id"]
            row["conversation_title"] = summary["conversation_title"]
            row["request"] = json.loads(row["request"])
            row["result"] = json.loads(row["result"]) if row["result"] else None
            if row["kind"] in {"evaluation", "optimization"} and row["result"] is not None:
                from .evaluation_review import with_evaluation_comparison

                row["result"] = with_evaluation_comparison(row["result"])
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

                    threading.Thread(target=remote_timeout, daemon=True).start()
                    return {"ok": True, "state": "cancelling"}
                self._status(params["id"], "cancelled")
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

                def reap():
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

                threading.Thread(target=reap, daemon=True).start()
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
        if method == "connect.harness.draft":
            import yaml
            from superqode.harness.catalog import resolve_harness
            from superqode.harness.loader import harness_spec_to_dict

            spec = resolve_harness(
                str(params.get("harness") or "core"), root=self.project(params["project"])
            ).spec
            return {"yaml": yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False)}
        if method == "connect.harness.save":
            from .connect_workflow import save_harness

            with self.lock:
                root = self.project(params["project"])
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
        if method == "connect.auth.start":
            action = str(params.get("action") or "oauth")
            if action == "probe":
                from .connection_probe import probe_route
                from .connect_workflow import profile_route

                root = self.project(params["project"])
                reference = str(params.get("reference") or "")
                route = (
                    resolve_acp_route(root, reference)
                    if reference.startswith("acp:")
                    else profile_route(root, reference.removeprefix("connection:"))
                )

                async def probe(status):
                    return await probe_route(root, route, status)

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
        if method == "harnesses.list":
            from superqode.harness.catalog import list_harnesses

            return [
                {
                    "id": h.id,
                    "name": h.display_name,
                    "description": h.description,
                    "runtime": h.runtime,
                    "available": h.available,
                    "issue": h.issue,
                    "digest": h.digest,
                    "path": str(h.path) if h.path else None,
                }
                for h in list_harnesses(self.project(params["project"]))
            ]
        if method == "harnesses.inspect":
            from superqode.harness.catalog import resolve_harness
            from superqode.harness.loader import harness_spec_to_dict

            from .connect_workflow import desktop_routes

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
                "accepted": result.get("accepted") is True,
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

    def close(self):
        with self.lock:
            self.task_queues.enabled.clear()
        for identity in list(self.authentication.actions):
            self.authentication.cancel(identity)
        for job_id in list(self.processes):
            try:
                self.dispatch("jobs.cancel", {"id": job_id})
            except ValueError:
                pass
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline and (
            self.processes
            or any(r["state"] == "running" for r in self.authentication.actions.values())
        ):
            time.sleep(0.05)


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
