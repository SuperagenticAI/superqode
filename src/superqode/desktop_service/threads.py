"""Project-scoped, durable thread organization over immutable recorded runs."""

from __future__ import annotations

import base64
import json
import math
import time

ACTIVE = {"running", "needs_approval", "queued", "cancelling"}


def index_runs(service, project):
    missing = service._all(
        "SELECT j.id FROM jobs j LEFT JOIN thread_runs t ON t.job=j.id "
        "WHERE j.project=? AND j.kind='task' AND t.job IS NULL ORDER BY j.created,j.id",
        (project,),
    )
    records = []
    for row in missing:
        summary = service.job_summaries(row["id"], include_metadata=False)[0]
        records.append((row["id"], project, summary["conversation_id"]))
    if records:
        service.db.executemany("INSERT OR IGNORE INTO thread_runs VALUES(?,?,?)", records)
        service.db.commit()


def list_threads(service, params):
    project = params["project"]
    service.project(project)
    query = str(params.get("query") or "").strip()
    if len(query) > 200:
        raise ValueError("Keep thread searches under 200 characters")
    view = params.get("view", "active")
    if view not in {"active", "archived", "all", "pinned", "working", "attention"}:
        raise ValueError("Choose an available thread filter")
    limit = params.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Choose a thread page size between 1 and 100")
    signature = [project, query, view]
    cursor = None
    if params.get("cursor"):
        try:
            token = str(params["cursor"])
            if len(token) > 4096:
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(token.encode()))
            cursor = payload["position"]
            if payload["scope"] != signature or not isinstance(cursor, list) or len(cursor) != 3:
                raise ValueError()
            if (
                type(cursor[0]) is not int
                or type(cursor[1]) not in {int, float}
                or not isinstance(cursor[2], str)
            ):
                raise ValueError()
            if cursor[0] not in {0, 1} or not math.isfinite(cursor[1]):
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError(
                "Thread search changed. Refresh the list before loading more."
            ) from None
    with service.lock:
        index_runs(service, project)
        rows = service._all(
            """WITH ranked AS (
              SELECT j.id,j.project,j.kind,j.status,j.created,j.updated,t.conversation AS conversation_id,
                json_extract(j.request,'$.harness') AS harness,json_extract(j.request,'$.model') AS model,
                COALESCE(NULLIF(m.title,''),root.title) AS conversation_title,
                COALESCE(m.pinned,0) AS pinned,COALESCE(m.archived,0) AS archived,
                COUNT(*) OVER (PARTITION BY t.conversation) AS turn_count,
                MAX(CASE WHEN j.status IN ('running','needs_approval','queued','cancelling') THEN 1 ELSE 0 END)
                  OVER (PARTITION BY t.conversation) AS working,
                ROW_NUMBER() OVER (PARTITION BY t.conversation ORDER BY
                  CASE WHEN j.status IN ('running','needs_approval','queued','cancelling') THEN 0 ELSE 1 END,
                  j.updated DESC,j.created DESC,j.id DESC) AS rank
              FROM thread_runs t JOIN jobs j ON j.id=t.job JOIN jobs root ON root.id=t.conversation
              LEFT JOIN thread_metadata m ON m.project=t.project AND m.conversation=t.conversation
              WHERE t.project=?
            ) SELECT * FROM ranked WHERE rank=1
              AND (?='all' OR (?='archived' AND archived=1) OR
                (? NOT IN ('all','archived') AND archived=0))
              AND (?!='pinned' OR pinned=1)
              AND (?!='working' OR working=1)
              AND (?!='attention' OR status IN ('needs_approval','failed','interrupted'))
              AND (instr(lower(conversation_title),lower(?))>0 OR instr(conversation_id,?)>0
                OR instr(lower(COALESCE(harness,'')),lower(?))>0 OR instr(lower(COALESCE(model,'')),lower(?))>0
                OR EXISTS(SELECT 1 FROM thread_runs used JOIN jobs history ON history.id=used.job
                  WHERE used.project=ranked.project AND used.conversation=ranked.conversation_id
                  AND (instr(lower(COALESCE(json_extract(history.request,'$.harness'),'')),lower(?))>0
                    OR instr(lower(COALESCE(json_extract(history.request,'$._thread_harness.name'),
                      json_extract(history.request,'$._desktop_route.name'),
                      json_extract(history.request,'$._desktop_connection.name'),'')),lower(?))>0)))
            ORDER BY pinned DESC,updated DESC,conversation_id ASC""",
            (project, view, view, view, view, view, view, query, query, query, query, query, query),
        )
    # Fetching metadata does not read prompt bodies, event streams or provider state.
    if cursor:
        pinned, updated, identity = cursor
        rows = [
            r
            for r in rows
            if (-r["pinned"], -r["updated"], r["conversation_id"]) > (-pinned, -updated, identity)
        ]
    page = rows[:limit]
    next_cursor = ""
    if len(rows) > limit:
        last = page[-1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "scope": signature,
                    "position": [last["pinned"], last["updated"], last["conversation_id"]],
                }
            ).encode()
        ).decode()
    for row in page:
        for field in ("pinned", "archived", "working"):
            row[field] = bool(row[field])
        row.pop("rank", None)
    from .identities import thread_harnesses

    used = thread_harnesses(service, [row["conversation_id"] for row in page])
    for row in page:
        row["harnesses_used"] = used.get((project, row["conversation_id"]), [])
    return {"items": page, "next_cursor": next_cursor}


def update_thread(service, params):
    project = params["project"]
    service.project(project)
    changes = {key: params[key] for key in ("title", "pinned", "archived") if key in params}
    if not changes:
        raise ValueError("Choose a thread change")
    if "title" in changes:
        title = changes["title"]
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title.strip()) > 200
            or any(ord(c) < 32 for c in title)
        ):
            raise ValueError("Use a thread title of 1 to 200 characters without control characters")
        changes["title"] = title.strip()
    for field in ("pinned", "archived"):
        if field in changes and type(changes[field]) is not bool:
            raise ValueError("Thread flags must be true or false")
    with service.lock:
        index_runs(service, project)
        found = service._all(
            "SELECT conversation FROM thread_runs WHERE job=? AND project=?",
            (params["id"], project),
        )
        if not found:
            # Accept the stable root ID as well as the selected turn ID.
            raise ValueError("Thread not found in this project")
        identity = found[0]["conversation"]
        if changes.get("archived") and service._all(
            "SELECT j.id FROM jobs j JOIN thread_runs t ON t.job=j.id WHERE t.project=? AND t.conversation=? "
            "AND j.status IN ('running','needs_approval','queued','cancelling') LIMIT 1",
            (project, identity),
        ):
            raise ValueError("Finish or stop this thread before archiving it")
        current = service._all(
            "SELECT * FROM thread_metadata WHERE project=? AND conversation=?", (project, identity)
        )
        values = {
            "title": "",
            "pinned": False,
            "archived": False,
            **(current[0] if current else {}),
            **changes,
        }
        service._write(
            "INSERT INTO thread_metadata VALUES(?,?,?,?,?,?) ON CONFLICT(project,conversation) DO UPDATE SET "
            "title=excluded.title,pinned=excluded.pinned,archived=excluded.archived,updated=excluded.updated",
            (project, identity, values["title"], values["pinned"], values["archived"], time.time()),
        )
    return {"conversation_id": identity, **changes}


def get_thread(service, params):
    project = params["project"]
    service.project(project)
    with service.lock:
        index_runs(service, project)
        found = service._all(
            "SELECT conversation FROM thread_runs WHERE job=? AND project=?",
            (params["id"], project),
        )
        if not found:
            raise ValueError("Thread not found in this project")
        rows = service._all(
            "SELECT j.id FROM jobs j JOIN thread_runs t ON t.job=j.id WHERE t.project=? AND t.conversation=? "
            "ORDER BY CASE WHEN j.status IN ('running','needs_approval','queued','cancelling') THEN 0 ELSE 1 END, "
            "j.updated DESC,j.created DESC,j.id DESC LIMIT 1",
            (project, found[0]["conversation"]),
        )
        return service.job_summaries(rows[0]["id"])[0]
