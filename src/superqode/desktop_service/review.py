"""Read-only, file-scoped change review and evidence-based task summaries."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import subprocess

LIMIT = 1_000_000


def git(root: Path, *args: str, allow_diff=False) -> str:
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(root), *args],
        capture_output=True,
        timeout=15,
    )
    if result.returncode not in ({0, 1} if allow_diff else {0}):
        raise ValueError(result.stderr.decode(errors="replace").strip() or "Git review unavailable")
    if len(result.stdout) > LIMIT:
        raise ValueError(
            "This comparison is too large. Choose a smaller scope or use Git in Terminal."
        )
    return result.stdout.decode("utf-8", errors="replace")


def private_runtime_path(value):
    parts = Path(value).parts
    return any(
        parts[i] == ".superqode"
        and parts[i + 1] in {"checkpoints", "sessions", "history", "traffic"}
        for i in range(len(parts) - 1)
    )


def safe_path(root: Path, value: str) -> Path:
    path = Path(value)
    target = root / path
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or not target.resolve().is_relative_to(root)
    ):
        raise ValueError("Choose a file inside this project")
    if private_runtime_path(path) or any(
        p in {".git", ".ssh", ".aws"} or p.startswith(".env") for p in path.parts
    ):
        raise ValueError("Sensitive files are not available in change review")
    return target


def comparison(root, params):
    scope = params.get("scope", "working")
    try:
        head = git(root, "rev-parse", "--verify", "HEAD").strip()
    except ValueError:
        head = ""
    if scope == "working":
        return scope, [head] if head else [], not head
    if scope == "staged":
        return scope, ["--cached"], False
    if scope == "unstaged":
        return scope, [], False
    if scope == "branch":
        base = str(params.get("base") or "").strip()
        if not base or len(base) > 300 or not head:
            raise ValueError("Enter an existing base branch or commit")
        resolved = git(
            root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}"
        ).strip()
        ancestor = git(root, "merge-base", resolved, head).strip()
        return scope, [ancestor, head], False
    raise ValueError("Unknown comparison scope")


def review(root: Path, params):
    scope, revision, unborn = comparison(root, params)
    flags = ["--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
    if params.get("path") is not None:
        path = str(params["path"])
        target = safe_path(root, path)
        if unborn or (
            scope == "working" and not git(root, "ls-files", "-z", "--", ":(literal)" + path)
        ):
            if not target.is_file():
                raise ValueError("This new file is no longer available")
            if target.stat().st_size > LIMIT:
                raise ValueError("This file is too large to preview")
            with target.open("rb") as stream:
                content = stream.read(LIMIT + 1)
            if len(content) > LIMIT:
                raise ValueError("This file is too large to preview")
            if b"\0" in content:
                return {"path": path, "diff": "", "binary": True}
            text = content.decode("utf-8", errors="replace")
            patch = "".join(
                difflib.unified_diff(
                    [], text.splitlines(True), fromfile="/dev/null", tofile="b/" + path
                )
            )
        else:
            patch = git(root, "diff", *flags, *revision, "--", ":(literal)" + path)
        return {
            "path": path,
            "diff": patch,
            "binary": "Binary files " in patch or "GIT binary patch" in patch,
        }
    names = git(root, "diff", *flags, "--name-only", "-z", *revision).split("\0")
    if scope == "working":
        names += git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        if unborn:
            names += git(root, "ls-files", "-z").split("\0")
    staged = set(git(root, "diff", *flags, "--cached", "--name-only", "-z").split("\0"))
    rows, hidden = [], 0
    for name in sorted(set(filter(None, names))):
        try:
            target = safe_path(root, name)
        except ValueError:
            hidden += 1
            continue
        rows.append({"path": name, "staged": name in staged, "exists": target.is_file()})
    return {
        "scope": scope,
        "files": rows,
        "hidden": hidden,
        "branch": git(root, "branch", "--show-current").strip(),
    }


def task_summary(service, identity):
    rows = service._all("SELECT * FROM jobs WHERE id=?", (identity,))
    if not rows:
        raise ValueError("Task not found")
    job = rows[0]
    result = json.loads(job["result"]) if job["result"] else {}
    request = json.loads(job["request"])
    checkpoint = ""
    for event in service._all(
        "SELECT payload FROM events WHERE job=? AND json_extract(payload, '$.type')='checkpoint' ORDER BY seq",
        (identity,),
    ):
        event = json.loads(event["payload"])
        data = event.get("data") or {}
        if event.get("type") == "checkpoint" and data.get("phase") in {"baseline", "sealed"}:
            checkpoint = data.get("id", "")
    changes, recorded = [], False
    if checkpoint:
        from .checkpoints import action

        try:
            checkpoints = action(service.project(job["project"]), "checkpoints.list", {})
            item = next((c for c in checkpoints["items"] if c["id"] == checkpoint), None)
            if item and item["sealed"]:
                changes = [
                    {"path": change["path"], "change_type": change["change_type"]}
                    for change in item["changes"]
                ]
                recorded = True
        except (ValueError, OSError):
            pass
    checks = service._all(
        "SELECT id,title,status,result FROM jobs WHERE project=? AND kind='check' AND created>=? ORDER BY created DESC LIMIT 10",
        (job["project"], job["created"]),
    )
    for check in checks:
        check["result"] = json.loads(check["result"]) if check["result"] else {}
    return {
        "id": identity,
        "status": job["status"],
        "kind": job["kind"],
        "harness": request.get("harness", ""),
        "changes": changes,
        "changes_recorded": recorded,
        "checks": checks,
        "error": result.get("error", ""),
    }


def project_actions(root: Path):
    """Suggest declared commands without executing or installing anything."""
    import re

    actions = []
    try:
        package = safe_path(root, "package.json")
        if package.is_file() and package.stat().st_size <= LIMIT:
            value = json.loads(package.read_text())
            scripts = value.get("scripts", {}) if isinstance(value, dict) else {}
            manager = (
                "pnpm"
                if (root / "pnpm-lock.yaml").exists()
                else "yarn"
                if (root / "yarn.lock").exists()
                else "bun"
                if (root / "bun.lock").exists() or (root / "bun.lockb").exists()
                else "npm"
            )
            for name in [
                "test",
                "test:unit",
                "lint",
                "typecheck",
                "type-check",
                "check",
                "build",
            ]:
                if (
                    isinstance(scripts, dict)
                    and isinstance(scripts.get(name), str)
                    and re.fullmatch(r"[a-zA-Z0-9:_-]+", name)
                ):
                    actions.append(
                        {"name": name, "command": f"{manager} run {name}", "source": "package.json"}
                    )
    except (ValueError, OSError):
        pass
    if (root / "pyproject.toml").is_file() and (root / "tests").is_dir():
        actions.append(
            {
                "name": "Python tests",
                "command": "uv run pytest" if (root / "uv.lock").is_file() else "python3 -m pytest",
                "source": "Python project",
            }
        )
    if (root / "Cargo.toml").is_file():
        for name in ["test", "check", "build"]:
            actions.append(
                {"name": "Cargo " + name, "command": "cargo " + name, "source": "Cargo.toml"}
            )
    return actions
