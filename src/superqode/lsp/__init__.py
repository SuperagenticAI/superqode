"""
SuperQode LSP Integration.

Language Server Protocol support for real-time diagnostics,
code intelligence, and IDE-like features.
"""

from .client import (
    LSPClient,
    LSPConfig,
    Diagnostic,
    DiagnosticSeverity,
    Location,
    Position,
    Range,
)

__all__ = [
    "LSPClient",
    "LSPConfig",
    "Diagnostic",
    "DiagnosticSeverity",
    "Location",
    "Position",
    "Range",
]
