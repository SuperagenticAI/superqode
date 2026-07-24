# Serve Commands

Expose SuperQode to other tools: an ACP agent for editors and benchmarks, an MCP server for your harnesses, and a browser-based TUI. A2A serving is available through the Python API.

---

## Servers at a glance

| Surface | Command | Who connects |
|---------|---------|--------------|
| ACP | `superqode serve acp` | Any ACP client: Zed, JetBrains IDEs, Neovim, Devin Desktop, and the Harbor benchmark framework. Runs SuperQode as the coding agent, driven by your HarnessSpec. |
| MCP | `superqode mcp` | Any MCP client (Claude Desktop, IDEs, other agents). Exposes your HarnessSpec workflows as `list_harnesses`, `describe_harness`, and `run_harness` tools. |
| Harness MCP alias | `superqode serve harness --spec harness.yaml` | Same MCP server, shaped around one harness file or directory. |
| Local Session API | `superqode serve api` | Browser/mobile companions and local tools that inspect or drive the switchboard and Software Factory graph. |
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

## serve acp

Run SuperQode as an ACP agent on stdio, for Zed, JetBrains IDEs, Neovim, and Harbor/Terminal-Bench:

```bash
superqode serve acp                       # per-session harness discovery
superqode serve acp --spec harness.yaml   # pin one HarnessSpec
```

| Option | Description |
|--------|-------------|
| `--spec` | HarnessSpec file to use for all sessions |
| `--dir` | Directory of harness specs for discovery |
| `--provider` | Provider override (env: `SUPERQODE_ACP_PROVIDER`) |
| `--model` | Model override (env: `SUPERQODE_ACP_MODEL`) |

`SUPERQODE_ACP_SPEC` accepts a spec path or `template:<name>` for a built-in template. stdout carries JSON-RPC, so human-facing output goes to stderr. See the full guide: [ACP Agent Server](../advanced/acp-agent-server.md).

---

## serve harness

Expose harness workflows as MCP tools with a command that reads like harness-as-a-service:

```bash
superqode serve harness --spec harness.yaml
superqode serve harness --dir ./harnesses --http --port 8765
```

`--spec` serves the containing directory so relative `inherits` paths keep working; use the file stem as the harness name.

---

## serve api

Serve the local switchboard and Software Factory graph over JSON HTTP.

```bash
superqode serve api --port 8766
superqode serve api --host 0.0.0.0 --allow-remote --token "$SUPERQODE_API_TOKEN"
```

Options:

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8766`) |
| `--storage-dir` | Session storage directory (default: `.superqode/sessions`) |
| `--allow-remote` | Allow binding outside localhost |
| `--token` | Optional bearer token |

Useful endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `GET /sessions` | List graph sessions |
| `GET /sessions/graph` | Session switchboard tree |
| `GET /sessions/{id}/history` | Recent transcript messages |
| `POST /sessions/{id}/switch` | Mark a session active |
| `POST /sessions/{id}/handoff` | Create or deliver a handoff |
| `GET /factory/routes` | List Software Factory routes |
| `GET /sessions/{id}/factory` | Factory metadata for a session |
| `POST /sessions/{id}/factory/model` | Record a model/provider switch |
| `POST /sessions/{id}/factory/harness` | Record a harness switch |
| `POST /sessions/{id}/factory/mode` | Set a route such as `no-subscription` |

Remote serving should use `--token` and a trusted network.

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

---

## serve status

Inspect server integrations supplied by the optional SuperQode Enterprise
package.

```bash
superqode serve status
```

The open-source package reports that this surface requires the Enterprise
package. The open-source `serve acp`, `serve harness`, `serve api`, and
`serve web` commands remain available as documented above.
