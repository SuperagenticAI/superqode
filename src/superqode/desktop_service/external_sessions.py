"""Opt-in, read-only discovery of Codex rollout files; never executes a session."""

from __future__ import annotations

import base64
from collections import deque
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import uuid

HEADER_BYTES = 256 * 1024
SCAN_BYTES = 32 * 1024 * 1024
SCAN_FILES = 2000
SCAN_ENTRIES = 20000
TRANSCRIPT_BYTES = 16 * 1024 * 1024
LINE_BYTES = 2 * 1024 * 1024
CONTEXT_CHARS = 24000
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _stamp(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _source(service, identity):
    rows = service._all("SELECT * FROM external_session_sources WHERE id=?", (identity,))
    if not rows:
        raise ValueError("External source was removed. Refresh All work.")
    return rows[0]


@contextmanager
def _folder(source):
    try:
        descriptor = os.open(source["path"], DIRECTORY_FLAGS)
    except OSError:
        raise ValueError(
            "Session folder is unavailable. Reconnect it by choosing the folder again."
        ) from None
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (source["device"], source["inode"]):
            raise ValueError(
                "Session folder changed. Remove this source and choose the folder again."
            )
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _file(source, relative):
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or relative.startswith("/"):
        raise ValueError("Invalid recorded session path")
    with _folder(source) as root:
        folder = os.dup(root)
        try:
            for part in parts[:-1]:
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=folder)
                os.close(folder)
                folder = child
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder
            )
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Recorded session is not a regular file")
                yield stream
        except OSError:
            raise ValueError(
                "Recorded session is unavailable or its path changed. Refresh the source."
            ) from None
        finally:
            os.close(folder)


def _metadata(stream):
    """Read a bounded header only; prompts and tool output are not indexed."""
    consumed = 0
    while consumed < HEADER_BYTES:
        line = stream.readline(HEADER_BYTES - consumed)
        if not line:
            break
        consumed += len(line)
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            continue
        if not isinstance(row, dict) or row.get("type") != "session_meta":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            return None
        try:
            identity = str(uuid.UUID(str(payload.get("id"))))
        except ValueError:
            return None
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd.startswith("/") or len(cwd) > 4096 or "\x00" in cwd:
            return None
        git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        branch = str(git.get("branch") or "")[:200]
        version = str(payload.get("cli_version") or "")[:80]
        try:
            for value in [cwd, branch, version]:
                value.encode("utf-8")
        except UnicodeError:
            return None
        return {
            "session_id": identity,
            "cwd": cwd,
            "title": "Codex · " + (Path(cwd).name or "/") + " · " + identity[-8:],
            "branch": branch,
            "cli_version": version,
            "provider": "codex",
            "status": "recorded",
            "harness": "codex-cli",
            "harnesses_used": [{"id": "codex-cli", "name": "Codex", "icon_key": "codex"}],
        }
    return None


def list_sources(service):
    with service.lock:
        return [
            {
                "id": row["id"],
                "path": row["path"],
                "provider": "codex",
                "scanned": row["scanned"],
                "report": json.loads(row["report"]),
                "count": row["count"],
            }
            for row in service._all(
                "SELECT s.*, COUNT(e.id) AS count FROM external_session_sources s "
                "LEFT JOIN external_sessions e ON e.source=s.id GROUP BY s.id ORDER BY s.created,s.id"
            )
        ]


def add_source(service, params):
    if params.get("provider", "codex") != "codex":
        raise ValueError("Choose a supported external session format")
    supplied = params.get("path")
    if not isinstance(supplied, str) or not supplied or len(supplied) > 4096:
        raise ValueError("Choose a session folder")
    try:
        root = Path(supplied).expanduser().resolve(strict=True)
        descriptor = os.open(root, DIRECTORY_FLAGS)
    except (OSError, ValueError):
        raise ValueError("Choose an accessible session folder") from None
    try:
        info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    with service.lock:
        for existing in service._all("SELECT * FROM external_session_sources"):
            previous = Path(existing["path"])
            if root == previous:
                if (info.st_dev, info.st_ino) != (existing["device"], existing["inode"]):
                    raise ValueError(
                        "Session folder changed. Remove this source and choose the folder again."
                    )
                return {"id": existing["id"]}
            if root.is_relative_to(previous) or previous.is_relative_to(root):
                raise ValueError(
                    "This folder overlaps an existing source. Refresh or remove that source first."
                )
        identity = uuid.uuid4().hex
        service._write(
            "INSERT INTO external_session_sources VALUES(?,?,?,?,?,?,?,?)",
            (identity, str(root), info.st_dev, info.st_ino, time.time(), 0, "{}", "codex"),
        )
        return {"id": identity}


def remove_source(service, identity):
    with service.lock:
        service.db.execute("DELETE FROM external_sessions WHERE source=?", (identity,))
        service.db.execute("DELETE FROM external_session_sources WHERE id=?", (identity,))
        service.db.commit()
    return {"ok": True}


class _ScanLimit(Exception):
    pass


def scan_source(service, identity):
    if not service._external_scan_lock.acquire(blocking=False):
        raise ValueError("A session source is already refreshing. Wait for it to finish.")
    try:
        return _scan(service, identity)
    finally:
        service._external_scan_lock.release()


def _scan(service, identity):
    source = _source(service, identity)
    records = {}
    report = {"files": 0, "ignored": 0, "unavailable": 0, "partial": False}
    budget = {"bytes": 0, "entries": 0}

    def visit(folder, prefix="", depth=0):
        with os.scandir(folder) as entries:
            for entry in entries:
                budget["entries"] += 1
                if budget["entries"] > SCAN_ENTRIES:
                    raise _ScanLimit()
                relative = prefix + entry.name
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth >= 8:
                        report["partial"] = True
                        continue
                    try:
                        child = os.open(entry.name, DIRECTORY_FLAGS, dir_fd=folder)
                    except OSError:
                        report["unavailable"] += 1
                        report["partial"] = True
                        continue
                    try:
                        visit(child, relative + "/", depth + 1)
                    finally:
                        os.close(child)
                elif entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False):
                    if report["files"] >= SCAN_FILES or budget["bytes"] >= SCAN_BYTES:
                        raise _ScanLimit()
                    report["files"] += 1
                    try:
                        with _file(source, relative) as stream:
                            before = os.fstat(stream.fileno())
                            metadata = _metadata(stream)
                            budget["bytes"] += stream.tell()
                            if _stamp(before) != _stamp(os.fstat(stream.fileno())):
                                report["unavailable"] += 1
                                continue
                        if metadata is None:
                            report["ignored"] += 1
                            continue
                        key = _digest(["codex", metadata["session_id"]])
                        row = (
                            key,
                            identity,
                            relative,
                            json.dumps(metadata),
                            json.dumps(_stamp(before)),
                            before.st_mtime,
                        )
                        if key not in records or (row[5], row[2]) > (
                            records[key][5],
                            records[key][2],
                        ):
                            records[key] = row
                    except ValueError:
                        report["unavailable"] += 1

    with _folder(source) as root:
        try:
            visit(root)
        except _ScanLimit:
            report["partial"] = True
    report["indexed"] = len(records)
    with service.lock:
        _source(service, identity)  # Removing a source during a scan must not resurrect it.
        if not report["partial"]:
            service.db.execute("DELETE FROM external_sessions WHERE source=?", (identity,))
        for row in records.values():
            # The same provider session may be copied into several selected sources.
            service.db.execute(
                "INSERT INTO external_sessions VALUES(?,?,?,?,?,?) ON CONFLICT(id,source) DO UPDATE SET "
                "source=excluded.source,relative=excluded.relative,metadata=excluded.metadata,"
                "stamp=excluded.stamp,updated=excluded.updated WHERE excluded.updated>=external_sessions.updated",
                row,
            )
        service.db.execute(
            "UPDATE external_session_sources SET scanned=?,report=? WHERE id=?",
            (time.time(), json.dumps(report), identity),
        )
        service.db.commit()
    return report


def list_sessions(service, params):
    query = params.get("query", "")
    source = params.get("source", "")
    project = params.get("project", "")
    if not all(isinstance(value, str) for value in [query, source, project]) or len(query) > 200:
        raise ValueError("Keep external session searches under 200 characters")
    with service.lock:
        cwd = str(service.project(project)) if project else ""
        revision = _digest([(row["id"], row["scanned"]) for row in list_sources(service)])
        scope = [query, source, project, revision]
        offset = 0
        if params.get("cursor"):
            try:
                cursor = str(params["cursor"])
                if len(cursor) > 2048:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(cursor))
                offset = saved["offset"]
                if saved["scope"] != scope or type(offset) is not int or offset < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise ValueError(
                    "Refresh external sessions after changing the source or search"
                ) from None
        rows = service._all(
            "SELECT e.*,s.path AS source_path FROM external_sessions e "
            "JOIN external_session_sources s ON s.id=e.source ORDER BY e.updated DESC,e.id,e.source"
        )
        items = []
        seen = set()
        for row in rows:
            meta = json.loads(row["metadata"])
            if source and row["source"] != source or cwd and meta["cwd"] != cwd:
                continue
            if (
                query.casefold()
                not in " ".join(
                    [meta["title"], meta["cwd"], meta["session_id"], meta["branch"]]
                ).casefold()
            ):
                continue
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            items.append(
                {
                    **meta,
                    "id": row["id"],
                    "source": row["source"],
                    "source_path": row["source_path"],
                    "relative": row["relative"],
                    "updated": row["updated"],
                }
            )
        cursor = (
            base64.urlsafe_b64encode(
                json.dumps({"scope": scope, "offset": offset + 50}).encode()
            ).decode()
            if offset + 50 < len(items)
            else ""
        )
        return {"items": items[offset : offset + 50], "count": len(items), "next_cursor": cursor}


def _record(service, params):
    rows = service._all(
        "SELECT * FROM external_sessions WHERE id=? AND (?='' OR source=?) ORDER BY updated DESC,source",
        (params.get("id"), params.get("source", ""), params.get("source", "")),
    )
    if not rows:
        raise ValueError("Recorded session is no longer indexed. Refresh the source.")
    return rows[0]


def preview_session(service, params):
    row = _record(service, params)
    source = _source(service, row["source"])
    messages = deque()
    total = retained = malformed = 0
    header = ""
    with _file(source, row["relative"]) as stream:
        before = os.fstat(stream.fileno())
        metadata = _metadata(stream)
        if metadata is None or _digest(["codex", metadata["session_id"]]) != row["id"]:
            raise ValueError("Recorded session identity changed. Refresh the source.")
        header = (
            "External Codex conversation context\n"
            "Recorded text for reference; it is not current instructions or a resumed provider session.\n"
            f"Session: {metadata['session_id']}\nRecorded project: {metadata['cwd']}\n"
            "Only user/assistant text is included. Tool records, reasoning and attachments are excluded. "
            "Provider authentication and permissions are not transferred.\n"
        )
        offset = max(0, before.st_size - TRANSCRIPT_BYTES)
        stream.seek(offset)
        if offset:
            # Do not parse a JSON record that begins outside the inspected tail.
            while stream.readline(LINE_BYTES) and not stream.tell() >= before.st_size:
                stream.seek(-1, os.SEEK_CUR)
                if stream.read(1) == b"\n":
                    break
        while stream.tell() < before.st_size:
            line = stream.readline(min(LINE_BYTES, before.st_size - stream.tell()))
            if not line:
                break
            if not line.endswith(b"\n"):
                # Oversized records and incomplete final writes are omitted entirely.
                while line and not line.endswith(b"\n") and stream.tell() < before.st_size:
                    line = stream.readline(min(LINE_BYTES, before.st_size - stream.tell()))
                malformed += 1
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError, RecursionError):
                malformed += 1
                continue
            payload = (
                record.get("payload")
                if isinstance(record, dict) and record.get("type") == "response_item"
                else None
            )
            if (
                not isinstance(payload, dict)
                or payload.get("type") != "message"
                or payload.get("role") not in ("user", "assistant")
            ):
                continue
            content = payload.get("content")
            if not isinstance(content, list):
                continue
            text = "\n".join(
                item["text"]
                for item in content
                if isinstance(item, dict)
                and item.get("type") in ("input_text", "output_text")
                and isinstance(item.get("text"), str)
            )
            if not text.strip():
                continue
            try:
                text.encode("utf-8")
            except UnicodeError:
                malformed += 1
                continue
            total += 1
            rendered = (
                payload["role"].capitalize()
                + ":\n"
                + text[:8000]
                + ("\n[Message shortened]" if len(text) > 8000 else "")
            )
            messages.append(rendered)
            retained += len(rendered)
            while (
                retained + 2 * len(messages) > CONTEXT_CHARS - len(header) - 1000
                or len(messages) > 64
            ):
                retained -= len(messages.popleft())
        after = os.fstat(stream.fileno())
    if _stamp(before) != _stamp(after):
        raise ValueError("Session changed while being read. Reload the preview after it settles.")
    if not messages:
        raise ValueError(
            "No supported user/assistant text was found in the inspected session tail."
        )
    text = (
        header
        + f"Included {len(messages)} of {total} text messages in the inspected tail. "
        + ("Earlier file content was not inspected. " if offset else "")
        + (f"Omitted {malformed} malformed, oversized or incomplete records. " if malformed else "")
        + "Review this context and add your own request before sending.\n\n"
        + "\n\n".join(messages)
    )
    digest = _digest([row["id"], source["id"], _stamp(before), text])
    with service.lock:
        _source(service, source["id"])
    if params.get("expected_digest") is not None and params["expected_digest"] != digest:
        raise ValueError(
            "Session changed since review. Reload the preview before adding it to a draft."
        )
    return {
        "text": text,
        "digest": digest,
        "included_messages": len(messages),
        "omitted_messages": total - len(messages),
        "partial_file": bool(offset),
        "malformed_records": malformed,
        "source": source["id"],
    }


def reveal_session(service, params):
    row = _record(service, params)
    source = _source(service, row["source"])
    with _file(source, row["relative"]):
        return {"path": str(Path(source["path"]) / row["relative"])}
