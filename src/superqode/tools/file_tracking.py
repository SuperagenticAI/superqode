"""
File Time Tracking - Prevent edit conflicts.

Tracks when files were last read per session. Before editing, we check that
the file has not been modified externally since the last read. If it has,
we require the user/agent to re-read and try again.

"""

from pathlib import Path
from typing import Dict, Optional, Tuple

# (session_id, resolved_path_str) -> mtime at last read
_file_read_times: Dict[Tuple[str, str], float] = {}


def record_file_read(session_id: str, path: str, mtime: float) -> None:
    """Record that a file was read at the given mtime."""
    resolved = str(Path(path).resolve())
    _file_read_times[(session_id, resolved)] = mtime


def get_file_read_mtime(session_id: str, path: str) -> Optional[float]:
    """Get the mtime when this file was last read in this session, or None."""
    resolved = str(Path(path).resolve())
    return _file_read_times.get((session_id, resolved))


def check_file_unchanged(
    session_id: str, path: str, current_mtime: float
) -> Tuple[bool, Optional[str]]:
    """
    Check that the file has not been modified since last read.
    Returns (True, None) if ok to edit, or (False, error_message) if not.
    If the file was never read in this session, we allow the edit (no prior read to compare).
    """
    stored = get_file_read_mtime(session_id, path)
    if stored is None:
        return (True, None)
    if current_mtime != stored:
        return (
            False,
            "File was modified externally since last read. Re-read the file and try again.",
        )
    return (True, None)
