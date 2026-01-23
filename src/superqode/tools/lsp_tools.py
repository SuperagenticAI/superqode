"""
LSP Tools - Expose Language Server Protocol Operations to Agents.

Provides code intelligence operations through LSP including:
- Go to definition
- Find references
- Hover information (docs, types)
- Document symbols
- Workspace symbols
- Go to implementation
- Call hierarchy

Features:
- Multi-language support via configured language servers
- Async execution for non-blocking operations
- Graceful fallback when LSP unavailable
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, ToolContext


class LSPTool(Tool):
    """
    Language Server Protocol operations tool.

    Exposes LSP capabilities to agents for code intelligence
    features like navigation, symbol lookup, and documentation.

    Operations:
    - goto_definition: Jump to where a symbol is defined
    - find_references: Find all usages of a symbol
    - hover: Get documentation and type information
    - document_symbols: List all symbols in a file
    - workspace_symbols: Search symbols across workspace
    - goto_implementation: Find interface implementations
    - call_hierarchy: Get incoming/outgoing function calls
    """

    # Supported LSP operations
    OPERATIONS = [
        "goto_definition",
        "find_references",
        "hover",
        "document_symbols",
        "workspace_symbols",
        "goto_implementation",
        "call_hierarchy",
    ]

    @property
    def name(self) -> str:
        return "lsp"

    @property
    def description(self) -> str:
        return """Language Server Protocol operations for code intelligence.

Operations:
- goto_definition: Find where a symbol is defined
- find_references: Find all references to a symbol
- hover: Get documentation and type info for symbol at position
- document_symbols: List all symbols (functions, classes, etc.) in a file
- workspace_symbols: Search for symbols across the entire workspace
- goto_implementation: Find implementations of interfaces/abstract classes
- call_hierarchy: Get functions that call or are called by a function"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": self.OPERATIONS,
                    "description": "LSP operation to perform",
                },
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "line": {
                    "type": "integer",
                    "description": "1-based line number (required for position-based operations)",
                },
                "character": {
                    "type": "integer",
                    "description": "1-based column number (required for position-based operations)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for workspace_symbols operation)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["incoming", "outgoing"],
                    "description": "Direction for call_hierarchy (incoming = callers, outgoing = callees)",
                },
            },
            "required": ["operation", "file_path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        operation = args.get("operation", "")
        file_path = args.get("file_path", "")
        line = args.get("line", 1)
        character = args.get("character", 1)
        query = args.get("query", "")
        direction = args.get("direction", "incoming")

        if operation not in self.OPERATIONS:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown operation: {operation}. Valid operations: {', '.join(self.OPERATIONS)}",
            )

        if not file_path:
            return ToolResult(success=False, output="", error="file_path is required")

        # Resolve file path
        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = ctx.working_directory / target_path

        if not target_path.exists() and operation != "workspace_symbols":
            return ToolResult(success=False, output="", error=f"File not found: {file_path}")

        try:
            # Import LSP client
            from superqode.lsp.client import LSPClient, LSPConfig

            client = LSPClient(ctx.working_directory, LSPConfig())

            # Determine language and start server
            language = client._get_language(str(target_path))
            if not language:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"No language server configured for file type: {target_path.suffix}",
                )

            started = await client.start_server(language)
            if not started:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to start language server for {language}",
                )

            # Open the file to initialize
            rel_path = str(target_path.relative_to(ctx.working_directory))
            await client.open_file(rel_path)

            # Wait for initialization
            await asyncio.sleep(0.5)

            # Dispatch to operation handler
            try:
                if operation == "goto_definition":
                    result = await self._goto_definition(
                        client, language, target_path, line, character
                    )
                elif operation == "find_references":
                    result = await self._find_references(
                        client, language, target_path, line, character
                    )
                elif operation == "hover":
                    result = await self._hover(client, language, target_path, line, character)
                elif operation == "document_symbols":
                    result = await self._document_symbols(client, language, target_path)
                elif operation == "workspace_symbols":
                    result = await self._workspace_symbols(client, language, query)
                elif operation == "goto_implementation":
                    result = await self._goto_implementation(
                        client, language, target_path, line, character
                    )
                elif operation == "call_hierarchy":
                    result = await self._call_hierarchy(
                        client, language, target_path, line, character, direction
                    )
                else:
                    result = ToolResult(success=False, output="", error="Operation not implemented")
            finally:
                await client.shutdown()

            return result

        except ImportError:
            return ToolResult(
                success=False,
                output="",
                error="LSP client not available. Install language server dependencies.",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"LSP operation failed: {str(e)}")

    async def _goto_definition(
        self, client: Any, language: str, file_path: Path, line: int, character: int
    ) -> ToolResult:
        """Go to symbol definition."""
        uri = f"file://{file_path}"

        try:
            result = await client._send_request(
                language,
                "textDocument/definition",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line - 1, "character": character - 1},
                },
            )

            if not result:
                return ToolResult(
                    success=True,
                    output="No definition found at this position",
                    metadata={"operation": "goto_definition"},
                )

            # Handle single location or array
            locations = result if isinstance(result, list) else [result]

            output_lines = ["Definitions found:"]
            for loc in locations:
                loc_uri = loc.get("uri", "").replace("file://", "")
                loc_range = loc.get("range", {})
                start = loc_range.get("start", {})
                output_lines.append(
                    f"  {loc_uri}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}"
                )

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"operation": "goto_definition", "count": len(locations)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"goto_definition failed: {str(e)}")

    async def _find_references(
        self, client: Any, language: str, file_path: Path, line: int, character: int
    ) -> ToolResult:
        """Find all references to a symbol."""
        uri = f"file://{file_path}"

        try:
            result = await client._send_request(
                language,
                "textDocument/references",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line - 1, "character": character - 1},
                    "context": {"includeDeclaration": True},
                },
            )

            if not result:
                return ToolResult(
                    success=True,
                    output="No references found",
                    metadata={"operation": "find_references", "count": 0},
                )

            output_lines = [f"References found ({len(result)}):"]
            for loc in result[:50]:  # Limit output
                loc_uri = loc.get("uri", "").replace("file://", "")
                loc_range = loc.get("range", {})
                start = loc_range.get("start", {})
                output_lines.append(
                    f"  {loc_uri}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}"
                )

            if len(result) > 50:
                output_lines.append(f"  ... and {len(result) - 50} more")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"operation": "find_references", "count": len(result)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"find_references failed: {str(e)}")

    async def _hover(
        self, client: Any, language: str, file_path: Path, line: int, character: int
    ) -> ToolResult:
        """Get hover information (docs, types)."""
        uri = f"file://{file_path}"

        try:
            result = await client._send_request(
                language,
                "textDocument/hover",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line - 1, "character": character - 1},
                },
            )

            if not result:
                return ToolResult(
                    success=True,
                    output="No hover information available at this position",
                    metadata={"operation": "hover"},
                )

            contents = result.get("contents", {})

            # Handle different content formats
            if isinstance(contents, str):
                output = contents
            elif isinstance(contents, dict):
                output = contents.get("value", str(contents))
            elif isinstance(contents, list):
                parts = []
                for item in contents:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        parts.append(item.get("value", str(item)))
                output = "\n\n".join(parts)
            else:
                output = str(contents)

            return ToolResult(
                success=True,
                output=f"Hover information:\n{output}",
                metadata={"operation": "hover"},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"hover failed: {str(e)}")

    async def _document_symbols(self, client: Any, language: str, file_path: Path) -> ToolResult:
        """List all symbols in a document."""
        uri = f"file://{file_path}"

        try:
            result = await client._send_request(
                language, "textDocument/documentSymbol", {"textDocument": {"uri": uri}}
            )

            if not result:
                return ToolResult(
                    success=True,
                    output="No symbols found in document",
                    metadata={"operation": "document_symbols", "count": 0},
                )

            # Format symbols
            symbols = self._format_symbols(result)

            return ToolResult(
                success=True,
                output=f"Document symbols ({len(symbols)} top-level):\n" + "\n".join(symbols),
                metadata={"operation": "document_symbols", "count": len(result)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"document_symbols failed: {str(e)}")

    def _format_symbols(self, symbols: List[Dict], indent: int = 0) -> List[str]:
        """Format symbols hierarchically."""
        result = []
        prefix = "  " * indent

        # Symbol kind names
        kind_names = {
            1: "File",
            2: "Module",
            3: "Namespace",
            4: "Package",
            5: "Class",
            6: "Method",
            7: "Property",
            8: "Field",
            9: "Constructor",
            10: "Enum",
            11: "Interface",
            12: "Function",
            13: "Variable",
            14: "Constant",
            15: "String",
            16: "Number",
            17: "Boolean",
            18: "Array",
            19: "Object",
            20: "Key",
            21: "Null",
            22: "EnumMember",
            23: "Struct",
            24: "Event",
            25: "Operator",
            26: "TypeParameter",
        }

        for sym in symbols:
            name = sym.get("name", "unknown")
            kind = sym.get("kind", 0)
            kind_name = kind_names.get(kind, "Unknown")

            # Get range for line number
            sym_range = sym.get("range", sym.get("location", {}).get("range", {}))
            start_line = sym_range.get("start", {}).get("line", 0) + 1

            result.append(f"{prefix}{kind_name}: {name} (line {start_line})")

            # Handle children (DocumentSymbol format)
            children = sym.get("children", [])
            if children:
                result.extend(self._format_symbols(children, indent + 1))

        return result

    async def _workspace_symbols(self, client: Any, language: str, query: str) -> ToolResult:
        """Search for symbols across workspace."""
        try:
            result = await client._send_request(language, "workspace/symbol", {"query": query})

            if not result:
                return ToolResult(
                    success=True,
                    output=f"No symbols found matching '{query}'",
                    metadata={"operation": "workspace_symbols", "count": 0},
                )

            output_lines = [f"Workspace symbols matching '{query}' ({len(result)}):"]

            for sym in result[:50]:  # Limit output
                name = sym.get("name", "unknown")
                kind = sym.get("kind", 0)
                location = sym.get("location", {})
                uri = location.get("uri", "").replace("file://", "")
                sym_range = location.get("range", {})
                start = sym_range.get("start", {})

                output_lines.append(
                    f"  {name} ({self._kind_name(kind)}) - {uri}:{start.get('line', 0) + 1}"
                )

            if len(result) > 50:
                output_lines.append(f"  ... and {len(result) - 50} more")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"operation": "workspace_symbols", "count": len(result)},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"workspace_symbols failed: {str(e)}")

    def _kind_name(self, kind: int) -> str:
        """Get symbol kind name."""
        kind_names = {
            1: "File",
            2: "Module",
            3: "Namespace",
            4: "Package",
            5: "Class",
            6: "Method",
            7: "Property",
            8: "Field",
            9: "Constructor",
            10: "Enum",
            11: "Interface",
            12: "Function",
            13: "Variable",
            14: "Constant",
            15: "String",
            16: "Number",
            17: "Boolean",
            18: "Array",
            19: "Object",
            20: "Key",
            21: "Null",
            22: "EnumMember",
            23: "Struct",
            24: "Event",
            25: "Operator",
            26: "TypeParameter",
        }
        return kind_names.get(kind, "Unknown")

    async def _goto_implementation(
        self, client: Any, language: str, file_path: Path, line: int, character: int
    ) -> ToolResult:
        """Go to implementation of interface/abstract."""
        uri = f"file://{file_path}"

        try:
            result = await client._send_request(
                language,
                "textDocument/implementation",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line - 1, "character": character - 1},
                },
            )

            if not result:
                return ToolResult(
                    success=True,
                    output="No implementations found",
                    metadata={"operation": "goto_implementation", "count": 0},
                )

            locations = result if isinstance(result, list) else [result]

            output_lines = [f"Implementations found ({len(locations)}):"]
            for loc in locations[:50]:
                loc_uri = loc.get("uri", "").replace("file://", "")
                loc_range = loc.get("range", {})
                start = loc_range.get("start", {})
                output_lines.append(
                    f"  {loc_uri}:{start.get('line', 0) + 1}:{start.get('character', 0) + 1}"
                )

            if len(locations) > 50:
                output_lines.append(f"  ... and {len(locations) - 50} more")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"operation": "goto_implementation", "count": len(locations)},
            )

        except Exception as e:
            return ToolResult(
                success=False, output="", error=f"goto_implementation failed: {str(e)}"
            )

    async def _call_hierarchy(
        self, client: Any, language: str, file_path: Path, line: int, character: int, direction: str
    ) -> ToolResult:
        """Get call hierarchy (callers or callees)."""
        uri = f"file://{file_path}"

        try:
            # First, prepare call hierarchy
            prep_result = await client._send_request(
                language,
                "textDocument/prepareCallHierarchy",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line - 1, "character": character - 1},
                },
            )

            if not prep_result:
                return ToolResult(
                    success=True,
                    output="No call hierarchy available at this position",
                    metadata={"operation": "call_hierarchy"},
                )

            items = prep_result if isinstance(prep_result, list) else [prep_result]

            output_lines = []

            for item in items:
                item_name = item.get("name", "unknown")
                output_lines.append(f"Call hierarchy for: {item_name}")

                # Get incoming or outgoing calls
                if direction == "incoming":
                    calls = await client._send_request(
                        language, "callHierarchy/incomingCalls", {"item": item}
                    )
                    label = "Called by"
                else:
                    calls = await client._send_request(
                        language, "callHierarchy/outgoingCalls", {"item": item}
                    )
                    label = "Calls"

                if not calls:
                    output_lines.append(f"  No {direction} calls found")
                else:
                    output_lines.append(f"  {label} ({len(calls)}):")
                    for call in calls[:30]:
                        call_item = call.get("from" if direction == "incoming" else "to", {})
                        call_name = call_item.get("name", "unknown")
                        call_uri = call_item.get("uri", "").replace("file://", "")
                        call_range = call_item.get("range", {})
                        start = call_range.get("start", {})
                        output_lines.append(
                            f"    {call_name} - {call_uri}:{start.get('line', 0) + 1}"
                        )

                    if len(calls) > 30:
                        output_lines.append(f"    ... and {len(calls) - 30} more")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"operation": "call_hierarchy", "direction": direction},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"call_hierarchy failed: {str(e)}")
