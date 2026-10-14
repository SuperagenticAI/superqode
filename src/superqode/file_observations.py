"""Session-scoped content observations and guarded file replacement.

Checks detect intervening saves, including saves preserving mtime. Replacement
is atomic but is not an OS compare-and-swap against arbitrary external writers.
Shell commands and third-party tools do not participate in this protocol.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile


class FileConflictError(ValueError):
    """The agent's view is older than the file on disk."""


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FileObservations:
    def __init__(self) -> None:
        self._seen: dict[Path, str] = {}

    def record_path(self, path: Path) -> None:
        with path.open("rb") as stream:
            self._seen[path.resolve()] = hashlib.file_digest(stream, "sha256").hexdigest()

    def check_path(self, path: Path) -> None:
        previous = self._seen.get(path.resolve())
        if previous is None:
            return
        with path.open("rb") as stream:
            current = hashlib.file_digest(stream, "sha256").hexdigest()
        if previous != current:
            raise FileConflictError(
                "File was modified externally since last read. Re-read the file and try again."
            )

    def record(self, path: Path, data: bytes) -> None:
        self._seen[path.resolve()] = fingerprint(data)

    def check(self, path: Path, data: bytes, *, require_read: bool = False) -> None:
        previous = self._seen.get(path.resolve())
        if previous is None and require_read:
            raise FileConflictError("Read the existing file before replacing it.")
        if previous is not None and previous != fingerprint(data):
            raise FileConflictError(
                "File was modified externally since last read. Re-read the file and try again."
            )

    def write(
        self,
        path: Path,
        data: bytes,
        *,
        require_read: bool = False,
        expected: bytes | None = None,
    ) -> None:
        # Resolve existing symlinks and preserve their target, not the link inode.
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            if expected is not None or path in self._seen:
                raise FileConflictError(
                    "File was removed since last read. Re-read before retrying."
                )
            # Exclusive creation prevents overwriting a file created after exists().
            with path.open("xb") as stream:
                stream.write(data)
            self.record(path, data)
            return
        original = path.read_bytes()
        self.check(path, original, require_read=require_read)
        if expected is not None and original != expected:
            raise FileConflictError("File changed during editing. Re-read the file and try again.")
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if path.read_bytes() != original:
                raise FileConflictError(
                    "File changed during editing. Re-read the file and try again."
                )
            os.replace(temporary, path)
            self.record(path, data)
        finally:
            Path(temporary).unlink(missing_ok=True)
