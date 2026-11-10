"""Local-only aggregate counters. No prompts, model names or network transport."""

import json
import threading
from pathlib import Path

_NAMES = frozenset(
    {
        "request_attempts",
        "lean_requests",
        "valid_calls",
        "repaired_calls",
        "invalid_calls",
        "corrective_retries",
        "retry_limit_hits",
        "text_calls",
    }
)
_LOCK = threading.Lock()


def counters(event=None, amount=1):
    """Best-effort cross-process totals for local doctor and live context status."""
    if event is not None and event not in _NAMES:
        raise ValueError("Unknown local counter")
    path = Path.home() / ".superqode/local-reliability.json"
    result = dict.fromkeys(sorted(_NAMES), 0)
    try:
        import fcntl

        with _LOCK:
            if event is None and not path.exists():
                return result
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+", encoding="utf-8") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                stream.seek(0)
                try:
                    saved = json.loads(stream.read(65536))
                    result.update(
                        {
                            k: v
                            for k, v in saved.items()
                            if k in _NAMES and type(v) is int and v >= 0
                        }
                    )
                except (ValueError, AttributeError):
                    pass
                if event:
                    result[event] += amount
                    stream.seek(0)
                    stream.truncate()
                    stream.write(json.dumps(result))
    except (OSError, ImportError):
        pass  # An unwritable diagnostics file never blocks a request.
    return result
