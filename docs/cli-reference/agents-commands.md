# Agents Commands

Manage ACP (Agent Client Protocol) coding agents for SuperQode.

---

## Overview

The `superqode agents` command group discovers, inspects, installs, and checks
ACP coding agents. The catalog combines the cached official ACP Registry,
bundled offline metadata, and user definitions from `~/.superqode/agents`.

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
| `--protocol acp` | Limit output to ACP agents |
| `--tier featured` | Show installed agents and missing featured agents |
| `--tier enterprise` | Show installed agents and missing enterprise agents |
| `--tier all` | Show the complete catalog. This is the default |
| `--refresh` | Refresh the official ACP Registry cache before listing |

### Examples

```bash
# List all agents
superqode agents list

# Show the focused catalog
superqode agents list --tier featured
superqode agents list --tier enterprise

# Refresh upstream metadata and versions
superqode agents list --refresh

# Show agent store
superqode agents list --store
```

Installed agents are always shown regardless of the selected catalog tier.

---

## agents refresh

Refresh the official ACP Registry and write the result to
`~/.superqode/acp_registry_cache.json`.

```bash
superqode agents refresh
```

Normal startup and picker operations do not require network access. If the
registry cannot be reached, SuperQode uses the stale cache or bundled catalog.

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
- `:connect acp` - Open the installed and featured TUI picker
- `:connect acp enterprise` - Open the enterprise agent picker
- `:connect acp all` - Open the complete TUI catalog
- `:connect acp refresh` - Refresh the cache from the TUI
- `superqode providers list` - List BYOK providers
