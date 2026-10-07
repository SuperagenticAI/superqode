"""Bounded on-demand previews for pasted text and local shell output."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea
from rich.text import Text

from superqode.app.constants import THEME
from superqode.app.mixins.composer_blocks import PREVIEW_CHARS


class BoundedExcerptArea(TextArea):
    def _on_paste(self, event):
        if len(self.text) - len(self.selected_text) + len(event.text) > PREVIEW_CHARS:
            event.prevent_default()
            event.stop()
            self.screen.query_one("#block-notice", Static).update(
                "Excerpt limit is 32,768 characters. Select a smaller part."
            )


class ComposerBlockPreview(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    DEFAULT_CSS = """
    ComposerBlockPreview { align: center middle; }
    #block-panel { width: 94%; height: 90%; padding: 0 1; border: round $primary; }
    #block-title { height: 2; }
    #block-notice { height: 2; }
    #block-text { height: 1fr; }
    #block-actions { height: 3; }
    #block-actions Button { width: 1fr; min-width: 8; }
    """

    def __init__(self, text, label, *, stage=None, remove=None, total=None):
        super().__init__()
        self._block_text = text
        self._block_label = label
        self._stage_excerpt = stage
        self._remove_block = remove
        self._reported_total = len(text) if total is None else total
        self.preview_offset = 0
        self._excerpt_staged = False

    def compose(self) -> ComposeResult:
        with Vertical(id="block-panel"):
            yield Static(Text(self._block_label), id="block-title")
            yield Static("", id="block-notice")
            yield BoundedExcerptArea(
                self._block_text[:PREVIEW_CHARS],
                read_only=self._stage_excerpt is None,
                id="block-text",
            )
            with Horizontal(id="block-actions"):
                yield Button("Previous", id="block-prev", disabled=True)
                yield Button(
                    "Next", id="block-next", disabled=len(self._block_text) <= PREVIEW_CHARS
                )
                yield Button("Stage excerpt" if self._stage_excerpt else "Remove", id="block-use")
                yield Button("Back", id="block-back")

    def on_mount(self):
        self.query_one("#block-panel").styles.background = THEME["surface2"]
        self.query_one("#block-panel").styles.border = ("round", THEME["purple"])
        self.query_one("#block-title").styles.color = THEME["magenta"]
        self.query_one("#block-text", TextArea).focus()
        self._notice()

    def _notice(self):
        end = min(len(self._block_text), self.preview_offset + PREVIEW_CHARS)
        suffix = (
            " Edit this page or select text; only that excerpt will be staged."
            if self._stage_excerpt
            else " Full block stays intact when sent."
        )
        if self._reported_total > len(self._block_text):
            suffix += " Output retention capped; remaining content is unavailable here."
        self.query_one("#block-notice", Static).update(
            Text(
                f"Characters {self.preview_offset:,}–{end:,} of {self._reported_total:,}." + suffix
            )
        )

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        name = event.button.id
        if name == "block-back":
            self.action_close()
        elif name == "block-use":
            if self._stage_excerpt:
                viewer = self.query_one("#block-text", TextArea)
                excerpt = viewer.selected_text or viewer.text
                if len(excerpt) > PREVIEW_CHARS:
                    self.query_one("#block-notice", Static).update(
                        "Excerpt limit is 32,768 characters. Select a smaller part."
                    )
                    return
                if excerpt and not self._excerpt_staged and self._stage_excerpt(excerpt):
                    self._excerpt_staged = True
                    self.dismiss()
            else:
                self._remove_block()
                self.dismiss()
        elif name in {"block-prev", "block-next"}:
            self.preview_offset += PREVIEW_CHARS if name == "block-next" else -PREVIEW_CHARS
            self.preview_offset = max(
                0, min(self.preview_offset, max(0, len(self._block_text) - 1))
            )
            self.query_one("#block-text", TextArea).load_text(
                self._block_text[self.preview_offset : self.preview_offset + PREVIEW_CHARS]
            )
            self.query_one("#block-prev", Button).disabled = self.preview_offset == 0
            self.query_one("#block-next", Button).disabled = (
                self.preview_offset + PREVIEW_CHARS >= len(self._block_text)
            )
            self._notice()

    def action_close(self):
        self.dismiss()
