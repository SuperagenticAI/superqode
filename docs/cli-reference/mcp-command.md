# MCP Command

`superqode mcp` exposes SuperQode harnesses as MCP tools. Any MCP client can
discover and run your HarnessSpec workflows while the harness remains the
portable contract.

```bash
superqode mcp [OPTIONS]
```

This complements ACP and A2A. ACP connects to external coding agents. A2A
connects agent services. MCP exposes your harness workflows as tools.

Without a subcommand this remains the **serving** command. Client subcommands
manage external MCP servers that SuperQode consumes as agent tools; see
[MCP Configuration](../configuration/mcp-config.md).

## Examples

```bash
superqode mcp
superqode mcp --dir ./harnesses
superqode mcp --http --host 127.0.0.1 --port 8765
```

A typical stdio client entry is:

```json
{
  "mcpServers": {
    "superqode": {
      "command": "superqode",
      "args": ["mcp", "--dir", "./harnesses"]
    }
  }
}
```

For a repository-local, runnable MCP consumer example:

```bash
superqode harness run \
  --spec examples/harnesses/mcp-docs.yaml \
  --prompt "Where is HarnessSpec documented?"
```

## Options

| Option | Purpose |
| --- | --- |
| `--http` | Serve over streamable HTTP instead of stdio |
| `--host TEXT` | HTTP host, default `127.0.0.1` |
| `--port INTEGER` | HTTP port, default `8765` |
| `--dir TEXT` | Directory of harness specs |

## Compatibility

| Surface | Implementation in this release | Ownership |
| --- | --- | --- |
| `superqode mcp` / `superqode serve harness` | Standalone FastMCP 3.4.4 over MCP Python SDK v1 | SuperQode |
| Harness `runtime.config.mcp_servers` with `builtin` | SuperQode MCP bridge | SuperQode |
| Harness `runtime.config.mcp_servers` with `openai-agents` | SuperQode tools bridged as SDK function tools | SuperQode |
| PydanticAI MCP configuration | PydanticAI-native MCP toolsets | PydanticAI |
| Codex, Claude, and Copilot MCP configuration | Runtime or local agent configuration | Runtime owner |
| Google ADK MCP configuration | Not yet bridged | SuperQode follow-up |

The production dependency remains on MCP Python SDK v1 while FastMCP 4 and MCP
Python SDK v2 are prerelease. This release therefore preserves the legacy
initialization protocol. Modern stateless MCP will be enabled through FastMCP
after its v4 compatibility matrix passes.

SSE is retained only for legacy MCP servers. Prefer stdio for local servers and
Streamable HTTP for remote servers.

## When To Use It

Use MCP serving when you want Claude Desktop, an IDE, another agent, or an
internal tool to call a SuperQode harness without handing control of the harness
to that client.

HTTP binds to loopback by default. Do not bind to `0.0.0.0` or another
non-loopback address unless an authenticated reverse proxy or equivalent
network access control protects the endpoint. `run_harness` can execute tools
and workflows allowed by the selected HarnessSpec.

Related pages:

- [Harness System](../advanced/harness-system.md)
- [MCP Configuration](../configuration/mcp-config.md)
- [Serve Commands](serve-commands.md)

## Client controls

```bash
sq mcp list
sq mcp list --connect --cwd ./project
sq mcp login SERVER
sq mcp logout SERVER
sq mcp reconnect SERVER
```

All four subcommands accept `--cwd DIRECTORY` and `--config FILE`. They resolve
the shared user/project files and use the same credentials as hosted PiPy.
`list` reports configured state without launching servers; `--connect` checks
live connections. Reports omit server URLs, command arguments and credential
values. Invalid configuration, failed controls and failed requested connections
return a nonzero exit status. Each command closes the transports it owns.
