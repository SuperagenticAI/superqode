<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Configuration Reference

This section provides comprehensive documentation for configuring SuperQode through YAML configuration files.

---

## Quick Navigation

<div class="grid cards" markdown>

-   **YAML Reference**

    ---

    Complete reference for all configuration options with examples and defaults.

    [:octicons-arrow-right-24: YAML Reference](yaml-reference.md)

-   **Team Configuration**

    ---

    Configure team modes, roles, and multi-agent settings.

    [:octicons-arrow-right-24: Team Configuration](team.md)

-   **Provider Configuration**

    ---

    Configure BYOK, ACP, and local provider settings.

    [:octicons-arrow-right-24: Provider Configuration](../providers/index.md)

-   **MCP Configuration**

    ---

    Configure Model Context Protocol servers for tool integration.

    [:octicons-arrow-right-24: MCP Configuration](mcp-config.md)

-   **Noise Configuration**

    ---

    Configure noise filtering, deduplication, and severity thresholds.

    [:octicons-arrow-right-24: Noise Configuration](noise-config.md)

-   **Guidance Configuration**

    ---

    Configure QE guidance prompts, time constraints, and verification requirements.

    [:octicons-arrow-right-24: Guidance Configuration](guidance-config.md)

</div>

---

## Configuration File Locations

SuperQode loads configuration from multiple locations in order of precedence:

| Priority | Location | Scope |
|----------|----------|-------|
| 1 (highest) | `./superqode.yaml` | Project-specific |
| 2 | `~/.superqode.yaml` | User-specific |
| 3 (lowest) | `/etc/superqode/superqode.yaml` | System-wide |

Values in higher-priority files override lower ones.

---

## Creating Configuration

### Initialize Project Configuration

```bash
superqe init
```

Creates `superqode.yaml` in the current directory.
The generated file includes a comprehensive role catalog; disable or remove roles you don’t need.

### Optional: User Configuration

If you want user-wide defaults, you can create `~/.superqode.yaml` manually (it has lower precedence than `./superqode.yaml`).

---

## Minimal Configuration

The simplest valid configuration (ACP recommended):

```yaml
superqode:
  version: "2.0"
  team_name: "My Project"

default:
  mode: acp
  coding_agent: opencode
```

Or with BYOK:

```yaml
superqode:
  version: "2.0"
  team_name: "My Project"

default:
  mode: byok
  provider: google
  model: gemini-3-pro
```

---

## Standard Configuration

A typical project configuration:

```yaml
superqode:
  version: "2.0"
  team_name: "My Project"
  description: "Quality engineering configuration"

# Gateway settings
superqode:
  gateway:
    type: litellm
  cost_tracking:
    enabled: true
    show_after_task: true

# Default execution mode (ACP recommended, or BYOK with Google)
default:
  mode: byok
  provider: google
  model: gemini-3-pro

# Provider settings
providers:
  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-3-pro
      - gemini-3
      - gemini-2.5-flash

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
      - llama3.2:latest

# QE settings
qe:
  output:
    directory: ".superqode"
    reports_format: markdown

  allow_suggestions: false

  noise:
    min_confidence: 0.7
    min_severity: "low"

# Team roles
team:
  modes:
    qe:
      description: "Quality engineering roles"
      enabled: true
      roles:
        security_tester:
          enabled: true
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
```

---

## Configuration Sections

### Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Configuration format version |
| `team_name` | string | Team or project name |
| `description` | string | Configuration description |

### superqode Section

Gateway and global settings:

```yaml
superqode:
  gateway:
    type: litellm  # or openresponses
  cost_tracking:
    enabled: true
    show_after_task: true
```

### default Section

Default execution mode for all roles:

```yaml
default:
  mode: acp           # acp (recommended), byok, or local
  coding_agent: opencode  # Agent ID (for ACP mode)
  # Or for BYOK:
  # mode: byok
  # provider: google  # Provider ID
  # model: gemini-3-pro  # Model ID
```

### providers Section

Provider-specific settings:

```yaml
providers:
  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-3-pro
      - gemini-3
      - gemini-2.5-flash
```

### qe Section

Quality engineering settings:

```yaml
qe:
  allow_suggestions: false
  noise:
    min_confidence: 0.7
```

### team Section

Team modes and roles:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          enabled: true
```

---

## Viewing Configuration

```bash
# View the current project config
cat superqode.yaml

# View configured modes/roles
superqode config list-modes
```

---

## Modifying Configuration

### Using CLI

```bash
# Update common settings
superqode config set-model qe.security_tester claude-opus-4-5
superqode config set-agent qe.fullstack opencode
superqode config enable-role qe.security_tester
superqode config disable-role qe.performance_tester
```

### Editing Directly

Edit `superqode.yaml` with your preferred editor.

---

## Validating Configuration

```bash
superqe run . --mode quick
```

This will load your config and surface common configuration and dependency issues.

---

## Environment Variables

Configuration can reference environment variables:

```yaml
providers:
  google:
    api_key_env: GOOGLE_API_KEY  # Will read from $GOOGLE_API_KEY
```

SuperQode respects these environment variables:

| Variable | Description |
|----------|-------------|
| `SUPERQODE_CONFIG` | Override config file path |
| `SUPERQODE_OUTPUT_DIR` | Default output directory |
| `SUPERQODE_LOG_LEVEL` | Logging level |

---

## Common Patterns

### Multi-Provider Setup

```yaml
providers:
  google:
    api_key_env: GOOGLE_API_KEY
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
  openai:
    api_key_env: OPENAI_API_KEY
  ollama:
    base_url: http://localhost:11434

team:
  modes:
    qe:
      roles:
        security_tester:
          mode: acp
          coding_agent: opencode
        api_tester:
          mode: byok
          provider: google
          model: gemini-3-pro
        unit_tester:
          mode: local
          provider: ollama
          model: qwen3:8b
```

### Role-Specific Configuration

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          enabled: true
          mode: acp
          coding_agent: opencode
          job_description: |
            Focus on OWASP Top 10 vulnerabilities,
            injection attacks, authentication flaws.
          expert_prompt_enabled: false  # Enterprise
```

### Noise Filtering

```yaml
qe:
  noise:
    min_confidence: 0.8
    min_severity: "medium"
    deduplicate: true
    max_per_file: 5
    max_total: 50
```

---

## Troubleshooting

### Configuration Not Found

```
No configuration found.
Run 'superqe init' to create a configuration.
```

**Solution**: Create a configuration file.

### Invalid YAML Syntax

```
Error loading configuration: YAML syntax error
```

**Solution**: Check indentation and formatting.

### Missing API Key

```
Warning: Provider 'google': GOOGLE_API_KEY not set
```

**Solution**: Set the environment variable.

---

## Next Steps

- [YAML Reference](yaml-reference.md) - Complete configuration reference
- [Team Configuration](team.md) - Advanced team setup
- [MCP Configuration](mcp-config.md) - MCP server setup
- [Noise Configuration](noise-config.md) - Filtering and deduplication
- [Guidance Configuration](guidance-config.md) - QE guidance prompts
