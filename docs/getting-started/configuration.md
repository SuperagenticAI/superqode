# Configuration

This guide covers SuperQode configuration, from basic setup to advanced customization.

---

## Configuration Files

SuperQode uses YAML configuration files with the following precedence (highest to lowest):

1. **Project**: `./superqode.yaml` (current directory)
2. **User**: `~/.superqode.yaml` (home directory)
3. **System**: `/etc/superqode/superqode.yaml` (system-wide)

---

## Initialize Configuration

Create a default configuration file:

```bash
# In your project directory (recommended)
cd /path/to/your/project
superqe init
```

`superqe init` writes a comprehensive role catalog to `superqode.yaml`. Keep only the roles you want enabled; leave the rest disabled or remove them.

---

## Basic Configuration

### Minimal Configuration

```yaml
# superqode.yaml
superqode:
  version: "2.0"
  team_name: "My Project"

# Default mode for all roles (ACP recommended)
default:
  mode: acp
  coding_agent: opencode
```

### Standard Configuration

```yaml
# superqode.yaml
superqode:
  version: "2.0"
  team_name: "My Development Team"
  description: "Quality engineering configuration"

# Gateway settings
superqode:
  gateway:
    type: litellm  # or openresponses
  cost_tracking:
    enabled: true
    show_after_task: true

# Default execution mode (ACP recommended, or BYOK with Google)
default:
  mode: byok
  provider: google
  model: gemini-3-pro

# Provider-specific settings
providers:
  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-3-pro
      - gemini-3
      - gemini-2.5-flash

  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o
      - gpt-4o-mini

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
      - llama3.2:latest
```

---

## Team Configuration

Define roles and modes for your team:

```yaml
team:
  modes:
    # Development mode
    dev:
      description: "Development team roles"
      enabled: true
      roles:
        fullstack:
          description: "Full-stack developer"
          mode: acp
          coding_agent: opencode
          enabled: true

    # Quality Engineering mode
    qe:
      description: "Quality engineering roles"
      enabled: true
      roles:
        lint_tester:
          description: "Fast static linting"
          enabled: true

        security_tester:
          description: "Security vulnerability detection"
          mode: acp
          coding_agent: opencode
          enabled: true
          job_description: |
            Focus on OWASP Top 10 vulnerabilities,
            injection attacks, authentication flaws,
            and sensitive data exposure.

        api_tester:
          description: "API contract and security testing"
          mode: byok
          provider: google
          model: gemini-3-pro
          enabled: true
          job_description: |
            Test API endpoints for schema compliance,
            input validation, rate limiting, and
            proper error handling.

        performance_tester:
          description: "Performance bottleneck detection"
          mode: byok
          provider: openai
          model: gpt-4o
          enabled: true

        fullstack:
          description: "Senior QE comprehensive review"
          mode: acp
          coding_agent: opencode
          enabled: true
```

---

## QE Configuration

Configure quality engineering settings:

```yaml
qe:
  # Output settings
  output:
    directory: ".superqode"
    reports_format: markdown  # markdown, html, json
    keep_history: true

  # Suggestion workflow (OFF by default)
  allow_suggestions: false
  suggestions:
    enabled: false
    verify_fixes: true
    require_proof: true
    auto_generate_tests: false
    max_fix_attempts: 3
    revert_on_failure: true

  # Noise filtering
  noise:
    min_confidence: 0.7
    deduplicate: true
    min_severity: "low"  # low, medium, high, critical
    suppress_known_risks: false
    max_per_file: 10
    max_total: 100

  # Execution modes
  modes:
    quick_scan:
      timeout: 60
      depth: shallow
      generate_tests: false
      destructive: false

    deep_qe:
      timeout: 1800
      depth: full
      generate_tests: true
      destructive: true

  # Harness validation
  harness:
    enabled: true
    timeout_seconds: 30
    fail_on_error: false
    structural_formats:
      - json
      - yaml
      - toml
    python_tools:
      - ruff
      - mypy
    javascript_tools:
      - eslint
    typescript_tools:
      - tsc
      - eslint
    go_tools:
      - go vet
      - golangci-lint
    rust_tools:
      - cargo check
    shell_tools:
      - shellcheck
```

---

## Provider Configuration

### BYOK Providers

```yaml
providers:
  # Anthropic (Claude)
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    description: "Claude models by Anthropic"
    recommended_models:
      - claude-opus-4-5
      - claude-sonnet-4-5
      - claude-haiku-4-5

  # OpenAI
  openai:
    api_key_env: OPENAI_API_KEY
    description: "GPT models by OpenAI"
    recommended_models:
      - gpt-4o
      - gpt-4o-mini
      - o1
      - o1-mini

  # Google AI
  google:
    api_key_env: GOOGLE_API_KEY
    description: "Gemini models by Google"
    recommended_models:
      - gemini-2.5-pro
      - gemini-2.5-flash

  # Deepseek
  deepseek:
    api_key_env: DEEPSEEK_API_KEY
    description: "Deepseek models"
    recommended_models:
      - deepseek-v3
      - deepseek-r1

  # OpenRouter (aggregator)
  openrouter:
    api_key_env: OPENROUTER_API_KEY
    description: "Access 95+ models via OpenRouter"
    recommended_models:
      - anthropic/claude-sonnet-4
      - openai/gpt-4o
      - google/gemini-2.5-pro
```

### Local Providers

```yaml
providers:
  ollama:
    base_url: http://localhost:11434
    description: "Local Ollama models"
    type: openai-compatible
    recommended_models:
      - qwen3:8b
      - llama3.2:latest
      - codellama:13b

  lmstudio:
    base_url: http://localhost:1234
    description: "LM Studio local models"
    type: openai-compatible

  vllm:
    base_url: http://localhost:8000
    description: "vLLM inference server"
    type: openai-compatible
```

### OpenResponses Gateway

```yaml
superqode:
  gateway:
    type: openresponses
    openresponses:
      base_url: http://localhost:11434
      reasoning_effort: medium  # low, medium, high
      truncation: auto
      timeout: 300.0
      enable_apply_patch: true
      enable_code_interpreter: true
      enable_file_search: false
```

---

## MCP Server Configuration

Configure Model Context Protocol servers:

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    auto_connect: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "/path/to/workspace"

  github:
    transport: stdio
    enabled: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"

  database:
    transport: http
    enabled: false
    url: http://localhost:8080/mcp
    headers:
      Authorization: "Bearer ${MCP_DB_TOKEN}"
    timeout: 30.0
```

---

## Agent Configuration

Configure ACP agents:

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

  custom_agent:
    description: "Custom ACP agent"
    protocol: acp
    command: /path/to/agent
    args:
      - --mode
      - interactive
```

---

## Role Configuration Details

### Role Properties

| Property | Type | Description |
|----------|------|-------------|
| `description` | string | Human-readable role description |
| `mode` | enum | Execution mode: `byok`, `acp`, `local` |
| `provider` | string | Provider ID (for BYOK/Local) |
| `model` | string | Model ID |
| `agent` | string | Agent ID (for ACP mode) |
| `enabled` | bool | Whether role is active |
| `job_description` | string | Detailed job description for agent |
| `mcp_servers` | list | MCP servers to connect |
| `expert_prompt_enabled` | bool | Enterprise expert system prompts |
| `expert_prompt` | string | Enterprise expert prompt override |

### Example Role with All Options

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          description: "Security vulnerability detection"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
          job_description: |
            You are a senior security engineer specializing in:
            - OWASP Top 10 vulnerability detection
            - SQL injection and XSS prevention
            - Authentication and authorization flaws
            - Sensitive data exposure
            - Security misconfigurations

            Focus on finding vulnerabilities that could be
            exploited in production environments.
          mcp_servers:
            - filesystem
          expert_prompt_enabled: false  # Enterprise
          cross_validation:
            enabled: true
            exclude_same_model: true
```

---

## Environment Variables

SuperQode respects these environment variables:

| Variable | Description |
|----------|-------------|
| `SUPERQODE_CONFIG` | Path to configuration file |
| `SUPERQODE_OUTPUT_DIR` | Default output directory |
| `SUPERQODE_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google AI API key |
| `DEEPSEEK_API_KEY` | Deepseek API key |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

---

## Configuration Commands

### View Configuration

```bash
# List configured modes and roles
superqode config list-modes

# Show role details
superqode roles info qe.security_tester
```

### Modify Configuration

```bash
# Set model for a role
superqode config set-model qe.security_tester claude-opus-4-5

# Set agent for a role
superqode config set-agent qe.fullstack opencode

# Enable/disable roles
superqode config enable-role qe.performance_tester
superqode config disable-role qe.e2e_tester
```

---

## Configuration Validation

SuperQode validates configuration on load. Common validation errors:

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid provider` | Provider not in registry | Check provider name spelling |
| `Missing API key` | Environment variable not set | Set the required API key |
| `Invalid mode` | Mode not `byok`, `acp`, or `local` | Use valid mode value |
| `Unknown agent` | Agent not registered | Check agent name or install it |

---

## Next Steps

- [YAML Reference](../configuration/yaml-reference.md) - Complete configuration reference
- [Team Configuration](../configuration/team.md) - Advanced team setup
- [Provider Setup](../providers/index.md) - Provider-specific configuration
- [QE Settings](../configuration/yaml-reference.md) - Quality engineering options
