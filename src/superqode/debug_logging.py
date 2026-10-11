"""Opt-in local logging with the same redaction as diagnostic exports."""

from __future__ import annotations

import logging
import os
from pathlib import Path


class RedactedFormatter(logging.Formatter):
    def format(self, record):
        from .cli_output import sanitize_diagnostic

        return sanitize_diagnostic(super().format(record))


class DebugFileHandler(logging.StreamHandler):
    def close(self):
        try:
            if self.stream and not self.stream.closed:
                self.flush()
                self.stream.close()
        finally:
            super().close()


def configure_debug_log(path: Path):
    path = Path(path).expanduser().absolute()
    if path.resolve() != path:
        raise OSError("Diagnostic logs cannot follow symbolic links.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            # Python 3.12 on Windows does not expose descriptor chmod.
            os.chmod(path, 0o600)
        stream = os.fdopen(descriptor, "a", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    handler = DebugFileHandler(stream)
    handler.setFormatter(RedactedFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("superqode")
    for previous in list(logger.handlers):
        if getattr(previous, "_superqode_debug", False):
            logger.removeHandler(previous)
            previous.close()
    handler._superqode_debug = True
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    os.environ["SUPERQODE_DEBUG"] = "1"
    os.environ["SUPERQODE_LOG_FILE"] = str(path)
    logger.debug("Diagnostic logging enabled")
    return handler
