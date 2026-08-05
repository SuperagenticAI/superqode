"""Windows implementations of the advisory file locks superqode takes on POSIX.

POSIX callers use ``fcntl.flock`` directly and never reach this module: every
call site keeps its original ``fcntl`` line and only falls through to here when
``import fcntl`` fails, which happens on native Windows alone. Keeping the
Windows code in a separate module means the POSIX import graph is unchanged.

``msvcrt.locking`` is the closest Windows equivalent. It differs from ``flock``
in two ways that the helpers below paper over:

* It locks a byte range starting at the current file position rather than the
  whole file, so each helper seeks to 0 and locks a single byte. Every superqode
  lock file is a pure mutex whose contents are advisory, so one byte is enough
  as long as all parties agree on the range.
* It raises bare ``OSError`` when the range is already held, where ``flock``
  raises ``BlockingIOError``. The non-blocking helper translates it so callers
  can keep catching ``BlockingIOError`` unchanged.
"""

from __future__ import annotations

import contextlib
import time
from typing import IO, Iterator

# Number of bytes each helper locks. Every caller must agree, so this is fixed
# rather than derived from the file size (which is 0 for a freshly created lock).
_LOCK_BYTES = 1

# msvcrt.LK_LOCK retries for ~10 seconds then gives up; superqode's blocking
# locks are expected to wait as long as it takes, so we retry around it.
_BLOCKING_RETRY_SECONDS = 0.25


def _seek_zero(handle: IO) -> None:
    try:
        handle.seek(0)
    except (OSError, ValueError):
        pass


def acquire_nonblocking(handle: IO) -> None:
    """Windows analogue of ``flock(fd, LOCK_EX | LOCK_NB)``.

    Raises ``BlockingIOError`` when another process holds the lock, matching
    what the POSIX branch raises so callers need no extra except clause.
    """
    import msvcrt

    _seek_zero(handle)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
    except OSError as exc:
        raise BlockingIOError(str(exc)) from exc


def acquire_blocking(handle: IO) -> None:
    """Windows analogue of ``flock(fd, LOCK_EX)``: wait until the lock is ours."""
    import msvcrt

    while True:
        _seek_zero(handle)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
            return
        except OSError:
            time.sleep(_BLOCKING_RETRY_SECONDS)


def release(handle: IO) -> None:
    """Windows analogue of ``flock(fd, LOCK_UN)``.

    Releasing a lock we no longer hold is not an error worth propagating: the
    POSIX branch treats unlock as best-effort teardown, so this does too.
    """
    import msvcrt

    _seek_zero(handle)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
    except OSError:
        pass


@contextlib.contextmanager
def file_lock(handle: IO) -> Iterator[None]:
    """Hold an exclusive lock on ``handle`` for the duration of the block."""
    acquire_blocking(handle)
    try:
        yield
    finally:
        release(handle)
