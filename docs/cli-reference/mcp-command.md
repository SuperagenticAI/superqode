# MCP Command

`superqode mcp` exposes SuperQode harnesses as MCP tools. Any MCP client can
discover and run your HarnessSpec workflows while the harness remains the
portable contract.

```bash
superqode mcp [OPTIONS]
```

This complements ACP and A2A. ACP connects to external coding agents. A2A
connects agent services. MCP exposes your harness workflows as tools.

## Examples

```bash
superqode mcp
superqode mcp --dir ./harnesses
superqode mcp --http --host 127.0.0.1 --port 8765
```

## Options

| Option | Purpose |
| --- | --- |
| `--http` | Serve over streamable HTTP instead of stdio |
| `--host TEXT` | HTTP host, default `127.0.0.1` |
| `--port INTEGER` | HTTP port, default `8765` |
| `--dir TEXT` | Directory of harness specs |

## When To Use It

Use MCP serving when you want Claude Desktop, an IDE, another agent, or an
internal tool to call a SuperQode harness without handing control of the harness
to that client.

Related pages:

- [Harness System](../advanced/harness-system.md)
- [MCP Configuration](../configuration/mcp-config.md)
- [Serve Commands](serve-commands.md)

