"""Vim-mode search and ex-command history."""

from __future__ import annotations
from superqode.app.widgets import (
    ConversationLog,
)


class HelperVimMixin:
    """Vim-mode search and ex-command history."""

    def _record_ex_command(self, cmd: str, command_name: str) -> None:
        if not cmd.startswith(":"):
            return
        if command_name in {"vim", "set"}:
            return
        normalized = ":" + cmd[1:].strip()
        if normalized in {":", ":history"}:
            return
        self._last_ex_command = normalized
    def _repeat_last_ex_command(self, log: ConversationLog) -> None:
        command = getattr(self, "_last_ex_command", "")
        if not command:
            log.add_info("No Ex command to repeat yet.")
            return
        log.add_info(f"Repeating {command}")
        self._handle_command(command, log)
    def _try_vim_search_input(self, text: str, log: ConversationLog) -> bool:
        if text in {"n", "N"}:
            self._vim_search_next(log, reverse=(text == "N"))
            return True
        if text.startswith("?") and len(text) > 1:
            self._vim_search(log, text[1:].strip(), reverse=True)
            return True
        if text.startswith("/") and len(text) > 1 and not self._is_known_slash_input(text):
            self._vim_search(log, text[1:].strip(), reverse=False)
            return True
        return False
    def _scroll_to_vim_search_match(self, log: ConversationLog) -> None:
        matches = getattr(self, "_vim_search_matches", [])
        if not matches or self._vim_search_index < 0:
            return
        message_index = matches[self._vim_search_index]
        try:
            log.auto_scroll = False
            messages = list(getattr(log, "_messages", []))
            target_y = 0
            for _role, content, _agent in messages[:message_index]:
                target_y += max(2, len(str(content).splitlines()) + 2)
            visible_height = max(6, int(getattr(getattr(log, "size", None), "height", 18) or 18))
            log.scroll_to(y=max(0, target_y - max(1, visible_height // 3)), animate=False)
        except Exception:
            pass

        query = getattr(self, "_vim_search_query", "")
        self._set_vim_search_highlight(log, query)
        self._vim_search_feedback(
            log,
            f"Match {self._vim_search_index + 1}/{len(matches)} for {query!r}. "
            "Use n/N to navigate.",
        )
    def _set_vim_search_highlight(self, log: ConversationLog, query: str) -> None:
        setter = getattr(log, "set_search_highlight", None)
        if callable(setter):
            setter(query)
