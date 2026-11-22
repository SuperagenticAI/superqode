"""Review and commit only declared Factory sources, independently of engine state.

The normal desktop commit policy stays closed to .superqode. This narrow path
pins source bytes and Git state, then uses an isolated index for a local commit.
"""

from __future__ import annotations

from contextlib import contextmanager
import difflib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .definition import MAX_FILE_BYTES, load_factory, project_path, read_mapping, relative_path
from .snapshot import canonical, digest, resolve_factory

FORMAT = "superqode.factory-source-review/1"
DEFINITION = ".superqode/factory.yaml"
SOURCE_FOLDERS = {
    "components",
    "harnesses",
    "skills",
    "roles",
    "context",
    "evals",
    "evaluators",
    "trials",
}
SECRET_PARTS = {".git", ".ssh", ".aws", ".gnupg", "credentials", "secrets", "credentials.json"}
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
DIFF_LIMIT = 200_000
TOTAL_DIFF_LIMIT = 600_000


def source_name(value):
    """Validate a portable source name without accessing the filesystem."""
    relative_path(value)
    if value != Path(value).as_posix() or any(ord(c) < 32 for c in value):
        raise ValueError("Factory source paths must use canonical relative names")
    parts = Path(value).parts
    if not parts or any(p in SECRET_PARTS or p.startswith((".env", ".superqode-")) for p in parts):
        raise ValueError(f"Sensitive or private Factory source path: {value}")
    if any(p == ".superqode" for p in parts):
        if value != DEFINITION and not (
            len(parts) >= 3
            and parts[0] == ".superqode"
            and parts[1] in SOURCE_FOLDERS
            and ".superqode" not in parts[1:]
        ):
            raise ValueError(f"Runtime state cannot be versioned as a Factory source: {value}")
    if Path(value).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"}:
        raise ValueError(f"Sensitive or runtime Factory source: {value}")
    return value


def source_path(root, value):
    """Allow declared sources; never grant a blanket .superqode exemption."""
    return project_path(root, source_name(value))


def _safe_text(path, text):
    from superqode.desktop_service.studio import _credentials

    if not isinstance(text, str):
        raise ValueError(f"Factory source disappeared during review: {path}")
    if len(text.encode()) > MAX_FILE_BYTES or "\0" in text or PRIVATE_KEY.search(text):
        raise ValueError(f"Factory source is binary, too large or contains a private key: {path}")
    if text.strip() and Path(path).suffix.lower() in {".yaml", ".yml", ".json"}:
        import yaml

        try:
            _credentials(yaml.safe_load(text))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid structured Factory source: {path}") from exc


def _git(root, *args, input=None, index=None, check=True, timeout=30):
    from superqode.desktop_service.ship import _env, plain_error

    env = _env()
    # A caller's alternative repository/index must never redirect this operation.
    for key in tuple(env):
        if key.startswith("GIT_") and key not in {"GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM"}:
            env.pop(key)
    if index:
        env["GIT_INDEX_FILE"] = str(index)
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        input=input,
        stdin=subprocess.DEVNULL if input is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and result.returncode:
        raise ValueError(
            plain_error((result.stderr or result.stdout).decode("utf-8", errors="replace"))
        )
    return result


def _out(root, *args, **kwargs):
    return _git(root, *args, **kwargs).stdout.decode("utf-8")


def _git_file(root, revision, path, *, prefix):
    # The caller gets paths from a verified tree, not from a Git revision string.
    result = _git(root, "show", f"{revision}:{prefix}{path}", check=False)
    if result.returncode:
        return None
    if len(result.stdout) > MAX_FILE_BYTES:
        raise ValueError(f"Tracked Factory source exceeds 250 KB: {path}")
    return result.stdout.decode("utf-8")


def _tree_files(root, revision, prefix):
    raw = _git(root, "ls-tree", "-rz", "--full-name", revision, "--", ".").stdout
    if len(raw) > 8_000_000:
        raise ValueError("Repository tree is too large for Factory source review")
    entries = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        attributes, name = record.split(b"\t", 1)
        mode, kind, token = attributes.decode().split()
        path = name.decode("utf-8")
        if not path.startswith(prefix):
            continue
        entries[path[len(prefix) :]] = {"mode": mode, "kind": kind, "blob": token}
    return entries


def _previous_sources(root, revision, prefix, tree):
    """Walk only HEAD-declared context and inheritance; removed sources stay reviewable."""
    from superqode.harness.loader import (
        _deep_merge_dicts,
        harness_spec_from_dict,
        harness_spec_to_dict,
    )
    from superqode.harness.templates import get_harness_template

    paths = set()

    def read(path):
        source_path(root, path)
        row = tree.get(path)
        if row is None:
            return None
        if row["mode"] not in {"100644", "100755"} or row["kind"] != "blob":
            raise ValueError(f"Tracked Factory sources must be regular files: {path}")
        paths.add(path)
        if len(paths) > 256:
            raise ValueError("Too many tracked Factory sources")
        text = _git_file(root, revision, path, prefix=prefix)
        _safe_text(path, text)
        return text

    text = read(DEFINITION)
    if text is None:
        return paths
    data = read_mapping(text)
    if "apiVersion" not in data:
        return paths

    def harness(reference, base=Path("."), chain=()):
        path = (base / reference).as_posix()
        if len(chain) >= 16 or path in chain:
            raise ValueError("Tracked Factory harness inheritance is cyclic or too deep")
        if path not in tree and "/" not in reference and "." not in reference:
            return harness_spec_to_dict(get_harness_template(reference))
        raw = read(path)
        if raw is None:
            return {}
        value = read_mapping(raw)
        value = value.get("harness", value)
        parent = value.get("inherits", value.get("extends"))
        if parent:
            value = _deep_merge_dicts(harness(parent, Path(path).parent, (*chain, path)), value)
        value.pop("inherits", None)
        value.pop("extends", None)
        return value

    for asset in data.get("data_context", {}).get("files", {}).values():
        read(asset["path"])
    for binding in data.get("inference", {}).get("harnesses", {}).values():
        value = (
            harness(binding["path"])
            if "path" in binding
            else harness_spec_to_dict(get_harness_template(binding["template"]))
        )
        if not value:
            continue
        spec = harness_spec_from_dict(value)
        for path in spec.context.instruction_files:
            read(path)
        for folder in (spec.context.skills_dir, spec.context.roles_dir):
            if folder:
                source_path(root, folder + "/placeholder")
                for path in tree:
                    if path.startswith(folder.rstrip("/") + "/"):
                        read(path)
    return paths


def inspect_sources(root):
    root = Path(root).resolve()
    # Versioning targets the selected project, including a project within a monorepo.
    _out(root, "rev-parse", "--is-inside-work-tree")
    prefix = _out(root, "rev-parse", "--show-prefix").strip()
    branch = _out(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    head = _out(root, "rev-parse", "--verify", "HEAD", check=False).strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise ValueError(
            "Create the application's initial Git commit before versioning its Factory"
        )
    definition = load_factory(root=root)
    if definition.path != root / DEFINITION:
        raise ValueError("Factory source review requires the saved project definition")
    if definition.legacy:
        sources = {DEFINITION: {"text": definition.path.read_text(encoding="utf-8")}}
        snapshot = ""
    else:
        resolved = resolve_factory(definition)
        sources = resolved.payload["sources"]
        snapshot = resolved.digest
    for path, source in sources.items():
        source_path(root, path)
        _safe_text(path, source["text"])
    tree = _tree_files(root, head, prefix)
    previous = _previous_sources(root, head, prefix, tree)
    paths = sorted(set(sources) | previous)
    rows = []
    remaining = TOTAL_DIFF_LIMIT
    for path in paths:
        target = source_path(root, path)
        if path not in sources and target.exists():
            # Removing a reference does not authorize deleting a file that still exists.
            continue
        old = tree.get(path)
        if old and (old["kind"] != "blob" or old["mode"] not in {"100644", "100755"}):
            raise ValueError(f"Factory source is not a regular Git file: {path}")
        old_text = _git_file(root, head, path, prefix=prefix) if old else ""
        _safe_text(path, old_text)
        new_text = sources[path]["text"] if path in sources else None
        row = {
            "path": path,
            "old_blob": old["blob"] if old else "",
            "old_mode": old["mode"] if old else "",
            "blob": "",
            "mode": "",
            "disk_digest": "",
        }
        if new_text is not None:
            if not target.is_file() or target.stat().st_nlink != 1:
                raise ValueError(
                    f"Factory source must be a regular file without hard links: {path}"
                )
            raw = target.read_bytes()
            if raw != new_text.encode():
                raise ValueError("Factory sources changed during review; refresh")
            attribute = _out(root, "check-attr", "-z", "filter", "--", path).split("\0")
            if len(attribute) < 3 or attribute[2] not in {"unspecified", "unset"}:
                raise ValueError(
                    f"Factory source uses an external Git filter; review and commit it separately: {path}"
                )
            row["disk_digest"] = digest(new_text)
            row["blob"] = _out(
                root, "hash-object", "-w", "--path", path, "--stdin", input=raw
            ).strip()
            new_text = _out(root, "cat-file", "blob", row["blob"])
            _safe_text(path, new_text)
            filemode = (
                _out(root, "config", "--bool", "core.filemode", check=False).strip() != "false"
            )
            row["mode"] = "100755" if target.stat().st_mode & stat.S_IXUSR else "100644"
            if not filemode:
                row["mode"] = (old or {}).get("mode", "100644")
        row["changed"] = (row["old_blob"], row["old_mode"]) != (row["blob"], row["mode"])
        row["status"] = (
            "deleted"
            if new_text is None
            else "new"
            if not old
            else "modified"
            if row["changed"]
            else "unchanged"
        )
        patch = "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in difflib.unified_diff(
                old_text.splitlines(True),
                (new_text or "").splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        if row["old_mode"] != row["mode"]:
            patch = f"mode {row['old_mode'] or '(absent)'} → {row['mode'] or '(absent)'}\n" + patch
        limit = min(DIFF_LIMIT, remaining)
        encoded = patch.encode()
        row["diff_truncated"] = len(encoded) > limit
        row["diff"] = encoded[:limit].decode("utf-8", errors="ignore")
        remaining -= len(row["diff"].encode())
        rows.append(row)
    payload = {
        "format": FORMAT,
        "repository": str(root),
        "repository_prefix": prefix,
        "head": head,
        "branch": branch,
        "snapshot_digest": snapshot,
        "files": rows,
    }
    payload["digest"] = review_digest(payload)
    return payload


def review_digest(payload):
    return digest(
        canonical(
            {
                key: value
                for key, value in payload.items()
                if key not in {"digest", "review", "created"}
            }
        )
    )


def selected_review(review, paths):
    if review.get("format") != FORMAT or review.get("digest") != review_digest(review):
        raise ValueError("Factory source review is invalid")
    if (
        not isinstance(paths, list)
        or not paths
        or len(paths) > 256
        or any(not isinstance(path, str) for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("Choose the Factory source files to commit")
    files = {row["path"]: row for row in review["files"]}
    for path in paths:
        if (
            not isinstance(path, str)
            or path not in files
            or not files[path]["changed"]
            or files[path]["diff_truncated"]
        ):
            raise ValueError("Choose changed Factory sources with a complete reviewed diff")
    # The canonical saved definition anchors the declared manifest. Never commit a
    # new dependency while silently leaving a changed declaration out of the commit.
    missing = [
        row["path"]
        for row in files.values()
        if row["blob"]
        and not row["old_blob"]
        and row["path"] != DEFINITION
        and row["path"] not in paths
    ]
    if missing:
        raise ValueError("Include the new declared Factory sources: " + ", ".join(missing))
    if files[DEFINITION]["changed"] and DEFINITION not in paths:
        raise ValueError("Include the changed Factory definition in this source commit")
    return [files[path] for path in paths]


@contextmanager
def _index(root):
    folder = project_path(root, ".superqode/factory-studio/git")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=folder, prefix="index-")
    os.close(fd)
    path = Path(name)
    path.unlink()
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".lock").unlink(missing_ok=True)


@contextmanager
def _detached_writer(root, index, head):
    # Let normal commit hooks and signing run against a detached HEAD. Publishing
    # to the user's branch is a separate compare-and-swap against the reviewed HEAD.
    worktree = index.with_name(index.name + "-worktree")
    _git(root, "worktree", "add", "--detach", "--no-checkout", str(worktree), head)
    try:
        gitdir = _out(root, "-C", str(worktree), "rev-parse", "--absolute-git-dir").strip()
        yield ["--git-dir=" + gitdir, "--work-tree=" + str(root)]
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree), check=False)


def commit_sources(root, review, paths, message):
    """Called while the existing desktop job owns the project's writer lease."""
    root = Path(root).resolve()
    selected = selected_review(review, paths)
    if not isinstance(message, str) or not message.strip() or len(message) > 5000:
        raise ValueError("Enter a Factory commit message of up to 5,000 characters")
    fresh = inspect_sources(root)
    if fresh["digest"] != review["digest"] or str(root) != review["repository"]:
        raise ValueError(
            "Factory sources, branch or HEAD changed after review; refresh before committing"
        )
    if not fresh["branch"]:
        raise ValueError("Create or select a Git branch before committing Factory sources")
    with _index(root) as index:
        _git(root, "read-tree", review["head"], index=index)
        for row in selected:
            path = review["repository_prefix"] + row["path"]
            if row["blob"]:
                _git(
                    root,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    row["mode"],
                    row["blob"],
                    path,
                    index=index,
                )
            else:
                _git(root, "update-index", "--force-remove", "--", row["path"], index=index)
        expected = _out(root, "write-tree", index=index).strip()
        with _detached_writer(root, index, review["head"]) as writer:
            output = _out(root, *writer, "commit", "-m", message.strip(), index=index, timeout=180)
            commit = _out(root, *writer, "rev-parse", "HEAD").strip()
            actual = _out(root, *writer, "rev-parse", "HEAD^{tree}").strip()
            parents = _out(root, *writer, "rev-list", "--parents", "-n", "1", "HEAD").split()
            if actual != expected or parents != [commit, review["head"]]:
                raise ValueError(
                    "Git hooks changed the prepared Factory commit; refresh and inspect before retrying"
                )
            reference = "refs/heads/" + review["branch"]
            if _out(root, "symbolic-ref", "--quiet", "HEAD").strip() != reference:
                raise ValueError("Git branch changed while the Factory commit was being prepared")
            # Git performs this comparison atomically. A concurrent writer's newer
            # history is never replaced by the old review's prepared tree.
            published = _git(
                root,
                "update-ref",
                "-m",
                "Factory source commit",
                reference,
                commit,
                review["head"],
                check=False,
            )
            if published.returncode:
                raise ValueError(
                    "Git HEAD changed while preparing the Factory commit; no Factory commit was published. Refresh before retrying"
                )
        # Preserve unrelated staged work; reconcile only the sources just committed.
        sync = _git(
            root,
            "reset",
            "-q",
            "HEAD",
            "--",
            *[":(literal)" + row["path"] for row in selected],
            check=False,
        )
    return {
        "sha": commit,
        "tree": actual,
        "paths": paths,
        "index_updated": sync.returncode == 0,
        "notice": ""
        if sync.returncode == 0
        else "Commit created; Git index reconciliation needs attention. Refresh source control before continuing.",
        "output": output[-4000:],
        "pushed": False,
    }
