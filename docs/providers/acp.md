# ACP Agents

Agent Client Protocol (ACP) mode connects SuperQode to external coding agents that implement ACP.

> **Note:** SuperQode can also run as an ACP agent inside Zed, JetBrains IDEs, Neovim, or the Harbor benchmark framework with `superqode serve acp`. See [ACP Agent Server](../advanced/acp-agent-server.md).

---

## Overview

An ACP agent is an external runtime such as Codex, Claude Agent, OpenCode, Kimi
or Qwen Code. A SuperQode HarnessSpec is the run contract around a model or
runtime. Select the runtime with `:connect acp`; select a SuperQode harness with
`:harness`.

ACP agents provide:

- **Full capabilities**: File editing, shell execution, MCP tools
- **Structured prompting**: Optimized for coding tasks
- **Tool integration**: Access to development environment
- **Persistent context**: Maintains state across operations

---

## Quick Start

```bash
# Inspect the catalog
superqode agents list --tier featured

# Connect to a specific agent
superqode connect acp opencode
```

In the TUI:

```text
:connect acp                 # installed and featured agents
:connect acp enterprise      # enterprise agents
:connect acp all             # complete catalog
:connect acp refresh         # refresh the official registry cache
```

---

## Supported Agents

Use `superqode agents list --protocol acp` to see the current list. SuperQode
combines the cached official ACP Registry, bundled offline definitions, and
user definitions from `~/.superqode/agents`.

The default TUI picker is intentionally curated:

- **Ready**: installed agents detected on the current machine
- **Featured**: commonly used terminal coding agents
- **Enterprise**: enterprise and platform-specific coding agents
- **All**: the complete official registry plus additional SuperQode adapters

Installed agents are always visible. Registry refresh is explicit so starting
the TUI does not require network access.

### OpenCode

[OpenCode](https://github.com/anomalyco/opencode) provides native ACP mode:

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

#### Web Fetch and MCP Tools

ACP agents do not automatically receive SuperQode's built-in Python tools such as `fetch` and `web_fetch`. To make web fetch available to OpenCode or another ACP agent, configure an enabled MCP fetch server. SuperQode passes enabled MCP servers from `.superqode/mcp.json`, `~/.superqode/mcp.json`, or `~/.config/superqode/mcp.json` into each ACP `session/new` request.

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

Restart the ACP session after changing MCP configuration so the agent receives the updated server list.

---

### Grok Build (xAI)

[Grok Build](https://x.ai/cli) is xAI's official coding agent and exposes a
native ACP server. It can use the official CLI's local subscription login or
an `XAI_API_KEY` configured for the CLI.

```bash
# Install and authenticate the official CLI (macOS/Linux/WSL)
curl -fsSL https://x.ai/cli/install.sh | bash
# Windows PowerShell: irm https://x.ai/cli/install.ps1 | iex
grok login

# Connect from SuperQode
superqode connect acp grok
```

Use `grok login --device-auth` on SSH or a headless machine. `:connect grok`
and `:connect acp grok` both start Grok Build over ACP; Grok Build follows the
signed-in account's default model (currently Grok 4.5).

To run **SuperQode's own harness** on the same subscription instead of Grok
Build, use `:grok api [model]`: it imports the session token into SuperQode and
routes through the CLI chat proxy. API-key billing is separate (`xai/grok-4.5`
BYOK). See [BYOK Providers → Grok Subscription](byok.md#grok-subscription-official-cli).

---

### Amp

[Amp](https://ampcode.com) is an AI coding agent by Ampcode with full ACP support:

```bash
# Install Amp CLI
curl -fsSL https://ampcode.com/install.sh | bash
amp login

# Install ACP adapter (Python - recommended)
uv tool install acp-amp

# Alternative: Node.js
npm install -g @superagenticai/acp-amp

# Connect via SuperQode
superqode connect acp amp
```

#### Capabilities

| Capability | Description |
|------------|-------------|
| `file_editing` | Create, read, edit files |
| `shell_execution` | Run shell commands |
| `mcp_tools` | Use MCP servers |
| `multi_turn` | Thread continuity across interactions |

---

### Curated Agent Groups

The featured catalog includes Codex, Claude Agent, OpenCode, Cursor, Cline,
GitHub Copilot, Grok Build, Goose, Kimi, Qwen Code, Pi, Amp, Kilo and Harn.

The enterprise catalog includes Factory Droid, Devin, Cortex Code, Junie,
Auggie and Poolside. Other official registry entries remain searchable through
`:connect acp all`.

Representative current ACP commands include:

| Agent | ACP command |
|---|---|
| Claude Agent | `claude-agent-acp` |
| Codex | `codex-acp` |
| Gemini CLI | `gemini --acp` |
| GitHub Copilot | `copilot --acp --stdio` |
| Goose | `goose acp` |
| Grok Build | `grok agent stdio` |
| Kimi CLI | `kimi acp` |
| Kilo | `kilo acp` |
| Qwen Code | `qwen --acp --experimental-skills` |
| Factory Droid | `droid exec --output-format acp-daemon` |
| Devin | `devin acp` |
| Cortex Code | `cortex acp serve` |
| Harn | `harn serve acp` |

Run `superqode agents show <agent>` for installation and authentication details.
Some agents use a maintained adapter rather than a native server.

### Registry and Offline Behavior

The official registry cache is stored at
`~/.superqode/acp_registry_cache.json`. Refresh it with:

```bash
superqode agents refresh
```

If refresh fails, SuperQode retains the stale cache. If no cache exists, the
bundled catalog remains available. Project and user agent definitions are not
deleted or overwritten by a registry refresh.

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

  amp:
    description: "Amp Code agent"
    protocol: acp
    command: acp-amp
    capabilities:
      - file_editing
      - shell_execution
      - mcp_tools
      - multi_turn
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

### Process and Protocol Flow

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

```json
[INCORRECT] Agent 'opencode' not found
```

**Solution**: Install the agent:

```bash
npm i -g opencode-ai
```

### Connection Failed

```json
[INCORRECT] Failed to connect to agent
```

**Solutions**:
- Verify agent is installed: `which opencode`
- Check agent version: `opencode --version`
- Run agent manually to check for errors

### Permission Denied

```json
[INCORRECT] Permission denied: auth_file
```

**Solution**: Check auth file permissions:

```bash
ls -la ~/.local/share/opencode/auth.json
```

### Agent Timeout

```json
[INCORRECT] Agent response timeout
```

**Solutions**:
- Increase timeout in configuration
- Check if agent is busy
- Restart the agent

---

## Best Practices

### 1. Use for Complex Tasks

ACP excels at multi-step tasks. Use it when you need file editing, shell access, and tool integration.

### 2. Combine with BYOK

Use ACP for complex automation, BYOK for simpler analysis tasks. Switch between them with `:connect`.

### 3. Monitor Resource Usage

ACP agents may use significant resources. Monitor:
- Memory usage
- CPU usage
- Disk I/O

---

## Next Steps

- [BYOK Providers](byok.md) - Cloud provider setup
- [Local Providers](local.md) - Self-hosted models
