"""Durable, explicitly started per-project coding queues; never replay after restart."""

import json
import time
import uuid


class TaskQueues:
    def __init__(self, service):
        self.service = service
        self.enabled = set()
        service._write(
            "CREATE TABLE IF NOT EXISTS task_queue(id TEXT PRIMARY KEY, project TEXT, position REAL, request TEXT, state TEXT, job TEXT, error TEXT)"
        )
        service._write(
            "UPDATE task_queue SET state='interrupted',error='App stopped; review the recorded run before retrying' WHERE state='running'"
        )

    def list(self, project):
        return {
            "running": project in self.enabled,
            "items": [
                {**row, "request": json.loads(row["request"])}
                for row in self.service._all(
                    "SELECT * FROM task_queue WHERE project=? ORDER BY position,id", (project,)
                )
            ],
        }

    def dispatch(self, method, params):
        service = self.service
        project = params["project"]
        service.project(project)
        with service.lock:
            if method == "queue.list":
                return self.list(project)
            if method == "queue.add":
                if len(self.list(project)["items"]) >= 100:
                    raise ValueError("Keep up to 100 tasks in the project queue")
                prompt = str(params.get("prompt") or "").strip()
                if not prompt or len(prompt) > 100_000:
                    raise ValueError("Enter a task of up to 100,000 characters")
                fields = {
                    "prompt",
                    "harness",
                    "provider",
                    "model",
                    "context_files",
                    "image_ids",
                    "interaction_mode",
                    "context_window",
                    "enable_summarization",
                    "acp_options",
                }
                request = {key: value for key, value in params.items() if key in fields}
                if len(json.dumps(request)) > 120_000:
                    raise ValueError("Queued task is too large")
                identity = uuid.uuid4().hex
                service._write(
                    "INSERT INTO task_queue VALUES(?,?,?,?,?,?,?)",
                    (identity, project, time.time_ns(), json.dumps(request), "pending", "", ""),
                )
                return {"id": identity}
            if method == "queue.pause":
                self.enabled.discard(project)
                return self.list(project)
            if method == "queue.run":
                self.enabled.add(project)
                self.advance(project)
                return self.list(project)
            rows = service._all(
                "SELECT * FROM task_queue WHERE id=? AND project=?", (params.get("id"), project)
            )
            if not rows:
                raise ValueError("Queued task no longer exists")
            item = rows[0]
            if item["state"] == "running":
                raise ValueError("Stop or finish this task before changing its queue entry")
            if method == "queue.remove":
                service._write("DELETE FROM task_queue WHERE id=?", (item["id"],))
            elif method == "queue.retry":
                self.enabled.discard(project)
                service._write(
                    "UPDATE task_queue SET state='pending',job='',error='' WHERE id=?",
                    (item["id"],),
                )
            elif method == "queue.move":
                items = self.list(project)["items"]
                index = next(i for i, row in enumerate(items) if row["id"] == item["id"])
                destination = max(
                    0, min(len(items) - 1, index + (-1 if params.get("direction") == "up" else 1))
                )
                other = items[destination]
                if other["state"] == "running":
                    raise ValueError("Cannot move a task ahead of the running task")
                service._write(
                    "UPDATE task_queue SET position=? WHERE id=?", (other["position"], item["id"])
                )
                service._write(
                    "UPDATE task_queue SET position=? WHERE id=?", (item["position"], other["id"])
                )
            else:
                raise ValueError("Unknown task queue action")
            return self.list(project)

    def advance(self, project):
        service = self.service
        with service.lock:
            if project not in self.enabled:
                return
            jobs = service._all("SELECT id,status FROM jobs WHERE project=?", (project,))
            if any(
                row["id"] in service.processes
                or row["status"] in {"running", "needs_approval", "cancelling"}
                for row in jobs
            ):
                return
            rows = service._all(
                "SELECT * FROM task_queue WHERE project=? AND state='pending' ORDER BY position,id LIMIT 1",
                (project,),
            )
            if not rows:
                self.enabled.discard(project)
                return
            item = rows[0]
            try:
                job = service.start(
                    project,
                    "task",
                    {
                        **json.loads(item["request"]),
                        "command_id": "queue-" + item["id"] + "-" + uuid.uuid4().hex,
                    },
                )
                service._write(
                    "UPDATE task_queue SET state='running',job=?,error='' WHERE id=?",
                    (job["id"], item["id"]),
                )
            except Exception as exc:
                service._write(
                    "UPDATE task_queue SET state='failed',error=? WHERE id=?",
                    (str(exc)[:2000], item["id"]),
                )
                self.enabled.discard(project)

    def finished(self, job_id):
        service = self.service
        with service.lock:
            jobs = service._all("SELECT project,status FROM jobs WHERE id=?", (job_id,))
            if not jobs:
                return
            job = jobs[0]
            status = job["status"]
            service._write(
                "UPDATE task_queue SET state=?,error=? WHERE job=?",
                (
                    status,
                    ""
                    if status == "completed"
                    else "Run stopped; review its evidence before retrying",
                    job_id,
                ),
            )
            if status != "completed":
                self.enabled.discard(job["project"])
            self.advance(job["project"])
