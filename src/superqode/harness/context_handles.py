"""Local context handles for recursive harnessing.

Handles let agents refer to large local artifacts without stuffing them into
the model window. The first implementation is intentionally file-backed and
small: resolve a handle to text, then expose peek/grep/chunk operations.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import FileHarnessStore


DEFAULT_CHUNK_CHARS = 12000
MAX_HANDLE_BYTES = 2_000_000


@dataclass(frozen=True)
class ContextChunk:
    """One bounded chunk from a context handle."""

    chunk_id: str
    handle: str
    offset: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "handle": self.handle,
            "offset": self.offset,
            "chars": len(self.text),
            "preview": self.text[:240],
        }


def resolve_context_handle(handle: str, cwd: Path, *, store_path: Path | None = None) -> str:
    """Resolve a local context handle into bounded text."""
    raw = str(handle or "").strip()
    if not raw:
        raise ValueError("context handle is required")
    root = Path(cwd).resolve()
    kind, _, value = raw.partition(":")
    if not value:
        kind, value = "file", raw
    kind = kind.strip().lower()
    value = value.strip()

    if kind == "file":
        return _read_file(_safe_path(value, root))
    if kind == "repo":
        return _repo_glob(value or "**/*", root)
    if kind == "diff":
        return _git_diff(root, value or "working-tree")
    if kind == "run":
        return _run_text(value, root, store_path=store_path)
    raise ValueError(f"Unknown context handle kind: {kind}")


def peek_context_handle(
    handle: str,
    cwd: Path,
    *,
    offset: int = 0,
    limit: int = 4000,
    store_path: Path | None = None,
) -> str:
    """Return a bounded slice from a context handle."""
    text = resolve_context_handle(handle, cwd, store_path=store_path)
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    return text[start:end]


def grep_context_handle(
    handle: str,
    pattern: str,
    cwd: Path,
    *,
    limit: int = 50,
    ignore_case: bool = True,
    store_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Search a resolved handle and return line matches."""
    if not pattern:
        raise ValueError("pattern is required")
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    text = resolve_context_handle(handle, cwd, store_path=store_path)
    matches: list[dict[str, Any]] = []
    offset = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            matches.append({"line": line_no, "offset": offset, "text": line[:500]})
            if len(matches) >= max(1, int(limit)):
                break
        offset += len(line) + 1
    return matches


def chunk_context_handle(
    handle: str,
    cwd: Path,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    max_chunks: int = 20,
    store_path: Path | None = None,
) -> list[ContextChunk]:
    """Split a context handle into character chunks on line boundaries."""
    text = resolve_context_handle(handle, cwd, store_path=store_path)
    size = max(1000, int(chunk_chars))
    chunks: list[ContextChunk] = []
    offset = 0
    index = 0
    while offset < len(text) and len(chunks) < max(1, int(max_chunks)):
        end = min(len(text), offset + size)
        if end < len(text):
            newline = text.rfind("\n", offset, end)
            if newline > offset:
                end = newline + 1
        chunks.append(
            ContextChunk(
                chunk_id=f"{_safe_handle_id(handle)}:{index}",
                handle=handle,
                offset=offset,
                text=text[offset:end],
            )
        )
        offset = end
        index += 1
    return chunks


def _safe_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Context handle path is outside the workspace: {resolved}") from exc
    return resolved


def _read_file(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"Context file does not exist: {path}")
    if path.is_dir():
        raise ValueError(f"Context file handle points to a directory: {path}")
    data = path.read_bytes()[:MAX_HANDLE_BYTES]
    return data.decode("utf-8", errors="replace")


def _repo_glob(pattern: str, root: Path) -> str:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts and fnmatch.fnmatch(str(path.relative_to(root)), pattern)
    ]
    files.sort()
    parts: list[str] = []
    total = 0
    for path in files:
        rel = path.relative_to(root)
        try:
            text = path.read_bytes()[:MAX_HANDLE_BYTES].decode("utf-8", errors="replace")
        except OSError:
            continue
        block = f"\n--- {rel} ---\n{text}"
        if total + len(block) > MAX_HANDLE_BYTES:
            parts.append(f"\n--- truncated after {rel} ---\n")
            break
        parts.append(block)
        total += len(block)
    return "".join(parts).lstrip()


def _git_diff(root: Path, target: str) -> str:
    args = ["git", "-C", str(root), "diff"]
    if target not in {"", "working-tree", "unstaged"}:
        args.extend(["--", target])
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode not in {0, 1}:
        raise ValueError(result.stderr.strip() or "git diff failed")
    return result.stdout[:MAX_HANDLE_BYTES]


def _run_text(run_id: str, root: Path, *, store_path: Path | None) -> str:
    store = FileHarnessStore(store_path or root / ".superqode" / "harness")
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown harness run: {run_id}")
    lines = [
        f"run_id: {run.run_id}",
        f"session_id: {run.session_id}",
        f"harness: {run.harness}",
        f"status: {run.status}",
        f"parent_run_id: {run.parent_run_id}",
        f"root_run_id: {run.root_run_id}",
        f"prompt_preview: {run.prompt_preview}",
        "",
        "events:",
    ]
    for index, event in enumerate(run.events):
        lines.append(f"- {index}: {event.type} {event.data}")
    return "\n".join(lines)[:MAX_HANDLE_BYTES]


def _safe_handle_id(handle: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", handle).strip("-")[:80] or "handle"


__all__ = [
    "ContextChunk",
    "chunk_context_handle",
    "grep_context_handle",
    "peek_context_handle",
    "resolve_context_handle",
]
