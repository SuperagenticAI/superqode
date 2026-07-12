"""OS clipboard copy helpers."""

from __future__ import annotations


class HelperClipboardMixin:
    """OS clipboard copy helpers."""

    @staticmethod
    def _os_clipboard_copy(text: str) -> bool:
        """Push ``text`` to the real OS clipboard via the platform CLI.

        Uses pbcopy (macOS), xclip/xsel (Linux), or clip (Windows) — the same
        proven path as ``:copy``. Returns True only if a backend accepted it.
        """
        import subprocess
        import sys

        if sys.platform == "darwin":
            candidates = [["pbcopy"]]
        elif sys.platform.startswith("linux"):
            candidates = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        elif sys.platform.startswith("win"):
            candidates = [["clip"]]
        else:
            candidates = []

        data = text.encode("utf-8")
        for cmd in candidates:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                proc.communicate(data)
                if proc.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return False

    def _copy_text_to_clipboard(self, text: str) -> bool:
        """Copy ``text`` to the clipboard as reliably as possible.

        Tries the real OS clipboard first (pbcopy/xclip/xsel/clip), which is what
        makes mouse-drag copy actually work locally, then always also emits
        Textual's OSC 52 ``copy_to_clipboard`` so it still works over SSH/remote
        sessions where the local CLI can't reach the user's clipboard. Returns
        True if at least one path succeeded.
        """
        if not text:
            return False
        copied = self._os_clipboard_copy(text)
        # Always also emit OSC 52 — harmless when the CLI worked, and the only
        # path that reaches the *local* clipboard from a remote/SSH session.
        try:
            self.copy_to_clipboard(text)
            copied = True
        except Exception:
            pass
        return copied
