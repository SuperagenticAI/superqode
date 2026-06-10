"""Doom-loop detection for the agent loop.

Local models in particular can get stuck re-issuing the same tool call —
the same failing grep, the same read of the same file — burning context
and tokens without progress. The detector watches *consecutive identical*
tool calls (same tool, same arguments). At the threshold the call is intercepted and the model gets
corrective feedback instead of another identical result; if the model
ignores the intervention and immediately repeats the same call again, the
run should be aborted.

Identical calls separated by a different call reset the streak, so the
legitimate read → edit → read-again pattern is never flagged.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

DEFAULT_DOOM_LOOP_THRESHOLD = 3


class DoomLoopAbort(RuntimeError):
    """Raised when the model immediately repeats the call it was just warned about.

    At that point more iterations cannot help — the run should stop with a
    clear message instead of burning tokens.
    """


def _signature(name: str, arguments: Dict[str, Any]) -> str:
    try:
        args_key = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_key = str(arguments)
    return f"{name}:{args_key}"


class DoomLoopDetector:
    """Track consecutive identical tool calls within one agent run.

    ``threshold`` is the streak length at which a call is intercepted
    (3 means the third identical call in a row is blocked). ``0`` or a
    negative value disables detection entirely.

    Lifecycle: callers check :meth:`should_abort` first (did the model repeat
    the exact call it was just warned about?), then :meth:`observe` (does this
    call complete a streak that must be blocked?).
    """

    def __init__(self, threshold: int = DEFAULT_DOOM_LOOP_THRESHOLD):
        self.threshold = threshold
        self._last_signature: Optional[str] = None
        self._streak = 0
        self._intervened_signature: Optional[str] = None
        self._fresh_intervention = False
        self.interventions = 0

    def observe(self, name: str, arguments: Dict[str, Any]) -> bool:
        """Record an about-to-execute call. Returns True when it should be blocked."""
        if self.threshold <= 0:
            return False
        sig = _signature(name, arguments)
        if sig == self._last_signature:
            self._streak += 1
        else:
            self._last_signature = sig
            self._streak = 1
        if sig != self._intervened_signature:
            # Any different call clears the post-intervention tripwire.
            self._fresh_intervention = False
        if self._streak < self.threshold:
            return False
        # Threshold reached: intercept, and arm the tripwire — if the very
        # next call is this same signature again, the run should abort.
        self.interventions += 1
        self._intervened_signature = sig
        self._fresh_intervention = True
        self._streak = 0
        return True

    def should_abort(self, name: str, arguments: Dict[str, Any]) -> bool:
        """True when the model repeated the exact call it was just warned about."""
        return (
            self._fresh_intervention and _signature(name, arguments) == self._intervened_signature
        )

    def guidance(self, name: str, count: Optional[int] = None) -> str:
        """Feedback for the model in place of the blocked call's result."""
        times = count or self.threshold
        return (
            f"Loop detected: '{name}' was called {times} times in a row with identical "
            "arguments, so this call was not executed — the result would not change. "
            "Take a different action: change the arguments, try another tool, or if you "
            "are stuck, stop and explain what you were trying to find out."
        )

    def abort_message(self, name: str) -> str:
        """Final message when the run is stopped because the loop persisted."""
        return (
            f"Run stopped: the model kept repeating the identical '{name}' tool call "
            "after being warned about the loop. Re-phrase the request or give more "
            "specific guidance, then try again."
        )


__all__ = ["DEFAULT_DOOM_LOOP_THRESHOLD", "DoomLoopAbort", "DoomLoopDetector"]
