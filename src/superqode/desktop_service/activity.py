"""Metadata-only overview of app-owned agent threads across projects."""

import base64
import json
import math
from pathlib import Path

from .threads import index_runs


def list_activity(service, params):
    project = str(params.get("project") or "")
    query = str(params.get("query") or "").strip()
    view = params.get("view", "all")
    if (
        len(query) > 200
        or not isinstance(view, str)
        or view not in {"all", "working", "attention", "done"}
    ):
        raise ValueError("Choose an activity filter and keep searches under 200 characters")
    scope = [project, query, view]
    position = None
    if params.get("cursor"):
        try:
            token = str(params["cursor"])
            if len(token) > 2048:
                raise ValueError()
            saved = json.loads(base64.urlsafe_b64decode(token))
            position = saved["position"]
            if saved["scope"] != scope or not isinstance(position, list) or len(position) != 3:
                raise ValueError()
            if (
                type(position[0]) is not int
                or type(position[1]) not in {int, float}
                or not isinstance(position[2], str)
                or position[0] not in {0, 1, 2, 3}
                or not math.isfinite(position[1])
            ):
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError("Refresh activity after changing its search or scope") from None
    with service.lock:
        if project:
            service.project(project)
        projects = service._all(
            "SELECT * FROM projects" + (" WHERE id=?" if project else ""),
            (project,) if project else (),
        )
        for item in projects:
            index_runs(service, item["id"])
        rows = service._all(
            """WITH ranked AS (
              SELECT j.id,j.project,j.status,j.updated,p.path,
                COALESCE(NULLIF(m.title,''),root.title) AS title,
                CASE WHEN j.status='needs_approval' THEN 0
                  WHEN j.status IN ('failed','interrupted') THEN 1
                  WHEN j.status IN ('running','queued','cancelling') THEN 2 ELSE 3 END AS priority,
                ROW_NUMBER() OVER(PARTITION BY t.project,t.conversation ORDER BY
                  CASE WHEN j.status IN ('running','queued','needs_approval','cancelling') THEN 0 ELSE 1 END,
                  j.updated DESC,j.created DESC,j.id DESC) AS rank
              FROM jobs j JOIN thread_runs t ON t.job=j.id JOIN jobs root ON root.id=t.conversation
              JOIN projects p ON p.id=j.project
              LEFT JOIN thread_metadata m ON m.project=t.project AND m.conversation=t.conversation
              WHERE (?='' OR j.project=?) AND COALESCE(m.archived,0)=0
            ) SELECT * FROM ranked WHERE rank=1 ORDER BY priority,updated DESC,id""",
            (project, project),
        )
        rows = [
            row
            for row in rows
            if not query or query.casefold() in (row["title"] + " " + row["path"]).casefold()
        ]
        counts = {
            "working": sum(row["priority"] == 2 for row in rows),
            "attention": sum(row["priority"] < 2 for row in rows),
            "done": sum(row["status"] == "completed" for row in rows),
            "all": len(rows),
        }
        if view != "all":
            rows = (
                [row for row in rows if row["priority"] == 2]
                if view == "working"
                else [row for row in rows if row["priority"] < 2]
                if view == "attention"
                else [row for row in rows if row["status"] == "completed"]
            )
        if position:
            rows = [
                row
                for row in rows
                if (row["priority"], -row["updated"], row["id"]) > tuple(position)
            ]
        page = rows[:50]
        summaries = {
            row["id"]: row for row in service.job_summaries(identities=[row["id"] for row in page])
        }
        items = [
            {
                **summaries[row["id"]],
                "project_path": row["path"],
                "project_name": Path(row["path"]).name,
                "priority": row["priority"],
            }
            for row in page
        ]
        cursor = ""
        if len(rows) > 50:
            last = page[-1]
            cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {"scope": scope, "position": [last["priority"], -last["updated"], last["id"]]}
                ).encode()
            ).decode()
        return {"items": items, "counts": counts, "next_cursor": cursor}
