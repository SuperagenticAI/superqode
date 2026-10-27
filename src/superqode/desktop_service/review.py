"""Revision-bound native review; inspecting and commenting never mutate the repository."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 500
MAX_ROWS = 5000


def _git(root, *args, data=None, index=None, limit=2_000_000):
    environment = dict(os.environ)
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
        input=data,
        capture_output=True,
        timeout=20,
        env=environment,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip() or "Git review failed")
    if len(result.stdout) > limit:
        raise ValueError("Review output is too large. Narrow the changes using your Git tools.")
    return result.stdout


def _name(path):
    if not isinstance(path, str) or not path or any(c in path for c in "\0\r\n\t"):
        return False
    parts = PurePosixPath(path).parts
    return not (
        PurePosixPath(path).is_absolute()
        or any(p in {"..", ".git", ".aws", ".ssh"} or p.startswith(".env") for p in parts)
        or path.startswith(".superqode/checkpoints/")
    )


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _head(root):
    try:
        return _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    except ValueError:
        # Distinguish an unborn branch from an invalid repository.
        _git(root, "rev-parse", "--git-dir")
        return None


def _source(service, root, params):
    scope = params.get("scope", "uncommitted")
    if scope == "uncommitted":
        return {
            "scope": scope,
            "head": _head(root),
            "label": "Staged, unstaged and untracked changes",
        }
    if scope == "branch":
        reference = params.get("base_ref", "main")
        if (
            not isinstance(reference, str)
            or not reference
            or reference.startswith("-")
            or len(reference) > 200
            or any(c in reference for c in "\0\r\n")
        ):
            raise ValueError("Choose a valid base branch or commit")
        base = (
            _git(root, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}")
            .decode()
            .strip()
        )
        head = _head(root)
        if not head:
            raise ValueError("Commit this branch before reviewing committed branch changes")
        merge_base = _git(root, "merge-base", base, head).decode().strip()
        return {
            "scope": scope,
            "base": merge_base,
            "head": head,
            "label": "Committed changes since the merge base with " + reference,
        }
    if scope != "turn":
        raise ValueError("Choose This turn, Uncommitted or Branch")
    job_id = params.get("job")
    jobs = service._all("SELECT project,kind,status FROM jobs WHERE id=?", (job_id,))
    if not jobs or jobs[0]["project"] != params["project"] or jobs[0]["kind"] != "task":
        raise ValueError("Select a coding run in this project to review its turn")
    if (
        jobs[0]["status"] not in {"completed", "failed", "cancelled", "interrupted", "regressed"}
        or job_id in service.processes
    ):
        raise ValueError("Wait for the selected turn and its output writer to finish")
    events = service._all(
        "SELECT payload FROM events WHERE job=? AND json_extract(payload,'$.type')='checkpoint' ORDER BY seq",
        (job_id,),
    )
    checkpoint = next(
        (
            json.loads(row["payload"])["data"].get("id")
            for row in events
            if json.loads(row["payload"])["data"].get("phase") == "baseline"
        ),
        None,
    )
    if not checkpoint:
        raise ValueError(
            "This turn has no local checkpoint. Choose Uncommitted to inspect current files."
        )
    from .checkpoints import manager_for

    task = manager_for(root)._tasks.get(checkpoint)
    if task is None or not task.finished:
        raise ValueError("The turn has no available sealed checkpoint. Choose Uncommitted instead.")
    return {
        "scope": scope,
        "checkpoint": checkpoint,
        "job": job_id,
        "task": task,
        "label": "Saved workspace changes during this turn; concurrent edits may be included",
    }


def _entries(root, source):
    if source["scope"] == "turn":
        return [("turn", path, "M") for path in sorted(source["task"].after)]
    result = []
    groups = (
        [("branch", [source["base"], source["head"]])]
        if source["scope"] == "branch"
        else [("staged", ["--cached"]), ("unstaged", [])]
    )
    for layer, revisions in groups:
        raw = _git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--name-status",
            "-z",
            *revisions,
            "--",
        )
        fields = raw.decode("utf-8").split("\0")
        for index in range(0, len(fields) - 1, 2):
            result.append((layer, fields[index + 1], fields[index]))
    if source["scope"] == "uncommitted":
        result.extend(
            ("untracked", path, "A")
            for path in _git(root, "ls-files", "--others", "--exclude-standard", "-z")
            .decode("utf-8")
            .split("\0")
            if path
        )
    return result


def _listing(root, source):
    entries = list(
        {
            (layer, path): (layer, path, change)
            for layer, path, change in reversed(_entries(root, source))
        }.values()
    )
    entries.sort(key=lambda row: (row[1], row[0]))
    safe = [(layer, path, change) for layer, path, change in entries if _name(path)]
    return {
        "scope": source["scope"],
        "label": source["label"],
        "files": [
            {"id": _identity([layer, path]), "path": path, "layer": layer, "change": change}
            for layer, path, change in safe[:MAX_FILES]
        ],
        "excluded_count": len(entries) - len(safe),
        "truncated": len(safe) > MAX_FILES,
    }


def _blob(root, revision, path, *, index=False):
    if index:
        raw = _git(root, "ls-files", "--stage", "-z", "--", ":(literal)" + path)
        records = [record for record in raw.split(b"\0") if record]
        if not records:
            return None, 0
        if len(records) != 1:
            raise ValueError("Resolve this file’s index conflict before reviewing its lines")
        mode, oid, stage = records[0].split(b"\t", 1)[0].split()
        if stage != b"0":
            raise ValueError("Resolve this file’s index conflict before reviewing its lines")
    else:
        if revision is None:
            return None, 0
        raw = _git(root, "ls-tree", "-z", revision, "--", ":(literal)" + path)
        if not raw:
            return None, 0
        mode, _, oid = raw.split(b"\t", 1)[0].split()
    mode = int(mode, 8)
    if mode not in {0o100644, 0o100755}:
        raise ValueError("Symbolic links and submodules require review in your Git tools")
    if int(_git(root, "cat-file", "-s", oid.decode())) > MAX_FILE_BYTES:
        raise ValueError("This file exceeds the 1 MB text-review limit")
    return _git(root, "cat-file", "blob", oid.decode(), limit=MAX_FILE_BYTES), mode


def _working(root, path):
    target = root / path
    if target.resolve() != target.absolute() or not target.resolve().is_relative_to(root):
        raise ValueError("Symbolic links require review in your Git tools")
    try:
        info = target.stat()
    except FileNotFoundError:
        return None, 0
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
        raise ValueError("This file is not a regular text file smaller than 1 MB")
    content = target.read_bytes()
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("The file grew beyond the text-review limit")
    return content, 0o100755 if info.st_mode & stat.S_IXUSR else 0o100644


def _versions(root, source, item):
    path, layer = item["path"], item["layer"]
    if layer == "turn":
        task = source["task"]
        before, after = task.before.get(path), task.after.get(path)
        if before is None or after is None:
            raise ValueError("This checkpoint has no complete file baseline")
        return (before.content, before.mode), (after.content, after.mode)
    if layer == "branch":
        return _blob(root, source["base"], path), _blob(root, source["head"], path)
    if layer == "staged":
        return _blob(root, source["head"], path), _blob(root, None, path, index=True)
    before = _blob(root, None, path, index=True) if layer == "unstaged" else (None, 0)
    after = _working(root, path)
    if layer == "unstaged" and before != _blob(root, None, path, index=True):
        raise ValueError("The index changed while loading. Refresh the review.")
    return before, after


def _revision(state):
    content, mode = state
    return _identity([content is not None, mode, hashlib.sha256(content or b"").hexdigest()])


def _hunks(before, after):
    if b"\0" in (before or b"") + (after or b""):
        raise ValueError("Binary files do not have a text-line review")
    old = (before or b"").decode("utf-8").splitlines(keepends=True)
    new = (after or b"").decode("utf-8").splitlines(keepends=True)
    if max(len(old), len(new)) > 20_000 or any(len(line) > 4000 for line in old + new):
        raise ValueError("This file exceeds the line-review limits; inspect it in your editor")
    hunks, count = [], 0
    for hunk_id, group in enumerate(difflib.SequenceMatcher(None, old, new).get_grouped_opcodes(3)):
        a, b = group[0][1], group[0][3]
        header = f"@@ -{a + 1 if group[-1][2] > a else a},{group[-1][2] - a} +{b + 1 if group[-1][4] > b else b},{group[-1][4] - b} @@"
        rows = []
        for tag, i, j, k, end_new in group:
            parts = (
                [("context", old[i:j], i, k)]
                if tag == "equal"
                else [("delete", old[i:j], i, None), ("add", new[k:end_new], None, k)]
            )
            for kind, lines, old_start, new_start in parts:
                for offset, line in enumerate(lines):
                    if count >= MAX_ROWS:
                        return hunks, True
                    rows.append(
                        {
                            "id": len(rows),
                            "kind": kind,
                            "text": line.rstrip("\r\n"),
                            "old_line": None if old_start is None else old_start + offset + 1,
                            "new_line": None if new_start is None else new_start + offset + 1,
                            "no_newline": not line.endswith("\n"),
                        }
                    )
                    count += 1
        hunks.append({"id": hunk_id, "header": header, "lines": rows})
    return hunks, False


def _detail(service, root, params):
    source = _source(service, root, params)
    listing = _listing(root, source)
    item = next((item for item in listing["files"] if item["id"] == params.get("file_id")), None)
    if item is None:
        raise ValueError("The selected change is no longer available. Refresh the review.")
    response = {
        **item,
        "scope": source["scope"],
        "label": source["label"],
        "hunks": [],
        "truncated": False,
        "can_stage": False,
        "issue": "",
    }
    try:
        before, after = _versions(root, source, item)
        if max(len(before[0] or b""), len(after[0] or b"")) > MAX_FILE_BYTES:
            raise ValueError("This file exceeds the 1 MB text-review limit")
        response["base_revision"], response["target_revision"] = _revision(before), _revision(after)
        response["base_mode"] = f"{before[1]:o}" if before[0] is not None else "absent"
        response["target_mode"] = f"{after[1]:o}" if after[0] is not None else "absent"
        revisions = {
            k: source[k] for k in ("base", "head", "checkpoint", "job") if source.get(k) is not None
        }
        response["revisions"] = revisions
        response["snapshot_id"] = _identity(
            [item, revisions, response["base_revision"], response["target_revision"]]
        )
        response["hunks"], response["truncated"] = _hunks(before[0], after[0])
        response["can_stage"] = (
            item["layer"] in {"unstaged", "untracked"} and not response["truncated"]
        )
        response["change"] = (
            "D" if after[0] is None else "A" if before[0] is None else item["change"]
        )
        return response, before, after
    except (ValueError, UnicodeError) as exc:
        response["issue"] = str(exc)
        return response, None, None


def _feedback(detail, params):
    comment = params.get("comment")
    if not isinstance(comment, str) or not comment.strip() or len(comment) > 4000:
        raise ValueError("Enter review feedback of up to 4,000 characters")
    hunk = next((h for h in detail["hunks"] if h["id"] == params.get("hunk_id")), None)
    start, end = params.get("start"), params.get("end")
    if (
        hunk is None
        or type(params.get("hunk_id")) is not int
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start <= end < len(hunk["lines"])
    ):
        raise ValueError("Choose a contiguous line range within one hunk")
    selected = hunk["lines"][start : end + 1]
    if len(selected) > 80 or sum(len(row["text"]) for row in selected) > 12_000:
        raise ValueError("Select up to 80 lines and 12,000 characters for one comment")
    payload = {
        key: detail[key]
        for key in (
            "scope",
            "layer",
            "path",
            "snapshot_id",
            "base_revision",
            "target_revision",
            "revisions",
            "base_mode",
            "target_mode",
        )
    }
    payload.update(comment=comment.strip(), hunk=hunk["header"], lines=selected)
    scope = {"turn": "This turn", "uncommitted": "Uncommitted", "branch": "Branch"}[detail["scope"]]
    lines = [
        f"Review feedback — {scope} / {detail['layer']}",
        f"File: {detail['path']}",
        f"Snapshot: {detail['snapshot_id']}",
        f"Base file fingerprint: {detail['base_revision']}",
        f"Target file fingerprint: {detail['target_revision']}",
        f"File mode: {detail['base_mode']} → {detail['target_mode']}",
        *[f"{key.capitalize()}: {value}" for key, value in detail["revisions"].items()],
        detail["label"],
        "",
        "Requested change:",
        comment.strip(),
        "",
        "Quoted source from the reviewed snapshot; inspect current files before editing:",
        hunk["header"],
    ]
    for row in selected:
        marker = {"add": "+", "delete": "-", "context": " "}[row["kind"]]
        lines.append(
            f"old {row['old_line'] or '–'} / new {row['new_line'] or '–'} [{marker}] "
            + json.dumps(row["text"], ensure_ascii=False)
            + (" (no final newline)" if row["no_newline"] else "")
        )
    return {"text": "\n".join(lines), "anchor": payload}


def _stage(service, root, params):
    # Own the real index lock across validation and replacement. Other Git
    # writers cannot change the selected baseline between those two operations.
    index = Path(
        _git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()
    )
    lock = Path(str(index) + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("The Git index is busy. Wait for the other operation and retry.") from exc
    os.close(descriptor)
    temporary = None
    try:
        detail, _, after = _detail(service, root, params)
        if detail.get("snapshot_id") != params.get("snapshot_id") or detail["issue"]:
            raise ValueError(
                "The reviewed revision changed or is unavailable. Refresh before staging."
            )
        if not detail["can_stage"] or detail["scope"] != "uncommitted":
            raise ValueError("Only complete unstaged or untracked text reviews can be staged here")
        handle, name = tempfile.mkstemp(prefix=".superqode-review-", dir=index.parent)
        os.close(handle)
        temporary = Path(name)
        if index.exists():
            if not stat.S_ISREG(index.lstat().st_mode):
                raise ValueError("The Git index must be a regular file")
            shutil.copyfile(index, temporary)
            temporary.chmod(stat.S_IMODE(index.stat().st_mode))
        else:
            temporary.unlink()
        content, mode = after
        if content is None:
            _git(root, "update-index", "--force-remove", "--", detail["path"], index=temporary)
        else:
            oid = (
                _git(root, "hash-object", "-w", "--path=" + detail["path"], "--stdin", data=content)
                .decode()
                .strip()
            )
            _git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode:o},{oid},{detail['path']}",
                index=temporary,
            )
        with temporary.open("rb") as saved:
            os.fsync(saved.fileno())
        os.replace(temporary, index)
        return {"ok": True}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + ".lock").unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def action(service, root, method, params):
    if method == "review.stage":
        return _stage(service, root, params)
    if method == "review.list":
        return _listing(root, _source(service, root, params))
    detail, _, _ = _detail(service, root, params)
    if method == "review.diff":
        return detail
    if method != "review.feedback":
        raise ValueError("Unknown review action")
    if not params.get("snapshot_id") or detail.get("snapshot_id") != params["snapshot_id"]:
        raise ValueError("The reviewed revision changed. Refresh and select the lines again.")
    if detail["issue"] or detail["truncated"]:
        raise ValueError("This file does not have a complete text review")
    return _feedback(detail, params)
