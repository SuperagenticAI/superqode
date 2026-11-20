"""Fast, orderly exit for short-lived desktop worker processes."""

from __future__ import annotations

import atexit
import os
import sys
import threading
import traceback
from typing import Callable


def run_and_exit(main: Callable[[], object]) -> None:
    """Run ``main``, then exit without tearing down the interpreter.

    A worker imports large libraries, and freeing every module at exit adds
    about half a second after the final answer before the app sees the run
    finish. This keeps the normal shutdown steps (non-daemon threads and
    atexit handlers) and skips only the module teardown.
    """
    try:
        main()
        code = 0
    except SystemExit as exc:
        code = _exit_code(exc.code)
    except BaseException:
        traceback.print_exc()
        code = 1
    finish(code)


def finish(code: int) -> None:
    shutdown = getattr(threading, "_shutdown", None)
    if callable(shutdown):
        # Joins non-daemon threads and stops thread pools, as normal exit does.
        try:
            shutdown()
        except Exception:
            traceback.print_exc()
    run_exitfuncs = getattr(atexit, "_run_exitfuncs", None)
    if callable(run_exitfuncs):
        run_exitfuncs()
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass
    os._exit(code)


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    print(value, file=sys.stderr)
    return 1
