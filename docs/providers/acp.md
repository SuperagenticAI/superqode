# ACP Agents

Agent Client Protocol (ACP) mode connects SuperQode to full-featured coding agents.

> **The other direction:** SuperQode can also run *as* an ACP agent — inside Zed, JetBrains IDEs, Neovim, or the Harbor benchmark framework — with `superqode serve acp`. See [ACP Agent Server](../advanced/acp-agent-server.md).

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

Use `grok login --device-auth` on SSH or a headless machine. In the TUI,
`:connect acp grok` starts Grok Build over ACP. Grok Build follows the
signed-in account's default model (currently Grok 4.5).

**Do not confuse this with `:connect grok`**, which uses SuperQode's harness on
the same subscription (CLI chat proxy), not Grok Build. Subscription credentials
start in the official Grok CLI; the harness path imports the session token into
SuperQode. API-key billing is separate (`xai/grok-4.5` BYOK). See
[BYOK Providers → Grok Subscription](byok.md#grok-subscription-official-cli).

---

### OpenClaw (Enterprise Integration, Experimental)

[OpenClaw](https://openclaw.ai/) provides an ACP bridge backed by the OpenClaw Gateway. This
integration is available in Enterprise.

```bash
# Install OpenClaw
npm install -g moltbot@latest

# Start the gateway (in a separate terminal)
moltbot gateway --port 18789 --verbose

# Connect via SuperQode
superqode connect acp moltbot
```

If your gateway requires auth, pass `--token` or `--password` in the agent command configuration.

**Note:** OpenClaw integration is experimental and intended for self-hosted environments with
secure, private local models.

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

### Other ACP-Compatible Agents

SuperQode includes registry entries for these ACP agents (availability depends on local installation):

- **Amp** (ACP adapter: `acp-amp` via [acp-amp](https://github.com/SuperagenticAI/acp-amp))
- **Claude Code** (ACP adapter: `claude-code-acp`)
- **Codex** (ACP adapter: `npx @openai/codex-acp` or `codex-acp`)
- **Grok Build** (`grok agent stdio`)
- **OpenHands** (`openhands acp`)
- **Gemini CLI** (`gemini --experimental-acp`): enterprise/API-key ACP route. Individual Google AI users should prefer `:connect antigravity`
- **Goose** (`goose`)
- **Kimi CLI** (`kimi --acp`)
- **Augment Code / Auggie** (`auggie --acp`)
- **Stakpak** (`stakpak`)
- **VT Code** (`vtcode-acp`)
- **fast-agent** (ACP entrypoint: `fast-agent-acp -x`)
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
