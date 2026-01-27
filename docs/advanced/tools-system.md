<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Tools System

Comprehensive tool system providing 20+ tools for AI coding agents in SuperQode.

---

## Overview

SuperQode provides a complete tool system for AI agents:

- **20+ tools**: File operations, editing, search, shell, network, diagnostics
- **Transparent**: No hidden prompts or context injection
- **Standard format**: OpenAI-compatible tool definitions
- **Extensible**: Easy to add custom tools
- **Permission system**: Fine-grained access control

---

## Tool Categories

### File Operations

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Write/create file |
| `list_directory` | List directory contents |

### Editing

| Tool | Description |
|------|-------------|
| `edit_file` | Edit file with diff-style changes |
| `insert_text` | Insert text at position |
| `patch` | Apply unified diff patch |
| `multi_edit` | Apply multiple edits atomically |

### Search

| Tool | Description |
|------|-------------|
| `grep` | Text search with regex |
| `glob` | File pattern matching |
| `code_search` | Semantic code search |

### Shell

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (with streaming) |

### Network

| Tool | Description |
|------|-------------|
| `fetch` | HTTP GET request |
| `download` | Download file from URL |
| `web_search` | Web search capability |
| `web_fetch` | Enhanced HTTP fetch |

### Diagnostics

| Tool | Description |
|------|-------------|
| `diagnostics` | LSP diagnostics (linting errors) |

### LSP

| Tool | Description |
|------|-------------|
| `lsp` | Language Server Protocol operations |

### Agent Tools

| Tool | Description |
|------|-------------|
| `sub_agent` | Spawn sub-agent for parallel work |
| `task_coordinator` | Coordinate multiple agents |

### Interactive

| Tool | Description |
|------|-------------|
| `question` | Ask user question during execution |
| `confirm` | Request user confirmation |

### TODO Management

| Tool | Description |
|------|-------------|
| `todo_write` | Write TODO item |
| `todo_read` | Read TODO items |

### Batch Operations

| Tool | Description |
|------|-------------|
| `batch` | Execute multiple tools in parallel |

---

## Tool Registry

### Default Registry

Minimal set of essential tools:

```python
from superqode.tools import ToolRegistry

registry = ToolRegistry.default()
# Includes: read_file, write_file, edit_file, insert_text, bash, grep, glob
```

### Full Registry

All available tools:

```python
registry = ToolRegistry.full()
# Includes all 20+ tools
```

### Custom Registry

Create custom tool sets:

```python
registry = ToolRegistry()
registry.register(ReadFileTool())
registry.register(WriteFileTool())
# ... add tools as needed
```

---

## Tool Format

All tools use OpenAI-compatible format:

```python
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read contents of a file",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to file"
        }
      },
      "required": ["path"]
    }
  }
}
```

---

## Permission System

Fine-grained permission control:

### Permission Levels

| Level | Description |
|-------|-------------|
| `ALLOW` | Always allow execution |
| `DENY` | Block execution |
| `ASK` | Prompt user for confirmation |

### Tool Groups

Tools organized into groups:

- **READ**: `read_file`, `list_directory`, `grep`, `glob`
- **WRITE**: `write_file`, `edit_file`, `insert_text`, `patch`
- **SHELL**: `bash`
- **NETWORK**: `fetch`, `download`, `web_search`
- **DIAGNOSTICS**: `diagnostics`
- **SEARCH**: `code_search`
- **AGENT**: `sub_agent`, `task_coordinator`

### Permission Configuration

```yaml
tools:
  permissions:
    read: allow
    write: ask
    shell: ask
    network: deny
```

---

## Tool Execution

### Tool Result

Every tool returns a `ToolResult`:

```python
class ToolResult:
    success: bool
    content: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
```

### Error Handling

Tools handle errors gracefully:

- **File not found**: Returns error in result
- **Permission denied**: Returns error (no exception)
- **Invalid input**: Validates before execution

---

## Advanced Features

### Caching

Tool results can be cached:

```python
@cacheable(ttl=300.0)
def read_file(self, path: str) -> ToolResult:
    # Results cached for 5 minutes
    ...
```

### Metrics Tracking

Track tool usage:

```python
registry.get_execution_history(limit=100)
registry.get_tool_metrics()
```

### Batch Execution

Execute multiple tools in parallel:

```python
result = await batch_tool.execute([
    {"tool": "read_file", "args": {"path": "file1.py"}},
    {"tool": "read_file", "args": {"path": "file2.py"}},
])
```

---

## Tool Examples

### Read File

```python
result = read_file_tool.execute({
    "path": "src/api/users.py"
})

if result.success:
    content = result.content
```

### Edit File

```python
result = edit_file_tool.execute({
    "path": "src/api/users.py",
    "old_string": "def get_user(id):",
    "new_string": "def get_user(user_id: int):"
})
```

### Grep Search

```python
result = grep_tool.execute({
    "pattern": "def get_user",
    "path": "src/",
    "recursive": True
})

# Returns: List of matches with file paths and line numbers
```

### Bash Command

```python
result = bash_tool.execute({
    "command": "python -m pytest tests/",
    "cwd": "/path/to/project"
})

# Supports streaming output
```

### Diagnostics

```python
result = diagnostics_tool.execute({
    "path": "src/api/users.py"
})

# Returns: LSP diagnostics (errors, warnings)
```

---

## Custom Tools

### Creating a Tool

```python
from superqode.tools import Tool, ToolResult

class CustomTool(Tool):
    name = "custom_tool"
    description = "Custom tool description"

    def execute(self, args: Dict[str, Any], context: ToolContext) -> ToolResult:
        # Implementation
        return ToolResult(
            success=True,
            content="Result"
        )
```

### Registering a Tool

```python
registry = ToolRegistry()
registry.register(CustomTool())
```

---

## Best Practices

### 1. Use Appropriate Tools

- **Read-only tasks**: Use `read_file`, `grep`, `list_directory`
- **File edits**: Use `edit_file` or `patch` (not `write_file`)
- **Search**: Use `grep` for text, `code_search` for semantic

### 2. Handle Errors

Always check `ToolResult.success`:

```python
result = tool.execute(args)
if not result.success:
    print(f"Error: {result.error}")
```

### 3. Use Permissions

Configure permissions for safety:

```yaml
tools:
  permissions:
    write: ask  # Confirm before file edits
    shell: ask  # Confirm before shell commands
```

### 4. Batch When Possible

Use `batch` tool for parallel operations:

```python
# Faster than sequential execution
batch_tool.execute([tool1, tool2, tool3])
```

---

## Troubleshooting

### Tool Not Found

**Symptom**: Tool not in registry

**Solution**: Use `ToolRegistry.full()` or register manually

### Permission Denied

**Symptom**: Tool execution blocked

**Solution**: Check permission configuration:

```yaml
tools:
  permissions:
    write: allow  # Or 'ask' for confirmation
```

### Tool Errors

**Symptom**: Tool returns error

**Solution**: Check `ToolResult.error` for details

---

## Related Features

- [QE Features](../qe-features/index.md) - QE tool usage

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Tool Reference](https://github.com/Shashikant86/superqode/tree/14dc05cf7ae0fbf95b55c33078b1852a45f10fc0/src/superqode/tools) - Tool source code
