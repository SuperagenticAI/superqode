"""
LSP Client - Language Server Protocol Integration.

Provides real-time code diagnostics and intelligence by
connecting to language servers for various languages.

Features:
- Multi-language support (Python, TypeScript, Go, etc.)
- Real-time diagnostics
- Code completion
- Hover information
- Go to definition
- Designed for SuperQode's QE workflow
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import threading


class DiagnosticSeverity(IntEnum):
    """LSP diagnostic severity levels."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass
class Position:
    """Position in a text document."""

    line: int
    character: int

    def to_dict(self) -> dict:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(line=data["line"], character=data["character"])


@dataclass
class Range:
    """Range in a text document."""

    start: Position
    end: Position

    def to_dict(self) -> dict:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "Range":
        return cls(
            start=Position.from_dict(data["start"]),
            end=Position.from_dict(data["end"]),
        )


@dataclass
class Location:
    """Location in a text document."""

    uri: str
    range: Range

    def to_dict(self) -> dict:
        return {"uri": self.uri, "range": self.range.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "Location":
        return cls(uri=data["uri"], range=Range.from_dict(data["range"]))


@dataclass
class Diagnostic:
    """A diagnostic (error, warning, etc.)."""

    range: Range
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    code: Optional[str] = None
    source: Optional[str] = None
    related_information: List[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Diagnostic":
        return cls(
            range=Range.from_dict(data["range"]),
            message=data["message"],
            severity=DiagnosticSeverity(data.get("severity", 1)),
            code=data.get("code"),
            source=data.get("source"),
            related_information=data.get("relatedInformation", []),
        )

    @property
    def severity_name(self) -> str:
        """Get human-readable severity name."""
        names = {
            DiagnosticSeverity.ERROR: "error",
            DiagnosticSeverity.WARNING: "warning",
            DiagnosticSeverity.INFORMATION: "info",
            DiagnosticSeverity.HINT: "hint",
        }
        return names.get(self.severity, "unknown")


@dataclass
class LSPConfig:
    """Configuration for LSP client."""

    # Language server commands
    servers: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "python": ["pyright-langserver", "--stdio"],
            "typescript": ["typescript-language-server", "--stdio"],
            "javascript": ["typescript-language-server", "--stdio"],
            "go": ["gopls"],
            "rust": ["rust-analyzer"],
            "c": ["clangd"],
            "cpp": ["clangd"],
        }
    )

    # File extensions to language mapping
    extensions: Dict[str, str] = field(
        default_factory=lambda: {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cc": "cpp",
        }
    )

    # Timeout for requests
    timeout: float = 10.0


class LSPClient:
    """
    Language Server Protocol client.

    Manages connections to language servers and provides
    code diagnostics and intelligence features.

    Usage:
        config = LSPConfig()
        client = LSPClient(project_root, config)

        # Start server for Python files
        await client.start_server("python")

        # Get diagnostics for a file
        diagnostics = await client.get_diagnostics("src/main.py")

        # Open a file for tracking
        await client.open_file("src/main.py")

        # Clean up
        await client.shutdown()
    """

    def __init__(
        self,
        project_root: Path,
        config: Optional[LSPConfig] = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.config = config or LSPConfig()

        # Server processes
        self._processes: Dict[str, subprocess.Popen] = {}
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}

        # Reader threads
        self._readers: Dict[str, threading.Thread] = {}
        self._running = False

        # Diagnostics cache
        self._diagnostics: Dict[str, List[Diagnostic]] = {}

        # Callbacks
        self._on_diagnostics: Optional[Callable[[str, List[Diagnostic]], None]] = None

        # Locks
        self._lock = asyncio.Lock()

    def _get_language(self, file_path: str) -> Optional[str]:
        """Get language ID from file extension."""
        ext = Path(file_path).suffix.lower()
        return self.config.extensions.get(ext)

    def _next_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    async def start_server(self, language: str) -> bool:
        """Start a language server."""
        if language in self._processes:
            return True  # Already running

        cmd = self.config.servers.get(language)
        if not cmd:
            return False

        try:
            # Start the language server process
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.project_root),
            )

            self._processes[language] = process

            # Start reader thread
            self._running = True
            reader = threading.Thread(
                target=self._read_responses,
                args=(language, process),
                daemon=True,
            )
            reader.start()
            self._readers[language] = reader

            # Initialize the server
            await self._initialize(language)

            return True

        except (FileNotFoundError, OSError) as e:
            return False

    async def _initialize(self, language: str) -> None:
        """Initialize a language server."""
        process = self._processes.get(language)
        if not process:
            return

        # Send initialize request
        result = await self._send_request(
            language,
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": f"file://{self.project_root}",
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": {"relatedInformation": True},
                        "completion": {"completionItem": {"snippetSupport": True}},
                        "hover": {},
                        "definition": {},
                    },
                },
            },
        )

        # Send initialized notification
        await self._send_notification(language, "initialized", {})

    def _read_responses(self, language: str, process: subprocess.Popen) -> None:
        """Read responses from language server (runs in thread)."""
        while self._running and process.poll() is None:
            try:
                # Read headers
                headers = {}
                while True:
                    line = process.stdout.readline().decode("utf-8")
                    if not line or line == "\r\n":
                        break
                    if ":" in line:
                        key, value = line.split(":", 1)
                        headers[key.strip().lower()] = value.strip()

                # Read content
                content_length = int(headers.get("content-length", 0))
                if content_length > 0:
                    content = process.stdout.read(content_length).decode("utf-8")
                    message = json.loads(content)
                    self._handle_message(language, message)

            except Exception:
                break

    def _handle_message(self, language: str, message: dict) -> None:
        """Handle a message from language server."""
        # Response to request
        if "id" in message and "result" in message:
            request_id = message["id"]
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if not future.done():
                    future.set_result(message.get("result"))

        # Error response
        elif "id" in message and "error" in message:
            request_id = message["id"]
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if not future.done():
                    future.set_exception(Exception(message["error"].get("message", "LSP Error")))

        # Notification
        elif "method" in message:
            method = message["method"]
            params = message.get("params", {})

            if method == "textDocument/publishDiagnostics":
                self._handle_diagnostics(params)

    def _handle_diagnostics(self, params: dict) -> None:
        """Handle diagnostics notification."""
        uri = params.get("uri", "")

        # Convert URI to path
        if uri.startswith("file://"):
            file_path = uri[7:]
        else:
            file_path = uri

        # Parse diagnostics
        diagnostics = [Diagnostic.from_dict(d) for d in params.get("diagnostics", [])]

        self._diagnostics[file_path] = diagnostics

        # Call callback if set
        if self._on_diagnostics:
            self._on_diagnostics(file_path, diagnostics)

    async def _send_request(
        self,
        language: str,
        method: str,
        params: dict,
    ) -> Any:
        """Send a request to language server."""
        process = self._processes.get(language)
        if not process or process.poll() is not None:
            raise Exception(f"Language server not running: {language}")

        request_id = self._next_request_id()

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        # Send request
        process.stdin.write(header.encode() + content.encode())
        process.stdin.flush()

        # Wait for response
        try:
            return await asyncio.wait_for(future, timeout=self.config.timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise Exception(f"LSP request timeout: {method}")

    async def _send_notification(
        self,
        language: str,
        method: str,
        params: dict,
    ) -> None:
        """Send a notification to language server."""
        process = self._processes.get(language)
        if not process or process.poll() is not None:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"

        process.stdin.write(header.encode() + content.encode())
        process.stdin.flush()

    async def open_file(self, file_path: str) -> None:
        """Notify server that a file is opened."""
        abs_path = self.project_root / file_path
        language = self._get_language(file_path)

        if not language:
            return

        if language not in self._processes:
            await self.start_server(language)

        if not abs_path.exists():
            return

        content = abs_path.read_text(errors="replace")

        await self._send_notification(
            language,
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": f"file://{abs_path}",
                    "languageId": language,
                    "version": 1,
                    "text": content,
                }
            },
        )

    async def close_file(self, file_path: str) -> None:
        """Notify server that a file is closed."""
        abs_path = self.project_root / file_path
        language = self._get_language(file_path)

        if not language or language not in self._processes:
            return

        await self._send_notification(
            language,
            "textDocument/didClose",
            {
                "textDocument": {
                    "uri": f"file://{abs_path}",
                }
            },
        )

    async def update_file(self, file_path: str, content: str) -> None:
        """Notify server of file changes."""
        abs_path = self.project_root / file_path
        language = self._get_language(file_path)

        if not language or language not in self._processes:
            return

        await self._send_notification(
            language,
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": f"file://{abs_path}",
                    "version": 2,  # Simplified versioning
                },
                "contentChanges": [{"text": content}],
            },
        )

    async def get_diagnostics(self, file_path: str) -> List[Diagnostic]:
        """Get cached diagnostics for a file."""
        abs_path = str(self.project_root / file_path)
        return self._diagnostics.get(abs_path, [])

    async def get_all_diagnostics(self) -> Dict[str, List[Diagnostic]]:
        """Get all cached diagnostics."""
        return dict(self._diagnostics)

    def on_diagnostics(
        self,
        callback: Callable[[str, List[Diagnostic]], None],
    ) -> None:
        """Set callback for diagnostic updates."""
        self._on_diagnostics = callback

    async def shutdown(self) -> None:
        """Shutdown all language servers."""
        self._running = False

        for language, process in self._processes.items():
            try:
                # Send shutdown request
                await self._send_request(language, "shutdown", {})
                await self._send_notification(language, "exit", {})
            except Exception:
                pass

            # Terminate process
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except Exception:
                process.kill()

        self._processes.clear()
        self._readers.clear()
        self._diagnostics.clear()

    def __enter__(self) -> "LSPClient":
        return self

    def __exit__(self, *args) -> None:
        asyncio.run(self.shutdown())


async def get_file_diagnostics(
    project_root: Path,
    file_path: str,
) -> List[Diagnostic]:
    """Convenience function to get diagnostics for a single file."""
    client = LSPClient(project_root)

    try:
        await client.open_file(file_path)
        # Wait a bit for diagnostics
        await asyncio.sleep(1.0)
        return await client.get_diagnostics(file_path)
    finally:
        await client.shutdown()
