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
| `--store` | Show agent store interface |

### Examples

```bash
# List all agents
superqode agents list

# Show agent store
superqode agents list --store
```

---

## agents show

Show detailed information about a specific agent.

```bash
superqode agents show AGENT
```

### Arguments

| Argument | Description |
|----------|-------------|
| `AGENT` | Agent identifier (e.g., `opencode`, `claude`) |

### Examples

```bash
# Show OpenCode agent details
superqode agents show opencode

# Show Claude Code agent details
superqode agents show claude
```

---

## agents doctor

Check ACP agent installation, setup, and optional protocol health.

```bash
superqode agents doctor [AGENT] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--live` | Start the ACP agent and check protocol support |
| `--timeout` | Live protocol check timeout in seconds (default: 10.0) |
| `--json` | Emit JSON output |

---

## agents install

Install an ACP coding agent.

```bash
superqode agents install AGENT
```

---

## agents free-models

List free-tier models discovered across all installed ACP agents.

```bash
superqode agents free-models [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--agent` | Only show free models from this agent |
| `--refresh` | Skip the discovery cache and re-probe live |
| `--json` | Emit JSON instead of a table |

---

## agents store

Show the agent store interface.

```bash
superqode agents store
```

---

## Related Commands

- `superqode connect acp <agent>` - Connect to an ACP agent
- `superqode providers list` - List BYOK providers
