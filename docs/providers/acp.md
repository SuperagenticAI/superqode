# ACP Agents

Agent Client Protocol (ACP) mode connects SuperQode to full-featured coding agents.

---

## Overview

ACP agents provide:

- **Full capabilities**: File editing, shell execution, MCP tools
- **Structured prompting**: Optimized for coding tasks
- **Tool integration**: Access to development environment
- **Persistent context**: Maintains state across operations

---

## Quick Start

```bash
# Connect to OpenCode
superqode connect acp opencode
```

---

## Supported Agents

Use `superqode agents list --protocol acp` to see the current list (it’s driven by the built‑in agent registry and any local agent definitions).

### OpenCode

[OpenCode](https://github.com/opencode/opencode) is the primary ACP agent:

```bash
# Install OpenCode
npm i -g opencode-ai

# Verify installation
opencode --version

# Connect via SuperQode
superqode connect acp opencode
```

#### Capabilities

| Capability | Description |
|------------|-------------|
| `file_editing` | Create, read, edit files |
| `shell_execution` | Run shell commands |
| `mcp_tools` | Use MCP servers |
| `git_operations` | Git commands |

---

### Other ACP-Compatible Agents

SuperQode includes registry entries for these ACP agents (availability depends on local installation):

- **Claude Code** (ACP adapter: `claude-code-acp`)
- **Codex** (ACP adapter: `npx @openai/codex-acp` or `codex-acp`)
- **OpenHands** (`openhands acp`)
- **Gemini CLI** (`gemini --experimental-acp`)
- **Goose** (`goose`)
- **Kimi CLI** (`kimi --acp`)
- **Augment Code / Auggie** (`auggie --acp`)
- **Stakpak** (`stakpak`)
- **VT Code** (`vtcode-acp`)
- **fast-agent** (ACP entrypoint: `fast-agent-acp`)
- **LLMling-Agent** (`llmling-agent`)
- **cagent** (`cagent`)
- **Code Assistant** (see its agent card for the ACP command)

If an agent requires an ACP adapter, install it first using the setup instructions from
`superqode agents show <agent>`.

---

## Configuration

### In superqode.yaml

```yaml
agents:
  opencode:
    description: "OpenCode coding agent"
    protocol: acp
    command: opencode
    auth_file: ~/.local/share/opencode/auth.json
    capabilities:
      - file_editing
      - shell_execution
      - mcp_tools
```

### Per-Role Configuration

```yaml
team:
  modes:
    qe:
      roles:
        fullstack:
          mode: acp
          coding_agent: opencode
          description: "Senior QE using OpenCode"
```

---

## Agent Properties

| Property | Type | Description |
|----------|------|-------------|
| `description` | string | Agent description |
| `protocol` | string | Protocol type (always `acp`) |
| `command` | string | Command to run agent |
| `args` | [string] | Command arguments |
| `auth_file` | string | Path to authentication file |
| `capabilities` | [string] | Agent capabilities |

---

## ACP Protocol

### How It Works

1. SuperQode spawns the agent process
2. Communicates via ACP (JSON over stdin/stdout)
3. Agent has access to file system and shell
4. Results streamed back to SuperQode

### Message Format

```json
{
  "type": "request",
  "id": "req-001",
  "method": "analyze",
  "params": {
    "path": "/src/api/users.py",
    "focus": "security"
  }
}
```

---

## Compared to BYOK

| Feature | BYOK | ACP |
|---------|------|-----|
| File editing | Via prompts | Native capability |
| Shell access | Via prompts | Native capability |
| Context | Per-request | Persistent |
| Speed | Fast | May be slower |
| Setup | API key only | Agent installation |

### When to Use ACP

- Complex multi-step tasks
- Tasks requiring file manipulation
- Tasks requiring shell commands
- Integration with other tools

### When to Use BYOK

- Simple analysis tasks
- Quick scans
- Cost-sensitive workloads
- Team environments

---

## Custom Agents

### Define a Custom Agent

```yaml
agents:
  custom_agent:
    description: "My custom ACP agent"
    protocol: acp
    command: /path/to/my-agent
    args:
      - --mode
      - interactive
      - --workspace
      - .
    capabilities:
      - file_editing
      - shell_execution
```

### Requirements

Custom agents must:

1. Accept ACP messages on stdin
2. Return ACP responses on stdout
3. Support the ACP protocol methods defined in the spec (initialize, session/new, session/prompt, session/update, fs/*, terminal/*)
4. Handle graceful shutdown

---

## Troubleshooting

### Agent Not Found

```
[INCORRECT] Agent 'opencode' not found
```

**Solution**: Install the agent:

```bash
npm i -g opencode-ai
```

### Connection Failed

```
[INCORRECT] Failed to connect to agent
```

**Solutions**:
- Verify agent is installed: `which opencode`
- Check agent version: `opencode --version`
- Run agent manually to check for errors

### Permission Denied

```
[INCORRECT] Permission denied: auth_file
```

**Solution**: Check auth file permissions:

```bash
ls -la ~/.local/share/opencode/auth.json
```

### Agent Timeout

```
[INCORRECT] Agent response timeout
```

**Solutions**:
- Increase timeout in configuration
- Check if agent is busy
- Restart the agent

---

## Best Practices

### 1. Use for Complex Tasks

ACP excels at multi-step tasks:

```yaml
team:
  modes:
    qe:
      roles:
        fullstack:
          mode: acp
          coding_agent: opencode
          job_description: |
            Perform comprehensive QE review:
            - Analyze code structure
            - Run tests
            - Check security issues
            - Generate fix patches
```

### 2. Combine with BYOK

Use ACP for complex roles, BYOK for simple ones:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          mode: byok
          provider: anthropic
          model: claude-sonnet-4

        fullstack:
          mode: acp
          coding_agent: opencode
```

### 3. Monitor Resource Usage

ACP agents may use significant resources. Monitor:
- Memory usage
- CPU usage
- Disk I/O

---

## Next Steps

- [BYOK Providers](byok.md) - Cloud provider setup
- [Local Providers](local.md) - Self-hosted models
- [Team Configuration](../configuration/team.md) - Role setup
