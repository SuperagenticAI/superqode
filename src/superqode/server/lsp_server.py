"""
SuperQode LSP Server - Language Server Protocol for QE Integration.

Provides IDE integration by exposing QE findings as LSP diagnostics.
Supports VSCode, Neovim, and other LSP-compatible editors.

Features:
- Real-time QIR findings as diagnostics
- Quick fixes from QE patches
- Code actions for findings
- Status updates during QE sessions

Usage:
    superqode serve --lsp         # Start LSP server (stdio)
    superqode serve --lsp --port 9000  # Start LSP server (TCP)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import IntEnum

logger = logging.getLogger(__name__)


class DiagnosticSeverity(IntEnum):
    """LSP diagnostic severity levels."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


class CodeActionKind:
    """LSP code action kinds."""

    QUICKFIX = "quickfix"
    REFACTOR = "refactor"
    SOURCE = "source"


@dataclass
class LSPPosition:
    """Position in a text document (0-indexed)."""

    line: int
    character: int

    def to_dict(self) -> dict:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_dict(cls, data: dict) -> "LSPPosition":
        return cls(line=data["line"], character=data["character"])


@dataclass
class LSPRange:
    """Range in a text document."""

    start: LSPPosition
    end: LSPPosition

    def to_dict(self) -> dict:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "LSPRange":
        return cls(
            start=LSPPosition.from_dict(data["start"]),
            end=LSPPosition.from_dict(data["end"]),
        )


@dataclass
class LSPDiagnostic:
    """A diagnostic (error, warning, etc.)."""

    range: LSPRange
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING
    code: Optional[str] = None
    source: str = "superqode"
    data: Optional[Dict] = None  # For code actions

    def to_dict(self) -> dict:
        result = {
            "range": self.range.to_dict(),
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
        }
        if self.code:
            result["code"] = self.code
        if self.data:
            result["data"] = self.data
        return result


@dataclass
class TextEdit:
    """A text edit operation."""

    range: LSPRange
    new_text: str

    def to_dict(self) -> dict:
        return {
            "range": self.range.to_dict(),
            "newText": self.new_text,
        }


@dataclass
class CodeAction:
    """A code action (quick fix, refactor, etc.)."""

    title: str
    kind: str
    diagnostics: List[LSPDiagnostic] = field(default_factory=list)
    edit: Optional[Dict] = None
    command: Optional[Dict] = None
    is_preferred: bool = False

    def to_dict(self) -> dict:
        result = {
            "title": self.title,
            "kind": self.kind,
        }
        if self.diagnostics:
            result["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        if self.edit:
            result["edit"] = self.edit
        if self.command:
            result["command"] = self.command
        if self.is_preferred:
            result["isPreferred"] = True
        return result


# Severity mapping from QE to LSP
QE_TO_LSP_SEVERITY = {
    "critical": DiagnosticSeverity.ERROR,
    "high": DiagnosticSeverity.ERROR,
    "medium": DiagnosticSeverity.WARNING,
    "low": DiagnosticSeverity.INFORMATION,
    "info": DiagnosticSeverity.HINT,
}


class SuperQodeLSPServer:
    """
    SuperQode Language Server Protocol Server.

    Exposes QE findings as LSP diagnostics for IDE integration.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        transport: str = "stdio",
        port: int = 9000,
    ):
        self.project_root = project_root
        self.transport = transport
        self.port = port

        # Server state
        self._initialized = False
        self._shutdown = False
        self._request_id = 0

        # Document tracking
        self._open_documents: Dict[str, str] = {}  # uri -> content

        # QE findings
        self._findings_by_file: Dict[str, List[Dict]] = {}
        self._patches_by_file: Dict[str, List[Dict]] = {}

        # Diagnostics cache
        self._diagnostics: Dict[str, List[LSPDiagnostic]] = {}

        # IO
        self._stdin = None
        self._stdout = None
        self._reader_thread = None

        # Callbacks
        self._on_qe_request: Optional[Callable[[str], None]] = None

    def _next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _uri_to_path(self, uri: str) -> Path:
        """Convert file URI to path."""
        if uri.startswith("file://"):
            return Path(uri[7:])
        return Path(uri)

    def _path_to_uri(self, path: Path) -> str:
        """Convert path to file URI."""
        return f"file://{path.resolve()}"

    # ================================================================
    # Finding to Diagnostic Conversion
    # ================================================================

    def load_qir(self, qr_path: Path) -> None:
        """Load findings from a QIR JSON file."""
        try:
            data = json.loads(qir_path.read_text())
            findings = data.get("findings", [])
            self._process_findings(findings)
            logger.info(f"Loaded {len(findings)} findings from QIR")
        except Exception as e:
            logger.error(f"Failed to load QIR: {e}")

    def load_patches(self, patches_dir: Path) -> None:
        """Load patches for quick fixes."""
        if not patches_dir.exists():
            return

        for patch_file in patches_dir.glob("*.patch"):
            try:
                patch_content = patch_file.read_text()
                # Parse patch to extract file and changes
                patch_info = self._parse_patch(patch_content, patch_file.stem)
                if patch_info:
                    file_path = patch_info["file"]
                    if file_path not in self._patches_by_file:
                        self._patches_by_file[file_path] = []
                    self._patches_by_file[file_path].append(patch_info)
            except Exception as e:
                logger.warning(f"Failed to parse patch {patch_file}: {e}")

    def _parse_patch(self, content: str, patch_id: str) -> Optional[Dict]:
        """Parse a unified diff patch."""
        lines = content.split("\n")
        file_path = None
        changes = []

        for i, line in enumerate(lines):
            if line.startswith("--- a/"):
                file_path = line[6:]
            elif line.startswith("+++ b/"):
                file_path = line[6:]
            elif line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                try:
                    parts = line.split(" ")
                    new_range = parts[2]  # +start,count
                    start = int(new_range.split(",")[0][1:]) - 1  # 0-indexed
                    changes.append({"start_line": start, "hunk_start": i})
                except (IndexError, ValueError):
                    pass

        if file_path:
            return {
                "id": patch_id,
                "file": file_path,
                "content": content,
                "changes": changes,
            }
        return None

    def _process_findings(self, findings: List[Dict]) -> None:
        """Process findings into diagnostics."""
        self._findings_by_file.clear()
        self._diagnostics.clear()

        for finding in findings:
            file_path = finding.get("file_path")
            if not file_path:
                continue

            if file_path not in self._findings_by_file:
                self._findings_by_file[file_path] = []
            self._findings_by_file[file_path].append(finding)

        # Convert to diagnostics
        for file_path, file_findings in self._findings_by_file.items():
            self._diagnostics[file_path] = [self._finding_to_diagnostic(f) for f in file_findings]

    def _finding_to_diagnostic(self, finding: Dict) -> LSPDiagnostic:
        """Convert a QE finding to an LSP diagnostic."""
        # Get line number (default to 0)
        line = finding.get("line_number", finding.get("line_start", 1)) - 1
        line = max(0, line)

        # Create range (default to whole line)
        start = LSPPosition(line=line, character=0)
        end = LSPPosition(line=line, character=1000)  # End of line

        # Map severity
        qe_severity = finding.get("severity", "medium").lower()
        lsp_severity = QE_TO_LSP_SEVERITY.get(qe_severity, DiagnosticSeverity.WARNING)

        # Build message
        title = finding.get("title", "QE Finding")
        description = finding.get("description", "")
        message = f"{title}\n\n{description}" if description else title

        return LSPDiagnostic(
            range=LSPRange(start=start, end=end),
            message=message,
            severity=lsp_severity,
            code=finding.get("id"),
            source="superqode",
            data={"finding": finding},
        )

    def get_diagnostics(self, uri: str) -> List[LSPDiagnostic]:
        """Get diagnostics for a document."""
        path = self._uri_to_path(uri)

        # Try relative path first
        rel_path = str(path)
        if self.project_root:
            try:
                rel_path = str(path.relative_to(self.project_root))
            except ValueError:
                pass

        return self._diagnostics.get(rel_path, [])

    def get_code_actions(
        self,
        uri: str,
        range_: LSPRange,
        diagnostics: List[Dict],
    ) -> List[CodeAction]:
        """Get code actions for a range."""
        actions: List[CodeAction] = []
        path = self._uri_to_path(uri)

        # Get relative path
        rel_path = str(path)
        if self.project_root:
            try:
                rel_path = str(path.relative_to(self.project_root))
            except ValueError:
                pass

        # Check for patches
        patches = self._patches_by_file.get(rel_path, [])
        for patch in patches:
            # Check if patch applies to this range
            for change in patch.get("changes", []):
                if change["start_line"] >= range_.start.line - 5:
                    action = CodeAction(
                        title=f"Apply QE fix: {patch['id']}",
                        kind=CodeActionKind.QUICKFIX,
                        is_preferred=True,
                        command={
                            "title": "Apply Patch",
                            "command": "superqode.applyPatch",
                            "arguments": [patch["id"], patch["content"]],
                        },
                    )
                    actions.append(action)
                    break

        # Add suppress action for diagnostics
        for diag_data in diagnostics:
            finding_id = diag_data.get("code")
            if finding_id:
                action = CodeAction(
                    title=f"Suppress finding: {finding_id}",
                    kind=CodeActionKind.QUICKFIX,
                    command={
                        "title": "Suppress Finding",
                        "command": "superqode.suppressFinding",
                        "arguments": [finding_id],
                    },
                )
                actions.append(action)

        # Add run QE action
        actions.append(
            CodeAction(
                title="Run SuperQode QE on this file",
                kind=CodeActionKind.SOURCE,
                command={
                    "title": "Run QE",
                    "command": "superqode.runQE",
                    "arguments": [uri],
                },
            )
        )

        return actions

    # ================================================================
    # LSP Protocol Handling
    # ================================================================

    def handle_request(self, method: str, params: Dict) -> Any:
        """Handle an LSP request."""
        handlers = {
            "initialize": self._handle_initialize,
            "shutdown": self._handle_shutdown,
            "textDocument/codeAction": self._handle_code_action,
            "textDocument/hover": self._handle_hover,
            "superqode/runQE": self._handle_run_qe,
            "superqode/loadQIR": self._handle_load_qir,
        }

        handler = handlers.get(method)
        if handler:
            return handler(params)

        logger.warning(f"Unhandled request: {method}")
        return None

    def handle_notification(self, method: str, params: Dict) -> None:
        """Handle an LSP notification."""
        handlers = {
            "initialized": self._handle_initialized,
            "exit": self._handle_exit,
            "textDocument/didOpen": self._handle_did_open,
            "textDocument/didClose": self._handle_did_close,
            "textDocument/didChange": self._handle_did_change,
            "textDocument/didSave": self._handle_did_save,
        }

        handler = handlers.get(method)
        if handler:
            handler(params)

    def _handle_initialize(self, params: Dict) -> Dict:
        """Handle initialize request."""
        root_uri = params.get("rootUri")
        if root_uri:
            self.project_root = self._uri_to_path(root_uri)

        self._initialized = True

        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,  # Full sync
                    "save": {"includeText": False},
                },
                "codeActionProvider": {
                    "codeActionKinds": [
                        CodeActionKind.QUICKFIX,
                        CodeActionKind.SOURCE,
                    ],
                },
                "hoverProvider": True,
                "executeCommandProvider": {
                    "commands": [
                        "superqode.runQE",
                        "superqode.applyPatch",
                        "superqode.suppressFinding",
                    ],
                },
            },
            "serverInfo": {
                "name": "SuperQode LSP",
                "version": "1.0.0",
            },
        }

    def _handle_initialized(self, params: Dict) -> None:
        """Handle initialized notification."""
        logger.info("LSP client initialized")

        # Load existing QIR if available
        if self.project_root:
            qr_dir = self.project_root / ".superqode" / "qe-artifacts" / "qr"
            if qr_dir.exists():
                qr_files = sorted(qir_dir.glob("*.json"), reverse=True)
                if qir_files:
                    self.load_qir(qir_files[0])

            # Load patches
            patches_dir = self.project_root / ".superqode" / "qe-artifacts" / "patches"
            self.load_patches(patches_dir)

    def _handle_shutdown(self, params: Dict) -> None:
        """Handle shutdown request."""
        self._shutdown = True
        return None

    def _handle_exit(self, params: Dict) -> None:
        """Handle exit notification."""
        sys.exit(0 if self._shutdown else 1)

    def _handle_did_open(self, params: Dict) -> None:
        """Handle textDocument/didOpen."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        text = doc.get("text", "")

        self._open_documents[uri] = text

        # Publish diagnostics for this file
        self._publish_diagnostics(uri)

    def _handle_did_close(self, params: Dict) -> None:
        """Handle textDocument/didClose."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")

        self._open_documents.pop(uri, None)

    def _handle_did_change(self, params: Dict) -> None:
        """Handle textDocument/didChange."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        changes = params.get("contentChanges", [])

        if changes:
            # Full sync - take the last change
            self._open_documents[uri] = changes[-1].get("text", "")

    def _handle_did_save(self, params: Dict) -> None:
        """Handle textDocument/didSave."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")

        # Could trigger incremental QE here
        logger.debug(f"Document saved: {uri}")

    def _handle_code_action(self, params: Dict) -> List[Dict]:
        """Handle textDocument/codeAction."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        range_data = params.get("range", {})
        context = params.get("context", {})

        range_ = LSPRange.from_dict(range_data)
        diagnostics = context.get("diagnostics", [])

        actions = self.get_code_actions(uri, range_, diagnostics)
        return [a.to_dict() for a in actions]

    def _handle_hover(self, params: Dict) -> Optional[Dict]:
        """Handle textDocument/hover."""
        doc = params.get("textDocument", {})
        uri = doc.get("uri", "")
        position = params.get("position", {})

        # Find finding at position
        diagnostics = self.get_diagnostics(uri)
        line = position.get("line", 0)

        for diag in diagnostics:
            if diag.range.start.line <= line <= diag.range.end.line:
                finding = diag.data.get("finding", {}) if diag.data else {}

                # Build hover content
                content = [
                    f"**{finding.get('title', 'QE Finding')}**",
                    "",
                    f"Severity: {finding.get('severity', 'unknown')}",
                    f"Category: {finding.get('category', 'unknown')}",
                    "",
                    finding.get("description", ""),
                ]

                if finding.get("suggested_fix"):
                    content.extend(["", "**Suggested Fix:**", finding["suggested_fix"]])

                return {
                    "contents": {
                        "kind": "markdown",
                        "value": "\n".join(content),
                    }
                }

        return None

    def _handle_run_qe(self, params: Dict) -> Dict:
        """Handle superqode/runQE request."""
        uri = params.get("uri")
        mode = params.get("mode", "quick")

        if self._on_qe_request:
            self._on_qe_request(uri)

        return {"status": "started", "mode": mode}

    def _handle_load_qir(self, params: Dict) -> Dict:
        """Handle superqode/loadQIR request."""
        qr_path = params.get("path")
        if qr_path:
            self.load_qir(Path(qr_path))

            # Republish diagnostics
            for uri in self._open_documents:
                self._publish_diagnostics(uri)

            return {"status": "loaded"}

        return {"status": "error", "message": "No path provided"}

    def _publish_diagnostics(self, uri: str) -> None:
        """Publish diagnostics for a document."""
        diagnostics = self.get_diagnostics(uri)
        self._send_notification(
            "textDocument/publishDiagnostics",
            {
                "uri": uri,
                "diagnostics": [d.to_dict() for d in diagnostics],
            },
        )

    # ================================================================
    # Transport Layer
    # ================================================================

    def _send_response(self, request_id: int, result: Any) -> None:
        """Send a response."""
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        self._write_message(message)

    def _send_error(self, request_id: int, code: int, message: str) -> None:
        """Send an error response."""
        msg = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
        self._write_message(msg)

    def _send_notification(self, method: str, params: Dict) -> None:
        """Send a notification."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(message)

    def _write_message(self, message: Dict) -> None:
        """Write a message to the transport."""
        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"

        if self._stdout:
            self._stdout.write(header.encode() + content.encode())
            self._stdout.flush()

    def _read_message(self) -> Optional[Dict]:
        """Read a message from the transport."""
        if not self._stdin:
            return None

        try:
            # Read headers
            headers = {}
            while True:
                line = self._stdin.readline().decode("utf-8")
                if not line or line == "\r\n":
                    break
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            # Read content
            content_length = int(headers.get("content-length", 0))
            if content_length > 0:
                content = self._stdin.read(content_length).decode("utf-8")
                return json.loads(content)

        except Exception as e:
            logger.error(f"Error reading message: {e}")

        return None

    def _process_message(self, message: Dict) -> None:
        """Process an incoming message."""
        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")

        if request_id is not None:
            # Request - needs response
            try:
                result = self.handle_request(method, params)
                self._send_response(request_id, result)
            except Exception as e:
                logger.error(f"Error handling request {method}: {e}")
                self._send_error(request_id, -32603, str(e))
        else:
            # Notification - no response
            self.handle_notification(method, params)

    def run_stdio(self) -> None:
        """Run the server using stdio transport."""
        self._stdin = sys.stdin.buffer
        self._stdout = sys.stdout.buffer

        logger.info("SuperQode LSP server started (stdio)")

        while not self._shutdown:
            message = self._read_message()
            if message:
                self._process_message(message)
            else:
                break

        logger.info("SuperQode LSP server stopped")

    def run_tcp(self) -> None:
        """Run the server using TCP transport."""
        import socket

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", self.port))
        server.listen(1)

        logger.info(f"SuperQode LSP server started on port {self.port}")

        try:
            while not self._shutdown:
                conn, addr = server.accept()
                logger.info(f"Client connected: {addr}")

                # Handle connection
                self._stdin = conn.makefile("rb")
                self._stdout = conn.makefile("wb")

                while not self._shutdown:
                    message = self._read_message()
                    if message:
                        self._process_message(message)
                    else:
                        break

                conn.close()

        finally:
            server.close()

        logger.info("SuperQode LSP server stopped")

    def run(self) -> None:
        """Run the server."""
        if self.transport == "tcp":
            self.run_tcp()
        else:
            self.run_stdio()


def start_lsp_server(
    project_root: Optional[Path] = None,
    transport: str = "stdio",
    port: int = 9000,
) -> None:
    """Start the LSP server."""
    server = SuperQodeLSPServer(
        project_root=project_root,
        transport=transport,
        port=port,
    )
    server.run()
