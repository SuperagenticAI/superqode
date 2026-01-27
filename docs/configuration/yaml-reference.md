# YAML Reference

Complete reference for all SuperQode configuration options.

---

## Configuration Structure

```yaml
superqode:
  version: "2.0"
  team_name: string
  description: string
  gateway: {}
  cost_tracking: {}

default:
  mode: string
  provider: string
  model: string

providers: {}
agents: {}
mcp_servers: {}

qe:
  output: {}
  allow_suggestions: boolean
  suggestions: {}
  noise: {}
  modes: {}
  optimize: {}
  harness: {}

team:
  modes: {}
```

---

## Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `superqode` | object | Yes | `{}` | Global SuperQode metadata and settings |
| `default` | object | No | `null` | Default execution mode for roles |
| `providers` | object | No | `{}` | Provider-specific settings |
| `agents` | object | No | `{}` | ACP agent definitions |
| `mcp_servers` | object | No | `{}` | MCP server definitions |
| `qe` | object | No | `{}` | QE-specific settings |
| `team` | object | No | `{}` | Team modes and roles |

---

## superqode Section

Global SuperQode settings.

### superqode.version

Configuration format version.

### superqode.team_name

Team or project name.

### superqode.description

Configuration description.

### superqode.gateway

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"litellm"` | Gateway type: `litellm` or `openresponses` |

#### OpenResponses Gateway

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

### superqode.cost_tracking

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable cost tracking |
| `show_after_task` | boolean | `true` | Show cost summary after tasks |

---

## default Section

Default execution mode for all roles.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | string | Yes | Execution mode: `byok`, `acp`, `local` |
| `provider` | string | Yes* | Provider ID (required for byok/local) |
| `model` | string | Yes* | Model ID (required for byok/local) |
| `agent` | string | Yes* | Agent ID (required for acp) |

```yaml
default:
  mode: byok
  provider: anthropic
  model: claude-sonnet-4
```

---

## providers Section

BYOK and local provider configurations.

### Provider Schema

```yaml
providers:
  <provider_id>:
    api_key_env: string        # Environment variable for API key
    optional_env: [string]     # Optional environment variables
    base_url_env: string       # Environment variable for base URL
    default_base_url: string   # Default base URL
    description: string        # Provider description
    recommended_models: [string]  # Recommended models
```

### Common Providers

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - claude-opus-4-5
      - claude-sonnet-4-5
      - claude-sonnet-4
      - claude-haiku-4

  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o
      - gpt-4o-mini
      - o1
      - o1-mini

  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-2.5-pro
      - gemini-2.5-flash

  deepseek:
    api_key_env: DEEPSEEK_API_KEY
    recommended_models:
      - deepseek-v3
      - deepseek-r1

  ollama:
    base_url: http://localhost:11434
    type: openai-compatible
    recommended_models:
      - qwen3:8b
      - llama3.2:latest

  lmstudio:
    base_url: http://localhost:1234
    type: openai-compatible

  vllm:
    base_url: http://localhost:8000
    type: openai-compatible
```

---

## agents Section

ACP agent configurations.

### Agent Schema

```yaml
agents:
  <agent_id>:
    description: string
    protocol: string         # acp
    command: string          # Command to run
    args: [string]           # Command arguments
    auth_file: string        # Path to auth file
    capabilities: [string]   # Agent capabilities
```

### Example

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
```

---

## mcp_servers Section

Model Context Protocol server configurations.

### MCP Server Schema

```yaml
mcp_servers:
  <server_id>:
    transport: string        # stdio or http
    enabled: boolean
    auto_connect: boolean
    command: string          # For stdio transport
    args: [string]           # Command arguments
    env: {}                  # Environment variables
    url: string              # For http transport
    headers: {}              # HTTP headers
    timeout: number          # Request timeout
```

### Examples

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

## qe Section

Quality engineering settings.

### qe.output

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `directory` | string | `".superqode"` | Output directory |
| `reports_format` | string | `"markdown"` | Format: `markdown`, `html`, `json` |
| `keep_history` | boolean | `true` | Keep session history |

### qe.allow_suggestions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allow_suggestions` | boolean | `false` | Enable suggestion mode |

### qe.suggestions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable suggestions |
| `verify_fixes` | boolean | `true` | Run tests to verify fixes |
| `require_proof` | boolean | `true` | Require before/after metrics |
| `auto_generate_tests` | boolean | `false` | Generate regression tests |
| `max_fix_attempts` | integer | `3` | Max attempts per issue |
| `revert_on_failure` | boolean | `true` | Revert if fix fails |

### qe.noise

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_confidence` | float | `0.7` | Minimum confidence threshold |
| `deduplicate` | boolean | `true` | Remove duplicate findings |
| `min_severity` | string | `"low"` | Minimum severity to report |
| `suppress_known_risks` | boolean | `false` | Suppress known risks |
| `max_per_file` | integer | `10` | Max findings per file |
| `max_total` | integer | `100` | Max total findings |

### qe.modes

| Field | Type | Description |
|-------|------|-------------|
| `quick_scan` | object | Quick scan mode settings |
| `deep_qe` | object | Deep QE mode settings |

```yaml
qe:
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
```

### qe.harness

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable harness validation |
| `timeout_seconds` | integer | `30` | Validation timeout |
| `fail_on_error` | boolean | `false` | Fail on validation error |
| `structural_formats` | [string] | `[json, yaml, toml]` | Structural validation |
| `python_tools` | [string] | `[ruff, mypy]` | Python linters |
| `javascript_tools` | [string] | `[eslint]` | JavaScript linters |
| `typescript_tools` | [string] | `[tsc, eslint]` | TypeScript linters |
| `go_tools` | [string] | `[go vet, golangci-lint]` | Go linters |
| `rust_tools` | [string] | `[cargo check]` | Rust linters |
| `shell_tools` | [string] | `[shellcheck]` | Shell linters |
| `custom_steps` | [object] | `[]` | Custom command-based harness steps |

#### qe.harness.custom_steps (BYOH)

Each entry defines a project-specific harness command. Commands run from the repo root; non-zero exit
codes are reported as harness errors.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `command` | Display name for reporting |
| `command` | string | `""` | Shell command to run |
| `enabled` | boolean | `true` | Enable the step |
| `timeout` | integer | `300` | Timeout in seconds |

```yaml
qe:
  harness:
    custom_steps:
      - name: "contracts"
        command: "python scripts/check_contracts.py"
        timeout: 180
      - name: "smoke-tests"
        command: "pytest -q tests/smoke"
        enabled: true
```

### qe.optimize

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable SuperOpt hook |
| `command` | string | `""` | Command to run SuperOpt |
| `timeout_seconds` | integer | `300` | Command timeout |

```yaml
qe:
  optimize:
    enabled: true
    command: "python -m superqode.integrations.superopt_runner --trace {trace} --output {output} --config superqode.yaml"
    timeout_seconds: 300
```

---

## team Section

Team modes and role configurations.

### Team Mode Schema

```yaml
team:
  modes:
    <mode_id>:
      description: string
      enabled: boolean
      roles: {}
```

### Role Schema

```yaml
team:
  modes:
    <mode_id>:
      roles:
        <role_id>:
          description: string
          mode: string          # byok, acp, local
          provider: string      # Provider ID
          model: string         # Model ID
          agent: string         # Agent ID (for acp)
          enabled: boolean
          job_description: string
          mcp_servers: [string]
          expert_prompt_enabled: boolean  # Enterprise
          expert_prompt: string  # Enterprise
          cross_validation:
            enabled: boolean
            exclude_same_model: boolean
```

### Complete Team Example

```yaml
team:
  modes:
    qe:
      description: "Quality engineering roles"
      enabled: true
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
            - Sensitive data exposure analysis
          expert_prompt_enabled: false  # Enterprise
          cross_validation:
            enabled: true
            exclude_same_model: true

        api_tester:
          description: "API contract and security testing"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true

        performance_tester:
          description: "Performance bottleneck detection"
          mode: byok
          provider: openai
          model: gpt-4o
          enabled: true

        fullstack:
          description: "Senior QE comprehensive review"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
```

---

## Complete Example

```yaml
superqode:
  version: "2.0"
  team_name: "My Project"
  description: "Complete SuperQode configuration"
  gateway:
    type: litellm
  cost_tracking:
    enabled: true
    show_after_task: true

default:
  mode: byok
  provider: anthropic
  model: claude-sonnet-4

providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - claude-opus-4-5
      - claude-sonnet-4-5
      - claude-sonnet-4
      - claude-haiku-4

  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o
      - gpt-4o-mini

  ollama:
    base_url: http://localhost:11434
    type: openai-compatible
    recommended_models:
      - qwen3:8b
      - llama3.2:latest

agents:
  opencode:
    description: "OpenCode coding agent"
    protocol: acp
    command: opencode
    capabilities:
      - file_editing
      - shell_execution
      - mcp_tools

mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    auto_connect: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "."

qe:
  output:
    directory: ".superqode"
    reports_format: markdown
    keep_history: true

  allow_suggestions: false

  suggestions:
    enabled: false
    verify_fixes: true
    require_proof: true
    auto_generate_tests: false
    max_fix_attempts: 3

  noise:
    min_confidence: 0.7
    deduplicate: true
    min_severity: "low"
    max_per_file: 10
    max_total: 100

  harness:
    enabled: true
    timeout_seconds: 30
    python_tools:
      - ruff
      - mypy
    javascript_tools:
      - eslint
    typescript_tools:
      - tsc
      - eslint

team:
  modes:
    qe:
      description: "Quality engineering roles"
      enabled: true
      roles:
        security_tester:
          description: "Security vulnerability detection"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true

        api_tester:
          description: "API contract testing"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true

        unit_tester:
          description: "Unit test coverage"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true

        performance_tester:
          description: "Performance analysis"
          mode: byok
          provider: openai
          model: gpt-4o
          enabled: true

        fullstack:
          description: "Senior QE review"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
```

---

## Next Steps

- [Team Configuration](team.md) - Advanced team setup
- [Providers](../providers/index.md) - Provider-specific settings
- [QE Settings](#qe-section) - Quality engineering options
