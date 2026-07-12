"""File view/info and in-file/directory search."""

from __future__ import annotations
from pathlib import Path
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.atomic import atomic_read
from superqode.file_viewer import (
    get_file_info,
)


class HelperFileViewMixin:
    """File view/info and in-file/directory search."""

    def _find_files(self, query: str, log: ConversationLog):
        if not query:
            log.add_info("Usage: :find <query>")
            return

        try:
            from superqode.file_explorer import fuzzy_find_files

            results = fuzzy_find_files(query, max_results=10)

            if results:
                t = Text()
                t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
                t.append(f"Results for '{query}'\n\n", style=f"bold {THEME['cyan']}")

                for item in results:
                    path = item[0] if isinstance(item, tuple) else item
                    t.append(f"  📄 {path.name}", style=THEME["text"])
                    t.append(f"  {path.parent}\n", style=THEME["muted"])

                log.write(t)
            else:
                log.add_info(f"No files matching '{query}'")
        except Exception as e:
            log.add_error(str(e))
    def _view_file(self, file_path: str, log: ConversationLog):
        """View file content with syntax highlighting."""
        from rich.syntax import Syntax

        try:
            info = get_file_info(file_path)

            # Header
            t = Text()
            t.append(f"\n  📄 ", style=f"bold {THEME['cyan']}")
            t.append(info.name, style=f"bold {THEME['cyan']}")
            t.append(f"  [{info.language}]", style=f"bold {THEME['purple']}")
            t.append(f"  {info.lines} lines\n", style=THEME["muted"])
            log.write(t)

            if info.is_binary:
                log.add_info("Binary file - cannot display content")
                return

            # Read and display content
            content = atomic_read(file_path)
            lines = content.splitlines()

            # Show first 50 lines
            preview_lines = lines[:50]
            preview_content = "\n".join(preview_lines)

            syntax = Syntax(
                preview_content,
                info.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                background_color="#000000",
            )

            log.write(Panel(syntax, border_style=THEME["border"], box=ROUNDED, padding=(0, 1)))

            if len(lines) > 50:
                log.add_info(f"Showing first 50 of {len(lines)} lines")

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error viewing file: {e}")
    def _view_file_info(self, file_path: str, log: ConversationLog):
        """View file information without content."""
        try:
            info = get_file_info(file_path)

            t = Text()
            t.append(f"\n  📄 ", style=f"bold {THEME['cyan']}")
            t.append("File Info\n\n", style=f"bold {THEME['cyan']}")

            t.append(f"  Name:     ", style=THEME["muted"])
            t.append(f"{info.name}\n", style=THEME["text"])

            t.append(f"  Path:     ", style=THEME["muted"])
            t.append(f"{info.path}\n", style=THEME["text"])

            t.append(f"  Language: ", style=THEME["muted"])
            t.append(f"{info.language}\n", style=f"bold {THEME['purple']}")

            t.append(f"  Size:     ", style=THEME["muted"])
            # Format size
            size = info.size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            t.append(f"{size_str}\n", style=THEME["text"])

            t.append(f"  Lines:    ", style=THEME["muted"])
            t.append(f"{info.lines}\n", style=THEME["text"])

            t.append(f"  Binary:   ", style=THEME["muted"])
            t.append(f"{'Yes' if info.is_binary else 'No'}\n", style=THEME["text"])

            log.write(t)

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error: {e}")
    def _search_in_file(self, term: str, file_path: str, log: ConversationLog):
        """Search for a term in a specific file."""
        try:
            content = atomic_read(file_path)
            lines = content.splitlines()

            results = []
            for i, line in enumerate(lines, 1):
                if term.lower() in line.lower():
                    results.append((i, line.strip()))

            if not results:
                log.add_info(f"No matches for '{term}' in {file_path}")
                return

            t = Text()
            t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
            t.append(
                f"{len(results)} match(es) for '{term}' in {file_path}\n\n",
                style=f"bold {THEME['cyan']}",
            )

            for line_no, content in results[:15]:
                t.append(f"  {line_no:>4}: ", style=THEME["muted"])

                # Highlight the search term
                content_lower = content.lower()
                term_lower = term.lower()

                if term_lower in content_lower:
                    idx = content_lower.index(term_lower)
                    t.append(content[:idx], style=THEME["text"])
                    t.append(
                        content[idx : idx + len(term)],
                        style=f"bold {THEME['warning']} on #f59e0b30",
                    )
                    t.append(content[idx + len(term) :], style=THEME["text"])
                else:
                    t.append(content, style=THEME["text"])
                t.append("\n", style="")

            if len(results) > 15:
                t.append(f"\n  ... and {len(results) - 15} more matches\n", style=THEME["muted"])

            log.write(t)

        except FileNotFoundError:
            log.add_error(f"File not found: {file_path}")
        except Exception as e:
            log.add_error(f"Error: {e}")
    def _search_in_directory(self, term: str, log: ConversationLog):
        """Search for a term in all files in current directory."""
        import os

        results = []
        cwd = Path.cwd()

        # Search in common code files
        extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".xml",
            ".html",
            ".css",
            ".scss",
            ".sql",
            ".sh",
            ".bash",
        }

        for root, dirs, files in os.walk(cwd):
            # Skip hidden and common ignore directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "venv", "__pycache__", "dist", "build", ".git"}
            ]

            for file in files:
                if Path(file).suffix.lower() in extensions:
                    file_path = Path(root) / file
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(content.splitlines(), 1):
                            if term.lower() in line.lower():
                                rel_path = file_path.relative_to(cwd)
                                results.append((str(rel_path), i, line.strip()))
                                if len(results) >= 50:
                                    break
                    except Exception:
                        continue

                    if len(results) >= 50:
                        break

            if len(results) >= 50:
                break

        if not results:
            log.add_info(f"No matches for '{term}' in current directory")
            return

        t = Text()
        t.append(f"\n  🔍 ", style=f"bold {THEME['cyan']}")
        t.append(f"{len(results)} match(es) for '{term}'\n\n", style=f"bold {THEME['cyan']}")

        current_file = None
        for file_path, line_no, content in results[:30]:
            if file_path != current_file:
                current_file = file_path
                t.append(f"\n  📄 {file_path}\n", style=f"bold {THEME['purple']}")

            t.append(f"    {line_no:>4}: ", style=THEME["muted"])

            # Truncate long lines
            if len(content) > 60:
                content = content[:57] + "..."

            t.append(f"{content}\n", style=THEME["text"])

        if len(results) > 30:
            t.append(f"\n  ... and {len(results) - 30} more matches\n", style=THEME["muted"])

        log.write(t)
