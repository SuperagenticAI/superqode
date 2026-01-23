"""
SuperQode Servers.

- Web Server: Run SuperQode TUI in a web browser using textual-serve
- LSP Server: Language Server Protocol for IDE integration
"""

from .web import (
    WebServer,
    WebServerConfig,
    start_server,
)

from .lsp_server import (
    SuperQodeLSPServer,
    start_lsp_server,
    LSPDiagnostic,
    DiagnosticSeverity,
    CodeAction,
)

__all__ = [
    # Web server
    "WebServer",
    "WebServerConfig",
    "start_server",
    # LSP server
    "SuperQodeLSPServer",
    "start_lsp_server",
    "LSPDiagnostic",
    "DiagnosticSeverity",
    "CodeAction",
]
