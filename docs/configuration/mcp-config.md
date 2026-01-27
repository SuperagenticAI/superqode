# MCP Configuration

Complete guide to configuring Model Context Protocol (MCP) servers in SuperQode.

---

## Overview

MCP servers provide tools and resources that agents can use during QE sessions. SuperQode supports:

- **Stdio Transport**: Local process-based servers
- **HTTP Transport**: HTTP/HTTPS servers
- **SSE Transport**: Server-Sent Events for streaming

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

2. **JSON Configuration** (`.superqode/mcp.json` or `~/.superqode/mcp.json`):
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

**Priority**: YAML configuration takes precedence over JSON.

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

## Per-Role MCP Configuration

Assign MCP servers to specific roles:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          enabled: true
          mcp_servers:
            - filesystem
            - github
            - brave-search

        api_tester:
          enabled: true
          mcp_servers:
            - postgres
            - filesystem
```

---

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
    auto_connect: false  # Manual connection only
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

1. Verify server is enabled:
   ```bash
   superqode providers mcp list
   ```

2. Check server connection:
   ```bash
   superqode providers mcp test filesystem
   ```

3. Verify role has access:
   ```yaml
   team:
     modes:
       qe:
         roles:
           security_tester:
             mcp_servers: [filesystem]  # Explicit list
   ```

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
superqode providers mcp test filesystem
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

**Note**: YAML configuration in `superqode.yaml` takes precedence over JSON configuration.

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

- [MCP Tools](../qe-features/mcp-tools.md) - Using MCP tools in QE
- [YAML Reference](yaml-reference.md) - Complete configuration reference
- [Team Configuration](team.md) - Role-specific MCP assignment
