"""
SuperQode Enhanced Sidebar - Colorful File Browser with Preview

Features:
- File type icons (Python, JS, etc.)
- Gradient colored folders
- File preview on selection
- Syntax highlighted content
- File info display
- Collapsible panels (Plan, Files, Preview)
- Git status indicator
- Quick file search (Ctrl+F)
"""

from __future__ import annotations

import subprocess
import asyncio
from pathlib import Path
from typing import Optional, Callable, List
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static, DirectoryTree, Tree, Label, Input, Collapsible
from textual.widgets.tree import TreeNode
from textual.widgets._directory_tree import DirEntry
from textual.reactive import reactive
from textual.message import Message
from textual import on, work
from textual.binding import Binding

from rich.text import Text
from rich.syntax import Syntax
from rich.panel import Panel
from rich.box import ROUNDED


# ============================================================================
# FILE TYPE ICONS - Nerd Font style icons with colors
# ============================================================================

FILE_ICONS = {
    # Python
    ".py": ("🐍", "#3776ab"),
    ".pyw": ("🐍", "#3776ab"),
    ".pyi": ("🐍", "#3776ab"),
    ".pyx": ("🐍", "#3776ab"),
    ".ipynb": ("📓", "#f37626"),
    # JavaScript/TypeScript
    ".js": ("📜", "#f7df1e"),
    ".jsx": ("⚛️", "#61dafb"),
    ".ts": ("💠", "#3178c6"),
    ".tsx": ("⚛️", "#61dafb"),
    ".mjs": ("📜", "#f7df1e"),
    ".cjs": ("📜", "#f7df1e"),
    ".vue": ("💚", "#42b883"),
    ".svelte": ("🔥", "#ff3e00"),
    # Web
    ".html": ("🌐", "#e34f26"),
    ".htm": ("🌐", "#e34f26"),
    ".css": ("🎨", "#1572b6"),
    ".scss": ("🎨", "#cc6699"),
    ".sass": ("🎨", "#cc6699"),
    ".less": ("🎨", "#1d365d"),
    # Data formats
    ".json": ("📋", "#cbcb41"),
    ".yaml": ("⚙️", "#cb171e"),
    ".yml": ("⚙️", "#cb171e"),
    ".toml": ("⚙️", "#9c4121"),
    ".xml": ("📰", "#e37933"),
    ".csv": ("📊", "#217346"),
    # Shell
    ".sh": ("💻", "#4eaa25"),
    ".bash": ("💻", "#4eaa25"),
    ".zsh": ("💻", "#4eaa25"),
    ".fish": ("🐟", "#4eaa25"),
    ".ps1": ("💻", "#012456"),
    ".bat": ("💻", "#c1f12e"),
    ".cmd": ("💻", "#c1f12e"),
    # Systems languages
    ".c": ("🔷", "#555555"),
    ".h": ("🔷", "#555555"),
    ".cpp": ("🔷", "#f34b7d"),
    ".hpp": ("🔷", "#f34b7d"),
    ".cc": ("🔷", "#f34b7d"),
    ".cxx": ("🔷", "#f34b7d"),
    ".rs": ("🦀", "#dea584"),
    ".go": ("🐹", "#00add8"),
    ".java": ("☕", "#b07219"),
    ".kt": ("🟣", "#a97bff"),
    ".kts": ("🟣", "#a97bff"),
    ".scala": ("🔴", "#c22d40"),
    ".swift": ("🍎", "#f05138"),
    # Other languages
    ".rb": ("💎", "#cc342d"),
    ".php": ("🐘", "#777bb4"),
    ".pl": ("🐪", "#0298c3"),
    ".lua": ("🌙", "#000080"),
    ".r": ("📊", "#198ce7"),
    ".R": ("📊", "#198ce7"),
    ".jl": ("🔮", "#9558b2"),
    ".ex": ("💧", "#6e4a7e"),
    ".exs": ("💧", "#6e4a7e"),
    ".erl": ("📡", "#b83998"),
    ".hs": ("λ", "#5e5086"),
    ".ml": ("🐫", "#dc6b1f"),
    ".fs": ("🔷", "#b845fc"),
    ".clj": ("🟢", "#63b132"),
    ".lisp": ("🟢", "#3fb68b"),
    # Config files
    ".ini": ("⚙️", "#6d8086"),
    ".cfg": ("⚙️", "#6d8086"),
    ".conf": ("⚙️", "#6d8086"),
    ".env": ("🔐", "#ecd53f"),
    ".gitignore": ("🚫", "#f05032"),
    ".dockerignore": ("🚫", "#2496ed"),
    ".editorconfig": ("⚙️", "#6d8086"),
    # Documentation
    ".md": ("📝", "#083fa1"),
    ".markdown": ("📝", "#083fa1"),
    ".rst": ("📝", "#141414"),
    ".txt": ("📄", "#6d8086"),
    ".log": ("📋", "#6d8086"),
    ".pdf": ("📕", "#ff0000"),
    # Database
    ".sql": ("🗄️", "#e38c00"),
    ".sqlite": ("🗄️", "#003b57"),
    ".db": ("🗄️", "#003b57"),
    # Build/Config
    ".dockerfile": ("🐳", "#2496ed"),
    ".docker": ("🐳", "#2496ed"),
    # Images
    ".png": ("🖼️", "#a4c639"),
    ".jpg": ("🖼️", "#a4c639"),
    ".jpeg": ("🖼️", "#a4c639"),
    ".gif": ("🖼️", "#a4c639"),
    ".svg": ("🎨", "#ffb13b"),
    ".ico": ("🖼️", "#a4c639"),
    ".webp": ("🖼️", "#a4c639"),
    # Archives
    ".zip": ("📦", "#6d8086"),
    ".tar": ("📦", "#6d8086"),
    ".gz": ("📦", "#6d8086"),
    ".rar": ("📦", "#6d8086"),
    ".7z": ("📦", "#6d8086"),
    # Other
    ".diff": ("📊", "#41b883"),
    ".patch": ("📊", "#41b883"),
    ".graphql": ("💜", "#e10098"),
    ".proto": ("📡", "#6d8086"),
    ".tf": ("🟣", "#844fba"),
    ".hcl": ("🟣", "#844fba"),
    ".lock": ("🔒", "#6d8086"),
}

# Special filenames
SPECIAL_FILES = {
    "Makefile": ("🔧", "#6d8086"),
    "Dockerfile": ("🐳", "#2496ed"),
    "Vagrantfile": ("📦", "#1868f2"),
    "Gemfile": ("💎", "#cc342d"),
    "Rakefile": ("💎", "#cc342d"),
    "CMakeLists.txt": ("🔧", "#064f8c"),
    "package.json": ("📦", "#cb3837"),
    "package-lock.json": ("🔒", "#cb3837"),
    "yarn.lock": ("🔒", "#2c8ebb"),
    "pnpm-lock.yaml": ("🔒", "#f9ad00"),
    "requirements.txt": ("📋", "#3776ab"),
    "pyproject.toml": ("🐍", "#3776ab"),
    "setup.py": ("🐍", "#3776ab"),
    "setup.cfg": ("🐍", "#3776ab"),
    "Cargo.toml": ("🦀", "#dea584"),
    "Cargo.lock": ("🔒", "#dea584"),
    "go.mod": ("🐹", "#00add8"),
    "go.sum": ("🔒", "#00add8"),
    ".gitignore": ("🚫", "#f05032"),
    ".gitattributes": ("📋", "#f05032"),
    ".prettierrc": ("🎨", "#f7b93e"),
    ".eslintrc": ("🔍", "#4b32c3"),
    ".eslintrc.js": ("🔍", "#4b32c3"),
    ".eslintrc.json": ("🔍", "#4b32c3"),
    "tsconfig.json": ("💠", "#3178c6"),
    "jsconfig.json": ("📜", "#f7df1e"),
    "README.md": ("📖", "#083fa1"),
    "LICENSE": ("📜", "#6d8086"),
    "CHANGELOG.md": ("📋", "#083fa1"),
    "CONTRIBUTING.md": ("🤝", "#083fa1"),
}

# Folder icons with gradient colors
FOLDER_ICONS = {
    "src": ("📁", "#a855f7"),
    "source": ("📁", "#a855f7"),
    "lib": ("📚", "#ec4899"),
    "libs": ("📚", "#ec4899"),
    "test": ("🧪", "#22c55e"),
    "tests": ("🧪", "#22c55e"),
    "spec": ("🧪", "#22c55e"),
    "specs": ("🧪", "#22c55e"),
    "__tests__": ("🧪", "#22c55e"),
    "docs": ("📖", "#06b6d4"),
    "doc": ("📖", "#06b6d4"),
    "documentation": ("📖", "#06b6d4"),
    "config": ("⚙️", "#f97316"),
    "configs": ("⚙️", "#f97316"),
    "settings": ("⚙️", "#f97316"),
    "public": ("🌐", "#3b82f6"),
    "static": ("🌐", "#3b82f6"),
    "assets": ("🎨", "#eab308"),
    "images": ("🖼️", "#a4c639"),
    "img": ("🖼️", "#a4c639"),
    "icons": ("🎯", "#f43f5e"),
    "styles": ("🎨", "#ec4899"),
    "css": ("🎨", "#1572b6"),
    "scripts": ("💻", "#4eaa25"),
    "bin": ("⚡", "#f59e0b"),
    "build": ("🔨", "#6d8086"),
    "dist": ("📦", "#6d8086"),
    "out": ("📦", "#6d8086"),
    "output": ("📦", "#6d8086"),
    "node_modules": ("📦", "#cb3837"),
    "vendor": ("📦", "#6d8086"),
    "packages": ("📦", "#6d8086"),
    ".git": ("📂", "#f05032"),
    ".github": ("🐙", "#181717"),
    ".vscode": ("💙", "#007acc"),
    ".idea": ("🧠", "#000000"),
    "components": ("🧩", "#61dafb"),
    "pages": ("📄", "#000000"),
    "views": ("👁️", "#42b883"),
    "models": ("🗃️", "#ff6b6b"),
    "controllers": ("🎮", "#4ecdc4"),
    "services": ("⚡", "#f7df1e"),
    "utils": ("🔧", "#6d8086"),
    "helpers": ("🤝", "#6d8086"),
    "hooks": ("🪝", "#61dafb"),
    "api": ("🔌", "#009688"),
    "routes": ("🛤️", "#ff5722"),
    "middleware": ("🔗", "#9c27b0"),
    "migrations": ("📊", "#e38c00"),
    "seeds": ("🌱", "#4caf50"),
    "fixtures": ("📌", "#795548"),
    "mocks": ("🎭", "#9e9e9e"),
    "__pycache__": ("📦", "#3776ab"),
    ".pytest_cache": ("🧪", "#22c55e"),
    "venv": ("🐍", "#3776ab"),
    ".venv": ("🐍", "#3776ab"),
    "env": ("🔐", "#ecd53f"),
    ".env": ("🔐", "#ecd53f"),
}

# Default icons
DEFAULT_FILE_ICON = ("📄", "#6d8086")
DEFAULT_FOLDER_ICON = ("📁", "#a855f7")
DEFAULT_FOLDER_OPEN_ICON = ("📂", "#ec4899")


def get_file_icon(path: Path) -> tuple[str, str]:
    """Get icon and color for a file."""
    name = path.name
    ext = path.suffix.lower()

    # Check special filenames first
    if name in SPECIAL_FILES:
        return SPECIAL_FILES[name]

    # Check extension
    if ext in FILE_ICONS:
        return FILE_ICONS[ext]

    return DEFAULT_FILE_ICON


def get_folder_icon(name: str, is_open: bool = False) -> tuple[str, str]:
    """Get icon and color for a folder."""
    name_lower = name.lower()

    if name_lower in FOLDER_ICONS:
        icon, color = FOLDER_ICONS[name_lower]
        # Use open folder variant if expanded
        if is_open and icon == "📁":
            icon = "📂"
        return icon, color

    return DEFAULT_FOLDER_OPEN_ICON if is_open else DEFAULT_FOLDER_ICON


# ============================================================================
# LANGUAGE DETECTION FOR SYNTAX HIGHLIGHTING
# ============================================================================

LANGUAGE_MAP = {
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".svg": "xml",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".md": "markdown",
    ".rst": "rst",
    ".sql": "sql",
    ".graphql": "graphql",
    ".dockerfile": "dockerfile",
    ".tf": "terraform",
    ".hcl": "hcl",
    ".vue": "vue",
    ".svelte": "svelte",
}


def detect_language(path: Path) -> str:
    """Detect programming language from file path."""
    name = path.name.lower()
    ext = path.suffix.lower()

    # Special filenames
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    if name in ("gemfile", "rakefile", "vagrantfile"):
        return "ruby"

    return LANGUAGE_MAP.get(ext, "text")


# ============================================================================
# CUSTOM DIRECTORY TREE WITH ICONS
# ============================================================================


class ColorfulDirectoryTree(DirectoryTree):
    """Enhanced DirectoryTree with colorful file type icons."""

    BINDINGS = [
        Binding("o", "open_file", "Open in view", show=True),
    ]

    class FileOpenRequested(Message):
        """Message sent when a file should be opened in main view."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def render_label(self, node: TreeNode, base_style, style) -> Text:
        """Render a label with file type icon."""
        path = node.data.path if node.data else None

        if path is None:
            return Text(str(node.label))

        label = Text()

        if path.is_dir():
            # Folder with icon
            is_open = node.is_expanded
            icon, color = get_folder_icon(path.name, is_open)
            label.append(f"{icon} ", style=f"bold {color}")
            label.append(path.name, style=f"{color}")
        else:
            # File with icon
            icon, color = get_file_icon(path)
            label.append(f"{icon} ", style=color)
            label.append(path.name, style="white")

        return label

    def filter_paths(self, paths):
        """Filter out hidden and ignored paths."""
        ignore_patterns = {
            "__pycache__",
            ".git",
            ".svn",
            ".hg",
            "node_modules",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".tox",
            ".nox",
            ".coverage",
            "dist",
            "build",
            "*.egg-info",
            ".eggs",
            "venv",
            ".venv",
            "env",
            ".env",
            ".DS_Store",
            "Thumbs.db",
        }

        for path in paths:
            name = path.name
            # Skip hidden files (except some config files)
            if name.startswith(".") and name not in {".github", ".gitignore", ".env", ".vscode"}:
                continue
            # Skip ignored patterns
            if name in ignore_patterns:
                continue
            if any(name.endswith(p.replace("*", "")) for p in ignore_patterns if "*" in p):
                continue
            yield path

    def action_open_file(self) -> None:
        """Open the selected file in main view."""
        node = self.cursor_node
        if node and node.data and hasattr(node.data, "path"):
            path = node.data.path
            if path.is_file():
                self.post_message(self.FileOpenRequested(path))


# ============================================================================
# FILE PREVIEW PANEL - Scrollable with user-friendly hints
# ============================================================================


class FilePreviewScroll(ScrollableContainer):
    """Scrollable container for file preview."""

    DEFAULT_CSS = """
    FilePreviewScroll {
        height: 100%;
        background: #000000;
        scrollbar-size: 1 1;
    }
    """


class FilePreview(Container):
    """Panel showing file content preview with syntax highlighting."""

    DEFAULT_CSS = """
    FilePreview {
        height: 100%;
        background: #000000;
        padding: 0;
        layout: vertical;
    }

    FilePreview #preview-header {
        height: 3;
        background: #000000;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    FilePreview #preview-hints {
        height: 2;
        background: #000000;
        border-top: solid #1a1a1a;
        padding: 0 1;
        text-align: center;
    }

    FilePreview #preview-content {
        height: 1fr;
        background: #000000;
    }

    FilePreview .preview-syntax {
        height: auto;
        padding: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close_preview", "Close", show=False),
        Binding("q", "close_preview", "Close", show=False),
        Binding("e", "edit_file", "Edit", show=False),
    ]

    current_file: reactive[Optional[Path]] = reactive(None)

    class PreviewClosed(Message):
        """Message sent when preview is closed."""

        pass

    class EditRequested(Message):
        """Message sent when user wants to edit the file."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content_cache: dict[Path, str] = {}

    def compose(self) -> ComposeResult:
        """Compose the preview layout."""
        # Header
        yield Static(self._render_header(), id="preview-header")

        # Scrollable content area
        with FilePreviewScroll(id="preview-content"):
            yield Static(self._render_content(), id="preview-syntax", classes="preview-syntax")

        # User-friendly hints at bottom
        yield Static(self._render_hints(), id="preview-hints")

    def watch_current_file(self, path: Optional[Path]) -> None:
        """Update display when file changes."""
        try:
            self.query_one("#preview-header", Static).update(self._render_header())
            self.query_one("#preview-syntax", Static).update(self._render_content())
            self.query_one("#preview-hints", Static).update(self._render_hints())
            # Scroll to top when new file selected
            scroll = self.query_one("#preview-content", FilePreviewScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def _render_header(self) -> Text:
        """Render the header with file info."""
        t = Text()

        if self.current_file is None:
            t.append("\n  📄 ", style="bold #a855f7")
            t.append("No file selected", style="#71717a")
            return t

        path = self.current_file
        icon, color = get_file_icon(path)

        t.append(f"\n  {icon} ", style=f"bold {color}")
        t.append(path.name, style=f"bold white")

        # File info
        try:
            size = path.stat().st_size
            size_str = self._format_size(size)
            t.append(f"  [{size_str}]", style="#71717a")
        except Exception:
            pass

        return t

    def _render_hints(self) -> Text:
        """Render user-friendly hints."""
        t = Text()
        t.append("\n", style="")

        if self.current_file is not None:
            # File is open - show file-specific hints
            t.append("↑↓", style="bold #ec4899")
            t.append(" scroll  ", style="#71717a")
            t.append("e", style="bold #22c55e")
            t.append(" edit  ", style="#71717a")
            t.append("o", style="bold #06b6d4")
            t.append(" open in chat  ", style="#71717a")
            t.append("q", style="bold #f59e0b")
            t.append(" close", style="#71717a")
        else:
            # No file - show navigation hints
            t.append("↑↓", style="bold #ec4899")
            t.append(" navigate  ", style="#71717a")
            t.append("Enter", style="bold #ec4899")
            t.append(" select  ", style="#71717a")
            t.append("Ctrl+B", style="bold #f59e0b")
            t.append(" close sidebar", style="#71717a")

        return t

    def _render_content(self) -> Text | Syntax:
        """Render the file content."""
        if self.current_file is None:
            return self._render_empty()

        return self._render_file_content(self.current_file)

    def _render_empty(self) -> Text:
        """Render empty state."""
        t = Text()
        t.append("\n\n", style="")
        t.append("  👆 ", style="bold #a855f7")
        t.append("Select a file from the tree\n\n", style="#71717a")
        t.append("  📁 ", style="#ec4899")
        t.append("Click folders to expand\n", style="#52525b")
        t.append("  📄 ", style="#ec4899")
        t.append("Click files to preview\n", style="#52525b")
        return t

    def _render_file_content(self, path: Path) -> Text | Syntax:
        """Render file content with syntax highlighting."""
        # Check if binary
        if self._is_binary(path):
            t = Text()
            t.append("\n  🔒 ", style="bold #f59e0b")
            t.append("Binary file\n\n", style="#f59e0b")
            t.append(f"  Size: {self._format_size(path.stat().st_size)}\n", style="#71717a")
            t.append("  Cannot display binary content\n", style="#52525b")
            return t

        # Read content
        try:
            if path in self._content_cache:
                text = self._content_cache[path]
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
                # Cache small files
                if len(text) < 100000:
                    self._content_cache[path] = text

            # Syntax highlight - show ALL content (scrollable)
            language = detect_language(path)
            syntax = Syntax(
                text,
                language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                background_color="#000000",
            )

            return syntax

        except Exception as e:
            t = Text()
            t.append(f"\n  ❌ ", style="bold #ef4444")
            t.append("Error reading file\n\n", style="#ef4444")
            t.append(f"  {str(e)}\n", style="#71717a")
            return t

    def _is_binary(self, path: Path) -> bool:
        """Check if file is binary."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                return b"\x00" in chunk
        except Exception:
            return False

    def _format_size(self, size: int) -> str:
        """Format file size."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def set_file(self, path: Path) -> None:
        """Set the file to preview."""
        self.current_file = path

    def clear(self) -> None:
        """Clear the preview."""
        self.current_file = None

    def action_close_preview(self) -> None:
        """Close the current file preview."""
        if self.current_file is not None:
            self.current_file = None
            self.post_message(self.PreviewClosed())

    def action_edit_file(self) -> None:
        """Open the file in the default editor."""
        if self.current_file is not None:
            self.post_message(self.EditRequested(self.current_file))


# ============================================================================
# ENHANCED SIDEBAR WITH FILE BROWSER AND PREVIEW
# ============================================================================


class EnhancedSidebar(Container):
    """
    Enhanced sidebar with colorful file browser and preview panel.

    Features:
    - Colorful file type icons
    - Gradient folder colors
    - Scrollable file preview with syntax highlighting
    - Simple keyboard shortcuts
    """

    DEFAULT_CSS = """
    EnhancedSidebar {
        width: 100%;
        height: 100%;
        layout: vertical;
        background: #000000;
    }

    EnhancedSidebar #sidebar-header {
        height: 3;
        background: #000000;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    EnhancedSidebar #sidebar-content {
        height: 1fr;
        layout: horizontal;
    }

    EnhancedSidebar #file-tree-container {
        width: 1fr;
        min-width: 25;
        max-width: 35;
        height: 100%;
        background: #000000;
        border-right: solid #1a1a1a;
    }

    EnhancedSidebar #file-tree {
        height: 100%;
        background: #000000;
        scrollbar-size: 1 1;
    }

    EnhancedSidebar #preview-container {
        width: 2fr;
        height: 100%;
        background: #000000;
    }

    EnhancedSidebar #file-preview {
        height: 100%;
    }

    EnhancedSidebar .sidebar-title {
        text-align: center;
        color: #a855f7;
        text-style: bold;
        padding: 1 0;
    }

    EnhancedSidebar ColorfulDirectoryTree {
        background: #000000;
    }

    EnhancedSidebar ColorfulDirectoryTree > .tree--guides {
        color: #1a1a1a;
    }

    EnhancedSidebar ColorfulDirectoryTree > .tree--cursor {
        background: #3f3f46;
        color: #ec4899;
        text-style: bold;
        border-left: tall #a855f7;
    }

    EnhancedSidebar ColorfulDirectoryTree:focus > .tree--cursor {
        background: #52525b;
        color: #ec4899;
        text-style: bold;
        border-left: tall #a855f7;
    }
    """

    class FileOpened(Message):
        """Message sent when a file should be opened/viewed."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(
        self,
        path: Path | str = ".",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.root_path = Path(path).resolve()

    def compose(self) -> ComposeResult:
        """Compose the sidebar layout."""
        # Header with close hint
        with Container(id="sidebar-header"):
            yield Static(self._render_header(), classes="sidebar-title")

        # Content: Tree + Preview
        with Horizontal(id="sidebar-content"):
            # File tree
            with Container(id="file-tree-container"):
                yield ColorfulDirectoryTree(self.root_path, id="file-tree")

            # Preview panel
            with Container(id="preview-container"):
                yield FilePreview(id="file-preview")

    def _render_header(self) -> Text:
        """Render the sidebar header with hints."""
        t = Text()
        t.append("📁 ", style="bold #ec4899")
        t.append(self.root_path.name or "Files", style="bold #a855f7")
        t.append("  ", style="")
        t.append("Ctrl+B", style="bold #71717a")
        t.append(" close", style="#52525b")
        return t

    @on(DirectoryTree.FileSelected)
    def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection - show preview."""
        event.stop()
        path = event.path
        preview = self.query_one("#file-preview", FilePreview)
        preview.set_file(path)

    @on(ColorfulDirectoryTree.FileOpenRequested)
    def on_file_open_requested(self, event: ColorfulDirectoryTree.FileOpenRequested) -> None:
        """Handle file open request - forward to parent."""
        event.stop()
        self.post_message(self.FileOpened(event.path))

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Update preview when navigating with keyboard."""
        node = event.node
        if node.data and hasattr(node.data, "path"):
            path = node.data.path
            if path.is_file():
                preview = self.query_one("#file-preview", FilePreview)
                preview.set_file(path)

    @on(FilePreview.EditRequested)
    def on_edit_requested(self, event: FilePreview.EditRequested) -> None:
        """Handle edit request - open file in default editor."""
        event.stop()
        import subprocess
        import os
        import platform

        path = event.path

        # Try to open in default editor
        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.Popen(["open", str(path)])
            elif system == "Windows":
                os.startfile(str(path))
            else:  # Linux
                # Try common editors
                editor = os.environ.get("EDITOR", "xdg-open")
                subprocess.Popen([editor, str(path)])
        except Exception:
            # Fallback: try $EDITOR or vim/nano
            editor = os.environ.get("EDITOR", "nano")
            try:
                subprocess.Popen([editor, str(path)])
            except Exception:
                pass

    def action_focus_tree(self) -> None:
        """Focus the file tree."""
        self.query_one("#file-tree", ColorfulDirectoryTree).focus()

    def refresh_tree(self) -> None:
        """Refresh the file tree."""
        tree = self.query_one("#file-tree", ColorfulDirectoryTree)
        tree.reload()


# ============================================================================
# COMPACT SIDEBAR (Tree only, no preview)
# ============================================================================


class CompactSidebar(Container):
    """Compact sidebar with just the file tree."""

    DEFAULT_CSS = """
    CompactSidebar {
        width: 32;
        height: 100%;
        background: #000000;
        border-right: solid #1a1a1a;
        padding: 1;
    }

    CompactSidebar #compact-header {
        height: 2;
        text-align: center;
    }

    CompactSidebar #compact-tree {
        height: 1fr;
        background: #000000;
    }

    CompactSidebar ColorfulDirectoryTree {
        background: #000000;
    }
    """

    class FileSelected(Message):
        """Message sent when a file is selected."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(
        self,
        path: Path | str = ".",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.root_path = Path(path).resolve()

    def compose(self) -> ComposeResult:
        """Compose the compact sidebar."""
        header = Text()
        header.append("📁 ", style="bold #ec4899")
        header.append("Files", style="bold #a855f7")
        yield Static(header, id="compact-header")
        yield ColorfulDirectoryTree(self.root_path, id="compact-tree")

    @on(ColorfulDirectoryTree.FileSelected)
    def on_file_selected(self, event: ColorfulDirectoryTree.FileSelected) -> None:
        """Forward file selection."""
        event.stop()
        self.post_message(self.FileSelected(event.path))


# ============================================================================
# GIT STATUS INDICATOR
# ============================================================================


@dataclass
class GitStatusInfo:
    """Git repository status information."""

    branch: str = ""
    modified: int = 0
    staged: int = 0
    untracked: int = 0
    is_repo: bool = False
    ahead: int = 0
    behind: int = 0


def get_git_status(path: Path) -> GitStatusInfo:
    """Get git status for a directory (runs in thread)."""
    info = GitStatusInfo()

    try:
        # Check if it's a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return info

        info.is_repo = True

        # Get branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            info.branch = result.stdout.strip()

        # Get status counts
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                status = line[:2]
                if status[0] in "MADRCU":  # Staged
                    info.staged += 1
                if status[1] in "MD":  # Modified
                    info.modified += 1
                if status == "??":  # Untracked
                    info.untracked += 1

        # Get ahead/behind
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", f"{info.branch}...@{{u}}"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) == 2:
                info.ahead = int(parts[0])
                info.behind = int(parts[1])

    except Exception:
        pass

    return info


class GitStatusWidget(Static):
    """Widget showing git status in sidebar header."""

    DEFAULT_CSS = """
    GitStatusWidget {
        height: 2;
        width: 100%;
        padding: 0 1;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
    }
    """

    status: reactive[GitStatusInfo] = reactive(GitStatusInfo)
    _loading: bool = True

    def __init__(self, path: Path, **kwargs):
        super().__init__(**kwargs)
        self.root_path = path
        self._loading = True

    def on_mount(self) -> None:
        """Start fetching git status."""
        self.refresh_status()

    @work(thread=True)
    def refresh_status(self) -> None:
        """Fetch git status in background thread."""
        status = get_git_status(self.root_path)
        # Use app.call_from_thread to safely update from worker thread
        self.app.call_from_thread(self._update_status, status)

    def _update_status(self, status: GitStatusInfo) -> None:
        """Update status from thread."""
        self._loading = False
        self.status = status

    def watch_status(self, status: GitStatusInfo) -> None:
        """Update display when status changes."""
        self.refresh()

    def render(self) -> Text:
        """Render git status line."""
        t = Text()

        # Loading state
        if self._loading:
            t.append("\n", style="")
            t.append("  ⎇ ", style="bold #a855f7")
            t.append("Loading git status...", style="#52525b italic")
            return t

        status = self.status

        t.append("\n", style="")

        if not status.is_repo:
            t.append("  📁 ", style="#71717a")
            t.append("Not a git repository", style="#52525b")
            return t

        # Branch icon and name
        t.append("  ⎇ ", style="bold #a855f7")
        t.append(status.branch[:20], style="bold #a855f7")

        # Status counts with icons
        if status.staged > 0:
            t.append(f"  ✓{status.staged}", style="bold #22c55e")
        if status.modified > 0:
            t.append(f"  ●{status.modified}", style="bold #f97316")
        if status.untracked > 0:
            t.append(f"  +{status.untracked}", style="#71717a")

        # Ahead/behind with arrows
        if status.ahead > 0:
            t.append(f"  ↑{status.ahead}", style="bold #06b6d4")
        if status.behind > 0:
            t.append(f"  ↓{status.behind}", style="bold #ec4899")

        # Show clean state if nothing to commit
        if status.staged == 0 and status.modified == 0 and status.untracked == 0:
            t.append("  ✓ clean", style="#22c55e")

        return t


# ============================================================================
# PLAN/TASK PANEL
# ============================================================================


@dataclass
class TaskItem:
    """A single task in the plan."""

    content: str
    status: str = "pending"  # pending, in_progress, completed
    priority: str = "medium"  # low, medium, high


class PlanPanel(Container):
    """Panel showing current agent plan/tasks."""

    DEFAULT_CSS = """
    PlanPanel {
        height: auto;
        max-height: 15;
        background: #000000;
        padding: 0 1;
    }

    PlanPanel .task-item {
        height: 1;
        padding: 0;
    }

    PlanPanel .task-pending {
        color: #71717a;
    }

    PlanPanel .task-in-progress {
        color: #f97316;
    }

    PlanPanel .task-completed {
        color: #22c55e;
    }

    PlanPanel .empty-state {
        color: #52525b;
        text-style: italic;
        padding: 1;
    }
    """

    tasks: reactive[List[TaskItem]] = reactive(list)

    def compose(self) -> ComposeResult:
        """Compose the plan panel."""
        yield Static(self._render_tasks(), id="plan-content")

    def watch_tasks(self, tasks: List[TaskItem]) -> None:
        """Update when tasks change."""
        try:
            self.query_one("#plan-content", Static).update(self._render_tasks())
        except Exception:
            pass

    def _render_tasks(self) -> Text:
        """Render task list."""
        t = Text()

        if not self.tasks:
            t.append("  No active tasks\n", style="italic #52525b")
            t.append("  Start a conversation to see plan", style="#3f3f46")
            return t

        for task in self.tasks[:8]:  # Show max 8 tasks
            # Status icon
            if task.status == "completed":
                t.append(" ✓ ", style="bold #22c55e")
            elif task.status == "in_progress":
                t.append(" ● ", style="bold #f97316")
            else:
                t.append(" ○ ", style="#71717a")

            # Task content (truncated)
            content = task.content[:40] + "..." if len(task.content) > 40 else task.content

            if task.status == "completed":
                t.append(content, style="#52525b")
            elif task.status == "in_progress":
                t.append(content, style="#f97316")
            else:
                t.append(content, style="#a1a1aa")

            t.append("\n")

        if len(self.tasks) > 8:
            t.append(f"  +{len(self.tasks) - 8} more tasks...", style="#52525b")

        return t

    def set_tasks(self, tasks: List[TaskItem]) -> None:
        """Update the task list."""
        self.tasks = tasks

    def add_task(self, content: str, status: str = "pending") -> None:
        """Add a new task."""
        self.tasks = self.tasks + [TaskItem(content=content, status=status)]

    def update_task_status(self, index: int, status: str) -> None:
        """Update a task's status."""
        if 0 <= index < len(self.tasks):
            tasks = list(self.tasks)
            tasks[index] = TaskItem(
                content=tasks[index].content, status=status, priority=tasks[index].priority
            )
            self.tasks = tasks


# ============================================================================
# FILE SEARCH
# ============================================================================


class FileSearchResults(Container):
    """Container showing file search results."""

    DEFAULT_CSS = """
    FileSearchResults {
        height: auto;
        max-height: 12;
        background: #000000;
        padding: 0;
        display: none;
    }

    FileSearchResults.visible {
        display: block;
    }

    FileSearchResults .search-result {
        height: 1;
        padding: 0 1;
    }

    FileSearchResults .search-result:hover {
        background: #1a1a1a;
    }

    FileSearchResults .search-result.selected {
        background: #a855f720;
    }
    """

    results: reactive[List[Path]] = reactive(list)
    selected_index: reactive[int] = reactive(0)

    class FileSelected(Message):
        """Message when a search result is selected."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def compose(self) -> ComposeResult:
        """Compose search results."""
        yield Static(self._render_results(), id="search-results-content")

    def watch_results(self, results: List[Path]) -> None:
        """Update when results change."""
        self.selected_index = 0
        try:
            self.query_one("#search-results-content", Static).update(self._render_results())
        except Exception:
            pass

    def watch_selected_index(self, index: int) -> None:
        """Update when selection changes."""
        try:
            self.query_one("#search-results-content", Static).update(self._render_results())
        except Exception:
            pass

    def _render_results(self) -> Text:
        """Render search results."""
        t = Text()

        if not self.results:
            t.append("  No matches found", style="italic #52525b")
            return t

        for i, path in enumerate(self.results[:10]):
            # Selection indicator
            if i == self.selected_index:
                t.append("▸ ", style="bold #a855f7")
            else:
                t.append("  ", style="")

            # File icon
            icon, color = get_file_icon(path)
            t.append(f"{icon} ", style=color)

            # Path (relative, truncated)
            rel_path = str(path)[-45:] if len(str(path)) > 45 else str(path)
            if len(str(path)) > 45:
                rel_path = "..." + rel_path

            if i == self.selected_index:
                t.append(rel_path, style="bold white")
            else:
                t.append(rel_path, style="#a1a1aa")

            t.append("\n")

        if len(self.results) > 10:
            t.append(f"  +{len(self.results) - 10} more results", style="#52525b")

        return t

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if self.results:
            new_index = (self.selected_index + delta) % min(len(self.results), 10)
            self.selected_index = new_index

    def get_selected(self) -> Optional[Path]:
        """Get the selected path."""
        if self.results and 0 <= self.selected_index < len(self.results):
            return self.results[self.selected_index]
        return None


class FileSearch(Container):
    """File search widget with fuzzy matching."""

    DEFAULT_CSS = """
    FileSearch {
        height: auto;
        background: #000000;
        padding: 0;
    }

    FileSearch #search-input {
        height: 1;
        background: #0a0a0a;
        border: none;
        padding: 0 1;
        margin: 0;
    }

    FileSearch #search-input:focus {
        border: none;
    }
    """

    BINDINGS = [
        Binding("escape", "close_search", "Close", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select_file", "Select", show=False),
    ]

    class FileSelected(Message):
        """Message when a file is selected from search."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    class SearchClosed(Message):
        """Message when search is closed."""

        pass

    def __init__(self, root_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.root_path = root_path
        self._all_files: List[Path] = []
        self._files_loaded = False

    def compose(self) -> ComposeResult:
        """Compose the search widget."""
        yield Input(placeholder="🔍 Search files...", id="search-input")
        yield FileSearchResults(id="search-results")

    def on_mount(self) -> None:
        """Load files on mount."""
        self._load_files()

    @work(thread=True)
    def _load_files(self) -> None:
        """Load all files in background."""
        files = []
        try:
            for path in self.root_path.rglob("*"):
                if path.is_file():
                    # Skip hidden and ignored
                    parts = path.parts
                    if any(
                        p.startswith(".") or p in {"node_modules", "__pycache__", "venv", ".venv"}
                        for p in parts
                    ):
                        continue
                    files.append(path)
                    if len(files) > 5000:  # Limit for performance
                        break
        except Exception:
            pass

        self._all_files = files
        self._files_loaded = True

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        query = event.value.lower().strip()
        results_widget = self.query_one("#search-results", FileSearchResults)

        if not query:
            results_widget.results = []
            results_widget.remove_class("visible")
            return

        # Fuzzy match files
        matches = []
        for path in self._all_files:
            name = path.name.lower()
            rel_path = str(path.relative_to(self.root_path)).lower()

            # Simple fuzzy match: all query chars appear in order
            if self._fuzzy_match(query, name) or self._fuzzy_match(query, rel_path):
                matches.append(path)
                if len(matches) >= 50:
                    break

        results_widget.results = matches
        if matches:
            results_widget.add_class("visible")
        else:
            results_widget.remove_class("visible")

    def _fuzzy_match(self, query: str, target: str) -> bool:
        """Simple fuzzy matching."""
        query_idx = 0
        for char in target:
            if query_idx < len(query) and char == query[query_idx]:
                query_idx += 1
        return query_idx == len(query)

    def action_close_search(self) -> None:
        """Close the search."""
        self.query_one("#search-input", Input).value = ""
        self.query_one("#search-results", FileSearchResults).results = []
        self.query_one("#search-results", FileSearchResults).remove_class("visible")
        self.post_message(self.SearchClosed())

    def action_move_up(self) -> None:
        """Move selection up."""
        self.query_one("#search-results", FileSearchResults).move_selection(-1)

    def action_move_down(self) -> None:
        """Move selection down."""
        self.query_one("#search-results", FileSearchResults).move_selection(1)

    def action_select_file(self) -> None:
        """Select the current file."""
        results = self.query_one("#search-results", FileSearchResults)
        path = results.get_selected()
        if path:
            self.post_message(self.FileSelected(path))
            self.action_close_search()


# ============================================================================
# CODEBASE SEARCH (Content Search / Grep)
# ============================================================================


@dataclass
class CodeSearchResult:
    """A single code search result."""

    path: Path
    line_no: int
    line_content: str
    match_start: int
    match_end: int


def search_codebase(root_path: Path, query: str, max_results: int = 100) -> List[CodeSearchResult]:
    """Search through file contents (grep-like)."""
    results = []
    query_lower = query.lower()

    # File extensions to search
    code_extensions = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".cs",
        ".vb",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".md",
        ".txt",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".sql",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".gitignore",
        ".dockerignore",
    }

    try:
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue

            # Skip hidden and ignored directories
            parts = path.parts
            if any(
                p.startswith(".")
                and p not in {".env", ".gitignore", ".dockerignore"}
                or p in {"node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
                for p in parts
            ):
                continue

            # Only search code files
            if path.suffix.lower() not in code_extensions:
                continue

            # Skip large files
            try:
                if path.stat().st_size > 500000:  # 500KB limit
                    continue
            except Exception:
                continue

            # Search file content
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        line_lower = line.lower()
                        idx = line_lower.find(query_lower)
                        if idx != -1:
                            results.append(
                                CodeSearchResult(
                                    path=path,
                                    line_no=line_no,
                                    line_content=line.rstrip()[:200],  # Limit line length
                                    match_start=idx,
                                    match_end=idx + len(query),
                                )
                            )
                            if len(results) >= max_results:
                                return results
            except Exception:
                continue

    except Exception:
        pass

    return results


class CodeSearchResults(Container):
    """Container showing code search results."""

    DEFAULT_CSS = """
    CodeSearchResults {
        height: auto;
        max-height: 20;
        background: #000000;
        padding: 0;
        display: none;
    }

    CodeSearchResults.visible {
        display: block;
    }
    """

    results: reactive[List[CodeSearchResult]] = reactive(list)
    selected_index: reactive[int] = reactive(0)

    class ResultSelected(Message):
        """Message when a search result is selected."""

        def __init__(self, result: CodeSearchResult) -> None:
            self.result = result
            super().__init__()

    def compose(self) -> ComposeResult:
        """Compose search results."""
        yield Static(self._render_results(), id="code-results-content")

    def watch_results(self, results: List[CodeSearchResult]) -> None:
        """Update when results change."""
        self.selected_index = 0
        try:
            self.query_one("#code-results-content", Static).update(self._render_results())
        except Exception:
            pass

    def watch_selected_index(self, index: int) -> None:
        """Update when selection changes."""
        try:
            self.query_one("#code-results-content", Static).update(self._render_results())
        except Exception:
            pass

    def _render_results(self) -> Text:
        """Render search results."""
        t = Text()

        if not self.results:
            t.append("  No matches found", style="italic #52525b")
            return t

        # Group by file
        current_file = None
        display_count = 0

        for i, result in enumerate(self.results[:30]):  # Show max 30 results
            # File header
            if result.path != current_file:
                if current_file is not None:
                    t.append("\n", style="")
                current_file = result.path

                # File icon and path
                icon, color = get_file_icon(result.path)
                rel_path = (
                    str(result.path)[-50:] if len(str(result.path)) > 50 else str(result.path)
                )
                if len(str(result.path)) > 50:
                    rel_path = "..." + rel_path
                t.append(f"  {icon} ", style=color)
                t.append(rel_path + "\n", style="bold #a1a1aa")

            # Result line
            if i == self.selected_index:
                t.append("  ▸ ", style="bold #a855f7")
            else:
                t.append("    ", style="")

            # Line number
            t.append(f"{result.line_no:>4}:", style="#52525b")

            # Line content with highlight
            line = result.line_content[:80]
            if result.match_start < len(line):
                # Before match
                t.append(line[: result.match_start], style="#71717a")
                # Match (highlighted)
                match_end = min(result.match_end, len(line))
                t.append(line[result.match_start : match_end], style="bold #fbbf24 on #1a1a1a")
                # After match
                t.append(line[match_end:], style="#71717a")
            else:
                t.append(line, style="#71717a")

            t.append("\n", style="")
            display_count += 1

        if len(self.results) > 30:
            t.append(f"\n  +{len(self.results) - 30} more results", style="#52525b")

        return t

    def move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        if self.results:
            max_idx = min(len(self.results), 30) - 1
            new_index = max(0, min(self.selected_index + delta, max_idx))
            self.selected_index = new_index

    def get_selected(self) -> Optional[CodeSearchResult]:
        """Get the selected result."""
        if self.results and 0 <= self.selected_index < len(self.results):
            return self.results[self.selected_index]
        return None


class CodebaseSearch(Container):
    """Codebase search widget - grep through file contents."""

    DEFAULT_CSS = """
    CodebaseSearch {
        height: auto;
        background: #000000;
        padding: 0;
    }

    CodebaseSearch #code-search-input {
        height: 1;
        background: #0a0a0a;
        border: none;
        padding: 0 1;
        margin: 0;
    }

    CodebaseSearch #code-search-input:focus {
        border: none;
    }

    CodebaseSearch #search-status {
        height: 1;
        padding: 0 1;
        color: #52525b;
    }
    """

    BINDINGS = [
        Binding("escape", "close_search", "Close", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select_result", "Select", show=False),
    ]

    _searching: bool = False

    class ResultSelected(Message):
        """Message when a result is selected."""

        def __init__(self, path: Path, line_no: int) -> None:
            self.path = path
            self.line_no = line_no
            super().__init__()

    class SearchClosed(Message):
        """Message when search is closed."""

        pass

    def __init__(self, root_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.root_path = root_path
        self._searching = False
        self._last_query = ""

    def compose(self) -> ComposeResult:
        """Compose the search widget."""
        yield Input(placeholder="🔎 Search in files...", id="code-search-input")
        yield Static("", id="search-status")
        yield CodeSearchResults(id="code-search-results")

    @on(Input.Changed, "#code-search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        query = event.value.strip()

        if not query or len(query) < 2:
            self.query_one("#code-search-results", CodeSearchResults).results = []
            self.query_one("#code-search-results", CodeSearchResults).remove_class("visible")
            self.query_one("#search-status", Static).update("")
            return

        if query != self._last_query:
            self._last_query = query
            self._do_search(query)

    @work(thread=True)
    def _do_search(self, query: str) -> None:
        """Perform search in background."""
        self._searching = True
        self.app.call_from_thread(self._update_status, "Searching...")

        results = search_codebase(self.root_path, query)

        self.app.call_from_thread(self._show_results, results)

    def _update_status(self, status: str) -> None:
        """Update status text."""
        try:
            self.query_one("#search-status", Static).update(status)
        except Exception:
            pass

    def _show_results(self, results: List[CodeSearchResult]) -> None:
        """Show search results."""
        self._searching = False
        try:
            results_widget = self.query_one("#code-search-results", CodeSearchResults)
            results_widget.results = results

            if results:
                results_widget.add_class("visible")
                self._update_status(f"Found {len(results)} matches")
            else:
                results_widget.remove_class("visible")
                self._update_status("No matches found")
        except Exception:
            pass

    def action_close_search(self) -> None:
        """Close the search."""
        self.query_one("#code-search-input", Input).value = ""
        self.query_one("#code-search-results", CodeSearchResults).results = []
        self.query_one("#code-search-results", CodeSearchResults).remove_class("visible")
        self.query_one("#search-status", Static).update("")
        self._last_query = ""
        self.post_message(self.SearchClosed())

    def action_move_up(self) -> None:
        """Move selection up."""
        self.query_one("#code-search-results", CodeSearchResults).move_selection(-1)

    def action_move_down(self) -> None:
        """Move selection down."""
        self.query_one("#code-search-results", CodeSearchResults).move_selection(1)

    def action_select_result(self) -> None:
        """Select the current result."""
        results = self.query_one("#code-search-results", CodeSearchResults)
        result = results.get_selected()
        if result:
            self.post_message(self.ResultSelected(result.path, result.line_no))
            self.action_close_search()


# ============================================================================
# TABBED SIDEBAR (Clean Tab-based Design)
# ============================================================================


class SidebarTabs(Container):
    """Tab bar for switching between sidebar views.

    Tabs: Files, Code, Changes, Search, Agent, Context, Diff, History
    Uses minimal SuperQode icons instead of emojis.
    """

    DEFAULT_CSS = """
    SidebarTabs {
        height: 2;
        width: 100%;
        layout: horizontal;
        background: #000000;
        border-bottom: solid #1a1a1a;
        overflow-x: auto;
    }

    SidebarTabs .tab {
        width: auto;
        min-width: 4;
        height: 100%;
        content-align: center middle;
        text-align: center;
        background: #000000;
        color: #71717a;
        padding: 0 1;
    }

    SidebarTabs .tab:hover {
        background: #0a0a0a;
        color: #a1a1aa;
    }

    SidebarTabs .tab.active {
        background: #0a0a0a;
        color: #a855f7;
        border-bottom: solid #a855f7;
    }
    """

    # All available tabs with SuperQode icons - Colorful symbols
    TABS = {
        "files": "📁",  # Files
        "code": "◇",  # Code preview
        "changes": "⟳",  # Git changes
        "search": "⌕",  # Search
        "agent": "◈",  # Agent info
        "context": "↳",  # Context
        "diff": "±",  # Diff
        "history": "◇",  # History
    }

    # Tab hints for hover
    TAB_HINTS = {
        "files": "Project Files",
        "code": "Code Preview",
        "changes": "Git Changes",
        "search": "Search Files",
        "agent": "Agent Info",
        "context": "Context",
        "diff": "File Diff",
        "history": "History",
    }

    active_tab: reactive[str] = reactive("files")

    class TabChanged(Message):
        """Message when tab changes."""

        def __init__(self, tab: str) -> None:
            self.tab = tab
            super().__init__()

    def compose(self) -> ComposeResult:
        """Compose tab bar with all tabs."""
        # Primary tabs (always shown) - Colorful symbols with hints
        yield Static(self.TABS["files"], id="tab-files", classes="tab active")
        yield Static(self.TABS["code"], id="tab-code", classes="tab")
        yield Static(self.TABS["changes"], id="tab-changes", classes="tab")
        yield Static(self.TABS["search"], id="tab-search", classes="tab")
        yield Static(self.TABS["agent"], id="tab-agent", classes="tab")
        yield Static(self.TABS["context"], id="tab-context", classes="tab")
        yield Static(self.TABS["diff"], id="tab-diff", classes="tab")
        yield Static(self.TABS["history"], id="tab-history", classes="tab")

    def on_mount(self) -> None:
        """Set tooltips after widgets are mounted."""
        for tab_name in self.TABS:
            try:
                tab_widget = self.query_one(f"#tab-{tab_name}", Static)
                hint = self.TAB_HINTS.get(tab_name, "")
                if hint:
                    tab_widget.tooltip = hint
            except Exception:
                pass

    def on_click(self, event) -> None:
        """Handle tab clicks."""
        widget_id = event.widget.id
        if widget_id and widget_id.startswith("tab-"):
            tab_name = widget_id[4:]  # Remove "tab-" prefix
            if tab_name in self.TABS:
                self.active_tab = tab_name

    def watch_active_tab(self, tab: str) -> None:
        """Update tab styles when active tab changes."""
        try:
            # Remove active class from all tabs
            for tab_name in self.TABS:
                try:
                    tab_widget = self.query_one(f"#tab-{tab_name}", Static)
                    tab_widget.remove_class("active")
                except Exception:
                    pass

            # Add active class to selected tab
            try:
                active_widget = self.query_one(f"#tab-{tab}", Static)
                active_widget.add_class("active")
            except Exception:
                pass

            self.post_message(self.TabChanged(tab))
        except Exception:
            pass

    def select_tab(self, tab: str) -> None:
        """Programmatically select a tab."""
        if tab in self.TABS:
            self.active_tab = tab


# ============================================================================
# GIT CHANGES VIEW
# ============================================================================


@dataclass
class GitChange:
    """A single git change entry."""

    path: str
    status: str  # M=modified, A=added, D=deleted, ?=untracked, R=renamed
    staged: bool = False


def get_git_changes(root_path: Path) -> List[GitChange]:
    """Get list of changed files from git."""
    changes = []
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                status = line[:2]
                path = line[3:]

                # Parse status
                staged = status[0] != " " and status[0] != "?"
                if status[0] in "MADRCU":
                    changes.append(GitChange(path=path, status=status[0], staged=True))
                if status[1] in "MD":
                    changes.append(GitChange(path=path, status=status[1], staged=False))
                if status == "??":
                    changes.append(GitChange(path=path, status="?", staged=False))
    except Exception:
        pass
    return changes


def get_file_diff(root_path: Path, file_path: str, staged: bool = False) -> str:
    """Get diff for a specific file."""
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        cmd.append("--")
        cmd.append(file_path)

        result = subprocess.run(cmd, cwd=root_path, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


class GitChangesPanel(Container):
    """Panel showing git changes with diffs."""

    DEFAULT_CSS = """
    GitChangesPanel {
        height: 100%;
        width: 100%;
        background: #000000;
        layout: vertical;
    }

    GitChangesPanel #changes-header {
        height: 2;
        background: #0a0a0a;
        border-bottom: solid #1a1a1a;
        padding: 0 1;
    }

    GitChangesPanel #changes-list {
        height: 1fr;
        background: #000000;
        overflow-y: auto;
        scrollbar-size: 1 1;
    }

    GitChangesPanel .change-item {
        height: 1;
        padding: 0 1;
        background: #000000;
    }

    GitChangesPanel .change-item:hover {
        background: #0a0a0a;
    }

    GitChangesPanel .change-item.selected {
        background: #a855f720;
    }

    GitChangesPanel #diff-view {
        height: 1fr;
        background: #000000;
        border-top: solid #1a1a1a;
        overflow-y: auto;
        overflow-x: auto;
        scrollbar-size: 1 1;
        display: none;
    }

    GitChangesPanel #diff-view.visible {
        display: block;
    }

    GitChangesPanel #no-changes {
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #52525b;
    }

    GitChangesPanel #loading {
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: #71717a;
    }
    """

    changes: reactive[List[GitChange]] = reactive(list)
    selected_index: reactive[int] = reactive(-1)
    _loading: bool = True

    class FileSelected(Message):
        """Message when a file is selected for diff viewing."""

        def __init__(self, path: str, staged: bool) -> None:
            self.path = path
            self.staged = staged
            super().__init__()

    def __init__(self, root_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.root_path = root_path
        self._loading = True
        self._current_diff = ""

    def compose(self) -> ComposeResult:
        """Compose the changes panel."""
        yield Static(self._render_header(), id="changes-header")
        yield Static("Loading changes...", id="loading")
        with ScrollableContainer(id="changes-list"):
            yield Static("", id="changes-content")
        with ScrollableContainer(id="diff-view"):
            yield Static("", id="diff-content")
        yield Static("✓ No changes\nWorking tree clean", id="no-changes")

    def on_mount(self) -> None:
        """Load changes on mount."""
        self.refresh_changes()

    @work(thread=True)
    def refresh_changes(self) -> None:
        """Refresh git changes in background."""
        changes = get_git_changes(self.root_path)
        self.app.call_from_thread(self._update_changes, changes)

    def _update_changes(self, changes: List[GitChange]) -> None:
        """Update changes from thread."""
        self._loading = False
        self.changes = changes

        # Reset selection if current selection is out of bounds
        if self.selected_index >= len(self.changes):
            self.selected_index = -1

        self._update_ui()

    def _update_ui(self) -> None:
        """Update UI based on current state."""
        try:
            loading = self.query_one("#loading", Static)
            no_changes = self.query_one("#no-changes", Static)
            changes_list = self.query_one("#changes-list", ScrollableContainer)
            diff_view = self.query_one("#diff-view", ScrollableContainer)

            loading.display = False

            if not self.changes:
                no_changes.display = True
                changes_list.display = False
                # Hide diff view when no changes
                diff_view.remove_class("visible")
                self.selected_index = -1
            else:
                no_changes.display = False
                changes_list.display = True
                self.query_one("#changes-content", Static).update(self._render_changes())

                # If we have a valid selection, ensure diff is loaded
                if 0 <= self.selected_index < len(self.changes):
                    change = self.changes[self.selected_index]
                    self._load_diff(change.path, change.staged)
                else:
                    # Clear diff view if no valid selection
                    diff_view.remove_class("visible")
        except Exception:
            pass

    def _render_header(self) -> Text:
        """Render the header."""
        t = Text()
        t.append("\n", style="")
        t.append("📊 Git Changes", style="bold #a855f7")
        t.append("  ", style="")
        t.append("r", style="bold #52525b")
        t.append(" refresh", style="#3f3f46")
        return t

    def _render_changes(self) -> Text:
        """Render the changes list."""
        t = Text()

        # Group by staged/unstaged
        staged = [c for c in self.changes if c.staged]
        unstaged = [c for c in self.changes if not c.staged]

        if staged:
            t.append("  Staged Changes\n", style="bold #22c55e")
            for i, change in enumerate(staged):
                self._render_change_item(t, change, i)

        if unstaged:
            if staged:
                t.append("\n", style="")
            t.append("  Unstaged Changes\n", style="bold #f97316")
            for i, change in enumerate(unstaged, len(staged)):
                self._render_change_item(t, change, i)

        return t

    def _render_change_item(self, t: Text, change: GitChange, index: int) -> None:
        """Render a single change item."""
        # Selection indicator
        if index == self.selected_index:
            t.append("  ▸ ", style="bold #a855f7")
        else:
            t.append("    ", style="")

        # Status icon
        if change.status == "M":
            t.append("● ", style="bold #f97316")
        elif change.status == "A":
            t.append("+ ", style="bold #22c55e")
        elif change.status == "D":
            t.append("- ", style="bold #ef4444")
        elif change.status == "?":
            t.append("? ", style="#71717a")
        elif change.status == "R":
            t.append("→ ", style="bold #06b6d4")
        else:
            t.append("  ", style="")

        # File path - show full path (no truncation)
        path = change.path

        if index == self.selected_index:
            t.append(path, style="bold white")
        else:
            t.append(path, style="#a1a1aa")

        t.append("\n", style="")

    def watch_changes(self, changes: List[GitChange]) -> None:
        """Update when changes change."""
        self._update_ui()

    def watch_selected_index(self, index: int) -> None:
        """Update when selection changes."""
        try:
            self.query_one("#changes-content", Static).update(self._render_changes())

            # Load diff for selected file
            if 0 <= index < len(self.changes):
                change = self.changes[index]
                self._load_diff(change.path, change.staged)
        except Exception:
            pass

    @work(thread=True)
    def _load_diff(self, path: str, staged: bool) -> None:
        """Load diff for a file in background."""
        diff = get_file_diff(self.root_path, path, staged)
        self.app.call_from_thread(self._show_diff, diff)

    def _show_diff(self, diff: str) -> None:
        """Show diff content."""
        try:
            diff_view = self.query_one("#diff-view", ScrollableContainer)
            diff_content = self.query_one("#diff-content", Static)

            if diff:
                diff_view.add_class("visible")
                diff_content.update(self._render_diff(diff))
            else:
                diff_view.remove_class("visible")
        except Exception:
            pass

    def _render_diff(self, diff: str) -> Text:
        """Render diff content with colors."""
        t = Text()

        for line in diff.split("\n"):
            if line.startswith("+++") or line.startswith("---"):
                t.append(line + "\n", style="bold #71717a")
            elif line.startswith("@@"):
                t.append(line + "\n", style="bold #06b6d4")
            elif line.startswith("+"):
                t.append(line + "\n", style="#22c55e on #22c55e15")
            elif line.startswith("-"):
                t.append(line + "\n", style="#ef4444 on #ef444415")
            else:
                t.append(line + "\n", style="#a1a1aa")

        return t

    def on_click(self, event) -> None:
        """Handle clicks on change items."""
        # Calculate which item was clicked based on y position
        try:
            changes_list = self.query_one("#changes-list", ScrollableContainer)
            if changes_list in event.widget.ancestors or event.widget == changes_list:
                # Rough calculation of clicked index
                y = event.y - 3  # Offset for header
                if 0 <= y < len(self.changes) + 4:  # Account for section headers
                    self.selected_index = max(0, min(y - 1, len(self.changes) - 1))
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh changes."""
        self._loading = True
        try:
            self.query_one("#loading", Static).display = True
        except Exception:
            pass
        self.refresh_changes()

    def select_next(self) -> None:
        """Select next change."""
        if self.changes:
            self.selected_index = (self.selected_index + 1) % len(self.changes)

    def select_prev(self) -> None:
        """Select previous change."""
        if self.changes:
            self.selected_index = (self.selected_index - 1) % len(self.changes)

    def highlight_files(self, files: List[str]) -> None:
        """Highlight specified files in the changes list.

        This method should be called after refresh_changes() completes.
        It will select the first matching file and load its diff.
        """
        # Clear previous selection
        self.selected_index = -1

        # Find and select the first file to highlight
        for i, change in enumerate(self.changes):
            if change.path in files:
                self.selected_index = i
                # This will trigger watch_selected_index which loads the diff
                break

        # If no match found but we have changes, select the first one
        if self.selected_index == -1 and self.changes:
            self.selected_index = 0


class CollapsibleSidebar(Container):
    """
    Clean tabbed sidebar with Files, Code, and Changes views.

    Features:
    - Git status indicator (always visible)
    - File search (Ctrl+F)
    - Tab switching: Files | Code | Changes
    - Click file to view code in sidebar
    - Git diff view for changed files
    - Dark black background
    """

    DEFAULT_CSS = """
    CollapsibleSidebar {
        width: 100%;
        height: 100%;
        layout: vertical;
        background: #000000;
    }

    CollapsibleSidebar #sidebar-header {
        height: auto;
        background: #000000;
        padding: 0;
    }

    CollapsibleSidebar .sidebar-title {
        height: 2;
        padding: 0 1;
        text-align: left;
        background: #000000;
    }

    CollapsibleSidebar #git-status {
        height: 2;
        background: #000000;
        border-bottom: solid #1a1a1a;
    }

    CollapsibleSidebar #file-search {
        background: #000000;
        border-bottom: solid #1a1a1a;
    }

    CollapsibleSidebar #file-search.-hidden {
        display: none;
    }

    CollapsibleSidebar #sidebar-content {
        height: 1fr;
        background: #000000;
    }

    CollapsibleSidebar #files-view {
        height: 100%;
        width: 100%;
        background: #000000;
    }

    CollapsibleSidebar #files-view.-hidden {
        display: none;
    }

    CollapsibleSidebar #code-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #code-view.visible {
        display: block;
    }

    CollapsibleSidebar #changes-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #changes-view.visible {
        display: block;
    }

    CollapsibleSidebar #search-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #search-view.visible {
        display: block;
    }

    CollapsibleSidebar #file-tree {
        height: 100%;
        background: #000000;
        scrollbar-size: 1 1;
    }

    CollapsibleSidebar #file-preview {
        height: 100%;
        background: #000000;
    }

    CollapsibleSidebar ColorfulDirectoryTree {
        background: #000000;
    }

    CollapsibleSidebar ColorfulDirectoryTree > .tree--guides {
        color: #1a1a1a;
    }

    CollapsibleSidebar ColorfulDirectoryTree > .tree--cursor {
        background: #3f3f46;
        color: #ec4899;
        text-style: bold;
        border-left: tall #a855f7;
    }

    CollapsibleSidebar ColorfulDirectoryTree:focus > .tree--cursor {
        background: #52525b;
        color: #ec4899;
        text-style: bold;
        border-left: tall #a855f7;
    }

    CollapsibleSidebar FilePreview {
        background: #000000;
    }

    CollapsibleSidebar #preview-header {
        background: #000000;
    }

    CollapsibleSidebar #preview-content {
        background: #000000;
    }

    CollapsibleSidebar #preview-hints {
        background: #000000;
    }

    CollapsibleSidebar GitChangesPanel {
        background: #000000;
    }

    /* New panel views - hidden by default */
    CollapsibleSidebar #agent-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #agent-view.visible {
        display: block;
    }

    CollapsibleSidebar #context-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #context-view.visible {
        display: block;
    }


    CollapsibleSidebar #diff-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #diff-view.visible {
        display: block;
    }

    CollapsibleSidebar #history-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
    }

    CollapsibleSidebar #history-view.visible {
        display: block;
    }

    /* QE Dashboard View */
    CollapsibleSidebar #qe-view {
        height: 100%;
        width: 100%;
        background: #000000;
        display: none;
        layout: vertical;
        padding: 1;
    }

    CollapsibleSidebar #qe-view.visible {
        display: block;
    }

    CollapsibleSidebar #qe-dashboard {
        height: auto;
        width: 100%;
    }

    CollapsibleSidebar #qe-dashboard-fallback {
        height: 100%;
        width: 100%;
        content-align: center middle;
        text-align: center;
        color: #71717a;
    }
    """

    BINDINGS = [
        Binding("ctrl+f", "toggle_search", "Search", show=True),
        Binding("escape", "dismiss", "Close", show=False),
        Binding("f", "show_files", "Files", show=False),
        Binding("c", "show_code", "Code", show=False),
        Binding("g", "show_changes", "Changes", show=False),
        Binding("s", "show_search", "Search", show=False),
        Binding("r", "refresh_changes", "Refresh", show=False),
        Binding("a", "show_agent", "Agent", show=False),
        Binding("x", "show_context", "Context", show=False),
        Binding("d", "show_diff", "Diff", show=False),
        Binding("h", "show_history", "History", show=False),
    ]

    current_view: reactive[str] = reactive("files")

    # All available views
    VIEWS = ["files", "code", "changes", "search", "agent", "context", "diff", "history"]

    class FileOpened(Message):
        """Message sent when a file should be opened/viewed."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    class Dismiss(Message):
        """Message to dismiss/close the sidebar."""

        pass

    def __init__(
        self,
        path: Path | str = ".",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.root_path = Path(path).resolve()
        self._current_file: Optional[Path] = None

    def compose(self) -> ComposeResult:
        """Compose the sidebar layout with all panels."""
        # Import new panels (lazy import to avoid circular deps)
        from superqode.widgets.sidebar_panels import (
            AgentPanel,
            ContextPanel,
            TerminalPanel,
            DiffPanel,
            HistoryPanel,
        )

        # Header with title
        with Container(id="sidebar-header"):
            yield Static(self._render_title(), classes="sidebar-title")
            yield GitStatusWidget(self.root_path, id="git-status")

        # File search (hidden by default)
        yield FileSearch(self.root_path, id="file-search", classes="-hidden")

        # Tab bar
        yield SidebarTabs(id="sidebar-tabs")

        # Content area
        with Container(id="sidebar-content"):
            # Files view (default)
            with Container(id="files-view"):
                yield ColorfulDirectoryTree(self.root_path, id="file-tree")

            # Code view (hidden by default)
            with Container(id="code-view"):
                yield FilePreview(id="file-preview")

            # Changes view (hidden by default)
            with Container(id="changes-view"):
                yield GitChangesPanel(self.root_path, id="git-changes")

            # Search view (hidden by default)
            with Container(id="search-view"):
                yield CodebaseSearch(self.root_path, id="codebase-search")

            # NEW: Agent panel
            with Container(id="agent-view"):
                yield AgentPanel(id="agent-panel")

            # NEW: Context panel
            with Container(id="context-view"):
                yield ContextPanel(id="context-panel")

            # NEW: Diff panel
            with Container(id="diff-view"):
                yield DiffPanel(id="diff-panel")

            # NEW: History panel
            with Container(id="history-view"):
                yield HistoryPanel(id="history-panel")

            # QE dashboard panel is not shown in OSS.

    def _render_title(self) -> Text:
        """Render the sidebar title."""
        t = Text()
        t.append("\n", style="")
        t.append("📁 ", style="bold #ec4899")
        t.append(self.root_path.name or "Project", style="bold #a855f7")
        t.append("  ", style="")
        t.append("Ctrl+B", style="#52525b")
        t.append(" close  ", style="#3f3f46")
        t.append("Ctrl+F", style="#52525b")
        t.append(" search", style="#3f3f46")
        return t

    def watch_current_view(self, view: str) -> None:
        """Switch between all sidebar views."""
        try:
            tabs = self.query_one("#sidebar-tabs", SidebarTabs)

            # Hide all views first
            all_views = [
                "files-view",
                "code-view",
                "changes-view",
                "search-view",
                "agent-view",
                "context-view",
                "diff-view",
                "history-view",
            ]

            for view_id in all_views:
                try:
                    v = self.query_one(f"#{view_id}", Container)
                    v.add_class("-hidden")
                    v.remove_class("visible")
                except Exception:
                    pass

            # Show selected view
            view_id = f"{view}-view"
            try:
                selected = self.query_one(f"#{view_id}", Container)
                selected.remove_class("-hidden")
                selected.add_class("visible")
                tabs.active_tab = view
            except Exception:
                pass

            # View-specific actions
            if view == "changes":
                # Refresh changes when switching to changes tab
                try:
                    self.query_one("#git-changes", GitChangesPanel).refresh_changes()
                except Exception:
                    pass
            elif view == "search":
                # Focus the search input
                try:
                    self.query_one("#codebase-search", CodebaseSearch).query_one(
                        "#code-search-input", Input
                    ).focus()
                except Exception:
                    pass
        except Exception:
            pass

    @on(SidebarTabs.TabChanged)
    def on_tab_changed(self, event: SidebarTabs.TabChanged) -> None:
        """Handle tab changes."""
        event.stop()
        self.current_view = event.tab

    def action_toggle_search(self) -> None:
        """Toggle file search visibility."""
        search = self.query_one("#file-search", FileSearch)
        if search.has_class("-hidden"):
            search.remove_class("-hidden")
            search.query_one("#search-input", Input).focus()
        else:
            search.add_class("-hidden")

    def action_dismiss(self) -> None:
        """Dismiss the sidebar."""
        self.post_message(self.Dismiss())

    def action_show_files(self) -> None:
        """Show files view."""
        self.current_view = "files"

    def action_show_code(self) -> None:
        """Show code view."""
        self.current_view = "code"

    def action_show_changes(self) -> None:
        """Show changes view."""
        self.current_view = "changes"

    def action_show_search(self) -> None:
        """Show search view."""
        self.current_view = "search"

    def action_refresh_changes(self) -> None:
        """Refresh git changes."""
        try:
            self.query_one("#git-changes", GitChangesPanel).refresh_changes()
            self.query_one("#git-status", GitStatusWidget).refresh_status()
        except Exception:
            pass

    def action_show_agent(self) -> None:
        """Show agent panel."""
        self.current_view = "agent"

    def action_show_context(self) -> None:
        """Show context panel."""
        self.current_view = "context"

    def action_show_diff(self) -> None:
        """Show diff panel."""
        self.current_view = "diff"

    def action_show_history(self) -> None:
        """Show history panel."""
        self.current_view = "history"

    # Panel access methods
    def get_agent_panel(self):
        """Get the agent panel widget."""
        try:
            from superqode.widgets.sidebar_panels import AgentPanel

            return self.query_one("#agent-panel", AgentPanel)
        except Exception:
            return None

    def get_context_panel(self):
        """Get the context panel widget."""
        try:
            from superqode.widgets.sidebar_panels import ContextPanel

            return self.query_one("#context-panel", ContextPanel)
        except Exception:
            return None

    def get_terminal_panel(self):
        """Get the terminal panel widget."""
        try:
            from superqode.widgets.sidebar_panels import TerminalPanel

            return self.query_one("#terminal-panel", TerminalPanel)
        except Exception:
            return None

    def get_diff_panel(self):
        """Get the diff panel widget."""
        try:
            from superqode.widgets.sidebar_panels import DiffPanel

            return self.query_one("#diff-panel", DiffPanel)
        except Exception:
            return None

    def get_history_panel(self):
        """Get the history panel widget."""
        try:
            from superqode.widgets.sidebar_panels import HistoryPanel

            return self.query_one("#history-panel", HistoryPanel)
        except Exception:
            return None

    @on(DirectoryTree.FileSelected)
    def on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection - show in code view."""
        event.stop()
        path = event.path
        self._current_file = path

        # Set file in preview
        preview = self.query_one("#file-preview", FilePreview)
        preview.set_file(path)

        # Switch to code view
        self.current_view = "code"

    @on(ColorfulDirectoryTree.FileOpenRequested)
    def on_file_open_requested(self, event: ColorfulDirectoryTree.FileOpenRequested) -> None:
        """Handle file open request - forward to parent."""
        event.stop()
        self.post_message(self.FileOpened(event.path))

    @on(FileSearch.FileSelected)
    def on_search_file_selected(self, event: FileSearch.FileSelected) -> None:
        """Handle file selection from search."""
        event.stop()
        path = event.path
        self._current_file = path

        # Set file in preview and switch to code view
        preview = self.query_one("#file-preview", FilePreview)
        preview.set_file(path)
        self.current_view = "code"

    @on(FileSearch.SearchClosed)
    def on_search_closed(self, event: FileSearch.SearchClosed) -> None:
        """Handle search close - hide search widget."""
        event.stop()
        self.query_one("#file-search", FileSearch).add_class("-hidden")
        if self.current_view == "files":
            self.query_one("#file-tree", ColorfulDirectoryTree).focus()

    @on(CodebaseSearch.ResultSelected)
    def on_codebase_search_result_selected(self, event: CodebaseSearch.ResultSelected) -> None:
        """Handle codebase search result selection - open file at line."""
        event.stop()
        path = event.path
        self._current_file = path

        # Set file in preview and switch to code view
        preview = self.query_one("#file-preview", FilePreview)
        preview.set_file(path)
        self.current_view = "code"

    @on(CodebaseSearch.SearchClosed)
    def on_codebase_search_closed(self, event: CodebaseSearch.SearchClosed) -> None:
        """Handle codebase search close."""
        event.stop()
        # Stay on search view but could switch to files
        pass

    @on(FilePreview.EditRequested)
    def on_edit_requested(self, event: FilePreview.EditRequested) -> None:
        """Handle edit request - open file in default editor."""
        event.stop()
        import os
        import platform

        path = event.path

        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", str(path)])
            elif system == "Windows":
                os.startfile(str(path))
            else:
                editor = os.environ.get("EDITOR", "xdg-open")
                subprocess.Popen([editor, str(path)])
        except Exception:
            editor = os.environ.get("EDITOR", "nano")
            try:
                subprocess.Popen([editor, str(path)])
            except Exception:
                pass

    @on(FilePreview.PreviewClosed)
    def on_preview_closed(self, event: FilePreview.PreviewClosed) -> None:
        """Handle preview close - switch back to files."""
        event.stop()
        self.current_view = "files"

    def refresh_tree(self) -> None:
        """Refresh the file tree."""
        tree = self.query_one("#file-tree", ColorfulDirectoryTree)
        tree.reload()

    def refresh_git_status(self) -> None:
        """Refresh git status."""
        git_widget = self.query_one("#git-status", GitStatusWidget)
        git_widget.refresh_status()

    def set_tasks(self, tasks: List[TaskItem]) -> None:
        """Update tasks (for compatibility)."""
        pass  # Plan panel removed in this version

    def focus_tree(self) -> None:
        """Focus the file tree."""
        self.current_view = "files"
        self.query_one("#file-tree", ColorfulDirectoryTree).focus()
