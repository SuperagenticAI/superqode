# Auth Commands

Show authentication and security information for SuperQode.

---

## Overview

The `superqode auth` command group provides commands for managing authentication, including storing API keys locally, checking configuration status, and understanding security practices.

---

## Authentication Modes

SuperQode supports **three authentication modes**:

| Mode | Description | Key Storage |
|------|-------------|-------------|
| **BYOK** | Bring Your Own Key via environment variables | Your shell/env |
| **Local** | Optional local file storage | `~/.superqode/auth.json` |
| **ACP** | Delegated to coding agents | Agent-specific |

### Resolution Order

When SuperQode needs an API key, it checks in this order:

1. **Environment variables** (e.g., `ANTHROPIC_API_KEY`)
2. **Local storage** (`~/.superqode/auth.json`)
3. Error if neither found

This means environment variables always take precedence over local storage.

---

## auth login

Store an API key for a provider in local storage.

```bash
superqode auth login PROVIDER
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER` | Provider ID (e.g., `anthropic`, `openai`, `google`) |

### Examples

```bash
# Store Anthropic API key
superqode auth login anthropic

# Store OpenAI API key
superqode auth login openai
```

### What Happens

1. Prompts for your API key (input is hidden)
2. Saves to `~/.superqode/auth.json` with `0600` permissions
3. Key is now available for SuperQode to use

### Example Session

```
$ superqode auth login anthropic

Configure Anthropic
Get your key at: https://console.anthropic.com/

Enter API key for anthropic: ********
✅ Saved anthropic API key to ~/.superqode/auth.json
```

---

## auth logout

Remove a stored API key from local storage.

```bash
superqode auth logout PROVIDER
```

### Examples

```bash
# Remove Anthropic key
superqode auth logout anthropic
```

### Output

```
✅ Removed anthropic from local storage
```

---

## auth list

List all credentials stored in local storage.

```bash
superqode auth list
```

### Output

```
┌───────────┬──────┬─────────────┐
│ Provider  │ Type │ Key Preview │
├───────────┼──────┼─────────────┤
│ anthropic │ api  │ sk-ant-a... │
│ openai    │ api  │ sk-proj-... │
└───────────┴──────┴─────────────┘

Stored in: ~/.superqode/auth.json
```

---

## auth info

Show comprehensive authentication information for all providers and agents.

```bash
superqode auth info
```

### Output

Displays authentication status showing both environment variables AND local storage:

```
╭──────────────────────────────────────────────────────────╮
│ 🔒 Auth Modes:                                           │
│ 1. BYOK - Environment variables (primary)               │
│ 2. Local - ~/.superqode/auth.json (optional)            │
│ 3. ACP - Delegated to agents                             │
╰──────────────────────────────────────────────────────────╯

═══ PROVIDER AUTH STATUS ═══

┌─────────────┬──────────────────┬───────────┬──────────────────────┐
│ Provider    │ Env Variable     │ Status    │ Source               │
├─────────────┼──────────────────┼───────────┼──────────────────────┤
│ anthropic   │ ANTHROPIC_API_KEY│ ✅ Set    │ ~/.superqode/auth.json│
│ openai      │ OPENAI_API_KEY   │ ✅ Set    │ ~/.zshrc             │
│ google      │ GOOGLE_API_KEY   │ ❌ Not set│ -                    │
│ ollama      │ (none)           │ 🏠 Local  │ localhost:11434      │
└─────────────┴──────────────────┴───────────┴──────────────────────┘

═══ ACP MODE (Coding Agents) ═══
...
```

---

## auth check

Check authentication status for a specific provider or agent.

```bash
superqode auth check PROVIDER_OR_AGENT
```

### Examples

```bash
# Check Anthropic provider
superqode auth check anthropic

# Check OpenCode agent
superqode auth check opencode
```

---

## Security & Transparency

### Where Are Keys Stored?

| Source | Location | Permissions |
|--------|----------|-------------|
| Environment | Your shell config (`~/.zshrc`, `~/.bashrc`) | Your control |
| Local Storage | `~/.superqode/auth.json` | `0600` (owner only) |
| ACP Agents | Agent-specific (e.g., `~/.local/share/opencode/auth.json`) | Agent's control |

### What SuperQode Does NOT Do

- ❌ Send keys to any external server
- ❌ Log or display full key values
- ❌ Share keys between projects
- ❌ Store keys without your explicit action

### What SuperQode DOES Do

- ✅ Read keys from environment at runtime
- ✅ Optionally store keys locally if you use `auth login`
- ✅ Set secure file permissions (0600) on auth.json
- ✅ Show masked key previews (first 8 chars only)
- ✅ Show exactly where each key is configured

### File Format

The `~/.superqode/auth.json` file format:

```json
{
  "anthropic": {
    "type": "api",
    "key": "sk-ant-api03-..."
  },
  "openai": {
    "type": "api",
    "key": "sk-proj-..."
  }
}
```

### Inspecting Your Auth File

```bash
# View the file (keys will be visible!)
cat ~/.superqode/auth.json

# Check permissions
ls -la ~/.superqode/auth.json
# Should show: -rw------- (0600)

# Delete all stored keys
rm ~/.superqode/auth.json
```

---

## Choosing Between BYOK and Local Storage

| Use Case | Recommended |
|----------|-------------|
| CI/CD pipelines | BYOK (env vars) |
| Team shared environment | BYOK (env vars) |
| Personal development | Either works |
| Quick setup without shell config | Local storage |
| Multiple keys for same provider | BYOK (env vars) |

### Using Both

If you have a key in both environment AND local storage:
- **Environment variable wins** (checked first)
- Local storage is a fallback

This lets you override local storage with environment variables when needed.

---

## Workflow Examples

### Quick Personal Setup

```bash
# Store your keys locally
superqode auth login anthropic
superqode auth login openai

# Verify
superqode auth list
superqode auth info
```

### CI/CD Setup

```yaml
# GitHub Actions example
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

steps:
  - run: superqode auth info  # Will show keys from env
```

### Switching Providers

```bash
# Remove old key
superqode auth logout anthropic

# Add new key
superqode auth login anthropic

# Verify
superqode auth check anthropic
```

---

## Troubleshooting

### Key Not Found

```
❌ anthropic not set
```

**Solutions:**

```bash
# Option 1: Set via environment
export ANTHROPIC_API_KEY="sk-ant-..."

# Option 2: Store locally
superqode auth login anthropic
```

### Wrong Key Being Used

If environment has a different key than local storage, environment wins:

```bash
# Check which source is active
superqode auth info

# To use local storage key, unset env var
unset ANTHROPIC_API_KEY
```

### Permission Denied on Auth File

```bash
# Fix permissions
chmod 600 ~/.superqode/auth.json
chmod 700 ~/.superqode
```

### Clear All Local Keys

```bash
rm ~/.superqode/auth.json
```

---

## Related Commands

- `superqode providers list` - List available providers
- `superqode providers test` - Test provider connection
- `superqode agents show` - Show agent authentication info
- `superqode roles check` - Check role readiness (includes auth check)

---

## Next Steps

- [Provider Commands](provider-commands.md) - Provider management
- [Agents Commands](agents-commands.md) - Agent management
- [Configuration](../configuration/yaml-reference.md) - Config file structure
