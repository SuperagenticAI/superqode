<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Auth Commands

Show authentication and security information for SuperQode.

---

## Overview

The `superqode auth` command group provides commands for inspecting authentication status, checking API key configuration, and understanding security practices. SuperQode **NEVER stores API keys** - this command shows where keys are stored and who controls them.

---

## Security Principle

!!! warning "SuperQode NEVER stores API keys"
    All credentials are read from YOUR environment at runtime. You control where and how your keys are stored.

---

## auth info

Show comprehensive authentication information for all providers and agents.

```bash
superqode auth info
```

### Examples

```bash
# Show all auth information
superqode auth info
```

### Output

Displays three sections:

#### 1. BYOK Mode (Direct LLM)

Shows status for common providers:
- **Provider**: Provider identifier
- **Env Variable**: Environment variable name for API key
- **Status**: [CORRECT] Set or [INCORRECT] Not set
- **Source**: Where the env var is detected (e.g., `~/.zshrc`, `.env`, `environment`)

#### 2. ACP Mode (Coding Agents)

Shows authentication status for ACP agents:
- **Agent**: Agent identifier
- **Auth Location**: Where the agent stores its credentials
- **Status**: [CORRECT] Configured or WARNING: Check agent

#### 3. Data Flow

Shows how data flows through the system:
- **BYOK**: You → SuperQode → LiteLLM → Provider API
- **ACP**: You → SuperQode → Agent (e.g., opencode) → Provider API

### Example Output

```
SuperQode Auth Information

🔒 SECURITY PRINCIPLE: SuperQode NEVER stores your API keys.

All credentials are read from YOUR environment at runtime.
You control where and how your keys are stored.

═══ BYOK MODE (Direct LLM) ═══

Your API keys are read from YOUR environment variables:

┌─────────────┬──────────────────┬───────────┬─────────────┐
│ Provider    │ Env Variable     │ Status    │ Source      │
├─────────────┼──────────────────┼───────────┼─────────────┤
│ anthropic   │ ANTHROPIC_API_KEY│ [CORRECT] Set    │ ~/.zshrc    │
│ openai      │ OPENAI_API_KEY   │ [INCORRECT] Not set│ -           │
│ google      │ GOOGLE_API_KEY   │ [CORRECT] Set    │ .env        │
│ ollama      │ (none)           │  Local  │ localhost   │
└─────────────┴──────────────────┴───────────┴─────────────┘

 Keys are read at runtime, never stored by SuperQode

═══ ACP MODE (Coding Agents) ═══

Agent authentication is managed by each agent, not SuperQode:

┌───────────┬──────────────────────────┬───────────┐
│ Agent     │ Auth Location            │ Status    │
├───────────┼──────────────────────────┼───────────┤
│ opencode  │ ~/.local/share/opencode/ │ [CORRECT] Config │
│           │   auth.json              │           │
└───────────┴──────────────────────────┴───────────┘

 Agent auth is managed by the agent itself, not SuperQode
 Run the agent directly to configure: e.g., 'opencode' → /connect

═══ DATA FLOW ═══

BYOK:  You → SuperQode → LiteLLM → Provider API
ACP:   You → SuperQode → Agent (e.g., opencode) → Provider API

SuperQode is a pass-through orchestrator. Your data goes directly
to the LLM provider or agent. We don't intercept or store anything.
```

---

## auth check

Check authentication status for a specific provider or agent.

```bash
superqode auth check PROVIDER_OR_AGENT
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROVIDER_OR_AGENT` | Provider ID (e.g., `anthropic`) or Agent ID (e.g., `opencode`) |

### Examples

```bash
# Check Anthropic provider
superqode auth check anthropic

# Check OpenCode agent
superqode auth check opencode

# Check OpenAI provider
superqode auth check openai
```

### Output

#### For Providers

Shows:
- Provider name and details
- Environment variable status
- Masked API key (first 8 and last 4 characters)
- Source location of env var
- Setup instructions if not configured

**Example Output (Configured):**

```
Provider: Anthropic

[CORRECT] ANTHROPIC_API_KEY = sk-ant-api03-...
   Source: ~/.zshrc
```

**Example Output (Not Configured):**

```
Provider: Anthropic

[INCORRECT] ANTHROPIC_API_KEY = (not set)

To configure:
  export ANTHROPIC_API_KEY="your-api-key"

  Get your key at: https://console.anthropic.com/
```

#### For Agents

Shows:
- Agent name and authentication method
- Auth file location and existence
- Setup instructions if not configured

**Example Output (Configured):**

```
Agent: SST OpenCode

Auth managed by: SST OpenCode (not SuperQode)
Auth location: Managed by OpenCode CLI (run `opencode /connect`)

[CORRECT] Auth file exists: /home/user/.local/share/opencode/auth.json
```

**Example Output (Not Configured):**

```
Agent: SST OpenCode

Auth managed by: SST OpenCode (not SuperQode)
Auth location: Managed by OpenCode CLI (run `opencode /connect`)

WARNING: Auth file not found: /home/user/.local/share/opencode/auth.json

To configure:
  opencode /connect
```

#### For Local Providers

Shows that no API key is required:

```
Provider: Ollama

 Local provider - no API key required
Default URL: http://localhost:11434
```

---

## Understanding Auth Sources

SuperQode detects where environment variables are set by checking:

1. **Shell configuration files**: `~/.zshrc`, `~/.bashrc`, `~/.bash_profile`, `~/.profile`
2. **Project `.env` file**: `.env` in current directory
3. **Environment**: System environment (e.g., exported in current shell)

The `auth info` command shows the detected source for each configured variable.

---

## Setting Up Authentication

### BYOK Providers

1. Get your API key from the provider:
   - Anthropic: https://console.anthropic.com/
   - OpenAI: https://platform.openai.com/api-keys
   - Google AI: https://aistudio.google.com/app/apikey

2. Set the environment variable:

   ```bash
   # In shell config file (~/.zshrc, ~/.bashrc, etc.)
   export ANTHROPIC_API_KEY="sk-ant-api03-..."

   # Or in project .env file
   echo 'ANTHROPIC_API_KEY=sk-ant-api03-...' >> .env
   ```

3. Verify:

   ```bash
   superqode auth check anthropic
   ```

### ACP Agents

Each agent manages its own authentication:

```bash
# OpenCode example
opencode /connect
# Follow prompts to authenticate

# Verify
superqode auth check opencode
```

### Local Providers

No authentication required. Just ensure the service is running:

```bash
# Ollama example
ollama serve

# Verify
superqode auth check ollama
```

---

## Security Best Practices

### 1. Never Commit API Keys

```bash
# Add to .gitignore
echo ".env" >> .gitignore
echo "*_api_key*" >> .gitignore
```

### 2. Use Environment Variables

```bash
# Good: Set in environment
export ANTHROPIC_API_KEY="sk-ant-..."

# Bad: Hardcode in config files
# ANTHROPIC_API_KEY: "sk-ant-..."  # [INCORRECT] DON'T DO THIS
```

### 3. Use Different Keys for Different Environments

```bash
# Development
export ANTHROPIC_API_KEY="sk-ant-dev-..."

# Production (in CI/CD)
export ANTHROPIC_API_KEY="${{ secrets.ANTHROPIC_API_KEY }}"
```

### 4. Rotate Keys Regularly

If a key is compromised:
1. Generate a new key from the provider dashboard
2. Update the environment variable
3. Revoke the old key

---

## Troubleshooting

### Key Not Detected

```
[INCORRECT] ANTHROPIC_API_KEY = (not set)
```

**Solution**:
```bash
# 1. Verify key is exported
echo $ANTHROPIC_API_KEY

# 2. If empty, set it
export ANTHROPIC_API_KEY="your-key"

# 3. For persistence, add to shell config
echo 'export ANTHROPIC_API_KEY="your-key"' >> ~/.zshrc
source ~/.zshrc

# 4. Verify again
superqode auth check anthropic
```

### Agent Auth Not Found

```
WARNING: Auth file not found: /home/user/.local/share/opencode/auth.json
```

**Solution**:
```bash
# Run the agent's authentication command
opencode /connect

# Or follow agent-specific setup
superqode agents show opencode  # Check setup instructions
```

### Multiple Keys Set

If multiple environment variables are set for the same provider, SuperQode uses the first one found in this order:
1. Shell environment
2. `.env` file
3. Shell config files

To use a specific key, export it explicitly:
```bash
export ANTHROPIC_API_KEY="desired-key"
```

---

## Data Flow and Privacy

### BYOK Mode

```
You (API Key) → SuperQode CLI → LiteLLM Gateway → Provider API
                   ↑
                   No storage, pass-through only
```

- SuperQode reads keys from your environment
- Keys are passed to LiteLLM (local process)
- LiteLLM makes API calls to providers
- SuperQode never writes keys to disk

### ACP Mode

```
You → SuperQode CLI → Agent Process → Agent's Auth → Provider API
                      ↑
                      Agent manages its own auth
```

- SuperQode connects to agent subprocess
- Agent handles its own authentication
- Agent makes API calls using its credentials
- SuperQode doesn't see agent credentials

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
