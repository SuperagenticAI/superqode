# MCP Tools Integration

Integrate Model Context Protocol (MCP) servers to extend SuperQode with external tools, resources, and prompts.

---

## Overview

MCP (Model Context Protocol) is a standard protocol for connecting AI applications to external tools and services. SuperQode includes full MCP client support, allowing QE agents to use tools from MCP servers during quality engineering sessions.

### Capabilities

- **Tool Execution**: Agents can call tools from MCP servers
- **Resource Access**: Read files, databases, APIs via MCP resources
- **Prompt Templates**: Use MCP prompt templates in QE workflows
- **Multi-Server**: Connect to multiple MCP servers simultaneously
- **Auto-Discovery**: Tools, resources, and prompts automatically discovered on connection

---

## What is MCP?

MCP is a protocol standard (aligned with Zed editor's implementation) that enables:

- **Tools**: Executable functions (e.g., file operations, API calls, code analysis)
- **Resources**: Readable data sources (e.g., files, databases, configuration)
- **Prompts**: Reusable prompt templates with arguments

MCP servers expose these capabilities, and SuperQode agents can use them during QE sessions.

---

## Transport Types

SuperQode supports three transport types for MCP servers:

### stdio (Default)

Local process communication via stdin/stdout:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem", "--root", "."]
    }
  }
}
```

**Use case**: Local MCP servers installed on your system

### HTTP

HTTP-based communication with streaming support:

```json
{
  "mcpServers": {
    "remote-server": {
      "transport": "http",
      "url": "https://mcp.example.com/api",
      "headers": {
        "Authorization": "Bearer token"
      }
    }
  }
}
```

**Use case**: Remote MCP servers accessible via HTTP

### SSE

Server-Sent Events for real-time streaming:

```json
{
  "mcpServers": {
    "realtime-server": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "sse_read_timeout": 300.0
    }
  }
}
```

**Use case**: Real-time updates and streaming responses

---

## Configuration

### Config File Location

MCP server configurations are stored in:

1. `.superqode/mcp.json` (project directory)
2. `~/.superqode/mcp.json` (user home)
3. `~/.config/superqode/mcp.json` (user config)

SuperQode searches in this order and uses the first file found.

### Configuration Format

```json
{
  "mcpServers": {
    "server-id": {
      "name": "Server Name",
      "description": "Server description",
      "transport": "stdio",
      "enabled": true,
      "autoConnect": true,
      "command": "command-to-run",
      "args": ["arg1", "arg2"],
      "env": {
        "VAR": "value"
      }
    }
  }
}
```

### stdio Configuration

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem", "--root", "."],
      "env": {
        "LOG_LEVEL": "info"
      },
      "cwd": "/path/to/working/dir",
      "timeout": 30.0
    }
  }
}
```

**Options**:
- `command`: Executable command
- `args`: Command arguments
- `env`: Environment variables
- `cwd`: Working directory
- `timeout`: Connection timeout (seconds)

### HTTP Configuration

```json
{
  "mcpServers": {
    "api-server": {
      "transport": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer token",
        "X-API-Key": "key"
      },
      "timeout": 30.0,
      "sse_read_timeout": 300.0
    }
  }
}
```

**Options**:
- `url`: HTTP endpoint URL
- `headers`: HTTP headers
- `timeout`: Request timeout (seconds)
- `sse_read_timeout`: SSE read timeout (seconds)

### SSE Configuration

```json
{
  "mcpServers": {
    "streaming-server": {
      "transport": "sse",
      "url": "https://stream.example.com/sse",
      "headers": {
        "Authorization": "Bearer token"
      },
      "timeout": 5.0,
      "sse_read_timeout": 300.0
    }
  }
}
```

---

## Server Management

### Enable/Disable Servers

```json
{
  "mcpServers": {
    "server-id": {
      "enabled": true,  // Enable/disable server
      "autoConnect": true  // Auto-connect on startup
    }
  }
}
```

### Multiple Servers

Connect to multiple servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem"]
    },
    "github": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-github", "--token", "${GITHUB_TOKEN}"]
    },
    "database": {
      "transport": "http",
      "url": "https://db.example.com/mcp"
    }
  }
}
```

---

## Tool Discovery

When an MCP server connects, SuperQode automatically discovers:

- **Tools**: Available tool functions
- **Resources**: Available resources
- **Prompts**: Available prompt templates

Tools are made available to QE agents with the naming convention:

```
mcp_{server_id}_{tool_name}
```

For example, `mcp_filesystem_read_file` or `mcp_github_create_issue`.

---

## Tool Execution

### Agent Usage

Agents automatically see and can use MCP tools during QE sessions. Tools are discovered and listed alongside built-in SuperQode tools.

### Tool Result Formatting

MCP tool results are automatically formatted for agent consumption:

```python
# Tool executed via MCP
result = await execute_mcp_tool("mcp_filesystem_read_file", {
    "path": "src/api/users.py"
})

# Result formatted for agent
# - Success/failure status
# - Content/error messages
# - Structured data when available
```

---

## Example Servers

### Filesystem Server

Access local filesystem:

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem", "--root", "."],
      "enabled": false  // Disabled by default for security
    }
  }
}
```

### GitHub Server

GitHub integration:

```json
{
  "mcpServers": {
    "github": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-github", "--token", "${GITHUB_TOKEN}"]
    }
  }
}
```

### Database Server

Database access via HTTP:

```json
{
  "mcpServers": {
    "database": {
      "transport": "http",
      "url": "https://db.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${DB_TOKEN}"
      }
    }
  }
}
```

---

## Environment Variables

Use environment variables in configuration:

```json
{
  "mcpServers": {
    "github": {
      "command": "uvx",
      "args": ["mcp-server-github", "--token", "${GITHUB_TOKEN}"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

Variables are resolved from your environment at runtime.

---

## Connection States

MCP servers have connection states:

| State | Description |
|-------|-------------|
| **DISCONNECTED** | Not connected |
| **CONNECTING** | Connection in progress |
| **CONNECTED** | Successfully connected |
| **ERROR** | Connection failed |

---

## TUI Commands

In the SuperQode TUI, use MCP commands:

```
:mcp list          # List all MCP servers
:mcp status        # Show connection status
:mcp tools         # List available tools
:mcp connect <id>  # Connect to server
:mcp disconnect <id> # Disconnect from server
```

---

## Capabilities

MCP servers can provide:

- **Tools**: Executable functions
- **Resources**: Readable data sources
- **Prompts**: Prompt templates
- **Completions**: Code completion support
- **Logging**: Server-side logging
- **Experimental**: Experimental features

SuperQode checks server capabilities and enables features accordingly.

---

## Resource Access

MCP resources provide read-only access to data:

```python
# Read resource via MCP
content = await manager.read_resource("server-id", "resource://path/to/data")
```

Resources can be:
- File contents
- Database queries
- API responses
- Configuration data

---

## Prompt Templates

MCP prompts are reusable prompt templates:

```python
# Get prompt template
prompt = await manager.get_prompt("server-id", "prompt-id", {
    "arg1": "value1"
})
```

Prompts can include:
- System prompts
- User message templates
- Argument completion
- Dynamic content

---

## Best Practices

### 1. Security

Disable untrusted servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": false  // Disable if not needed
    }
  }
}
```

### 2. Environment Variables

Use environment variables for secrets:

```json
{
  "args": ["--token", "${GITHUB_TOKEN}"]
}
```

Never hardcode secrets in config files.

### 3. Auto-Connect

Control auto-connection:

```json
{
  "autoConnect": true  // Connect on startup
  "autoConnect": false // Manual connection only
}
```

### 4. Error Handling

Check connection status before using tools:

```python
if manager.get_connection_state("server-id") == MCPConnectionState.CONNECTED:
    # Use tools
```

### 5. Timeouts

Set appropriate timeouts:

```json
{
  "timeout": 30.0,  // Request timeout
  "sse_read_timeout": 300.0  // SSE read timeout
}
```

---

## Troubleshooting

### Connection Failed

**Symptom**: Server fails to connect

**Solutions**:
1. Check `command` path is correct
2. Verify server is installed
3. Check `timeout` setting
4. Review server logs

### Tools Not Available

**Symptom**: Tools not discovered

**Solutions**:
1. Verify server is connected
2. Check server capabilities include `tools`
3. Review tool discovery logs

### Timeout Errors

**Symptom**: Requests timeout

**Solutions**:
```json
{
  "timeout": 60.0  // Increase timeout
}
```

---

## Integration with QE

MCP tools are automatically available to QE agents:

1. **Tool Discovery**: Tools discovered on connection
2. **Agent Access**: Agents can call tools during QE
3. **Result Formatting**: Results formatted for agent use
4. **Error Handling**: Errors handled gracefully

---

## Related Features

- [MCP Configuration](../configuration/mcp-config.md) - MCP usage and settings
- [Configuration](../configuration/yaml-reference.md) - Config reference
- [QE Features Index](index.md) - All QE features

---

## Next Steps

- [MCP Configuration](../configuration/mcp-config.md) - Detailed config guide
- [MCP Configuration](../configuration/mcp-config.md) - MCP patterns and settings
