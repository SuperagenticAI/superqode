"""A common filesystem boundary for execution, offline capture and recovery."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path

from .definition import project_path

_exclusive_root = ContextVar("factory_exclusive_root", default=None)


def assert_enabled(root):
    marker = project_path(
        Path(root).resolve(), ".superqode/factory-operations/recovery-required.json"
    )
    if marker.exists():
        raise ValueError(
            "Recovered Factory is disarmed; inspect and explicitly acknowledge recovery first"
        )
    retired = project_path(Path(root).resolve(), ".superqode/factory-operations/retired.json")
    if retired.exists():
        raise ValueError(
            "Factory instance is retired; explicitly reactivate after reviewing its evidence"
        )


@contextmanager
def execution(root, *, exclusive=False, require_enabled=True):
    import fcntl

    root = Path(root).resolve()
    path = project_path(root, ".superqode/factory-operations/execution.lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "Factory execution or offline maintenance still owns this project"
            ) from None
        if require_enabled:
            assert_enabled(root)
        token = _exclusive_root.set(root) if exclusive else None
        try:
            yield
        finally:
            if token is not None:
                _exclusive_root.reset(token)
    finally:
        os.close(fd)


@contextmanager
def store_transaction(path):
    path = Path(path).resolve()
    if (
        path.name == "store.sqlite3"
        and path.parent.name == "workorders"
        and path.parent.parent.name == ".superqode"
    ):
        root = path.parent.parent.parent
        if _exclusive_root.get() == root:
            yield
        else:
            with execution(root, require_enabled=False):
                yield
    else:
        yield
