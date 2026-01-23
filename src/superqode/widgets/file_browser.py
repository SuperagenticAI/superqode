"""File browser modal widget with fuzzy search and preview."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from superqode.utils.fuzzy import FuzzySearch, PathFuzzySearch


@dataclass
class FileItem:
    """A file or directory item."""

    path: Path
    name: str
    is_dir: bool
    size: int = 0
    extension: str = ""
    relative_path: str = ""


class FileListItem(Static):
    """A single file item in the browser list."""

    DEFAULT_CSS = """
    FileListItem {
        height: 1;
        padding: 0 1;
        layout: horizontal;
    }

    FileListItem:hover {
        background: $primary-darken-2;
    }

    FileListItem.selected {
        background: $primary;
    }

    FileListItem.directory {
        color: $secondary;
    }

    FileListItem .file-icon {
        width: 3;
    }

    FileListItem .file-name {
        width: 1fr;
    }

    FileListItem.selected .file-name {
        color: $text;
        text-style: bold;
    }

    FileListItem .file-size {
        width: 10;
        color: $text-muted;
        text-align: right;
    }

    FileListItem .file-path {
        width: 30;
        color: $text-muted;
        text-style: dim;
    }
    """

    class Selected(Message):
        """Message when item is selected."""

        def __init__(self, item: FileItem) -> None:
            self.item = item
            super().__init__()

    selected: reactive[bool] = reactive(False)

    def __init__(self, item: FileItem, show_path: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.item = item
        self.show_path = show_path

    def compose(self) -> ComposeResult:
        # Icon
        if self.item.is_dir:
            icon = "📁"
        else:
            # File type icons
            ext_icons = {
                ".py": "🐍",
                ".js": "📜",
                ".ts": "📘",
                ".json": "📋",
                ".yaml": "⚙️",
                ".yml": "⚙️",
                ".md": "📝",
                ".txt": "📄",
                ".html": "🌐",
                ".css": "🎨",
                ".sh": "🔧",
                ".toml": "⚙️",
            }
            icon = ext_icons.get(self.item.extension, "📄")

        yield Static(icon, classes="file-icon")
        yield Static(self.item.name, classes="file-name")

        if self.show_path and self.item.relative_path:
            # Show parent directory
            parent = str(Path(self.item.relative_path).parent)
            if parent != ".":
                yield Static(parent, classes="file-path")

        # Size for files
        if not self.item.is_dir and self.item.size > 0:
            size_str = self._format_size(self.item.size)
            yield Static(size_str, classes="file-size")

    def _format_size(self, size: int) -> str:
        """Format file size for display."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    def on_mount(self) -> None:
        self.set_class(self.item.is_dir, "directory")

    def watch_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")

    def on_click(self) -> None:
        self.post_message(self.Selected(self.item))


class FilePreview(Static):
    """File content preview panel."""

    DEFAULT_CSS = """
    FilePreview {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        border: round $primary-darken-2;
        padding: 1;
    }

    FilePreview #preview-header {
        height: 1;
        color: $primary;
        text-style: bold;
        border-bottom: solid $primary-darken-2;
        margin-bottom: 1;
    }

    FilePreview #preview-content {
        height: 1fr;
        color: $text;
    }

    FilePreview .preview-line {
        height: 1;
    }

    FilePreview .line-number {
        width: 4;
        color: $text-muted;
        text-align: right;
        padding-right: 1;
    }

    FilePreview .line-content {
        width: 1fr;
    }

    FilePreview .preview-error {
        color: $error;
        text-style: italic;
    }

    FilePreview .preview-binary {
        color: $warning;
        text-style: italic;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.current_file: Path | None = None

    def compose(self) -> ComposeResult:
        yield Static("No file selected", id="preview-header")
        yield VerticalScroll(id="preview-content")

    def show_file(self, path: Path, max_lines: int = 50) -> None:
        """Show preview of a file."""
        self.current_file = path

        header = self.query_one("#preview-header", Static)
        content = self.query_one("#preview-content", VerticalScroll)
        content.remove_children()

        if not path.exists():
            header.update(f"File not found: {path.name}")
            return

        if path.is_dir():
            header.update(f"📁 {path.name}/")
            # Show directory contents
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                for item in items[:20]:
                    icon = "📁" if item.is_dir() else "📄"
                    content.mount(Static(f"{icon} {item.name}"))
                if len(list(path.iterdir())) > 20:
                    content.mount(Static(f"... and more", classes="preview-line"))
            except PermissionError:
                content.mount(Static("Permission denied", classes="preview-error"))
            return

        header.update(f"📄 {path.name}")

        # Check if file is binary
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
                if b"\x00" in chunk:
                    content.mount(
                        Static("Binary file - preview not available", classes="preview-binary")
                    )
                    return
        except Exception as e:
            content.mount(Static(f"Error reading file: {e}", classes="preview-error"))
            return

        # Read and display text content
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            for i, line in enumerate(lines[:max_lines], 1):
                line = line.rstrip("\n\r")
                if len(line) > 80:
                    line = line[:77] + "..."
                # Escape Rich markup
                line = line.replace("[", r"\[")
                with Horizontal(classes="preview-line"):
                    content.mount(Static(f"{i:3}", classes="line-number"))
                    content.mount(Static(line, classes="line-content"))

            if len(lines) > max_lines:
                content.mount(
                    Static(f"... {len(lines) - max_lines} more lines", classes="preview-line")
                )

        except Exception as e:
            content.mount(Static(f"Error: {e}", classes="preview-error"))

    def clear(self) -> None:
        """Clear the preview."""
        self.current_file = None
        header = self.query_one("#preview-header", Static)
        header.update("No file selected")
        content = self.query_one("#preview-content", VerticalScroll)
        content.remove_children()

    class FileBrowser(Widget):
        """
        Interactive file browser modal with fuzzy search.

        Features:
        - Fuzzy file search
        - Directory navigation
        - File preview
        - Keyboard navigation
        - Bookmarks and recent files
        """

        is_visible: reactive[bool] = reactive(False)

        DEFAULT_CSS = """
        FileBrowser {
            layer: overlay;
            align: center middle;
            width: 90%;
            height: 85%;
            max-width: 120;
            max-height: 40;
            background: $surface;
            border: tall $primary;
            display: none;
        }

        FileBrowser.visible {
            display: block;
        }

        FileBrowser #browser-header {
            dock: top;
            height: 3;
            background: $primary-darken-2;
            padding: 1;
        }

        FileBrowser #browser-title {
            text-style: bold;
            color: $secondary;
        }

        FileBrowser #browser-path {
            color: $text-muted;
            text-style: dim;
        }

        FileBrowser #search-container {
            dock: top;
            height: 3;
            padding: 1;
            background: $surface-darken-1;
            layout: horizontal;
        }

        FileBrowser #search-input {
            width: 1fr;
        }

        FileBrowser #browser-main {
            height: 1fr;
        layout: horizontal;
    }

    FileBrowser #file-list-container {
        width: 1fr;
        height: 100%;
        border-right: solid $primary-darken-2;
    }

    FileBrowser #file-list {
        height: 100%;
    }

    FileBrowser #preview-container {
        width: 45%;
        height: 100%;
        padding: 1;
    }

    FileBrowser #browser-footer {
        dock: bottom;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
    }

    FileBrowser .empty-message {
        padding: 2;
        color: $text-muted;
        text-style: italic;
        text-align: center;
    }

    FileBrowser #quick-actions {
        dock: top;
        height: 2;
        padding: 0 1;
        layout: horizontal;
        background: $surface-darken-1;
        border-bottom: solid $primary-darken-2;
    }

    FileBrowser #quick-actions Button {
        margin-right: 1;
        min-width: 8;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "select", "Select"),
        Binding("up", "move_up", "Up"),
        Binding("down", "move_down", "Down"),
        Binding("ctrl+u", "go_up", "Parent Dir"),
        Binding("ctrl+h", "go_home", "Home"),
        Binding("ctrl+b", "toggle_bookmarks", "Bookmarks"),
        Binding("ctrl+r", "toggle_recent", "Recent"),
    ]

    class FileSelected(Message):
        """Message when a file is selected."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    class Closed(Message):
        """Message when browser is closed."""

        pass

    # State
    visible: reactive[bool] = reactive(False)
    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        root_path: Path | None = None,
        on_select: Callable[[Path], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.root_path = root_path or Path.cwd()
        self.current_path = self.root_path
        self._on_select = on_select
        self._items: list[FileItem] = []
        self._filtered_items: list[FileItem] = []
        self._search_query = ""
        self._show_bookmarks = False
        self._show_recent = False
        self.fuzzy = PathFuzzySearch()
        self._render_counter = 0  # Unique ID counter to prevent duplicates

    def compose(self) -> ComposeResult:
        # Header
        with Vertical(id="browser-header"):
            yield Static("📁 File Browser", id="browser-title")
            yield Static(str(self.current_path), id="browser-path")

        # Quick actions
        with Horizontal(id="quick-actions"):
            yield Button("⬆ Parent", id="btn-parent")
            yield Button("🏠 Home", id="btn-home")
            yield Button("🔖 Bookmarks", id="btn-bookmarks")
            yield Button("📋 Recent", id="btn-recent")

        # Search
        with Horizontal(id="search-container"):
            yield Input(placeholder="Search files... (fuzzy matching)", id="search-input")

        # Main content
        with Horizontal(id="browser-main"):
            with Container(id="file-list-container"):
                yield VerticalScroll(id="file-list")
            with Container(id="preview-container"):
                yield FilePreview(id="file-preview")

        # Footer
        yield Static(
            "↑↓ Navigate │ Enter Select │ Ctrl+U Parent │ Esc Close",
            id="browser-footer",
        )

    def show(self, path: Path | None = None) -> None:
        """Show the file browser."""
        if path:
            self.current_path = path
        self.is_visible = True
        self.add_class("visible")
        self._load_directory()

        # Focus search
        self.query_one("#search-input", Input).focus()

    def hide(self) -> None:
        """Hide file browser."""
        self.is_visible = False
        self.remove_class("visible")
        self.post_message(self.Closed())

    def _load_directory(self) -> None:
        """Load the current directory contents."""
        self._items = []
        self._show_bookmarks = False
        self._show_recent = False

        # Update path display
        path_display = self.query_one("#browser-path", Static)
        path_display.update(str(self.current_path))

        try:
            # Get directory contents
            entries = sorted(
                self.current_path.iterdir(),
                key=lambda x: (not x.is_dir(), x.name.lower()),
            )

            # Filter out hidden and ignored files
            from superqode.file_explorer import PathFilter

            path_filter = PathFilter.from_git_root(self.root_path)

            for entry in entries:
                # Skip hidden files (starting with .)
                if entry.name.startswith("."):
                    continue

                # Skip ignored files
                try:
                    rel_path = entry.relative_to(self.root_path)
                    if path_filter.match(rel_path):
                        continue
                except ValueError:
                    pass

                try:
                    size = entry.stat().st_size if entry.is_file() else 0
                except OSError:
                    size = 0

                self._items.append(
                    FileItem(
                        path=entry,
                        name=entry.name,
                        is_dir=entry.is_dir(),
                        size=size,
                        extension=entry.suffix.lower() if entry.is_file() else "",
                        relative_path=str(entry.relative_to(self.root_path)),
                    )
                )

        except PermissionError:
            pass

        self._apply_filter()

    def _load_bookmarks(self) -> None:
        """Load bookmarked files."""
        from superqode.file_explorer import Bookmarks

        self._items = []
        self._show_bookmarks = True
        self._show_recent = False

        path_display = self.query_one("#browser-path", Static)
        path_display.update("🔖 Bookmarks")

        bookmarks = Bookmarks()
        for name, path in bookmarks.get_bookmarks().items():
            if path.exists():
                try:
                    size = path.stat().st_size if path.is_file() else 0
                except OSError:
                    size = 0

                self._items.append(
                    FileItem(
                        path=path,
                        name=f"{name} → {path.name}",
                        is_dir=path.is_dir(),
                        size=size,
                        extension=path.suffix.lower() if path.is_file() else "",
                        relative_path=str(path),
                    )
                )

        self._apply_filter()

    def _load_recent(self) -> None:
        """Load recent files."""
        from superqode.file_explorer import RecentFiles

        self._items = []
        self._show_bookmarks = False
        self._show_recent = True

        path_display = self.query_one("#browser-path", Static)
        path_display.update("📋 Recent Files")

        recent = RecentFiles()
        for path in recent.get_recent_files(limit=20):
            if path.exists():
                try:
                    size = path.stat().st_size if path.is_file() else 0
                except OSError:
                    size = 0

                self._items.append(
                    FileItem(
                        path=path,
                        name=path.name,
                        is_dir=path.is_dir(),
                        size=size,
                        extension=path.suffix.lower() if path.is_file() else "",
                        relative_path=str(path),
                    )
                )

        self._apply_filter()

    def _apply_filter(self) -> None:
        """Apply search filter to items."""
        if self._search_query:
            # Fuzzy search
            items = [(item.name, item) for item in self._items]
            results = self.fuzzy.search_with_data(self._search_query, items, max_results=50)
            self._filtered_items = [item for _, item in results]
        else:
            self._filtered_items = self._items

        self.selected_index = 0
        self._render_items()

    def _render_items(self) -> None:
        """Render the file list."""
        self._render_counter += 1
        render_id = self._render_counter

        file_list = self.query_one("#file-list", VerticalScroll)
        file_list.remove_children()

        if not self._filtered_items:
            file_list.mount(
                Static(
                    "No files found.\nTry a different search.",
                    classes="empty-message",
                )
            )
            return

        show_path = self._show_bookmarks or self._show_recent or bool(self._search_query)

        for i, item in enumerate(self._filtered_items):
            # Use render counter in ID to ensure uniqueness across renders
            list_item = FileListItem(item, show_path=show_path, id=f"file-{render_id}-{i}")
            list_item.selected = i == self.selected_index
            file_list.mount(list_item)

        # Update preview
        self._update_preview()

    def _update_selection(self) -> None:
        """Update visual selection state."""
        for i, item in enumerate(self.query("#file-list FileListItem")):
            if isinstance(item, FileListItem):
                item.selected = i == self.selected_index

        self._update_preview()

    def _update_preview(self) -> None:
        """Update the file preview."""
        preview = self.query_one("#file-preview", FilePreview)

        if self._filtered_items and 0 <= self.selected_index < len(self._filtered_items):
            item = self._filtered_items[self.selected_index]
            preview.show_file(item.path)
        else:
            preview.clear()

    # === Actions ===

    def action_close(self) -> None:
        """Close the browser."""
        self.hide()

    def action_select(self) -> None:
        """Select the current item."""
        if not self._filtered_items:
            return

        if 0 <= self.selected_index < len(self._filtered_items):
            item = self._filtered_items[self.selected_index]

            if item.is_dir:
                # Navigate into directory
                self.current_path = item.path
                self._search_query = ""
                self.query_one("#search-input", Input).value = ""
                self._load_directory()
            else:
                # Select file
                self.post_message(self.FileSelected(item.path))
                if self._on_select:
                    self._on_select(item.path)
                self.hide()

    def action_move_up(self) -> None:
        """Move selection up."""
        if self._filtered_items and self.selected_index > 0:
            self.selected_index -= 1
            self._update_selection()

    def action_move_down(self) -> None:
        """Move selection down."""
        if self._filtered_items and self.selected_index < len(self._filtered_items) - 1:
            self.selected_index += 1
            self._update_selection()

    def action_go_up(self) -> None:
        """Go to parent directory."""
        if self.current_path != self.root_path:
            self.current_path = self.current_path.parent
            self._search_query = ""
            self.query_one("#search-input", Input).value = ""
            self._load_directory()

    def action_go_home(self) -> None:
        """Go to root directory."""
        self.current_path = self.root_path
        self._search_query = ""
        self.query_one("#search-input", Input).value = ""
        self._load_directory()

    def action_toggle_bookmarks(self) -> None:
        """Toggle bookmarks view."""
        if self._show_bookmarks:
            self._load_directory()
        else:
            self._load_bookmarks()

    def action_toggle_recent(self) -> None:
        """Toggle recent files view."""
        if self._show_recent:
            self._load_directory()
        else:
            self._load_recent()

    # === Event handlers ===

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        self._search_query = event.value

        if self._show_bookmarks or self._show_recent:
            # Just filter current list
            self._apply_filter()
        elif event.value:
            # Do project-wide fuzzy search
            self._search_project(event.value)
        else:
            # Show current directory
            self._load_directory()

    @work(exclusive=True)
    async def _search_project(self, query: str) -> None:
        """Search files across the project."""
        import asyncio

        def do_search():
            from superqode.file_explorer import fuzzy_find_files

            results = fuzzy_find_files(query, max_results=50)
            items = []
            for path, rel_path, score in results:
                try:
                    size = path.stat().st_size if path.is_file() else 0
                except OSError:
                    size = 0

                items.append(
                    FileItem(
                        path=path,
                        name=path.name,
                        is_dir=path.is_dir(),
                        size=size,
                        extension=path.suffix.lower() if path.is_file() else "",
                        relative_path=rel_path,
                    )
                )
            return items

        self._items = await asyncio.to_thread(do_search)
        self._filtered_items = self._items
        self.selected_index = 0
        self._render_items()

    @on(Button.Pressed, "#btn-parent")
    def on_parent_pressed(self, event: Button.Pressed) -> None:
        self.action_go_up()

    @on(Button.Pressed, "#btn-home")
    def on_home_pressed(self, event: Button.Pressed) -> None:
        self.action_go_home()

    @on(Button.Pressed, "#btn-bookmarks")
    def on_bookmarks_pressed(self, event: Button.Pressed) -> None:
        self.action_toggle_bookmarks()

    @on(Button.Pressed, "#btn-recent")
    def on_recent_pressed(self, event: Button.Pressed) -> None:
        self.action_toggle_recent()

    @on(FileListItem.Selected)
    def on_item_selected(self, event: FileListItem.Selected) -> None:
        """Handle item click."""
        # Find index
        for i, item in enumerate(self._filtered_items):
            if item.path == event.item.path:
                self.selected_index = i
                self._update_selection()
                break

        # Double-click behavior (select on click)
        self.action_select()
