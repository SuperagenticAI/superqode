"""
SuperQode File Reference Widget - @ file mentions with fuzzy search.

Enables @filename syntax for including files in context.

Features:
- Fuzzy file search when typing @
- Autocomplete popup with file suggestions
- Highlights matched characters
- Automatically includes file content in message

Usage:
    > Fix the bug in @utils/parser.py
    > Review @src/main.py and @tests/test_main.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple, TYPE_CHECKING

from rich.text import Text

from textual.widgets import Static, Input, OptionList
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.binding import Binding

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# DESIGN CONSTANTS
# ============================================================================

try:
    from superqode.design_system import COLORS as SQ_COLORS
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        success = "#10b981"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        bg_surface = "#0a0a0a"
        border_default = "#27272a"


# ============================================================================
# FILE REFERENCE PARSER
# ============================================================================

# Pattern to match @filename references
FILE_REFERENCE_PATTERN = re.compile(r"@([\w./\-_]+)")


def parse_file_references(text: str) -> List[str]:
    """
    Extract all @filename references from text.

    Args:
        text: Input text possibly containing @references

    Returns:
        List of file paths referenced
    """
    matches = FILE_REFERENCE_PATTERN.findall(text)
    return matches


def expand_file_references(text: str, root_path: Path) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Expand @filename references to include file content.

    Args:
        text: Input text with @references
        root_path: Root directory for resolving files

    Returns:
        Tuple of (clean_text, [(path, content), ...])
    """
    references = parse_file_references(text)
    file_contents = []

    for ref in references:
        # Try to resolve the file path
        file_path = root_path / ref

        # Also try without leading path components
        if not file_path.exists():
            # Search for the file
            for candidate in root_path.rglob(f"*{ref}"):
                if candidate.is_file():
                    file_path = candidate
                    break

        if file_path.exists() and file_path.is_file():
            try:
                content = file_path.read_text(errors="replace")
                # Limit content size
                if len(content) > 50000:
                    content = content[:50000] + "\n... (truncated)"
                file_contents.append((str(file_path.relative_to(root_path)), content))
            except Exception:
                pass

    # Remove @ prefixes from text for clean display
    clean_text = FILE_REFERENCE_PATTERN.sub(r"\1", text)

    return clean_text, file_contents


# ============================================================================
# FILE SCANNER
# ============================================================================


class FileScanner:
    """
    Scans and caches files in a directory for quick fuzzy search.
    """

    # File extensions to include
    CODE_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".swift",
        ".vue",
        ".svelte",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".md",
        ".txt",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".sql",
        ".graphql",
    }

    # Directories to exclude
    EXCLUDE_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "eggs",
        "*.egg-info",
    }

    def __init__(self, root_path: Path, max_files: int = 5000):
        self.root_path = root_path
        self.max_files = max_files
        self._files: List[str] = []
        self._scanned = False

    def scan(self, force: bool = False) -> List[str]:
        """Scan directory for files."""
        if self._scanned and not force:
            return self._files

        self._files = []
        count = 0

        try:
            for item in self.root_path.rglob("*"):
                if count >= self.max_files:
                    break

                # Skip excluded directories
                if any(excl in item.parts for excl in self.EXCLUDE_DIRS):
                    continue

                if item.is_file():
                    # Check extension
                    if item.suffix.lower() in self.CODE_EXTENSIONS or item.suffix == "":
                        rel_path = str(item.relative_to(self.root_path))
                        self._files.append(rel_path)
                        count += 1
        except Exception:
            pass

        self._scanned = True
        return self._files

    def search(self, query: str, max_results: int = 10) -> List[Tuple[str, float, List[int]]]:
        """
        Fuzzy search files matching query.

        Returns:
            List of (path, score, match_positions)
        """
        from superqode.utils.fuzzy import path_fuzzy_search

        files = self.scan()
        if not query:
            return [(f, 0.0, []) for f in files[:max_results]]

        matches = path_fuzzy_search.search(query, files, max_results=max_results)
        return [(m.text, m.score, m.positions) for m in matches]


# ============================================================================
# FILE AUTOCOMPLETE WIDGET
# ============================================================================


class FileAutocomplete(Container):
    """
    Dropdown autocomplete widget for file references.

    Shows fuzzy-matched files when user types @.
    """

    DEFAULT_CSS = """
    FileAutocomplete {
        layer: overlay;
        width: auto;
        max-width: 60;
        height: auto;
        max-height: 12;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 0;
        display: none;
    }

    FileAutocomplete.visible {
        display: block;
    }

    FileAutocomplete OptionList {
        height: auto;
        max-height: 10;
        background: #0a0a0a;
        border: none;
        padding: 0;
    }

    FileAutocomplete OptionList:focus {
        border: none;
    }

    FileAutocomplete OptionList > .option-list--option {
        padding: 0 1;
    }

    FileAutocomplete OptionList > .option-list--option-highlighted {
        background: #7c3aed40;
    }

    FileAutocomplete .header {
        height: 1;
        background: #1a1a1a;
        padding: 0 1;
        color: #71717a;
    }
    """

    class FileSelected(Message):
        """Posted when a file is selected."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class Dismissed(Message):
        """Posted when autocomplete is dismissed."""

        pass

    visible: reactive[bool] = reactive(False)

    def __init__(self, root_path: Path, **kwargs):
        super().__init__(**kwargs)
        self._scanner = FileScanner(root_path)
        self._query = ""
        self._results: List[Tuple[str, float, List[int]]] = []

    def compose(self):
        """Compose the autocomplete widget."""
        yield Static("◇ Files", classes="header")
        yield OptionList(id="file-options")

    def on_mount(self) -> None:
        """Start file scan in background."""
        self._scanner.scan()

    def watch_visible(self, visible: bool) -> None:
        """Toggle visibility."""
        if visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def show(self, query: str = "") -> None:
        """Show autocomplete with query."""
        self._query = query
        self._update_results()
        self.visible = True
        try:
            self.query_one("#file-options", OptionList).focus()
        except Exception:
            pass

    def hide(self) -> None:
        """Hide autocomplete."""
        self.visible = False
        self.post_message(self.Dismissed())

    def _update_results(self) -> None:
        """Update search results."""
        from superqode.utils.fuzzy import path_fuzzy_search

        self._results = self._scanner.search(self._query, max_results=10)

        # Update option list
        try:
            options = self.query_one("#file-options", OptionList)
            options.clear_options()

            for path, score, positions in self._results:
                # Highlight matched characters
                display = path_fuzzy_search.highlight_match(
                    path, positions, highlight_start="[bold cyan]", highlight_end="[/bold cyan]"
                )
                options.add_option(Text.from_markup(f"↳ {display}"))
        except Exception:
            pass

    def update_query(self, query: str) -> None:
        """Update search query."""
        self._query = query
        self._update_results()

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle file selection."""
        event.stop()
        if 0 <= event.option_index < len(self._results):
            path = self._results[event.option_index][0]
            self.post_message(self.FileSelected(path))
            self.hide()

    def select_highlighted(self) -> None:
        """Select the currently highlighted option."""
        try:
            options = self.query_one("#file-options", OptionList)
            if options.highlighted is not None and 0 <= options.highlighted < len(self._results):
                path = self._results[options.highlighted][0]
                self.post_message(self.FileSelected(path))
                self.hide()
        except Exception:
            pass

    def move_up(self) -> None:
        """Move selection up."""
        try:
            options = self.query_one("#file-options", OptionList)
            options.action_cursor_up()
        except Exception:
            pass

    def move_down(self) -> None:
        """Move selection down."""
        try:
            options = self.query_one("#file-options", OptionList)
            options.action_cursor_down()
        except Exception:
            pass


# ============================================================================
# ENHANCED INPUT WITH FILE REFERENCES
# ============================================================================


class FileReferenceInput(Input):
    """
    Enhanced input that supports @file references.

    Shows autocomplete when typing @ and includes file content
    in the final message.
    """

    BINDINGS = [
        Binding("tab", "complete", "Complete", show=False),
        Binding("escape", "cancel_complete", "Cancel", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
    ]

    class MessageWithFiles(Message):
        """Posted when message is submitted with file references."""

        def __init__(self, text: str, files: List[Tuple[str, str]]) -> None:
            self.text = text  # Clean text without @ prefixes
            self.files = files  # List of (path, content) tuples
            super().__init__()

    def __init__(self, root_path: Path = None, **kwargs):
        super().__init__(**kwargs)
        self._root_path = root_path or Path.cwd()
        self._autocomplete: Optional[FileAutocomplete] = None
        self._at_position: int = -1  # Position of @ that triggered autocomplete

    def on_mount(self) -> None:
        """Mount autocomplete widget."""
        # Note: Autocomplete is mounted by parent app
        pass

    def set_autocomplete(self, autocomplete: FileAutocomplete) -> None:
        """Set the autocomplete widget to use."""
        self._autocomplete = autocomplete

    def _check_for_trigger(self) -> None:
        """Check if we should show autocomplete."""
        value = self.value
        cursor = self.cursor_position

        # Look for @ before cursor
        before_cursor = value[:cursor]
        at_pos = before_cursor.rfind("@")

        if at_pos >= 0:
            # Check if @ is at start or after whitespace
            if at_pos == 0 or before_cursor[at_pos - 1] in " \t":
                # Get query after @
                query = before_cursor[at_pos + 1 :]

                # Don't trigger if query contains space (completed reference)
                if " " not in query:
                    self._at_position = at_pos
                    if self._autocomplete:
                        self._autocomplete.show(query)
                    return

        # No trigger, hide autocomplete
        self._at_position = -1
        if self._autocomplete and self._autocomplete.visible:
            self._autocomplete.hide()

    def watch_value(self, value: str) -> None:
        """Watch for @ triggers."""
        self._check_for_trigger()

    def on_file_autocomplete_file_selected(self, event: FileAutocomplete.FileSelected) -> None:
        """Handle file selection from autocomplete."""
        if self._at_position >= 0:
            # Replace @query with @full_path
            before = self.value[: self._at_position]
            after_at = self.value[self._at_position + 1 :]

            # Find end of current query (next space or end)
            space_pos = after_at.find(" ")
            if space_pos >= 0:
                after = after_at[space_pos:]
            else:
                after = ""

            # Insert selected file
            self.value = f"{before}@{event.path}{after}"
            self.cursor_position = len(before) + 1 + len(event.path)

        self._at_position = -1

    def action_complete(self) -> None:
        """Tab to select highlighted autocomplete option."""
        if self._autocomplete and self._autocomplete.visible:
            self._autocomplete.select_highlighted()

    def action_cancel_complete(self) -> None:
        """Escape to cancel autocomplete."""
        if self._autocomplete and self._autocomplete.visible:
            self._autocomplete.hide()
            self._at_position = -1

    def action_move_up(self) -> None:
        """Move autocomplete selection up."""
        if self._autocomplete and self._autocomplete.visible:
            self._autocomplete.move_up()

    def action_move_down(self) -> None:
        """Move autocomplete selection down."""
        if self._autocomplete and self._autocomplete.visible:
            self._autocomplete.move_down()

    def get_message_with_files(self) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Get the message text and any referenced files.

        Returns:
            (clean_text, [(path, content), ...])
        """
        return expand_file_references(self.value, self._root_path)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def format_file_context(files: List[Tuple[str, str]]) -> str:
    """
    Format file contents for inclusion in AI context.

    Args:
        files: List of (path, content) tuples

    Returns:
        Formatted string with file contents
    """
    if not files:
        return ""

    parts = []
    for path, content in files:
        parts.append(f'<file path="{path}">\n{content}\n</file>')

    return "\n\n".join(parts)


def count_file_tokens(files: List[Tuple[str, str]]) -> int:
    """
    Estimate token count for files.

    Rough estimate: ~4 chars per token
    """
    total_chars = sum(len(content) for _, content in files)
    return total_chars // 4


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "parse_file_references",
    "expand_file_references",
    "FileScanner",
    "FileAutocomplete",
    "FileReferenceInput",
    "format_file_context",
    "count_file_tokens",
]
