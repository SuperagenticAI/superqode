"""Bounded, read-only source and change inspection in the main workspace."""

from __future__ import annotations

from collections import OrderedDict
import codecs
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Select, Static
from textual.worker import get_current_worker

from superqode.app.constants import THEME
from superqode.code_theme import SourceSyntax
from superqode.sidebar import FilePreviewScroll, _brand_code_bg, _brand_code_theme, detect_language

PAGE_BYTES = 65_536
PAGE_LINES = 400
SEARCH_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SourcePage:
    text: str
    offset: int = 0
    line: int = 1
    next_offset: int | None = None
    next_line: int = 1
    note: str = ""


def read_source_page(path: Path, offset: int = 0, line: int = 1) -> SourcePage:
    """Read one section without loading an entire large or minified file."""
    with path.open("rb") as source:
        if b"\0" in source.read(8192):
            return SourcePage("", note="Binary file · content preview unavailable")
        source.seek(offset)
        data = bytearray()
        count = 0
        while len(data) < PAGE_BYTES and count < PAGE_LINES:
            chunk = source.readline(PAGE_BYTES - len(data))
            if not chunk:
                break
            data.extend(chunk)
            count += chunk.count(b"\n")
        end_offset = source.tell()
        next_offset = end_offset if source.read(1) else None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    text = decoder.decode(bytes(data), final=next_offset is None)
    if next_offset is not None:
        next_offset -= len(decoder.getstate()[0])
    return SourcePage(
        text,
        offset,
        line,
        next_offset,
        line + count,
    )


def text_page(text: str, offset: int = 0) -> SourcePage:
    """Bound change rendering as well as source rendering."""
    section = (
        text[offset : offset + PAGE_BYTES]
        .encode("utf-8")[:PAGE_BYTES]
        .decode("utf-8", errors="ignore")
    )
    lines = section.splitlines(keepends=True)
    data = "".join(lines[:PAGE_LINES])
    next_offset = offset + len(data)
    return SourcePage(data, offset, 1, next_offset if next_offset < len(text) else None)


class WorkspaceReadPane(FilePreviewScroll):
    BINDINGS = [
        Binding("j", "vim_down", "Down", show=False),
        Binding("k", "vim_up", "Up", show=False),
        Binding("g", "vim_top", "Top (gg)", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("ctrl+u", "vim_page_up", "Page up", show=False),
        Binding("ctrl+d", "vim_page_down", "Page down", show=False),
        Binding("escape,q", "chat", "Chat"),
        Binding("ctrl+f,/", "find", "Find"),
        Binding("ctrl+g", "line", "Go to line"),
        Binding("n", "next_match", "Next match"),
        Binding("p", "previous_hunk", "Previous hunk"),
        Binding("]", "next_page", "Next section"),
        Binding("[", "previous_page", "Previous section"),
        Binding("y", "copy", "Copy section"),
        Binding("r", "reload", "Reload"),
    ]

    def _viewer(self) -> WorkspaceViewer:
        return self.parent

    def check_action(self, action, parameters):
        if action.startswith("vim_"):
            return self.app._vim_enabled() and self.app._vim_input_mode == "normal"
        return super().check_action(action, parameters)

    def action_vim_down(self):
        self.scroll_to(y=self.scroll_y + 1, animate=False)

    def action_vim_up(self):
        self.scroll_to(y=max(0, self.scroll_y - 1), animate=False)

    def action_vim_top(self):
        now = monotonic()
        if now - getattr(self, "_top_pending", 0) < 1:
            self.scroll_home(animate=False)
            self._top_pending = 0
        else:
            self._top_pending = now

    def action_vim_bottom(self):
        self.scroll_end(animate=False)

    def action_vim_page_up(self):
        self.scroll_page_up(animate=False)

    def action_vim_page_down(self):
        self.scroll_page_down(animate=False)

    def action_chat(self):
        self._viewer().action_chat()

    def action_find(self):
        self._viewer().show_search("find")

    def action_line(self):
        self._viewer().show_search("line")

    def action_next_match(self):
        viewer = self._viewer()
        if viewer.mode == "changes":
            viewer.move_hunk(1)
        else:
            viewer.find_next()

    def action_previous_hunk(self):
        self._viewer().move_hunk(-1)

    def action_next_page(self):
        self._viewer().next_page()

    def action_previous_page(self):
        self._viewer().previous_page()

    def action_copy(self):
        self._viewer().copy_section()

    def action_reload(self):
        self._viewer().reload()


class WorkspaceViewer(Container):
    """One reusable preview, bounded pinned files, and no file-write actions."""

    BINDINGS = [
        Binding("escape", "dismiss", "Chat", show=False),
        Binding("ctrl+g", "go_line", "Go to line", show=False),
    ]

    DEFAULT_CSS = """
    WorkspaceViewer { display: none; height: 100%; width: 1fr; background: $sq-bg; }
    WorkspaceViewer.visible { display: block; }
    WorkspaceViewer Horizontal { height: 1; }
    WorkspaceViewer Button { height: 1; min-height: 1; min-width: 0; width: auto; border: none !important;
        padding: 0 1; background: $sq-surface; color: $sq-text; }
    WorkspaceViewer Button:hover { background: $sq-hover; }
    WorkspaceViewer Button.active { background: $sq-selected-bg; color: $sq-selected-text; }
    WorkspaceViewer Select { height: 1; border: none; padding: 0; }
    WorkspaceViewer SelectCurrent { height: 1; border: none; padding: 0; }
    WorkspaceViewer Select > SelectCurrent { background: $sq-surface; color: $sq-text; }
    WorkspaceViewer #workspace-files { width: 1fr; }
    WorkspaceViewer #workspace-baseline { width: 19; }
    WorkspaceViewer #workspace-path { width: 1fr; }
    WorkspaceViewer #workspace-path { height: 1; color: $sq-muted; padding: 0 1; }
    WorkspaceViewer #workspace-reader { height: 1fr; background: $sq-code-bg; }
    WorkspaceViewer #workspace-source { height: auto; padding: 0 1; background: $sq-code-bg; }
    WorkspaceViewer #workspace-search { height: 3; }
    WorkspaceViewer #workspace-search Input { height: 3; width: 1fr; }
    WorkspaceViewer #workspace-note { height: 1; color: $sq-muted; padding: 0 1; }
    WorkspaceViewer #workspace-pages { height: 1; }
    WorkspaceViewer #workspace-page-label { width: 1fr; color: $sq-muted; padding: 0 1; }
    """

    class ChatRequested(Message):
        pass

    class SplitRequested(Message):
        pass

    class PromptRequested(Message):
        pass

    def __init__(self, root: Path, **kwargs):
        super().__init__(**kwargs)
        self.root = root
        self.path: Path | None = None
        self.mode = "contents"
        self.baseline = "working"
        self._generation = 0
        self._page = SourcePage("")
        self._patch = ""
        self._pages: list[tuple[int, int]] = []
        self._states: OrderedDict[Path, dict] = OrderedDict()
        self._cache: OrderedDict[tuple, SourcePage] = OrderedDict()
        self._pinned: list[Path] = []
        self._find = ""
        self._match_line = 0
        self._find_position = -1
        self._search_kind = "find"
        self._hunk = -1

    def compose(self):
        with Horizontal(id="workspace-tabs"):
            yield Button("Chat", id="workspace-chat")
            yield Select([], allow_blank=True, prompt="File preview", id="workspace-files")
            yield Button("Pin", id="workspace-pin")
            yield Button("Split", id="workspace-split")
            yield Button("Close", id="workspace-close")
        with Horizontal(id="workspace-heading"):
            yield Static("", id="workspace-path")
            yield Button(
                "Hide prompt · F4", id="workspace-prompt", tooltip="Show or hide the prompt · F4"
            )
        with Horizontal(id="workspace-controls"):
            yield Button("Contents", id="workspace-contents")
            yield Button("Changes", id="workspace-changes")
            yield Select(
                [("Working tree", "working"), ("Staged", "staged"), ("Latest task", "task")],
                value="working",
                allow_blank=False,
                id="workspace-baseline",
            )
        with Horizontal(id="workspace-tools"):
            yield Button("Find", id="workspace-find")
            yield Button("Line", id="workspace-line")
            yield Button("Copy", id="workspace-copy")
            yield Button("Path", id="workspace-copy-path")
        with Horizontal(id="workspace-search"):
            yield Input(placeholder="Find text · Enter next · Esc close", id="workspace-query")
        with WorkspaceReadPane(id="workspace-reader"):
            yield Static("", id="workspace-source")
        with Horizontal(id="workspace-pages"):
            yield Button("Previous", id="workspace-previous")
            yield Static("", id="workspace-page-label")
            yield Button("Next", id="workspace-next")
        yield Static(
            "F4 prompt · Esc Chat · Ctrl+F find · Ctrl+G line · [ ] sections", id="workspace-note"
        )

    def on_mount(self):
        self.query_one("#workspace-search").display = False
        self._controls()

    def _remember(self):
        if self.path is None:
            return
        self._states[self.path] = {
            "mode": self.mode,
            "baseline": self.baseline,
            "offset": self._page.offset,
            "line": self._page.line,
            "pages": self._pages[:],
            "scroll": self.query_one("#workspace-reader").scroll_y,
        }
        self._states.move_to_end(self.path)
        while len(self._states) > 8:
            self._states.popitem(last=False)

    def open_file(self, path: Path, *, mode="contents", baseline="working", line=1):
        self._remember()
        self.path = path.absolute()
        saved = self._states.get(self.path, {})
        self.mode, self.baseline = mode, baseline
        self._pages = saved.get("pages", [])[:] if saved.get("mode") == mode else []
        self._find = ""
        self._match_line = 0
        self._find_position = -1
        same_view = saved.get("mode") == mode and saved.get("baseline") == baseline
        offset = saved.get("offset", 0) if same_view and line == 1 else 0
        start = saved.get("line", 1) if same_view and line == 1 else 1
        self._page = SourcePage("", offset=offset, line=start)
        self._patch = ""
        self.add_class("visible")
        self.query_one("#workspace-search").display = False
        self._controls()
        self._load(offset, start, scroll=saved.get("scroll", 0) if same_view else 0)
        if line > 1:
            self._seek(line, "", self._generation)
        self.call_after_refresh(self.focus_reader)

    def focus_reader(self):
        if self.is_mounted and self.has_class("visible"):
            self.query_one("#workspace-reader").focus()

    def action_dismiss(self):
        if self.query_one("#workspace-search").display:
            self.query_one("#workspace-search").display = False
            self.focus_reader()
        else:
            self.action_chat()

    def action_go_line(self):
        if self.mode == "contents":
            self.show_search("line")

    def _controls(self):
        if not self.is_mounted:
            return
        paths = list(self._pinned)
        if self.path is not None and self.path not in paths:
            paths.append(self.path)
        selector = self.query_one("#workspace-files", Select)
        selector.set_options([(self.relative(path), str(path)) for path in paths])
        if self.path is not None:
            selector.value = str(self.path)
        self.query_one("#workspace-pin", Button).label = (
            "Unpin" if self.path in self._pinned else "Pin"
        )
        self.query_one("#workspace-contents").set_class(self.mode == "contents", "active")
        self.query_one("#workspace-changes").set_class(self.mode == "changes", "active")
        scope = self.query_one("#workspace-baseline", Select)
        scope.display = self.mode == "changes"
        scope.value = self.baseline
        self.query_one("#workspace-line").display = self.mode == "contents"
        self.query_one("#workspace-path", Static).update(
            Text(f"{self.relative(self.path)} · Read only", style=THEME["text"])
        )

    def relative(self, path):
        if path is None:
            return ""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _load(self, offset=0, line=1, *, scroll=0):
        if self.path is None:
            return
        self._generation += 1
        generation = self._generation
        self._hunk = -1
        self.query_one("#workspace-source", Static).update("Loading…")
        self._load_worker = self._read(
            self.path, self.mode, self.baseline, offset, line, generation, scroll
        )

    @work(thread=True, exclusive=True, group="workspace-preview")
    def _read(self, path, mode, baseline, offset, line, generation, scroll):
        if get_current_worker().is_cancelled:
            return
        patch = ""
        cache_key = None
        try:
            if mode == "contents":
                stat = path.stat()
                if not path.is_file():
                    raise OSError("Select a regular file")
                cache_key = (path, stat.st_mtime_ns, stat.st_size, offset, line)
                page = self._cache.get(cache_key) or read_source_page(path, offset, line)
            else:
                if baseline == "task":
                    task = getattr(self.app, "_task_changes_current", None)
                    data = task.diffs.get(self.relative(path), {}) if task else {}
                    patch = data.get("diff_text", "")
                    if not patch:
                        from superqode.widgets.sidebar_panels import DiffPanel

                        panels = self.app.query(DiffPanel)
                        if panels:
                            patch = next(
                                (
                                    item.diff_text
                                    for item in panels.first()._files
                                    if item.path in (str(path), self.relative(path))
                                ),
                                "",
                            )
                    note = "No recorded changes for this file in the latest task"
                else:
                    from superqode.sidebar import get_file_diff

                    patch = get_file_diff(self.root, self.relative(path), baseline == "staged")
                    note = (
                        "No staged changes" if baseline == "staged" else "No working-tree changes"
                    )
                page = text_page(patch, offset) if patch else SourcePage("", note=note)
        except (OSError, ValueError) as exc:
            page = SourcePage("", note=f"Cannot preview file: {exc}")
        if not get_current_worker().is_cancelled:
            self.app.call_from_thread(self._show, generation, page, patch, cache_key, scroll)

    def _show(self, generation, page, patch="", cache_key=None, scroll=0):
        if generation != self._generation or not self.is_mounted:
            return
        self._page, self._patch = page, patch
        if cache_key is not None:
            self._cache[cache_key] = page
            self._cache.move_to_end(cache_key)
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
        self.refresh_theme_colors()
        self.query_one("#workspace-previous", Button).disabled = not self._pages
        self.query_one("#workspace-next", Button).disabled = page.next_offset is None
        label = (
            f"Line {page.line}"
            if self.mode == "contents"
            else self.baseline.replace("working", "Working tree").title()
        )
        if page.next_offset is not None:
            label += " · More available"
        self.query_one("#workspace-page-label", Static).update(label)
        self.call_after_refresh(
            self.query_one("#workspace-reader").scroll_to, y=scroll, animate=False
        )

    def refresh_theme_colors(self):
        if not self.is_mounted:
            return
        page = self._page
        if page.note:
            rendered = Text(page.note, style=THEME["muted"])
        elif self.mode == "contents" and self.path is not None:
            rendered = SourceSyntax(
                page.text,
                detect_language(self.path),
                theme=_brand_code_theme(),
                background_color=_brand_code_bg(),
                line_numbers=True,
                start_line=page.line,
                word_wrap=True,
            )
        else:
            rendered = Text()
            for line in page.text.splitlines(keepends=True):
                role = (
                    "diff_add"
                    if line.startswith("+")
                    else "diff_remove"
                    if line.startswith("-")
                    else "cyan"
                    if line.startswith("@@")
                    else "text"
                )
                rendered.append(line, style=THEME[role])
        self.query_one("#workspace-source", Static).update(rendered)
        self._controls()

    def next_page(self):
        if self._page.next_offset is not None:
            self._pages.append((self._page.offset, self._page.line))
            self._pages = self._pages[-64:]
            self._load(self._page.next_offset, self._page.next_line)

    def previous_page(self):
        if self._pages:
            self._load(*self._pages.pop())

    def reload(self):
        self._cache.clear()
        self._load(
            self._page.offset, self._page.line, scroll=self.query_one("#workspace-reader").scroll_y
        )

    def show_search(self, kind):
        self._search_kind = kind
        self.query_one("#workspace-search").display = True
        query = self.query_one("#workspace-query", Input)
        query.placeholder = (
            "Go to line · Enter · Esc close"
            if kind == "line"
            else "Find text in file · Enter next · Esc close"
        )
        query.value = "" if kind == "line" else self._find
        query.focus()

    @on(Input.Submitted, "#workspace-query")
    def submit_search(self, event):
        event.stop()
        query = event.value.strip()
        if self._search_kind == "line":
            if not query.isdecimal() or int(query) < 1:
                self.app.notify("Enter a positive line number", severity="warning")
                return
            self._seek(int(query), "", self._generation)
        else:
            if query != self._find:
                self._match_line = 0
                self._find_position = -1
            self._find = query
            self.find_next()

    def on_key(self, event):
        if event.key == "escape" and self.query_one("#workspace-search").display:
            event.stop()
            event.prevent_default()
            self.query_one("#workspace-search").display = False
            self.focus_reader()

    def find_next(self):
        if not self._find:
            self.show_search("find")
        elif self.mode == "changes":
            content = self._page.text
            position = content.casefold().find(self._find.casefold(), self._find_position + 1)
            if position < 0:
                position = content.casefold().find(self._find.casefold())
            if position >= 0:
                self._find_position = position
                self._scroll_line(content[:position].count("\n"))
            else:
                self.app.notify("No match in this section", severity="warning")
        else:
            self._seek(self._match_line + 1, self._find, self._generation)

    @work(thread=True, exclusive=True, group="workspace-seek")
    def _seek(self, target, query, generation):
        path = self.path
        if path is None:
            return
        offset, number, scanned = 0, 1, 0
        found = None
        try:
            with path.open("rb") as source:
                while scanned < SEARCH_BYTES and not get_current_worker().is_cancelled:
                    row = source.readline(min(PAGE_BYTES, SEARCH_BYTES - scanned))
                    if not row:
                        break
                    if number >= target and (
                        not query
                        or query.casefold() in row.decode("utf-8", errors="replace").casefold()
                    ):
                        found = (offset, number)
                        break
                    scanned += len(row)
                    offset += len(row)
                    number += row.count(b"\n")
        except OSError:
            pass
        if not get_current_worker().is_cancelled:
            self.app.call_from_thread(self._seek_done, generation, found, query)

    def _seek_done(self, generation, found, query=""):
        if generation != self._generation or not self.has_class("visible"):
            return
        if found is None:
            self.app.notify(
                "Not found within the first 8 MiB. Continue with Next section.", severity="warning"
            )
            return
        self._pages.append((self._page.offset, self._page.line))
        if query:
            self._match_line = found[1]
        self._pages = self._pages[-64:]
        self._load(*found)
        self.query_one("#workspace-search").display = False
        self.focus_reader()

    def _scroll_line(self, number):
        width = max(1, self.query_one("#workspace-source").content_size.width)
        rows = sum(
            max(1, len(Text(line).wrap(self.app.console, width)))
            for line in self._page.text.splitlines()[:number]
        )
        self.query_one("#workspace-reader").scroll_to(y=rows, animate=False)

    def move_hunk(self, direction):
        hunks = [i for i, line in enumerate(self._page.text.splitlines()) if line.startswith("@@")]
        if hunks:
            self._hunk = (self._hunk + direction) % len(hunks)
            self._scroll_line(hunks[self._hunk])

    def copy_section(self):
        self.app.copy_to_clipboard(self._page.text)
        self.app.notify("Copied displayed section")

    def action_chat(self):
        self.suspend()
        self.post_message(self.ChatRequested())

    def suspend(self):
        """Invalidate pending loads before another workspace flow takes over."""
        self._remember()
        self._generation += 1
        self.workers.cancel_group(self, "workspace-preview")
        self.workers.cancel_group(self, "workspace-seek")
        self.remove_class("visible")

    @on(Select.Changed, "#workspace-files")
    def select_file(self, event):
        event.stop()
        if event.value == Select.BLANK or event.value != event.select.value:
            return
        path = Path(str(event.value))
        if path != self.path and path in self._pinned:
            saved = self._states.get(path, {})
            self.open_file(
                path, mode=saved.get("mode", "contents"), baseline=saved.get("baseline", "working")
            )

    @on(Select.Changed, "#workspace-baseline")
    def select_baseline(self, event):
        event.stop()
        if (
            event.value in ("working", "staged", "task")
            and event.value == event.select.value
            and event.value != self.baseline
        ):
            self.baseline = event.value
            self._pages.clear()
            self._load()

    @on(Button.Pressed)
    def button_pressed(self, event):
        event.stop()
        action = event.button.id.removeprefix("workspace-")
        if action in ("chat", "close"):
            self.action_chat()
        elif action == "split":
            self.post_message(self.SplitRequested())
        elif action == "prompt":
            self.post_message(self.PromptRequested())
        elif action in ("contents", "changes"):
            if self.mode != action:
                self.mode = action
                self._pages.clear()
                self._controls()
                self._load()
        elif action == "pin":
            if self.path in self._pinned:
                self._pinned.remove(self.path)
            elif len(self._pinned) < 4 and self.path is not None:
                self._pinned.append(self.path)
            else:
                self.app.notify(
                    "Four files are pinned. Unpin one to keep another.", severity="warning"
                )
            self._controls()
        elif action in ("find", "line"):
            self.show_search(action)
        elif action == "copy":
            self.copy_section()
        elif action == "copy-path" and self.path is not None:
            self.app.copy_to_clipboard(self.relative(self.path))
            self.app.notify("Copied file path")
        elif action == "next":
            self.next_page()
        elif action == "previous":
            self.previous_page()
