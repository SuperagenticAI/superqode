"""Context as data: the corpus an RLM works over.

The other half of the recursive pattern. `llm_query` asks bounded questions;
this is the thing worth asking them about. A repository is held as a Python
object the model can measure, narrow, slice and query, instead of a wall of text
pasted into the conversation.

Two properties matter more than the API surface:

**Nothing is read until something asks for it.** ``len(context)`` reports the
size of the corpus from directory metadata, so a model can decide how to
approach a repository without paying to load it.

**Chunks remember where they came from.** A chunk carries its file, index and
offsets, so a batched query over chunks produces answers that can be traced back
to the source rather than a pile of anonymous strings.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from superqode.pipy.tools.search import DEFAULT_IGNORED_DIRS

#: Extensions never worth handing to a language model.
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".tiff",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".class",
        ".pyc",
        ".pyo",
        ".wasm",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".wav",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".db",
        ".sqlite",
    }
)


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """Bounds on how much of a repository can become context."""

    max_files: int = 2000
    max_file_bytes: int = 512_000
    max_total_bytes: int = 20_000_000
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None = None) -> "ContextPolicy":
        data = {str(key): value for key, value in dict(config or {}).items()}
        default = cls()

        def number(name: str, fallback: int) -> int:
            value = data.get(f"context_{name}", data.get(name))
            return fallback if value is None else max(1, int(value))

        return cls(
            max_files=number("max_files", default.max_files),
            max_file_bytes=number("max_file_bytes", default.max_file_bytes),
            max_total_bytes=number("max_total_bytes", default.max_total_bytes),
            include=tuple(str(item) for item in data.get("context_include") or ()),
            exclude=tuple(str(item) for item in data.get("context_exclude") or ()),
        )


@dataclass(frozen=True, slots=True)
class ContextChunk:
    """One slice of the corpus, with the provenance to trace it back."""

    text: str
    path: str
    index: int
    start: int
    end: int

    def size(self) -> int:
        """Portable alternative to ``len``; see :meth:`RLMContext.size`."""
        return len(self.text)

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        suffix = "..." if len(self.text) > 60 else ""
        return (
            f"ContextChunk(path={self.path!r}, index={self.index}, "
            f"chars={len(self.text)}, preview={preview + suffix!r})"
        )

    def labelled(self) -> str:
        """The chunk with its source, for handing to a subcall."""
        return f"# {self.path} (chars {self.start}-{self.end})\n{self.text}"


class RLMContext:
    """A repository or document held as data.

    Construct a narrowed view with :meth:`select` rather than mutating; a view
    shares the policy and root, so a model can keep several around at once.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        policy: ContextPolicy | None = None,
        paths: Sequence[str] | None = None,
        document: str = "",
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.policy = policy or ContextPolicy()
        self.document = document
        self._explicit = [str(item) for item in paths] if paths is not None else None
        self._files: list[str] | None = None
        self._truncated: list[str] = []

    @property
    def profile(self) -> str:
        if self.document:
            return "document"
        return "explicit" if self._explicit is not None else "repository"

    def files(self) -> list[str]:
        """In-scope paths, relative to the root, discovered once and cached."""
        if self._files is None:
            self._files = self._discover()
        return list(self._files)

    def size(self) -> int:
        """Portable alternative to ``len``.

        Monty does not dispatch ``len()`` to a user class, so code that must run
        under every profile calls this instead.
        """
        return len(self)

    def __len__(self) -> int:
        """Total bytes of the corpus, from metadata rather than by reading it."""
        if self.document:
            return len(self.document)
        total = 0
        for name in self.files():
            try:
                total += (self.root / name).stat().st_size
            except OSError:
                continue
        return total

    def __repr__(self) -> str:
        if self.document:
            return f"RLMContext(profile='document', chars={len(self.document)})"
        return (
            f"RLMContext(profile={self.profile!r}, root={str(self.root)!r}, "
            f"files={len(self.files())}, bytes={len(self)})"
        )

    def stats(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "root": str(self.root),
            "files": len(self.files()) if not self.document else 0,
            "bytes": len(self),
            "truncated": list(self._truncated),
            "max_files": self.policy.max_files,
            "max_file_bytes": self.policy.max_file_bytes,
            "max_total_bytes": self.policy.max_total_bytes,
        }

    def read(self, path: str | Path) -> str:
        """Read one in-scope file, bounded by the per-file limit."""
        if self.document:
            raise ValueError("A document context has no files; use text() instead")
        target = self._resolve(path)
        name = str(target.relative_to(self.root))
        if name not in self.files():
            raise ValueError(f"Path is outside the configured RLM context: {name}")
        return self._read(target, name)

    def search(self, pattern: str, *, limit: int = 200) -> list[str]:
        """Matching lines as ``path:line:text``, bounded so it stays readable."""
        regex = re.compile(pattern)
        matches: list[str] = []
        for name, text in self._contents():
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{name}:{number}:{line}")
                    if len(matches) >= limit:
                        return matches
        return matches

    def select(self, *patterns: str) -> "RLMContext":
        """A narrowed view, matched by glob against in-scope paths."""
        if self.document:
            raise ValueError("A document context cannot be narrowed by path")
        chosen = [
            name
            for name in self.files()
            if any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
        ]
        narrowed = RLMContext(self.root, policy=self.policy, paths=chosen)
        narrowed._files = chosen
        return narrowed

    def text(self) -> str:
        """The whole corpus as one string, bounded by the total limit."""
        if self.document:
            return self.document
        parts: list[str] = []
        used = 0
        for name, content in self._contents():
            block = f"# {name}\n{content}"
            if used + len(block) > self.policy.max_total_bytes:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)

    def chunk(self, size: int = 20_000, *, overlap: int = 0) -> list[ContextChunk]:
        """Split the corpus into slices that remember where they came from."""
        if size <= 0:
            raise ValueError("Chunk size must be positive")
        step = max(1, size - max(0, overlap))
        chunks: list[ContextChunk] = []
        used = 0
        for name, content in self._contents():
            if not content:
                continue
            for index, start in enumerate(range(0, len(content), step)):
                piece = content[start : start + size]
                if not piece:
                    break
                chunks.append(
                    ContextChunk(
                        text=piece,
                        path=name,
                        index=index,
                        start=start,
                        end=start + len(piece),
                    )
                )
                used += len(piece)
                if used >= self.policy.max_total_bytes:
                    return chunks
        return chunks

    def _contents(self) -> Iterator[tuple[str, str]]:
        if self.document:
            yield ("<document>", self.document)
            return
        for name in self.files():
            try:
                yield (name, self._read(self.root / name, name))
            except OSError:
                continue

    def _read(self, target: Path, name: str) -> str:
        data = target.read_bytes()[: self.policy.max_file_bytes + 1]
        if len(data) > self.policy.max_file_bytes:
            data = data[: self.policy.max_file_bytes]
            if name not in self._truncated:
                self._truncated.append(name)
        return data.decode("utf-8", errors="replace")

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        target = (
            candidate.resolve() if candidate.is_absolute() else (self.root / candidate).resolve()
        )
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path escapes context root: {path}") from exc
        return target

    def _discover(self) -> list[str]:
        if self.document:
            return []
        names = self._explicit if self._explicit is not None else _walk(self.root)
        selected: list[str] = []
        for name in names:
            if len(selected) >= self.policy.max_files:
                break
            if not self._in_scope(name):
                continue
            selected.append(name)
        return sorted(selected)

    def _in_scope(self, name: str) -> bool:
        if self.policy.include and not any(
            fnmatch.fnmatch(name, pattern) for pattern in self.policy.include
        ):
            return False
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.policy.exclude):
            return False
        target = self.root / name
        if target.suffix.lower() in BINARY_SUFFIXES:
            return False
        try:
            if not target.is_file():
                return False
            with target.open("rb") as handle:
                # A NUL byte early on is the cheap, reliable binary signal.
                if b"\0" in handle.read(8192):
                    return False
        except OSError:
            return False
        return True


def _walk(root: Path) -> list[str]:
    """Repository files, respecting .gitignore when git can answer."""
    try:
        completed = subprocess.run(  # noqa: S603,S607 - fixed listing command
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode == 0:
            listed = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if listed:
                return listed
    except (OSError, subprocess.TimeoutExpired):
        pass
    return _walk_filesystem(root)


def _walk_filesystem(root: Path) -> list[str]:
    import os

    names: list[str] = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in DEFAULT_IGNORED_DIRS and not name.startswith(".")
        ]
        for name in files:
            path = Path(directory) / name
            try:
                names.append(str(path.relative_to(root)))
            except ValueError:
                continue
    return names


__all__ = [
    "BINARY_SUFFIXES",
    "ContextChunk",
    "ContextPolicy",
    "RLMContext",
]
