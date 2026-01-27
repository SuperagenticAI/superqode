<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Roles Commands

Manage team roles and their execution configuration in SuperQode.

---

## Overview

The `superqode roles` command group provides commands for viewing and inspecting team roles, their execution modes (BYOK or ACP), and configuration details.

---

## roles list

List all configured roles with their execution mode and status.

```bash
superqode roles list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--mode`, `-m` | Filter by mode (e.g., `dev`, `qe`, `devops`) |
| `--enabled-only` | Show only enabled roles |

### Examples

```bash
# List all roles
superqode roles list

# List only dev mode roles
superqode roles list --mode dev

# List only enabled roles
superqode roles list --enabled-only

# Filter to enabled qe roles
superqode roles list --mode qe --enabled-only
```

### Output

Shows a table with:
- **Role**: Role identifier (format: `mode.role`)
- **Mode**: Execution mode name
- **Exec Mode**: BYOK (direct LLM) or ACP (coding agent)
- **Provider/Agent**: Provider ID (BYOK) or Agent ID (ACP)
- **Model**: Model name (BYOK) or "(agent-managed)" (ACP)
- **Status**: [CORRECT] Enabled or [INCORRECT] Disabled

### Example Output

```
Team Roles
┌───────────────┬──────┬──────────┬───────────┬───────────────┬──────────────┐
│ Role          │ Mode │ Exec Mode│ Provider  │ Model         │ Status       │
├───────────────┼──────┼──────────┼───────────┼───────────────┼──────────────┤
│ dev.fullstack │ dev  │ BYOK     │ anthropic │ claude-sonnet │ [CORRECT] Enabled   │
│ qe.api_tester │ qe   │ ACP      │ opencode  │ (agent-managed)│ [CORRECT] Enabled   │
└───────────────┴──────┴──────────┴───────────┴───────────────┴──────────────┘

Execution Modes:
  BYOK = Bring Your Own Key (direct LLM API via gateway)
  ACP  = Agent Client Protocol (full coding agent)
```

---

## roles info

Show detailed execution information for a specific role.

```bash
superqode roles info MODE.ROLE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `MODE.ROLE` | Role path in format `mode.role` (e.g., `dev.fullstack`, `qe.api_tester`) |

### Examples

```bash
# Show dev.fullstack role details
superqode roles info dev.fullstack

# Show qe.api_tester role details
superqode roles info qe.api_tester

# Show qe mode role (if using direct role config)
superqode roles info qe
```

### Output

Displays comprehensive role information including:

**BYOK Mode Roles:**
- Role name and description
- Provider and model configuration
- Provider status and API key configuration
- Capabilities (chat completion, streaming, tool calling)
- Limitations (no file editing, no shell commands, no MCP)

**ACP Mode Roles:**
- Agent identifier and status
- Protocol type
- Authentication method
- Agent LLM configuration (provider/model)
- Capabilities (file editing, shell commands, MCP tools, etc.)
- Setup instructions (if not supported)

**Common Information:**
- MCP servers (if configured)
- Job description (truncated if long)
- Security information

### Example Output (BYOK)

```
Role: dev.fullstack
Description: Full-stack development assistant
Enabled: Yes

═══ BYOK MODE (Direct LLM) ═══

Provider: anthropic
Model: claude-sonnet-4-20250514
Gateway: LiteLLM

Provider Status: [CORRECT] Configured
Required Env: ANTHROPIC_API_KEY

Capabilities:
  • Chat completion
  • Streaming responses
  • Tool calling (if model supports)

Limitations:
  • No file editing
  • No shell commands
  • No MCP tools

Job Description:
  You are a full-stack development assistant...

═══ SECURITY ═══

🔒 API key read from YOUR environment variables
🔒 SuperQode NEVER stores your keys
🔒 Data flows: You → SuperQode → LiteLLM → Provider
```

### Example Output (ACP)

```
Role: qe.api_tester
Description: API testing specialist
Enabled: Yes

═══ ACP MODE (Coding Agent) ═══

Agent: opencode
Agent Status: [CORRECT] Supported
Protocol: ACP
Auth: Managed by OpenCode CLI (run `opencode /connect`)

Agent LLM Config:
  Provider: anthropic
  Model: claude-sonnet-4-20250514

Capabilities:
  • File editing
  • Shell command execution
  • MCP tool integration
  • Git operations

MCP Servers:
  • filesystem
  • github

Job Description:
  You are an API testing specialist...

═══ SECURITY ═══

🔒 Auth managed by the agent (not SuperQode)
🔒 Agent stores its own credentials
🔒 Data flows: You → SuperQode → Agent → Provider
```

---

## roles check

Check if a role is ready to run (auth configured, dependencies available).

```bash
superqode roles check MODE.ROLE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `MODE.ROLE` | Role path in format `mode.role` |

### Examples

```bash
# Check if dev.fullstack is ready
superqode roles check dev.fullstack

# Check if qe.api_tester is ready
superqode roles check qe.api_tester
```

### Output

Reports issues and warnings:

- **Issues**: Must be fixed before role can run
  - Missing API keys
  - Missing provider/model configuration
  - Unsupported agents

- **Warnings**: May cause problems but won't prevent execution
  - Provider/agent not in registry (may still work)
  - Configuration inconsistencies

### Example Output

```bash
Checking role: dev.fullstack

[INCORRECT] Issues found:
  • API key not set. Set ANTHROPIC_API_KEY

To configure: export ANTHROPIC_API_KEY="your-key"
Get key at: https://console.anthropic.com/
```

### Success Output

```
Checking role: dev.fullstack

[CORRECT] Role is ready to run!
```

---

## Execution Modes

### BYOK Mode (Bring Your Own Key)

**Capabilities:**
- Direct LLM API access via LiteLLM
- Chat completion and streaming
- Tool calling (if model supports)

**Limitations:**
- No file editing
- No shell command execution
- No MCP tool integration

**Requirements:**
- Provider must be configured in `providers` section
- API key must be set in environment variable
- Model must be specified

### ACP Mode (Agent Client Protocol)

**Capabilities:**
- Full file editing and creation
- Shell command execution
- MCP tool integration
- Git operations
- Advanced coding workflows

**Requirements:**
- Agent must be installed on system
- Agent must be in agent registry
- Agent authentication must be configured

---

## Common Workflows

### List All Roles

```bash
# See all configured roles
superqode roles list

# See only enabled roles
superqode roles list --enabled-only
```

### Inspect Role Configuration

```bash
# Get detailed info about a role
superqode roles info dev.fullstack
```

### Verify Role Readiness

```bash
# Check if role is ready before use
superqode roles check qe.api_tester

# Fix any issues shown
export ANTHROPIC_API_KEY="your-key"
```

### Troubleshoot Role Issues

```bash
# 1. List roles to see current state
superqode roles list

# 2. Get detailed info
superqode roles info dev.fullstack

# 3. Check for issues
superqode roles check dev.fullstack

# 4. Fix issues (e.g., set API key)
export ANTHROPIC_API_KEY="sk-ant-..."

# 5. Verify again
superqode roles check dev.fullstack
```

---

## Troubleshooting

### Role Not Found

```
Error: Role 'dev.unknown' not found or disabled
```

**Solution**:
- Use `superqode roles list` to see available roles
- Check role name spelling (format: `mode.role`)
- Verify role is enabled in configuration

### Provider Not Configured

```
[INCORRECT] Issues found:
  • API key not set. Set ANTHROPIC_API_KEY
```

**Solution**:
```bash
# Set the API key
export ANTHROPIC_API_KEY="your-key"

# Verify
superqode roles check dev.fullstack
```

### Agent Not Supported

```
[INCORRECT] Issues found:
  • Agent 'experimental-agent' is not yet supported
```

**Solution**:
- Check `superqode agents list --supported` for supported agents
- Update role configuration to use a supported agent
- Or wait for agent to be marked as supported

---

## Related Commands

- `superqode agents list` - List available ACP agents
- `superqode agents show` - Show agent details
- `superqode config list-modes` - View configured modes and roles
- `superqode providers list` - List BYOK providers

---

## Next Steps

- [Config Commands](config-commands.md) - Configuration management
- [Agents Commands](agents-commands.md) - ACP agent management
- [Provider Commands](provider-commands.md) - BYOK provider management
- [Team Configuration](../configuration/team.md) - Role configuration guide
