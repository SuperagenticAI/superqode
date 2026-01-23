"""File explorer and fuzzy search functionality for SuperQode."""

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import fnmatch
from functools import lru_cache

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
except ImportError:
    Console = None


class PathFilter:
    """Filter paths based on gitignore patterns and common ignore rules."""

    def __init__(self, patterns: List[str]):
        self.patterns = patterns

    @classmethod
    def from_git_root(cls, path: Path) -> "PathFilter":
        """Create filter from .gitignore and common ignore patterns."""
        patterns = []

        # Read .gitignore if it exists
        gitignore_path = path / ".gitignore"
        if gitignore_path.exists():
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass  # Ignore gitignore read errors

        # Add common ignore patterns
        common_patterns = [
            ".git/",
            ".git",
            "__pycache__/",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".Python",
            "build/",
            "dist/",
            "*.egg-info/",
            ".DS_Store",
            "node_modules/",
            ".env",
            ".env.local",
            ".env.*",
            "*.log",
            ".vscode/",
            ".idea/",
            ".ruff_cache/",
            "*.swp",
            "*.swo",
            "*~",
        ]

        patterns.extend(common_patterns)
        return cls(patterns)

    def match(self, path: Path) -> bool:
        """Check if path matches any ignore pattern."""
        path_str = str(path)

        # Normalize path separators
        path_str = path_str.replace(os.sep, "/")

        # Check if path matches any pattern
        for pattern in self.patterns:
            if self._matches_pattern(path_str, pattern):
                return True

        # Also check the path name only (for files in current directory)
        path_name = path.name
        for pattern in self.patterns:
            if self._matches_pattern(path_name, pattern):
                return True

        return False

    def _matches_pattern(self, path_str: str, pattern: str) -> bool:
        """Check if path matches a single pattern."""
        # Normalize pattern separators
        pattern = pattern.replace(os.sep, "/")

        # Handle directory patterns (ending with /)
        if pattern.endswith("/"):
            pattern = pattern[:-1]
            # Match directory or any file/directory inside it
            return path_str == pattern or path_str.startswith(pattern + "/") or path_str == pattern

        # Handle wildcards
        return fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path_str, pattern + "/*")


class CodeExplorer:
    """Simple file explorer for SuperQode CLI."""

    def __init__(self, root_path: Optional[Path] = None):
        self.root_path = root_path or Path.cwd()
        self.path_filter = PathFilter.from_git_root(self.root_path)
        self.console = Console()

    def explore_directory(self, path: Optional[Path] = None, max_depth: int = 3) -> str:
        """Generate a text-based directory tree."""
        explore_path = path or self.root_path

        if not explore_path.exists():
            return f"Path does not exist: {explore_path}"

        if not explore_path.is_dir():
            return f"Not a directory: {explore_path}"

        tree_lines = []
        tree_lines.append(f"📁 {explore_path.name}/")
        tree_lines.extend(self._build_tree(explore_path, max_depth=max_depth, prefix=""))

        return "\n".join(tree_lines)

    def _build_tree(
        self, path: Path, max_depth: int = 3, prefix: str = "", current_depth: int = 0
    ) -> List[str]:
        """Recursively build directory tree."""
        if current_depth >= max_depth:
            return []

        lines = []
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            filtered_items = []

            for item in items:
                # Filter out items that match ignore patterns
                try:
                    rel_path = item.relative_to(self.root_path)
                    if not self.path_filter.match(rel_path) and not self.path_filter.match(item):
                        filtered_items.append(item)
                except ValueError:
                    # Item is not relative to root, check directly
                    if not self.path_filter.match(item):
                        filtered_items.append(item)

            for i, item in enumerate(filtered_items):
                is_last = i == len(filtered_items) - 1
                connector = "└── " if is_last else "├── "

                # Add emoji based on type
                if item.is_dir():
                    icon = "📁"
                elif item.suffix.lower() in [".py", ".js", ".ts", ".java", ".cpp", ".c", ".h"]:
                    icon = "📄"
                elif item.suffix.lower() in [".md", ".txt", ".rst"]:
                    icon = "📝"
                elif item.suffix.lower() in [".json", ".yaml", ".yml", ".toml"]:
                    icon = "⚙️"
                elif item.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".svg"]:
                    icon = "🖼️"
                else:
                    icon = "📄"

                lines.append(f"{prefix}{connector}{icon} {item.name}")

                if item.is_dir() and current_depth < max_depth - 1:
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    lines.extend(self._build_tree(item, max_depth, next_prefix, current_depth + 1))

        except PermissionError:
            lines.append(f"{prefix}└── 🔒 Permission denied")

        return lines


class FuzzySearch:
    """Fuzzy search implementation for finding files and content."""

    def __init__(self, case_sensitive: bool = False, cache_size: int = 1024):
        self.case_sensitive = case_sensitive
        self.cache = {}
        self.cache_size = cache_size

    def match(self, query: str, candidate: str) -> Tuple[float, List[int]]:
        """Match query against candidate with scoring.

        Returns:
            Tuple of (score, list of matching positions)
            Score of 0 means no match
        """
        cache_key = (query, candidate)
        if cache_key in self.cache:
            return self.cache[cache_key]

        if not query:
            return 0.0, []

        # Normalize case
        if not self.case_sensitive:
            candidate = candidate.lower()
            query = query.lower()

        score, positions = self._calculate_match(query, candidate)
        result = (score, positions)

        # Simple LRU-style cache
        if len(self.cache) >= self.cache_size:
            # Remove a random item (simple cache eviction)
            self.cache.pop(next(iter(self.cache)))
        self.cache[cache_key] = result

        return result

    def _calculate_match(self, query: str, candidate: str) -> Tuple[float, List[int]]:
        """Calculate fuzzy match score and positions."""
        if not query or not candidate:
            return 0.0, []

        # Find all positions where query characters appear in order
        positions = []
        query_idx = 0
        candidate_idx = 0

        while query_idx < len(query) and candidate_idx < len(candidate):
            if query[query_idx] == candidate[candidate_idx]:
                positions.append(candidate_idx)
                query_idx += 1
            candidate_idx += 1

        # Must match all characters in query
        if query_idx < len(query):
            return 0.0, []

        # Calculate score based on match quality
        if not positions:
            return 0.0, []

        score = len(positions)  # Base score from number of matches

        # Bonus for consecutive matches
        consecutive_bonus = 0
        for i in range(1, len(positions)):
            if positions[i] == positions[i - 1] + 1:
                consecutive_bonus += 2
        score += consecutive_bonus

        # Bonus for matches at word boundaries
        word_boundary_bonus = 0
        for pos in positions:
            if pos == 0 or not candidate[pos - 1].isalnum():
                word_boundary_bonus += 3
        score += word_boundary_bonus

        # Penalty for gaps between matches
        gap_penalty = 0
        for i in range(1, len(positions)):
            gap = positions[i] - positions[i - 1] - 1
            gap_penalty += gap * 0.1
        score -= gap_penalty

        return max(0, score), positions

    @classmethod
    @lru_cache(maxsize=1024)
    def get_word_starts(cls, candidate: str) -> List[int]:
        """Get positions of word starts for better scoring."""
        positions = [0]  # Start of string
        for i, char in enumerate(candidate):
            if i > 0 and not candidate[i - 1].isalnum() and char.isalnum():
                positions.append(i)
        return positions


class FuzzyFileSearch:
    """Fuzzy search specifically for files."""

    def __init__(self, root_path: Optional[Path] = None):
        self.root_path = root_path or Path.cwd()
        self.path_filter = PathFilter.from_git_root(self.root_path)
        self.fuzzy_search = FuzzySearch()
        self._file_cache = None
        self._cache_timestamp = 0

    def search_files(self, query: str, max_results: int = 20) -> List[Tuple[Path, str, float]]:
        """Search for files using fuzzy matching.

        Returns:
            List of (file_path, relative_path, score) tuples
        """
        if not query.strip():
            return []

        # Get all project files
        files = self._get_project_files()

        results = []
        for file_path in files:
            try:
                # Use relative path for searching
                rel_path = file_path.relative_to(self.root_path)
                rel_str = str(rel_path)

                # Search in filename and full path
                score1, _ = self.fuzzy_search.match(query, rel_path.name)
                score2, _ = self.fuzzy_search.match(query, rel_str)

                # Use the better score
                score = max(score1, score2)
                if score > 0:
                    results.append((file_path, str(rel_path), score))

            except ValueError:
                # File not relative to root
                continue

        # Sort by score (highest first)
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:max_results]

    def _get_project_files(self) -> List[Path]:
        """Get all files in project, respecting gitignore."""
        import time

        # Simple caching to avoid rescanning on every search
        now = time.time()
        if self._file_cache is not None and now - self._cache_timestamp < 30:  # 30 second cache
            return self._file_cache

        files = []
        try:
            for root, dirs, files_in_dir in os.walk(self.root_path):
                # Filter directories
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in [".git"] and not self.path_filter.match(Path(root) / d)
                ]

                for file in files_in_dir:
                    file_path = Path(root) / file
                    if not self.path_filter.match(file_path):
                        files.append(file_path)

        except Exception:
            # Fallback to current directory only
            try:
                files = [
                    f
                    for f in self.root_path.iterdir()
                    if f.is_file() and not self.path_filter.match(f)
                ]
            except Exception:
                files = []

        self._file_cache = files
        self._cache_timestamp = now
        return files


def fuzzy_find_files(query: str, max_results: int = 20) -> List[Tuple[Path, str, float]]:
    """Convenience function for fuzzy file search."""
    searcher = FuzzyFileSearch()
    return searcher.search_files(query, max_results)


def show_fuzzy_search_results(query: str, results: List[Tuple[Path, str, float]]):
    """Display fuzzy search results in a nice format with git status."""
    if not results:
        console = Console()
        console.print(f"[yellow]No files found matching '{query}'[/yellow]")
        return

    console = Console()
    console.print(f"\n[bold green]🔍 Found {len(results)} files matching '{query}':[/bold green]\n")

    # Initialize git status tracker
    git_tracker = GitStatusTracker(Path.cwd())

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Path", style="white")
    table.add_column("Status", style="magenta", width=6)
    table.add_column("Score", style="green", justify="right")

    for file_path, rel_path, score in results:
        # Add file type emoji
        if file_path.suffix.lower() in [".py", ".js", ".ts", ".java", ".cpp", ".c", ".h"]:
            icon = "📄"
        elif file_path.suffix.lower() in [".md", ".txt", ".rst"]:
            icon = "📝"
        elif file_path.suffix.lower() in [".json", ".yaml", ".yml", ".toml"]:
            icon = "⚙️"
        elif file_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".svg"]:
            icon = "🖼️"
        else:
            icon = "📄"

        # Get git status
        git_status = git_tracker.get_status_emoji(file_path)
        if not git_status:
            git_status = "✅"  # Clean

        table.add_row(f"{icon} {file_path.name}", rel_path, git_status, f"{score:.1f}")

    console.print(table)
    console.print(f"\n[dim]💡 Use ':open <path>' to open a file[/dim]")
    console.print(f"[dim]🔴 Modified  🟢 Added  🟡 Untracked  🔵 Staged  ✅ Clean[/dim]")


class GitStatusTracker:
    """Track git status for files in a repository."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.status_cache = {}
        self.last_update = 0
        self.cache_duration = 10  # seconds

    def get_status(self, file_path: Path) -> str:
        """Get git status for a file."""
        import time
        import subprocess

        # Check if cache is fresh
        now = time.time()
        if now - self.last_update > self.cache_duration:
            self._update_status()

        # Get relative path for lookup
        try:
            rel_path = file_path.relative_to(self.repo_path)
            return self.status_cache.get(str(rel_path), "")
        except ValueError:
            return ""

    def _update_status(self) -> None:
        """Update git status cache."""
        import time
        import subprocess

        self.status_cache = {}
        self.last_update = time.time()

        try:
            # Run git status --porcelain for efficient status
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.strip():
                        status = line[:2].strip()
                        file_path = line[3:].strip()

                        # Map git status to our status indicators
                        if status.startswith("M") or status.endswith("M"):
                            self.status_cache[file_path] = "modified"
                        elif status.startswith("A") or status == "A":
                            self.status_cache[file_path] = "added"
                        elif status.startswith("D") or status.endswith("D"):
                            self.status_cache[file_path] = "deleted"
                        elif status == "??":
                            self.status_cache[file_path] = "untracked"
                        elif status.startswith("R"):
                            self.status_cache[file_path] = "renamed"

        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            # Git not available or not a git repo
            pass

    def get_status_emoji(self, file_path: Path) -> str:
        """Get status emoji for display."""
        status = self.get_status(file_path)
        return {
            "modified": "🔴",
            "added": "🟢",
            "deleted": "🔴",
            "untracked": "🟡",
            "renamed": "🔵",
            "staged": "🔵",
        }.get(status, "")


class RecentFiles:
    """Track recently accessed files."""

    def __init__(self, max_files: int = 20):
        self.max_files = max_files
        self.recent_files = []
        self._load_from_disk()

    def add_file(self, file_path: Path) -> None:
        """Add a file to recent files list."""
        file_str = str(file_path.resolve())

        # Remove if already exists
        if file_str in self.recent_files:
            self.recent_files.remove(file_str)

        # Add to beginning
        self.recent_files.insert(0, file_str)

        # Trim to max size
        self.recent_files = self.recent_files[: self.max_files]

        # Save to disk
        self._save_to_disk()

    def get_recent_files(self, limit: int = 10) -> List[Path]:
        """Get list of recent files."""
        return [Path(f) for f in self.recent_files[:limit] if Path(f).exists()]

    def _load_from_disk(self) -> None:
        """Load recent files from disk."""
        try:
            import json

            config_dir = Path.home() / ".superqode"
            config_dir.mkdir(exist_ok=True)
            recent_file = config_dir / "recent_files.json"

            if recent_file.exists():
                with open(recent_file, "r") as f:
                    data = json.load(f)
                    self.recent_files = data.get("files", [])
        except Exception:
            self.recent_files = []

    def _save_to_disk(self) -> None:
        """Save recent files to disk."""
        try:
            import json

            config_dir = Path.home() / ".superqode"
            config_dir.mkdir(exist_ok=True)
            recent_file = config_dir / "recent_files.json"

            with open(recent_file, "w") as f:
                json.dump({"files": self.recent_files}, f, indent=2)
        except Exception:
            pass


class Bookmarks:
    """Manage bookmarked files."""

    def __init__(self):
        self.bookmarks = {}
        self._load_from_disk()

    def add_bookmark(self, file_path: Path, name: str = None) -> bool:
        """Add a file to bookmarks."""
        if not file_path.exists():
            return False

        if name is None:
            name = file_path.name

        self.bookmarks[name] = str(file_path.resolve())
        self._save_to_disk()
        return True

    def remove_bookmark(self, name: str) -> bool:
        """Remove a bookmark."""
        if name in self.bookmarks:
            del self.bookmarks[name]
            self._save_to_disk()
            return True
        return False

    def get_bookmarks(self):
        """Get all bookmarks as Path objects."""
        result = {}
        for name, path_str in self.bookmarks.items():
            path = Path(path_str)
            if path.exists():
                result[name] = path
        return result

    def get_bookmark(self, name: str) -> Optional[Path]:
        """Get a specific bookmark."""
        path_str = self.bookmarks.get(name)
        if path_str:
            path = Path(path_str)
            return path if path.exists() else None
        return None

    def _load_from_disk(self) -> None:
        """Load bookmarks from disk."""
        try:
            import json

            config_dir = Path.home() / ".superqode"
            config_dir.mkdir(exist_ok=True)
            bookmark_file = config_dir / "bookmarks.json"

            if bookmark_file.exists():
                with open(bookmark_file, "r") as f:
                    self.bookmarks = json.load(f)
        except Exception:
            self.bookmarks = {}

    def _save_to_disk(self) -> None:
        """Save bookmarks to disk."""
        try:
            import json

            config_dir = Path.home() / ".superqode"
            config_dir.mkdir(exist_ok=True)
            bookmark_file = config_dir / "bookmarks.json"

            with open(bookmark_file, "w") as f:
                json.dump(self.bookmarks, f, indent=2)
        except Exception:
            pass


def show_file_content(file_path: Path) -> None:
    """Launch interactive file explorer."""
    if not self.console:
        print("Rich library not available for interactive explorer")
        return

    current_path = self.root_path

    while True:
        # Clear screen and show current directory
        self.console.clear()

        # Show current path
        self.console.print(f"\n[bold blue]📁 File Explorer[/bold blue]")
        self.console.print(f"[dim]Current: {current_path}[/dim]\n")

        # Show directory tree
        tree = self.explore_directory(current_path, max_depth=2)
        self.console.print(tree)

        # Show options
        self.console.print("\n[bold cyan]Options:[/bold cyan]")
        self.console.print("  [1] Open file/directory")
        self.console.print("  [2] Search files")
        self.console.print("  [3] Go up (..)")
        self.console.print("  [4] Go to root")
        self.console.print("  [q] Quit")

        choice = Prompt.ask("\nChoose option", choices=["1", "2", "3", "4", "q"], default="q")

        if choice == "q":
            break
        elif choice == "1":
            name = Prompt.ask("Enter file/directory name")
            target = current_path / name
            if target.exists():
                if target.is_dir():
                    current_path = target
                else:
                    # Open file (for now just show path)
                    self.console.print(f"[green]Selected file: {target}[/green]")
                    input("Press Enter to continue...")
            else:
                self.console.print(f"[red]Not found: {target}[/red]")
                input("Press Enter to continue...")
        elif choice == "2":
            query = Prompt.ask("Search query")
            results = self.find_files(query, max_results=10)
            if results:
                self.console.print(f"\n[bold green]Found {len(results)} files:[/bold green]")
                for i, (path, rel_path) in enumerate(results, 1):
                    self.console.print(f"  {i}. {rel_path}")
            else:
                self.console.print("[yellow]No files found[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "3":
            if current_path != self.root_path:
                current_path = current_path.parent
        elif choice == "4":
            current_path = self.root_path


def show_file_explorer():
    """Show file explorer interface."""
    console = Console()

    try:
        explorer = CodeExplorer()
        tree = explorer.explore_directory(max_depth=3)

        panel = Panel.fit(
            tree,
            title="[bold blue]📁 Project Files[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )

        console.print(panel)
        console.print("\n[dim]Use ':files interactive' for full explorer[/dim]")

    except Exception as e:
        console.print(f"[red]Error opening file explorer: {e}[/red]")


def show_file_content(file_path: Path, preview_only: bool = False) -> None:
    """Show file content or open in editor with syntax highlighting."""
    console = Console()

    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    if file_path.is_dir():
        console.print(f"[yellow]Cannot open directory: {file_path}[/yellow]")
        console.print(f"[dim]Use ':files interactive' to browse directories[/dim]")
        return

    # Add to recent files
    recent = RecentFiles()
    recent.add_file(file_path)

    try:
        # Try to open in editor first (unless preview_only is True)
        if not preview_only:
            import subprocess
            import shutil

            editors = ["code", "cursor", "subl", "vim", "nano"]
            editor = None

            for ed in editors:
                if shutil.which(ed):
                    editor = ed
                    break

            if editor:
                console.print(f"[green]Opening {file_path} in {editor}...[/green]")
                subprocess.run([editor, str(file_path)], check=False)
                return

        # Fall back to showing content with syntax highlighting
        console.print(f"[bold cyan]📄 {file_path.name}[/bold cyan]")
        console.print(f"[dim]{file_path}[/dim]")
        console.print()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Syntax highlighting using pygments
            try:
                from pygments import highlight
                from pygments.lexers import get_lexer_for_filename, TextLexer
                from pygments.formatters import TerminalFormatter

                try:
                    lexer = get_lexer_for_filename(file_path.name)
                except Exception:
                    lexer = TextLexer()

                formatter = TerminalFormatter()
                highlighted = highlight(content, lexer, formatter)

                # Truncate if too long
                if len(content) > 2000:
                    lines = highlighted.split("\n")
                    truncated = "\n".join(lines[:50])  # Show first 50 lines
                    console.print(truncated)
                    console.print(
                        f"[dim]... ({len(lines) - 50} more lines, {len(content)} total chars)[/dim]"
                    )
                else:
                    console.print(highlighted)

            except ImportError:
                # Fallback without syntax highlighting
                if len(content) > 1000:
                    console.print(content[:1000] + "\n[dim]... (truncated)[/dim]")
                else:
                    console.print(content)

        except UnicodeDecodeError:
            console.print("[dim][Binary file - cannot display content][/dim]")
        except Exception as e:
            console.print(f"[red]Error reading file: {e}[/red]")

    except Exception as e:
        console.print(f"[red]Error opening file: {e}[/red]")


def interactive_file_explorer():
    """Launch full interactive file explorer."""
    console = Console()

    try:
        explorer = CodeExplorer()
        explorer.interactive_explorer()
    except KeyboardInterrupt:
        console.print("\n[green]File explorer closed.[/green]")
    except Exception as e:
        console.print(f"[red]Error in file explorer: {e}[/red]")
