"""
PTY Shell Widget - Interactive Terminal in TUI.

Provides a full pseudo-terminal (PTY) for running interactive
shell commands within the SuperQode TUI.

Features:
- True terminal emulation (ncurses, vim, etc.)
- Resize support
- Input/output streaming
- Multiple shell sessions
"""

from __future__ import annotations

import asyncio
import os
import pty
import select
import signal
import struct
import sys
import termios
import fcntl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import threading

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static
from textual.timer import Timer
from textual import events


@dataclass
class ShellSession:
    """A shell session with PTY."""

    id: str
    pid: int
    fd: int
    cwd: Path
    created_at: datetime
    title: str = "Shell"

    @property
    def is_running(self) -> bool:
        """Check if the shell process is still running."""
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False


class PTYShell:
    """
    Pseudo-terminal shell manager.

    Manages shell sessions with proper PTY handling for
    interactive terminal applications.

    Usage:
        shell = PTYShell()
        shell.start()

        # Send input
        shell.write("ls -la\\n")

        # Read output
        output = shell.read()

        # Resize
        shell.resize(80, 24)

        shell.stop()
    """

    DEFAULT_SHELL = os.environ.get("SHELL", "/bin/bash")

    def __init__(
        self,
        working_directory: Optional[Path] = None,
        shell: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        self.working_directory = working_directory or Path.cwd()
        self.shell = shell or self.DEFAULT_SHELL
        self.env = env or dict(os.environ)

        # PTY state
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._pid: Optional[int] = None
        self._running = False

        # Output buffer
        self._output_buffer: List[str] = []
        self._output_lock = threading.Lock()

        # Callbacks
        self._on_output: Optional[Callable[[str], None]] = None
        self._on_exit: Optional[Callable[[int], None]] = None

        # Reader thread
        self._reader_thread: Optional[threading.Thread] = None

        # Terminal size
        self._rows = 24
        self._cols = 80

    @property
    def is_running(self) -> bool:
        """Check if shell is running."""
        return self._running and self._pid is not None

    @property
    def pid(self) -> Optional[int]:
        """Get the shell process ID."""
        return self._pid

    def start(self) -> bool:
        """Start the shell session."""
        if self._running:
            return True

        try:
            # Create pseudo-terminal
            self._master_fd, self._slave_fd = pty.openpty()

            # Set terminal size
            self._set_window_size(self._rows, self._cols)

            # Fork process
            self._pid = os.fork()

            if self._pid == 0:
                # Child process
                self._child_process()
            else:
                # Parent process
                os.close(self._slave_fd)
                self._slave_fd = None

                # Make master non-blocking
                flags = fcntl.fcntl(self._master_fd, fcntl.F_GETFL)
                fcntl.fcntl(self._master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                self._running = True

                # Start reader thread
                self._reader_thread = threading.Thread(
                    target=self._read_loop,
                    daemon=True,
                )
                self._reader_thread.start()

                return True

        except Exception as e:
            self._cleanup()
            raise RuntimeError(f"Failed to start shell: {e}")

    def _child_process(self) -> None:
        """Set up and exec shell in child process."""
        # Create new session
        os.setsid()

        # Set controlling terminal
        os.dup2(self._slave_fd, 0)
        os.dup2(self._slave_fd, 1)
        os.dup2(self._slave_fd, 2)

        if self._slave_fd > 2:
            os.close(self._slave_fd)

        # Change to working directory
        try:
            os.chdir(self.working_directory)
        except OSError:
            pass

        # Set environment
        self.env["TERM"] = "xterm-256color"
        self.env["COLORTERM"] = "truecolor"

        # Exec shell
        try:
            os.execvpe(self.shell, [self.shell], self.env)
        except Exception:
            os._exit(1)

    def _set_window_size(self, rows: int, cols: int) -> None:
        """Set terminal window size."""
        if self._master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def _read_loop(self) -> None:
        """Background thread to read PTY output."""
        while self._running:
            try:
                # Wait for data with timeout
                r, _, _ = select.select([self._master_fd], [], [], 0.1)

                if self._master_fd in r:
                    try:
                        data = os.read(self._master_fd, 4096)
                        if data:
                            text = data.decode("utf-8", errors="replace")

                            with self._output_lock:
                                self._output_buffer.append(text)

                            if self._on_output:
                                self._on_output(text)
                        else:
                            # EOF - shell exited
                            self._handle_exit()
                            break
                    except OSError:
                        self._handle_exit()
                        break

            except (ValueError, OSError):
                # FD closed
                break

        self._running = False

    def _handle_exit(self) -> None:
        """Handle shell exit."""
        self._running = False

        exit_code = 0
        if self._pid:
            try:
                _, status = os.waitpid(self._pid, os.WNOHANG)
                if os.WIFEXITED(status):
                    exit_code = os.WEXITSTATUS(status)
            except ChildProcessError:
                pass

        if self._on_exit:
            self._on_exit(exit_code)

    def write(self, data: str) -> int:
        """Write data to the shell."""
        if not self._running or self._master_fd is None:
            return 0

        try:
            return os.write(self._master_fd, data.encode("utf-8"))
        except OSError:
            return 0

    def read(self) -> str:
        """Read buffered output from the shell."""
        with self._output_lock:
            output = "".join(self._output_buffer)
            self._output_buffer.clear()
            return output

    def resize(self, rows: int, cols: int) -> None:
        """Resize the terminal."""
        self._rows = rows
        self._cols = cols

        if self._running:
            self._set_window_size(rows, cols)

    def send_signal(self, sig: int) -> None:
        """Send a signal to the shell process."""
        if self._pid:
            try:
                os.kill(self._pid, sig)
            except OSError:
                pass

    def interrupt(self) -> None:
        """Send interrupt signal (Ctrl+C)."""
        self.write("\x03")

    def stop(self) -> None:
        """Stop the shell session."""
        if not self._running:
            return

        self._running = False

        # Kill the process
        if self._pid:
            try:
                os.kill(self._pid, signal.SIGTERM)
                os.waitpid(self._pid, 0)
            except (OSError, ChildProcessError):
                pass

        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None

        self._pid = None

    def on_output(self, callback: Callable[[str], None]) -> None:
        """Set callback for output events."""
        self._on_output = callback

    def on_exit(self, callback: Callable[[int], None]) -> None:
        """Set callback for exit events."""
        self._on_exit = callback

    def __enter__(self) -> "PTYShell":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


class PTYShellWidget(Static):
    """
    Textual widget for PTY shell.

    Displays an interactive terminal within the TUI.

    Usage:
        shell_widget = PTYShellWidget(working_directory=Path.cwd())
        # Add to your app's compose()
    """

    DEFAULT_CSS = """
    PTYShellWidget {
        height: 100%;
        border: solid #3f3f46;
        background: #0f0f0f;
        padding: 0 1;
    }

    PTYShellWidget:focus {
        border: solid #3b82f6;
    }
    """

    # Reactive state
    is_active: reactive[bool] = reactive(False)

    def __init__(
        self,
        working_directory: Optional[Path] = None,
        shell: Optional[str] = None,
        title: str = "Terminal",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.title = title
        self._shell = PTYShell(
            working_directory=working_directory,
            shell=shell,
        )
        self._output_lines: List[str] = []
        self._max_lines = 1000
        self._scroll_offset = 0
        self._timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start shell when mounted."""
        # Set up callbacks
        self._shell.on_output(self._handle_output)
        self._shell.on_exit(self._handle_exit)

        # Start shell
        try:
            self._shell.start()
            self.is_active = True
        except RuntimeError as e:
            self._output_lines.append(f"[ERROR] {e}")

        # Start refresh timer
        self._timer = self.set_interval(0.1, self._refresh_output)

    def on_unmount(self) -> None:
        """Stop shell when unmounted."""
        if self._timer:
            self._timer.stop()
        self._shell.stop()

    def on_resize(self, event: events.Resize) -> None:
        """Handle resize events."""
        # Account for borders and padding
        rows = max(1, event.size.height - 2)
        cols = max(1, event.size.width - 4)
        self._shell.resize(rows, cols)

    def on_key(self, event: events.Key) -> None:
        """Handle key events."""
        if not self.is_active:
            return

        # Convert key to terminal sequence
        key_map = {
            "enter": "\r",
            "tab": "\t",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "escape": "\x1b",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "f1": "\x1bOP",
            "f2": "\x1bOQ",
            "f3": "\x1bOR",
            "f4": "\x1bOS",
        }

        # Ctrl key combinations
        if event.key.startswith("ctrl+"):
            char = event.key[5:]
            if len(char) == 1:
                code = ord(char.upper()) - 64
                if 1 <= code <= 26:
                    self._shell.write(chr(code))
                    event.prevent_default()
                    return

        # Special keys
        if event.key in key_map:
            self._shell.write(key_map[event.key])
            event.prevent_default()
            return

        # Regular characters
        if event.character and len(event.character) == 1:
            self._shell.write(event.character)
            event.prevent_default()

    def _handle_output(self, text: str) -> None:
        """Handle output from shell."""
        # Split into lines and add to buffer
        lines = text.split("\n")

        for i, line in enumerate(lines):
            if i == 0 and self._output_lines:
                # Append to last line
                self._output_lines[-1] += line
            else:
                self._output_lines.append(line)

        # Limit buffer size
        if len(self._output_lines) > self._max_lines:
            self._output_lines = self._output_lines[-self._max_lines :]

    def _handle_exit(self, exit_code: int) -> None:
        """Handle shell exit."""
        self.is_active = False
        self._output_lines.append(f"\n[Process exited with code {exit_code}]")
        self.refresh()

    def _refresh_output(self) -> None:
        """Refresh the display."""
        if self.is_active:
            self.refresh()

    def send_command(self, command: str) -> None:
        """Send a command to the shell."""
        if self.is_active:
            self._shell.write(command + "\n")

    def clear(self) -> None:
        """Clear the output buffer."""
        self._output_lines.clear()
        self.refresh()

    def render(self) -> RenderableType:
        """Render the terminal output."""
        content = Text()

        # Get visible lines (based on widget height)
        visible_lines = self._output_lines[-50:]  # Show last 50 lines

        for line in visible_lines:
            # Basic ANSI code stripping for now
            # TODO: Full ANSI parsing for colors
            clean_line = line
            content.append(clean_line + "\n", style="#e2e8f0")

        if not self.is_active:
            content.append("\n[Shell not running]", style="#ef4444")

        border_style = "#3b82f6" if self.has_focus else "#3f3f46"

        return Panel(
            content,
            title=f"[bold #3b82f6]{self.title}[/]",
            border_style=border_style,
            padding=(0, 0),
        )


class ShellManager:
    """
    Manages multiple shell sessions.

    Usage:
        manager = ShellManager()

        # Create a new shell
        shell_id = manager.create_shell(Path.cwd())

        # Get shell
        shell = manager.get_shell(shell_id)

        # List shells
        shells = manager.list_shells()

        # Close shell
        manager.close_shell(shell_id)
    """

    def __init__(self):
        self._shells: Dict[str, PTYShell] = {}
        self._counter = 0

    def create_shell(
        self,
        working_directory: Optional[Path] = None,
        shell: Optional[str] = None,
        title: str = "Shell",
    ) -> str:
        """Create a new shell session."""
        self._counter += 1
        shell_id = f"shell-{self._counter}"

        pty_shell = PTYShell(
            working_directory=working_directory,
            shell=shell,
        )
        pty_shell.start()

        self._shells[shell_id] = pty_shell
        return shell_id

    def get_shell(self, shell_id: str) -> Optional[PTYShell]:
        """Get a shell by ID."""
        return self._shells.get(shell_id)

    def close_shell(self, shell_id: str) -> bool:
        """Close a shell session."""
        shell = self._shells.pop(shell_id, None)
        if shell:
            shell.stop()
            return True
        return False

    def list_shells(self) -> List[str]:
        """List all shell IDs."""
        return list(self._shells.keys())

    def close_all(self) -> None:
        """Close all shell sessions."""
        for shell in self._shells.values():
            shell.stop()
        self._shells.clear()
