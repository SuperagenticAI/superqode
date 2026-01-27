<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode Banner" />

# Agents Commands

Manage ACP (Agent Client Protocol) coding agents for SuperQode.

---

## Overview

The `superqode agents` command group provides commands for discovering, installing, and managing ACP coding agents. ACP agents are external coding assistants that integrate with SuperQode via the Agent Client Protocol.

---

## agents list

List all available coding agents.

```bash
superqode agents list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--protocol` | Filter by protocol: `acp` or `external` |
| `--supported` | Show only supported agents |

### Examples

```bash
# List all agents
superqode agents list

# List only ACP agents
superqode agents list --protocol acp

# List only supported agents
superqode agents list --supported
```

### Output

Shows a table with:
- **Agent**: Agent identifier
- **Name**: Full agent name
- **Protocol**: ACP or EXTERNAL
- **Status**: [CORRECT] Supported, 🔜 Coming Soon, or  Experimental
- **Description**: Brief agent description

### Example Output

```
Coding Agents
┌───────────┬──────────────────┬──────────┬─────────────────────┬────────────────────────────┐
│ Agent     │ Name             │ Protocol │ Status              │ Description                │
├───────────┼──────────────────┼──────────┼─────────────────────┼────────────────────────────┤
│ opencode  │ OpenCode         │ ACP      │ [CORRECT] Supported        │ Full-featured coding agent │
│ codex     │ Codex            │ ACP      │ Experimental         │ OpenAI ACP adapter         │
└───────────┴──────────────────┴──────────┴─────────────────────┴────────────────────────────┘

Total: 15 agents, 8 supported
```

The actual list is generated from built-in agent cards plus any local agent definitions on your machine.

---

## agents show

Show detailed information about a specific agent.

```bash
superqode agents show AGENT_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `AGENT_ID` | Agent identifier (e.g., `opencode`, `claude`) |

### Examples

```bash
# Show OpenCode agent details
superqode agents show opencode

# Show Claude Code agent details
superqode agents show claude
```

### Output

Displays detailed agent information including:
- Agent name and identifier
- Protocol type
- Status (Supported/Coming Soon/Experimental)
- Connection type
- Description
- Capabilities
- Authentication requirements
- Setup instructions
- Configuration example

### Example Output

```
Agent: SST OpenCode
ID: opencode
Protocol: ACP
Status: [CORRECT] Supported
Connection: stdio

Description:
  Full-featured coding agent with file editing, shell access, MCP support

Capabilities:
  • File editing
  • Shell command execution
  • MCP tool integration
  • Git operations

Authentication:
  Managed by OpenCode CLI (run `opencode /connect`)

Setup:
  npm i -g opencode-ai

Usage in superqode.yaml:
  team:
    dev:
      roles:
        my-role:
          mode: "acp"
          agent: "opencode"
          agent_config:
            provider: "anthropic"
            model: "claude-sonnet-4-20250514"
          job_description: |
            Your job description here...
```

---

## Related Commands

- `superqode connect acp <agent>` - Connect to an ACP agent
- `superqode providers list` - List BYOK providers
- `superqode config list-modes` - View configured modes and roles

---

## Agent Status Types

| Status | Description |
|--------|-------------|
| **[CORRECT] Supported** | Fully tested and ready for production use |
| **🔜 Coming Soon** | Planned for future release |
| ** Experimental** | Available but may have limitations |

---

## Common Workflows

### Discover Available Agents

```bash
# See all available agents
superqode agents list

# Filter to only supported ACP agents
superqode agents list --protocol acp --supported
```

### Get Agent Details

```bash
# View details for a specific agent
superqode agents show opencode
```

### Configure Agent in Team

After finding an agent, add it to your `superqode.yaml`:

```yaml
team:
  dev:
    roles:
      coding_assistant:
        mode: "acp"
        agent: "opencode"  # From agents list
        agent_config:
          provider: "anthropic"
          model: "claude-sonnet-4-20250514"
        job_description: |
          You are a coding assistant...
```

---

## Troubleshooting

### Agent Not Found

```
Error: Agent 'unknown-agent' not found
```

**Solution**: Use `superqode agents list` to see available agents.

### Agent Installation

Some agents require installation before use. Check the agent's setup instructions:

```bash
superqode agents show <agent-id>
```

The output includes setup commands and prerequisites.

---

## Next Steps

- [Provider Commands](provider-commands.md) - BYOK provider management
- [Config Commands](config-commands.md) - Configuration management
- [Team Configuration](../configuration/team.md) - Team and role setup
