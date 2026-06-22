# SuperQode LSP Integration

## Overview

The `superqode.lsp` module implements a minimal but functional LSP client that communicates with external language servers over stdin/stdout using JSON-RPC 2.0. Ships with defaults for Python, TypeScript, JavaScript, Go, Rust, C, and C++.

## Public API

### LSPConfig

Fields:

- `servers` (`Dict[str, List[str]]`): maps language to server command
- `extensions` (`Dict[str, str]`): maps file extension to language
- `timeout` (`float`, default `10.0`)

Default servers:

- python -> `pyright-langserver`
- typescript/javascript -> `typescript-language-server`
- go -> `gopls`
- rust -> `rust-analyzer`
- c/cpp -> `clangd`

### LSPClient

- `async start_server(language)` -- start language server process
- `async open_file(file_path)` -- open a file (auto-starts server)
- `async close_file(file_path)` -- close a file
- `async update_file(file_path, content)` -- notify server of content changes
- `async get_diagnostics(file_path)` -- get cached diagnostics for a file
- `async get_all_diagnostics()` -- get all cached diagnostics
- `on_diagnostics(callback)` -- register callback for live diagnostics
- `async shutdown()` -- shut down all servers

### Supporting Types

- `DiagnosticSeverity`: `ERROR` (1), `WARNING` (2), `INFORMATION` (3), `HINT` (4)
- `Position`: `line`, `character` (zero-based)
- `Range`: `start`, `end` (Position)
- `Location`: `uri`, `range`
- `Diagnostic`: `range`, `message`, `severity`, `code`, `source`, `related_information`

## Quick Start

```python
import asyncio
from pathlib import Path
from superqode.lsp import LSPClient

async def main():
    async with LSPClient(Path("/path/to/project")) as client:
        await client.open_file("src/main.py")
        diags = await client.get_diagnostics("src/main.py")
        for d in diags:
            print(f"{d.severity_name}: {d.message}")

asyncio.run(main())
```

## One-Shot Convenience

```python
from superqode.lsp import get_file_diagnostics
diags = asyncio.run(get_file_diagnostics(Path("~/myproject"), "src/lib.rs"))
```

## Language Server Requirements

Each language needs its language server on PATH:

- **Python**: `pyright-langserver` (`npm install -g pyright` or `uv pip install pyright`)
- **TypeScript/JavaScript**: `typescript-language-server` (`npm install -g typescript-language-server`)
- **Go**: `gopls` (`go install golang.org/x/tools/gopls@latest`)
- **Rust**: `rust-analyzer` (`rustup component add rust-analyzer`)
- **C/C++**: `clangd` (via LLVM/Clang package)

## Design

- Stdlib only: no external Python dependencies
- Async with asyncio
- Thread-based reader per server process
- Configurable request timeout (default 10s)
- Context manager support for safe teardown

## Limitations

What is NOT implemented: code completion, hover, go-to-definition (capability declared but no public method). Designed for diagnostics-focused integration.
