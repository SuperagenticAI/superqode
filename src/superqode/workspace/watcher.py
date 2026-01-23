"""
Directory Watcher - Real-time File Change Detection.

Uses watchdog for efficient file system monitoring.
Tracks file changes in real-time for:
- Live diff updates in TUI
- Automatic snapshot triggers
- Change notifications to agents
- Optimized for SuperQode's QE workflow
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from weakref import WeakSet

try:
    from watchdog.observers import Observer
    from watchdog.events import (
        FileSystemEventHandler,
        FileCreatedEvent,
        FileModifiedEvent,
        FileDeletedEvent,
        FileMovedEvent,
        DirCreatedEvent,
        DirDeletedEvent,
        DirMovedEvent,
    )

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object


class ChangeType(Enum):
    """Type of file system change."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class FileChange:
    """Represents a file system change event."""

    path: Path
    change_type: ChangeType
    timestamp: datetime = field(default_factory=datetime.now)
    is_directory: bool = False
    old_path: Optional[Path] = None  # For moves/renames

    @property
    def relative_path(self) -> str:
        """Get path as string."""
        return str(self.path)


@dataclass
class WatcherConfig:
    """Configuration for the directory watcher."""

    # Patterns to ignore (glob format)
    ignore_patterns: List[str] = field(
        default_factory=lambda: [
            "*.pyc",
            "__pycache__",
            ".git",
            ".git/*",
            "node_modules",
            "node_modules/*",
            ".superqode",
            ".superqode/*",
            "*.swp",
            "*.swo",
            "*~",
            ".DS_Store",
            "Thumbs.db",
            "*.log",
            "*.tmp",
        ]
    )

    # File extensions to watch (empty = all)
    watch_extensions: List[str] = field(default_factory=list)

    # Debounce interval (seconds) - combine rapid changes
    debounce_interval: float = 0.5

    # Maximum events to buffer
    max_buffer_size: int = 1000

    # Watch subdirectories
    recursive: bool = True


# Type alias for change callbacks
ChangeCallback = Callable[[FileChange], None]
# Async callbacks should be standard async callables taking a FileChange
AsyncChangeCallback = Callable[
    [FileChange], "asyncio.Future | asyncio.Task | asyncio.coroutines.CoroutineType"
]


class _WatchdogHandler(FileSystemEventHandler):
    """Internal handler for watchdog events."""

    def __init__(self, watcher: "DirectoryWatcher"):
        super().__init__()
        self.watcher = watcher

    def _should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        for pattern in self.watcher.config.ignore_patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        return False

    def _should_watch_extension(self, path: str) -> bool:
        """Check if file extension should be watched."""
        if not self.watcher.config.watch_extensions:
            return True

        _, ext = os.path.splitext(path)
        return ext.lower() in self.watcher.config.watch_extensions

    def _process_event(
        self, path: str, change_type: ChangeType, is_dir: bool = False, old_path: str = None
    ):
        """Process a file system event."""
        if self._should_ignore(path):
            return

        if not is_dir and not self._should_watch_extension(path):
            return

        change = FileChange(
            path=Path(path),
            change_type=change_type,
            is_directory=is_dir,
            old_path=Path(old_path) if old_path else None,
        )

        self.watcher._handle_change(change)

    def on_created(self, event):
        is_dir = isinstance(event, DirCreatedEvent)
        self._process_event(event.src_path, ChangeType.CREATED, is_dir)

    def on_modified(self, event):
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent, DirDeletedEvent)):
            return  # Ignore directory modifications
        self._process_event(event.src_path, ChangeType.MODIFIED)

    def on_deleted(self, event):
        is_dir = isinstance(event, DirDeletedEvent)
        self._process_event(event.src_path, ChangeType.DELETED, is_dir)

    def on_moved(self, event):
        is_dir = isinstance(event, DirMovedEvent)
        self._process_event(event.dest_path, ChangeType.MOVED, is_dir, event.src_path)


class DirectoryWatcher:
    """
    Real-time directory watcher using watchdog.

    Monitors a directory for file changes and notifies registered callbacks.
    Includes debouncing to handle rapid successive changes.

    Usage:
        watcher = DirectoryWatcher(project_root)

        @watcher.on_change
        def handle_change(change: FileChange):
            print(f"{change.change_type}: {change.path}")

        watcher.start()
        # ... files are monitored ...
        watcher.stop()

    Async usage:
        async def watch_files():
            async for change in watcher.async_changes():
                print(f"{change.change_type}: {change.path}")
    """

    def __init__(
        self,
        root_path: Path,
        config: Optional[WatcherConfig] = None,
    ):
        if not WATCHDOG_AVAILABLE:
            raise ImportError(
                "watchdog is required for directory watching. Install with: pip install watchdog"
            )

        self.root_path = Path(root_path).resolve()
        self.config = config or WatcherConfig()

        # State
        self._observer: Optional[Observer] = None
        self._running = False
        self._callbacks: Set[ChangeCallback] = set()
        self._async_callbacks: Set[AsyncChangeCallback] = set()

        # Debouncing
        self._pending_changes: Dict[str, FileChange] = {}
        self._debounce_timer: Optional[threading.Timer] = None
        self._debounce_lock = threading.Lock()

        # Async event queue
        self._async_queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Change buffer (for polling mode)
        self._change_buffer: List[FileChange] = []
        self._buffer_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    def on_change(self, callback: ChangeCallback) -> ChangeCallback:
        """Decorator to register a change callback."""
        self._callbacks.add(callback)
        return callback

    def on_change_async(self, callback: AsyncChangeCallback) -> AsyncChangeCallback:
        """Decorator to register an async change callback."""
        self._async_callbacks.add(callback)
        return callback

    def remove_callback(self, callback: ChangeCallback) -> None:
        """Remove a registered callback."""
        self._callbacks.discard(callback)
        self._async_callbacks.discard(callback)

    def _handle_change(self, change: FileChange) -> None:
        """Handle a change event (with debouncing)."""
        path_key = str(change.path)

        with self._debounce_lock:
            # Update or add the pending change
            existing = self._pending_changes.get(path_key)

            if existing:
                # Merge changes (e.g., create + modify = create)
                if (
                    existing.change_type == ChangeType.CREATED
                    and change.change_type == ChangeType.MODIFIED
                ):
                    change = existing  # Keep as created
                elif (
                    existing.change_type == ChangeType.CREATED
                    and change.change_type == ChangeType.DELETED
                ):
                    # Created then deleted = no change
                    del self._pending_changes[path_key]
                    return

            self._pending_changes[path_key] = change

            # Reset debounce timer
            if self._debounce_timer:
                self._debounce_timer.cancel()

            self._debounce_timer = threading.Timer(
                self.config.debounce_interval,
                self._flush_changes,
            )
            self._debounce_timer.start()

    def _flush_changes(self) -> None:
        """Flush pending changes to callbacks."""
        with self._debounce_lock:
            changes = list(self._pending_changes.values())
            self._pending_changes.clear()

        for change in changes:
            self._dispatch_change(change)

    def _dispatch_change(self, change: FileChange) -> None:
        """Dispatch a change to all callbacks."""
        # Add to buffer
        with self._buffer_lock:
            self._change_buffer.append(change)
            # Limit buffer size
            if len(self._change_buffer) > self.config.max_buffer_size:
                self._change_buffer = self._change_buffer[-self.config.max_buffer_size :]

        # Sync callbacks
        for callback in self._callbacks:
            try:
                callback(change)
            except Exception:
                pass  # Don't let one callback break others

        # Async queue
        if self._async_queue and self._loop:
            try:
                self._loop.call_soon_threadsafe(
                    self._async_queue.put_nowait,
                    change,
                )
            except Exception:
                pass

        # Async callbacks
        for callback in self._async_callbacks:
            if self._loop:
                try:
                    asyncio.run_coroutine_threadsafe(callback(change), self._loop)
                except Exception:
                    pass

    def start(self) -> None:
        """Start watching the directory."""
        if self._running:
            return

        self._observer = Observer()
        handler = _WatchdogHandler(self)

        self._observer.schedule(
            handler,
            str(self.root_path),
            recursive=self.config.recursive,
        )

        self._observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop watching the directory."""
        if not self._running:
            return

        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._flush_changes()  # Flush any pending changes

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        self._running = False

    def get_recent_changes(self, count: int = 100) -> List[FileChange]:
        """Get recent changes from the buffer."""
        with self._buffer_lock:
            return self._change_buffer[-count:]

    def clear_buffer(self) -> None:
        """Clear the change buffer."""
        with self._buffer_lock:
            self._change_buffer.clear()

    async def async_changes(self) -> asyncio.AsyncIterator[FileChange]:
        """Async iterator for file changes.

        Usage:
            async for change in watcher.async_changes():
                handle_change(change)
        """
        self._loop = asyncio.get_event_loop()
        self._async_queue = asyncio.Queue()

        try:
            while self._running:
                try:
                    change = await asyncio.wait_for(
                        self._async_queue.get(),
                        timeout=1.0,
                    )
                    yield change
                except asyncio.TimeoutError:
                    continue
        finally:
            self._async_queue = None
            self._loop = None

    def __enter__(self) -> "DirectoryWatcher":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


class PollingWatcher:
    """
    Fallback directory watcher using polling.

    Used when watchdog is not available. Less efficient but works everywhere.
    """

    def __init__(
        self,
        root_path: Path,
        poll_interval: float = 1.0,
        config: Optional[WatcherConfig] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.poll_interval = poll_interval
        self.config = config or WatcherConfig()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._file_mtimes: Dict[str, float] = {}
        self._callbacks: Set[ChangeCallback] = set()

    def on_change(self, callback: ChangeCallback) -> ChangeCallback:
        """Register a change callback."""
        self._callbacks.add(callback)
        return callback

    def _should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        for pattern in self.config.ignore_patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        return False

    def _scan_directory(self) -> Dict[str, float]:
        """Scan directory and get file modification times."""
        mtimes = {}

        for root, dirs, files in os.walk(self.root_path):
            # Filter ignored directories
            dirs[:] = [d for d in dirs if not self._should_ignore(d)]

            for file in files:
                file_path = os.path.join(root, file)
                if self._should_ignore(file_path):
                    continue

                try:
                    mtimes[file_path] = os.path.getmtime(file_path)
                except OSError:
                    continue

        return mtimes

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            current_mtimes = self._scan_directory()

            # Check for changes
            current_files = set(current_mtimes.keys())
            previous_files = set(self._file_mtimes.keys())

            # New files
            for path in current_files - previous_files:
                change = FileChange(path=Path(path), change_type=ChangeType.CREATED)
                for callback in self._callbacks:
                    try:
                        callback(change)
                    except Exception:
                        pass

            # Deleted files
            for path in previous_files - current_files:
                change = FileChange(path=Path(path), change_type=ChangeType.DELETED)
                for callback in self._callbacks:
                    try:
                        callback(change)
                    except Exception:
                        pass

            # Modified files
            for path in current_files & previous_files:
                if current_mtimes[path] != self._file_mtimes[path]:
                    change = FileChange(path=Path(path), change_type=ChangeType.MODIFIED)
                    for callback in self._callbacks:
                        try:
                            callback(change)
                        except Exception:
                            pass

            self._file_mtimes = current_mtimes
            time.sleep(self.poll_interval)

    def start(self) -> None:
        """Start polling."""
        if self._running:
            return

        self._file_mtimes = self._scan_directory()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None


def create_watcher(
    root_path: Path,
    config: Optional[WatcherConfig] = None,
    use_polling: bool = False,
) -> DirectoryWatcher | PollingWatcher:
    """Create the appropriate watcher for the platform.

    Args:
        root_path: Directory to watch
        config: Watcher configuration
        use_polling: Force polling mode (default: auto-detect)

    Returns:
        DirectoryWatcher or PollingWatcher
    """
    if use_polling or not WATCHDOG_AVAILABLE:
        return PollingWatcher(root_path, config=config)

    return DirectoryWatcher(root_path, config)
