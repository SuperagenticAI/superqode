"""A focused file editor that keeps the conversation mounted behind it."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat
import tempfile

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

MAX_EDIT_BYTES = 1024 * 1024


def read_editable_file(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError("Select a regular text file.")
    with path.open("rb") as stream:
        data = stream.read(MAX_EDIT_BYTES + 1)
    if len(data) > MAX_EDIT_BYTES:
        raise ValueError("Files over 1 MB must be edited in an external editor.")
    if b"\0" in data:
        raise ValueError("Binary files cannot be edited here.")
    data.decode("utf-8")  # Never silently replace bytes on save.
    return data


def save_edited_file(path: Path, original: bytes, text: str) -> bytes:
    """Reject external changes and replace atomically, preserving permissions."""
    if read_editable_file(path) != original:
        raise ValueError(
            "File changed on disk. Close and reopen it before saving; your draft is still here."
        )
    # TextArea uses LF internally. Retain the file's existing CRLF convention.
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    data = text.encode("utf-8")
    if len(data) > MAX_EDIT_BYTES:
        raise ValueError("Draft exceeds the 1 MB editing limit. Copy it to an external editor.")
    mode = stat.S_IMODE(path.stat().st_mode)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, mode)
        # Check again after writing the temporary file, before replacing.
        if read_editable_file(path) != original:
            raise ValueError("File changed on disk. Your draft has not been saved.")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return data


class FileEditorScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    FileEditorScreen { align: center middle; background: #000000 70%; }
    FileEditorScreen > Vertical { width: 95%; height: 95%; border: round #a855f7; background: #000000; }
    FileEditorScreen #editor-title { height: 2; padding: 0 1; color: #a855f7; }
    FileEditorScreen TextArea { height: 1fr; }
    FileEditorScreen #editor-status { height: 3; padding: 0 1; }
    FileEditorScreen Horizontal { height: 3; align-horizontal: right; }
    FileEditorScreen Button { margin: 0 1; }
    """
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "close", "Close", priority=True),
    ]

    def __init__(self, path: Path):
        super().__init__()
        self.path = path.resolve()
        self._original: bytes | None = None
        self._saved_text = ""
        self._saving = False
        self._saved = False
        self._discard_requested = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(str(self.path)), id="editor-title")
            yield TextArea("", show_line_numbers=True, id="file-editor", disabled=True)
            yield Static("Loading file…", id="editor-status", markup=False)
            with Horizontal():
                yield Button("Save · Ctrl+S", id="editor-save", variant="primary", disabled=True)
                yield Button("Close · Esc", id="editor-close")

    async def on_mount(self) -> None:
        try:
            self._original = await asyncio.to_thread(read_editable_file, self.path)
            self._saved_text = self._original.decode("utf-8").replace("\r\n", "\n")
            editor = self.query_one(TextArea)
            editor.load_text(self._saved_text)
            editor.disabled = False
            self.query_one("#editor-save", Button).disabled = False
            self._status("Ctrl+S saves · Esc returns to the conversation")
            editor.focus()
        except (OSError, ValueError) as exc:
            self._status(str(exc))

    def _status(self, message: str) -> None:
        self.query_one("#editor-status", Static).update(message)

    @on(TextArea.Changed)
    def _changed(self) -> None:
        self._discard_requested = False
        if self._original is not None and not self._saving:
            dirty = self.query_one(TextArea).text != self._saved_text
            self._status("Unsaved changes · Ctrl+S to save" if dirty else "No unsaved changes")

    async def action_save(self) -> None:
        if self._original is None or self._saving:
            return
        editor = self.query_one(TextArea)
        text = editor.text
        if text == self._saved_text:
            self._status("No unsaved changes")
            return
        self._saving = True
        editor.read_only = True
        try:
            self._original = await asyncio.to_thread(
                save_edited_file, self.path, self._original, text
            )
            self._saved_text = text
            self._saved = True
            self._discard_requested = False
            self._status("Saved · Esc returns to the conversation")
        except (OSError, ValueError) as exc:
            self._status(str(exc))
        finally:
            self._saving = False
            editor.read_only = False

    def action_close(self) -> None:
        if self._saving:
            return
        if self.query_one(TextArea).text != self._saved_text and not self._discard_requested:
            self._discard_requested = True
            self._status("Unsaved changes. Ctrl+S to save, or press Esc again to discard.")
            return
        self.dismiss(self._saved)

    @on(Button.Pressed)
    async def _button(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "editor-save":
            await self.action_save()
        else:
            self.action_close()
