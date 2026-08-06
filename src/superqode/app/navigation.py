"""Browser-style back for the terminal user interface.

Screens here are renders into the conversation log rather than Textual screens,
so history is a stack of the calls that draw them. Going back re-runs the
previous draw.

This is history, not hierarchy: it returns where the user came from, which is
not always a screen's declared parent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Screen:
    """One visited screen and the call that draws it again."""

    key: str
    label: str
    restore: Callable[[], None]


@dataclass
class NavigationHistory:
    """Where the user has been, most recent last."""

    _stack: list[Screen] = field(default_factory=list)
    #: Set while a restore runs, so redrawing a screen does not record it as a
    #: new visit and make back a no-op that returns to itself.
    _restoring: bool = False
    #: Set when the visible screen is a result rather than a recorded step, such
    #: as the panel drawn after picking an agent. Back from one of these returns
    #: to the list it was chosen from, so the result must not pop that list off.
    _detached: bool = False
    limit: int = 50

    def visit(self, key: str, label: str, restore: Callable[[], None]) -> None:
        if self._restoring:
            return
        self._detached = False
        if self._stack and self._stack[-1].key == key:
            # Re-rendering the same screen, such as moving the highlight, is
            # not a navigation step.
            self._stack[-1] = Screen(key, label, restore)
            return
        self._stack.append(Screen(key, label, restore))
        if len(self._stack) > self.limit:
            del self._stack[0]

    def detach(self) -> None:
        """Note that what is on screen now is a result, not a recorded step.

        Results are not pushed: re-running one would repeat whatever it did,
        such as reconnecting an agent. Marking instead means back restores the
        list above rather than popping it.
        """
        if not self._restoring:
            self._detached = True

    @property
    def can_go_back(self) -> bool:
        if self._detached:
            return bool(self._stack)
        return len(self._stack) > 1

    @property
    def previous_label(self) -> str:
        if not self.can_go_back:
            return ""
        return self._stack[-1].label if self._detached else self._stack[-2].label

    def back(self) -> bool:
        """Return to the previous screen. False when there is none."""
        if not self.can_go_back:
            return False
        if self._detached:
            # The result is not on the stack, so returning means redrawing the
            # screen above it rather than discarding that screen.
            self._detached = False
        else:
            self._stack.pop()
        target = self._stack[-1]
        self._restoring = True
        try:
            target.restore()
        finally:
            self._restoring = False
        return True

    def clear(self) -> None:
        self._stack.clear()
        self._detached = False


__all__ = ["NavigationHistory", "Screen"]
