# Authentication

How SuperQode handles API keys and credentials with full transparency.

---

## Overview

SuperQode is designed as a **pass-through orchestrator**. It connects you to LLM providers and coding agents without intercepting or storing your credentials unnecessarily.

```
┌─────────────────────────────────────────────────────────────┐
│                    YOUR CONTROL                             │
├─────────────────────────────────────────────────────────────┤
│  Environment Variables    OR    Local Storage               │
│  (~/.zshrc, .env)               (~/.superqode/auth.json)    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    SUPERQODE                                │
│  • Reads keys at runtime                                    │
│  • Never sends keys to external servers                     │
│  • Passes keys directly to LLM providers                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              LLM PROVIDER / AGENT                           │
│  (Anthropic, OpenAI, Google, etc.)                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Three Authentication Modes

### 1. BYOK (Bring Your Own Key)

**Primary mode.** Keys are read from environment variables.

| Provider | Environment Variable |
|----------|---------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| xAI | `XAI_API_KEY` |

```bash
# Set in your shell
export ANTHROPIC_API_KEY="sk-ant-..."

# Or in .env file
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
```

**Pros:**
- Keys never written to disk by SuperQode
- Standard approach for CI/CD
- Easy to rotate

**Cons:**
- Requires shell configuration
- Keys in shell history if not careful

### 2. Local Storage

**Optional mode.** Keys stored in `~/.superqode/auth.json`.

```bash
# Store a key
superqode auth login anthropic

# Remove a key
superqode auth logout anthropic

# List stored keys
superqode auth list
```

**Pros:**
- Quick setup without shell config
- Keys hidden during entry
- Portable across shell sessions

**Cons:**
- Keys written to disk
- Need to manage file security

**Security measures:**
- File permissions: `0600` (owner read/write only)
- Directory permissions: `0700`
- Keys never logged or displayed in full

### 3. ACP (Agent Capability Protocol)

**Delegated mode.** Authentication handled by the coding agent itself.

```bash
# Agent manages its own auth
opencode /connect
claude-code login
```

SuperQode doesn't see or store agent credentials.

---

## Resolution Order

When SuperQode needs an API key:

```
1. Check environment variable
   └─ Found? → Use it
   └─ Not found? → Continue

2. Check local storage (~/.superqode/auth.json)
   └─ Found? → Use it
   └─ Not found? → Continue

3. Raise error: "API key not configured"
```

**Environment always wins.** This lets you override local storage:

```bash
# Local storage has key X
# But you want to use key Y for this session:
export ANTHROPIC_API_KEY="key-Y"
superqode ...  # Uses key Y
```

---

## What SuperQode Does

### ✅ Does

- Reads keys from your environment at runtime
- Stores keys locally **only when you explicitly run `auth login`**
- Sets secure file permissions (0600) on stored keys
- Shows masked previews (first 8 characters only)
- Shows exactly where each key is configured
- Passes keys directly to LLM providers

### ❌ Does NOT

- Send keys to any SuperQode server
- Log or display full key values
- Store keys without your explicit action
- Share keys between projects
- Access keys from other applications

---

## File Locations

| File | Purpose | Permissions |
|------|---------|-------------|
| `~/.superqode/auth.json` | API key storage | `0600` |
| `~/.superqode/` | SuperQode data directory | `0700` |
| `~/.superqode/mcp-auth/` | MCP server credentials | `0700` |

---

## Inspecting Your Data

### View stored keys

```bash
# List keys (masked)
superqode auth list

# View raw file (full keys visible!)
cat ~/.superqode/auth.json
```

### Check what SuperQode sees

```bash
# Full auth status
superqode auth info

# Specific provider
superqode auth check anthropic
```

### Verify file security

```bash
ls -la ~/.superqode/auth.json
# Should show: -rw------- (only owner can read/write)
```

---

## Deleting Your Data

### Remove specific key

```bash
superqode auth logout anthropic
```

### Remove all stored keys

```bash
rm ~/.superqode/auth.json
```

### Remove all SuperQode data

```bash
rm -rf ~/.superqode/
```

---

## Security Best Practices

### 1. Use Environment Variables for CI/CD

```yaml
# GitHub Actions
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 2. Never Commit Keys

```bash
# .gitignore
.env
*_api_key*
```

### 3. Rotate Keys Regularly

If a key may be compromised:
1. Generate new key from provider dashboard
2. Update in SuperQode: `superqode auth login provider`
3. Revoke old key from provider dashboard

### 4. Use Different Keys for Different Environments

```bash
# Development
export ANTHROPIC_API_KEY="sk-ant-dev-..."

# Production (in secure CI/CD)
ANTHROPIC_API_KEY="${{ secrets.PROD_ANTHROPIC_KEY }}"
```

---

## Data Flow Transparency

### BYOK Mode

```
You → superqode → LiteLLM (local) → Provider API
         │
         └── API key read from env, passed to LiteLLM
```

### ACP Mode

```
You → superqode → Agent subprocess → Provider API
         │              │
         │              └── Agent uses its own credentials
         └── SuperQode doesn't see agent credentials
```

### Local Providers (Ollama, LM Studio)

```
You → superqode → Local model server
         │
         └── No API key needed, just local HTTP
```

---

## Comparison with Other Tools

| Feature | SuperQode | OpenCode | Toad |
|---------|-----------|----------|------|
| BYOK (env vars) | ✅ | ✅ | ❌ |
| Local storage | ✅ | ✅ | ❌ |
| ACP delegation | ✅ | ❌ | ✅ |
| OAuth support | ✅ (MCP) | ✅ | ✅ |
| File permissions | 0600 | 0600 | N/A |

---

## FAQ

### Does SuperQode send my keys anywhere?

No. Keys are only sent to the LLM provider you're using (Anthropic, OpenAI, etc.) via their official APIs.

### Where is my key stored if I use `auth login`?

In `~/.superqode/auth.json` on your local machine with `0600` permissions.

### Can I use both env vars and local storage?

Yes. Environment variables take precedence. Local storage is a fallback.

### How do I see which key source is active?

```bash
superqode auth info
# Shows "Source" column: env, local, or ~/.zshrc
```

### Is the auth.json file encrypted?

No. It's plain JSON with restricted file permissions. If you need encryption, use your OS keychain or a secrets manager.

---

## Related

- [Auth Commands](../cli-reference/auth-commands.md) - CLI reference
- [Modes](modes.md) - BYOK vs ACP execution modes
- [Providers](../providers/index.md) - Available LLM providers
