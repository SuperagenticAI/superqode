# MCP Configuration

Complete guide to configuring Model Context Protocol (MCP) servers in SuperQode.

---

## Overview

MCP servers provide tools and resources that agents can use during SuperQode sessions and harness runs. SuperQode supports:

- **Stdio Transport**: Local process-based servers
- **HTTP Transport**: Streamable HTTP servers
- **SSE Transport**: Legacy Server-Sent Events servers

This page describes SuperQode **consuming** external MCP servers. To expose
HarnessSpec workflows as an MCP server, use [`superqode mcp`](../cli-reference/mcp-command.md).

---

## Configuration Location

MCP servers can be configured in two ways:

1. **YAML Configuration** (`superqode.yaml`):
   ```yaml
   mcp_servers:
     filesystem:
       transport: stdio
       command: npx
       args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
   ```

2. **JSON Configuration** (`.superqode/mcp.json`, `~/.superqode/mcp.json`, or `~/.config/superqode/mcp.json`):
   ```json
   {
     "mcpServers": {
       "filesystem": {
         "transport": "stdio",
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
       }
     }
   }
   ```

The shared resolver merges files in this order, from lowest to highest priority:

1. `~/.config/superqode/mcp.json`
2. `~/.superqode/mcp.json`
3. `<working-directory>/.superqode/mcp.json`
4. Harness `runtime.config.mcp_servers` (or `runtime.config.mcp`) entries

A higher-priority server declaration replaces the whole earlier declaration.
Disabled or invalid overrides do not silently enable an older entry. Working
directories are resolved when configuration is loaded. Stdio servers default to
the harness working directory. `${NAME}` references are substituted in environment
values and HTTP headers; commands are not shell-expanded.

Set `runtime.config.mcp_config: false` for inline-only harness configuration,
or set it to a file path to use one explicit JSON file plus inline overrides.
Relative paths resolve against the harness working directory. This resolver is
shared by hosted PiPy, native MCP clients and SuperQode's harness MCP bridge;
vendor SDKs can retain their own configuration paths.

ACP sessions receive enabled JSON definitions when a new session is created.
Top-level YAML definitions remain available to native client sessions.

### Web Fetch for ACP Agents

SuperQode's built-in `fetch` and `web_fetch` tools are available to the default SuperQode runtime. ACP agents such as OpenCode need fetch exposed through MCP. Add an enabled fetch server to one of the JSON MCP config locations:

```json
{
  "mcpServers": {
    "fetch": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "enabled": true
    }
  }
}
```

Restart the ACP connection after editing this file. Existing ACP sessions keep the MCP server list they received at session creation.

---

## Transport Types

### Stdio Transport

Local process-based servers (most common):

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    auto_connect: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "."
    env:
      NODE_ENV: production
    cwd: /path/to/workspace
    timeout: 30.0
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `transport` | `"stdio"` | Transport type |
| `enabled` | boolean | Whether server is enabled |
| `auto_connect` | boolean | Auto-connect on startup |
| `command` | string | Executable command |
| `args` | array | Command arguments |
| `env` | object | Environment variables |
| `cwd` | string | Working directory |
| `timeout` | number | Connection timeout (seconds) |

### Semantic Code Search MCP

For AST-aware semantic repository search, install `ccc` and run
`cocoindex-code` as a stdio MCP server:

```bash
uv tool install 'cocoindex-code'
```

```yaml
mcp_servers:
  cocoindex-code:
    transport: stdio
    enabled: true
    auto_connect: true
    command: ccc
    args: ["mcp"]
    cwd: /path/to/workspace
```

Run `ccc init --litellm-model ollama/nomic-embed-text` and `ccc index` in the
workspace first if you want local Ollama embeddings. The MCP server exposes a
semantic `search` tool with `query`, `limit`, `offset`, `languages`, `paths`,
and `refresh_index`.

For local laptops, note that `ccc mcp` starts a background index task and its
search tool refreshes the index by default. For repeated searches after a manual
`ccc index`, pass `refresh_index=false` to keep calls lightweight. See
[Semantic Code Search](../advanced/semantic-search.md) for the native
`semantic_search` tool, MCP tradeoffs, and local-model setup.

### HTTP Transport

HTTP/HTTPS servers for remote or containerized MCP servers:

```yaml
mcp_servers:
  database:
    transport: http
    enabled: true
    auto_connect: true
    url: http://localhost:8080/mcp
    headers:
      Authorization: "Bearer ${MCP_DB_TOKEN}"
    timeout: 30.0
    sse_read_timeout: 300.0
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `transport` | `"http"` | Transport type |
| `enabled` | boolean | Whether server is enabled |
| `auto_connect` | boolean | Auto-connect on startup |
| `url` | string | Server URL |
| `headers` | object | HTTP headers |
| `timeout` | number | Request timeout (seconds) |
| `sse_read_timeout` | number | SSE read timeout (seconds) |

### SSE Transport

Server-Sent Events for streaming responses:

```yaml
mcp_servers:
  streaming:
    transport: sse
    enabled: true
    url: http://localhost:8080/mcp/events
    headers:
      Authorization: "Bearer ${TOKEN}"
    timeout: 5.0
    sse_read_timeout: 300.0
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `transport` | `"sse"` | Transport type |
| `enabled` | boolean | Whether server is enabled |
| `auto_connect` | boolean | Auto-connect on startup |
| `url` | string | SSE endpoint URL |
| `headers` | object | HTTP headers |
| `timeout` | number | Connection timeout (seconds) |
| `sse_read_timeout` | number | SSE read timeout (seconds) |

---

## Common MCP Servers

### Filesystem Server

Access local file system:

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "."
```

### GitHub Server

Interact with GitHub repositories:

```yaml
mcp_servers:
  github:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

### PostgreSQL Server

Query PostgreSQL databases:

```yaml
mcp_servers:
  postgres:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-postgres"
    env:
      POSTGRES_CONNECTION_STRING: "${POSTGRES_CONNECTION_STRING}"
```

### Slack Server

Interact with Slack:

```yaml
mcp_servers:
  slack:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-slack"
    env:
      SLACK_BOT_TOKEN: "${SLACK_BOT_TOKEN}"
      SLACK_TEAM_ID: "${SLACK_TEAM_ID}"
```

### Brave Search Server

Search the web:

```yaml
mcp_servers:
  brave-search:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-brave-search"
    env:
      BRAVE_API_KEY: "${BRAVE_API_KEY}"
```

---

## MCP Server Assignment

MCP ownership depends on the selected runtime:

| Runtime path | How MCP servers are attached |
| --- | --- |
| Hosted PiPy, `builtin` HarnessSpec | Shared JSON files plus inline runtime declarations |
| `openai-agents` HarnessSpec | SuperQode bridges discovered MCP tools as SDK function tools |
| PydanticAI | Uses its native MCP configuration path |
| Codex, Claude, and Copilot SDKs | Uses the runtime's local MCP configuration |
| ACP coding agents | SuperQode forwards enabled JSON MCP definitions during session creation |
| Google ADK | MCP tools are not bridged yet |

Project-level `mcp_servers` definitions are available to SuperQode-managed
client sessions, but they are not automatically injected into every vendor SDK.
Use the runtime-specific documentation when the runtime owns its MCP lifecycle.

### Runnable Harness Example

The repository includes a local FastMCP documentation server and a HarnessSpec
that consumes it over stdio:

```bash
superqode harness run \
  --spec examples/harnesses/mcp-docs.yaml \
  --prompt "Find the documentation for MCP serving"
```

The example server is
`examples/mcp/local_docs_server.py`. Its tool is exposed to the harness as
`mcp_docs_search_docs`.

## Environment Variables

Use environment variables in MCP configuration:

```yaml
mcp_servers:
  github:
    transport: stdio
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"  # Will read from $GITHUB_TOKEN
```

**Variable Resolution:**

- `${VAR_NAME}`: Reads from environment
- Default values: `${VAR_NAME:-default}` (not supported, use explicit env vars)

---

## Enabling/Disabling Servers

### Enable All Servers

```yaml
mcp_servers:
  filesystem:
    enabled: true
  github:
    enabled: true
```

### Disable Specific Server

```yaml
mcp_servers:
  filesystem:
    enabled: false  # Server defined but disabled
  github:
    enabled: true
```

### Auto-Connect Control

```yaml
mcp_servers:
  filesystem:
    enabled: true
    auto_connect: true   # Connect on startup
  github:
    enabled: true
    auto_connect: false  # Connect on demand
```

---

## Troubleshooting

### Server Not Starting

**Problem**: MCP server fails to start

**Solution**: Check command and environment:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env:
      DEBUG: "1"  # Enable debug logging
```

### Connection Timeout

**Problem**: Server connection times out

**Solution**: Increase timeout:

```yaml
mcp_servers:
  database:
    transport: http
    url: http://localhost:8080/mcp
    timeout: 60.0  # Increase from default 30.0
```

### Tools Not Available

**Problem**: MCP tools not showing up

**Solution**:

1. Verify the project configuration is valid:
   ```bash
   superqode config validate
   ```

2. Start SuperQode or the harness MCP server and watch startup output for MCP
   connection errors:
   ```bash
   superqode
   superqode mcp --dir ./harnesses
   ```

3. Verify the configured MCP server command works outside SuperQode. For stdio
   servers, run the configured command directly and check that it starts.

---

## Best Practices

### 1. Use Auto-Connect Selectively

Enable auto-connect only for frequently used servers:

```yaml
mcp_servers:
  filesystem:
    auto_connect: true   # Always needed

  github:
    auto_connect: false  # Only when working with GitHub
```

### 2. Organize by Purpose

Group related servers:

```yaml
# Development servers
mcp_servers:
  filesystem: {...}
  git: {...}

# External services
mcp_servers:
  github: {...}
  slack: {...}
  database: {...}
```

### 3. Use Environment Variables

Never hardcode secrets:

```yaml
mcp_servers:
  github:
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"  # [CORRECT] Good
      # GITHUB_TOKEN: "ghp_..."        # [INCORRECT] Bad
```

### 4. Test Connections

Verify servers work before using:

```bash
superqode config validate
superqode mcp --dir ./harnesses
```

---

## JSON Configuration Format

MCP servers can also be configured in JSON format:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "enabled": true,
      "autoConnect": true,
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "."
      ],
      "env": {
        "NODE_ENV": "production"
      },
      "timeout": 30.0
    }
  }
}
```

**Note**: Hosted harness inline declarations override shared JSON entries as described above.

---

## Advanced Configuration

### Multiple Instances

Run multiple instances of the same server:

```yaml
mcp_servers:
  filesystem-workspace:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]

  filesystem-home:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "~"]
```

### Custom Working Directory

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    cwd: /path/to/project  # Override working directory
```

### Custom Headers for HTTP

```yaml
mcp_servers:
  api:
    transport: http
    url: https://api.example.com/mcp
    headers:
      Authorization: "Bearer ${API_TOKEN}"
      X-API-Version: "v2"
      User-Agent: "SuperQode/1.0"
```

---

## Next Steps

- [YAML Reference](yaml-reference.md) - Complete configuration reference

## Inspect and refresh connections

```bash
sq mcp list --cwd ./project
sq mcp list --connect --cwd ./project
sq mcp login SERVER
sq mcp logout SERVER
sq mcp reconnect SERVER
```

In the TUI, `:mcp reload` reloads configuration and disconnects removed or changed
servers before reconnecting. `:mcp login SERVER` and `:mcp logout SERVER` use the
shared OAuth store. Login may open an authorization browser when the server
requires OAuth. Configuration reports omit credentials and endpoint URLs.
