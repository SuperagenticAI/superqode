# Serve Commands

Expose SuperQode over the network: a browser-based TUI and an MCP server for your harnesses. A2A serving is available through the Python API.

---

## Servers at a glance

| Surface | Command | Who connects |
|---------|---------|--------------|
| MCP | `superqode mcp` | Any MCP client (Claude Desktop, IDEs, other agents). Exposes your HarnessSpec workflows as `list_harnesses`, `describe_harness`, and `run_harness` tools. |
| Harness MCP alias | `superqode serve harness --spec harness.yaml` | Same MCP server, shaped around one harness file or directory. |
| Web TUI | `superqode serve web` | A browser, for the full TUI without a terminal emulator. |
| A2A | `create_a2a_server()` (Python API) | Other agents and orchestrators over the Agent-to-Agent protocol. See [A2A Providers](../providers/a2a.md). |

---

## mcp

Serve your harness specs over MCP, on stdio by default:

```bash
superqode mcp                                  # stdio (for MCP client configs)
superqode mcp --http --host 0.0.0.0 --port 8765
superqode mcp --dir ./harnesses                # serve specs from a directory
```

| Option | Description |
|--------|-------------|
| `--http` | Serve over streamable HTTP instead of stdio |
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8765`) |
| `--dir` | Directory of harness specs to expose |

A typical MCP client configuration entry:

```json
{
  "mcpServers": {
    "superqode": {
      "command": "superqode",
      "args": ["mcp"]
    }
  }
}
```

---

## serve harness

Expose harness workflows as MCP tools with a command that reads like harness-as-a-service:

```bash
superqode serve harness --spec harness.yaml
superqode serve harness --dir ./harnesses --http --port 8765
```

`--spec` serves the containing directory so relative `inherits` paths keep working; use the file stem as the harness name.

---

## serve web

Start the Textual TUI server over HTTP.

```bash
superqode serve web [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8000`) |

### Examples

```bash
superqode serve web
superqode serve web --host 0.0.0.0 --port 8080
```

Uses `textual-serve` to expose the full SuperQode TUI over HTTP. Open the provided URL in a browser for a terminal-like experience without a local terminal emulator.
