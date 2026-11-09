"""Commit, push and pull request actions using the user's own Git setup.

Every command is an explicit argv list (no shell) run in the project root with
a timeout. The user's Git config, SSH keys, credential helpers, signing and
hooks apply unchanged. Nothing here stores credentials, force pushes, or
touches a repository outside the project.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

ACTIVE = ("running", "needs_approval", "queued", "cancelling")
SENSITIVE_PARTS = {".git", ".ssh", ".aws", ".gnupg"}
# Engine state kept inside projects (checkpoint snapshots, work orders, drafts).
# Never listed for commit and never staged from here.
PRIVATE_PARTS = {".superqode"}
PRIVATE_PREFIXES = (".superqode-",)
# Git methods that change the repository. They hold the project writer lease.
MUTATIONS = {"ship.commit", "ship.push", "ship.create_branch"}
MAX_OUTPUT = 200_000
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


def _env() -> dict:
    env = dict(os.environ)
    # Never block on an interactive credential prompt; report it instead.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    env.setdefault("GCM_INTERACTIVE", "never")
    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    paths = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(paths + [p for p in extra if p not in paths])
    return env


def _run(root: Path, argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            "Git did not finish in time. If it is waiting for a passphrase or sign-in, "
            "run the same step once in Terminal, then try again."
        ) from exc
    except FileNotFoundError as exc:
        raise ValueError(f"{argv[0]} is not installed or not on PATH") from exc


def _git(root: Path, *args: str, timeout: int = 30, check: bool = True) -> str:
    result = _run(root, ["git", *args], timeout)
    if check and result.returncode:
        raise ValueError(plain_error(result.stderr or result.stdout))
    return (result.stdout or "")[:MAX_OUTPUT]


def plain_error(text: str) -> str:
    raw = (text or "").strip()
    low = raw.lower()
    rules = [
        (
            ("nothing to commit", "no changes added to commit"),
            "Nothing to commit. The selected files have no changes.",
        ),
        (
            (
                "authentication failed",
                "permission denied (publickey)",
                "could not read username",
                "terminal prompts disabled",
                "invalid username or password",
                "403",
            ),
            "Git could not sign in to the remote. Check your SSH key or credential helper in Terminal, then try again.",
        ),
        (
            ("non-fast-forward", "fetch first", "[rejected]", "updates were rejected"),
            "The remote has commits you do not have. Pull or rebase in Terminal, then push again. SuperQode never force pushes.",
        ),
        (
            ("hook", "pre-commit", "commit-msg"),
            "A Git hook stopped the commit. Read the hook output below, fix it, and commit again.",
        ),
        (
            ("not currently on any branch", "detached head", "head detached"),
            "You are not on a branch (detached HEAD). Create a branch first.",
        ),
        (
            ("has no upstream branch", "no upstream"),
            "This branch has no upstream yet. Push with Set upstream.",
        ),
        (
            ("gpg failed", "failed to sign", "signing failed", "error: gpg"),
            "Commit signing failed. Check your signing key setup in Terminal.",
        ),
        (
            ("could not resolve host", "network is unreachable", "connection timed out"),
            "The remote could not be reached. Check your network.",
        ),
        (("not a git repository",), "This project is not a Git repository."),
        (
            ("no configured push destination", "does not appear to be a git repository"),
            "This repository has no remote to push to. Add one in Terminal with git remote add.",
        ),
    ]
    for needles, message in rules:
        if any(n in low for n in needles):
            detail = raw.splitlines()[-6:] if raw else []
            return message + ("\n\n" + "\n".join(detail) if detail else "")
    return raw[:2000] or "Git reported an error."


def _gh_path() -> str | None:
    return shutil.which("gh", path=_env()["PATH"])


def assert_idle(service, project: str) -> None:
    """Refuse while any run in the project is active or still reaping."""
    placeholders = ",".join("?" for _ in ACTIVE)
    rows = service._all(
        f"SELECT id FROM jobs WHERE project=? AND status IN ({placeholders})",
        (project, *ACTIVE),
    )
    others = service._all("SELECT id FROM jobs WHERE project=?", (project,))
    if rows or any(row["id"] in getattr(service, "processes", {}) for row in others):
        raise ValueError("Finish or stop the active run before committing or pushing")


_assert_idle = assert_idle


def is_private(relative: str) -> bool:
    """True for engine state inside the project, such as .superqode/checkpoints."""
    parts = PurePosixPath(relative).parts
    return any(part in PRIVATE_PARTS or part.startswith(PRIVATE_PREFIXES) for part in parts)


def _real_root(root: Path) -> Path:
    return Path(os.path.realpath(root))


def _relative_path(root: Path, value) -> str:
    """Validate one project-relative path and return it in POSIX form."""
    if not isinstance(value, str) or not value or "\0" in value or len(value) > 4096:
        raise ValueError("Invalid file path")
    if value.startswith(("/", "~")) or os.path.isabs(value) or "\\" in value:
        raise ValueError("Files must be given relative to the project")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Files must be inside the project")
    real_root = _real_root(root)
    # realpath follows symlinks, so a link pointing outside the project is refused.
    target = Path(os.path.realpath(real_root / value))
    if target != real_root and not target.is_relative_to(real_root):
        raise ValueError("Files must be inside the project")
    if target == real_root:
        raise ValueError("Choose files, not the whole project")
    relative = PurePosixPath(value)
    if any(part in SENSITIVE_PARTS for part in relative.parts) or relative.name.startswith(".env"):
        raise ValueError(f"{relative} looks sensitive and cannot be committed from here")
    if is_private(value):
        raise ValueError(f"{relative} is SuperQode project state and is never committed")
    return value


def _paths(root: Path, values) -> list[str]:
    if not isinstance(values, list) or not values or len(values) > 2000:
        raise ValueError("Choose the files to commit")
    return [":(literal)" + _relative_path(root, value) for value in values]


def _prefix(root: Path) -> str:
    """The project's path inside its repository, for example "apps/web/" or ""."""
    return _git(root, "rev-parse", "--show-prefix").strip()


def changed_files(root: Path) -> list[dict]:
    """Changed files inside the project, relative to the project root.

    Git reports porcelain paths relative to the repository top level, so a
    project below the top level has its prefix removed. Renames keep their
    source path when it is inside the project too.
    """
    prefix = _prefix(root)
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".")
    entries = raw.split("\0")
    files = []
    index = 0

    def local(path: str) -> str | None:
        if prefix and not path.startswith(prefix):
            return None
        return path[len(prefix) :]

    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        source = ""
        if code[0] in "RC" or code[1] in "RC":
            source = entries[index] if index < len(entries) else ""
            index += 1
        relative = local(path)
        if not relative or is_private(relative):
            continue
        item = {
            "path": relative,
            "code": code.strip() or code,
            "staged": code[0] not in " ?",
            # Changes in the working tree that still need staging.
            "unstaged": code[1] != " ",
        }
        original = local(source) if source else None
        if original and not is_private(original):
            item["original"] = original
        files.append(item)
    return files


def _branch_name(name) -> str:
    if not isinstance(name, str) or not _BRANCH.match(name) or name.startswith("-"):
        raise ValueError("Enter a branch name using letters, numbers, '.', '_', '-' or '/'")
    return name


def status(root: Path) -> dict:
    _git(root, "rev-parse", "--is-inside-work-tree")
    prefix = _prefix(root)
    branch = _git(root, "branch", "--show-current").strip()
    has_commits = _run(root, ["git", "rev-parse", "--verify", "HEAD"]).returncode == 0
    upstream = ""
    ahead = behind = 0
    if branch:
        result = _run(root, ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        if result.returncode == 0:
            upstream = result.stdout.strip()
            counts = _run(root, ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"])
            if counts.returncode == 0 and counts.stdout.split():
                ahead, behind = (int(x) for x in counts.stdout.split()[:2])
    remotes = [r for r in _git(root, "remote").split() if r]
    default_branch = ""
    for remote in remotes[:1] if "origin" not in remotes else ["origin"]:
        ref = _run(
            root, ["git", "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"]
        )
        if ref.returncode == 0:
            default_branch = ref.stdout.strip().split("/", 1)[-1]
    if not default_branch:
        for candidate in ("main", "master"):
            if (
                _run(
                    root, ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"]
                ).returncode
                == 0
            ):
                default_branch = candidate
                break
    files = changed_files(root)
    gh = _gh_path()
    gh_ready = False
    if gh:
        gh_ready = _run(root, [gh, "auth", "status"], timeout=15).returncode == 0
    return {
        "branch": branch,
        "detached": not branch and has_commits,
        "has_commits": has_commits,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "remotes": remotes,
        "default_branch": default_branch,
        "on_default_branch": bool(branch) and branch in {default_branch, "main", "master"},
        "files": files[:2000],
        "repository_prefix": prefix,
        "gh_installed": bool(gh),
        "gh_ready": gh_ready,
    }


def draft_message(root: Path, paths: list[str], prompt: str) -> dict:
    names = [p.split(")", 1)[-1] for p in paths]
    stat = _run(root, ["git", "diff", "HEAD", "--shortstat", "--", *paths]).stdout.strip()
    subject = " ".join((prompt or "").split())
    subject = subject[:68].rstrip(" .,;:")
    if not subject:
        top = sorted({Path(n).parent.as_posix() or "." for n in names})
        subject = "Update " + (
            names[0] if len(names) == 1 else f"{len(names)} files in {', '.join(top[:2])}"
        )
    subject = subject[:1].upper() + subject[1:]
    body = "\n".join(f"- {n}" for n in names[:20])
    if len(names) > 20:
        body += f"\n- and {len(names) - 20} more"
    if stat:
        body += f"\n\n{stat}"
    return {"message": subject + "\n\n" + body}


def commit(service, root: Path, params: dict) -> dict:
    assert_idle(service, params["project"])
    selected = [_relative_path(root, value) for value in _list(params.get("paths"))]
    message = str(params.get("message") or "").strip()
    if not message or len(message) > 5000:
        raise ValueError("Enter a commit message of up to 5,000 characters")
    if not _git(root, "branch", "--show-current").strip():
        raise ValueError(plain_error("HEAD detached"))
    # A renamed file commits with its source so the old path is not left behind.
    changed = {f["path"]: f for f in changed_files(root)}
    sources = {path: f.get("original") for path, f in changed.items()}
    originals = {source for source in sources.values() if source}
    chosen = list(dict.fromkeys(selected))
    for path in selected:
        original = sources.get(path)
        if original and original not in chosen:
            chosen.append(_relative_path(root, original))
    paths = [":(literal)" + path for path in chosen]
    # Stage only working tree changes; a path already staged (such as a
    # rename source) has nothing left to add and would fail the pathspec.
    to_add = [
        ":(literal)" + path
        for path in chosen
        if path not in originals and (path not in changed or changed[path].get("unstaged", True))
    ]
    if to_add:
        _git(root, "add", "-A", "--", *to_add)
    # Hooks and signing run as configured; they may take a while.
    output = _git(root, "commit", "-m", message, "--", *paths, timeout=180)
    sha = _git(root, "rev-parse", "--short", "HEAD").strip()
    return {"ok": True, "sha": sha, "output": output[-4000:]}


def _list(values) -> list:
    if not isinstance(values, list) or not values or len(values) > 2000:
        raise ValueError("Choose the files to commit")
    return values


def push(service, root: Path, params: dict) -> dict:
    assert_idle(service, params["project"])
    branch = _git(root, "branch", "--show-current").strip()
    if not branch:
        raise ValueError(plain_error("HEAD detached"))
    argv = ["push"]
    if params.get("set_upstream"):
        remotes = [r for r in _git(root, "remote").split() if r]
        remote = str(
            params.get("remote") or ("origin" if "origin" in remotes else (remotes or [""])[0])
        )
        if remote not in remotes:
            raise ValueError("This repository has no remote to push to")
        argv += ["--set-upstream", remote, branch]
    result = _run(root, ["git", *argv], timeout=180)
    if result.returncode:
        raise ValueError(plain_error(result.stderr or result.stdout))
    return {"ok": True, "output": (result.stderr + result.stdout)[-4000:]}


def create_branch(service, root: Path, params: dict) -> dict:
    assert_idle(service, params["project"])
    name = _branch_name(params.get("name"))
    _git(root, "check-ref-format", "--branch", name)
    _git(root, "switch", "-c", name)
    return {"ok": True, "branch": name}


def create_pr(service, root: Path, params: dict) -> dict:
    gh = _gh_path()
    if not gh:
        raise ValueError(
            "Install the GitHub CLI (gh) and run gh auth login to create pull requests"
        )
    title = str(params.get("title") or "").strip()
    if not title or len(title) > 300:
        raise ValueError("Enter a pull request title")
    body = str(params.get("body") or "")[:60_000]
    argv = [gh, "pr", "create", "--title", title, "--body", body]
    base = params.get("base")
    if base:
        argv += ["--base", _branch_name(base)]
    if params.get("draft"):
        argv.append("--draft")
    result = _run(root, argv, timeout=120)
    if result.returncode:
        text = result.stderr or result.stdout
        if "already exists" in text:
            match = re.search(r"https://\S+", text)
            return {"ok": True, "url": match.group(0) if match else "", "existing": True}
        raise ValueError(plain_error(text))
    match = re.search(r"https://\S+", result.stdout)
    return {"ok": True, "url": match.group(0) if match else result.stdout.strip()}


def action(service, root: Path, method: str, params: dict) -> dict:
    if method == "ship.status":
        return status(root)
    if method == "ship.draft_message":
        return draft_message(
            root, _paths(root, params.get("paths")), str(params.get("prompt") or "")
        )
    if method == "ship.commit":
        return commit(service, root, params)
    if method == "ship.push":
        return push(service, root, params)
    if method == "ship.create_branch":
        return create_branch(service, root, params)
    if method == "ship.create_pr":
        return create_pr(service, root, params)
    raise ValueError("Unknown action")
