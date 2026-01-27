<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Team Configuration

Configure team modes, roles, and multi-agent settings for coordinated quality engineering.

---

## Overview

SuperQode's team configuration allows you to:

- Define multiple execution modes (dev, qe, etc.)
- Configure roles with specific providers and models
- Set up cross-model validation
- Customize job descriptions (expert prompts are Enterprise)

---

## Team Structure

```yaml
team:
  modes:
    <mode_id>:
      description: string
      enabled: boolean
      roles:
        <role_id>:
          # Role configuration
```

---

## Defining Modes

Modes group related roles together:

```yaml
team:
  modes:
    dev:
      description: "Development team roles"
      enabled: true
      roles:
        fullstack:
          enabled: true
          mode: byok
          provider: anthropic
          model: claude-sonnet-4

    qe:
      description: "Quality engineering roles"
      enabled: true
      roles:
        security_tester:
          enabled: true
        api_tester:
          enabled: true
        fullstack:
          enabled: true
```

---

## Role Configuration

### Basic Role

```yaml
roles:
  security_tester:
    description: "Security vulnerability detection"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    enabled: true
```

### Role Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `description` | string | No | Human-readable description |
| `mode` | string | Yes | `byok`, `acp`, or `local` |
| `provider` | string | Yes* | Provider ID (for byok/local) |
| `model` | string | Yes* | Model ID (for byok/local) |
| `agent` | string | Yes* | Agent ID (for acp mode) |
| `enabled` | boolean | No | Whether role is active (default: true) |
| `job_description` | string | No | Detailed job description |
| `expert_prompt_enabled` | boolean | No | Enterprise expert system prompts |
| `expert_prompt` | string | No | Enterprise custom expert prompt |
| `mcp_servers` | [string] | No | MCP servers to connect |
| `cross_validation` | object | No | Cross-model validation settings |

---

## Job Descriptions

Job descriptions guide the agent's focus:

```yaml
roles:
  security_tester:
    description: "Security vulnerability detection"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    enabled: true
    job_description: |
      You are a senior security engineer specializing in:

      **Primary Focus:**
      - OWASP Top 10 vulnerability detection
      - SQL injection and XSS prevention
      - Authentication and authorization flaws
      - Sensitive data exposure analysis
      - Security misconfigurations

      **Testing Approach:**
      - Analyze code for common vulnerability patterns
      - Look for insecure data handling
      - Check authentication implementations
      - Review authorization logic
      - Identify hardcoded secrets

      **Reporting:**
      - Prioritize critical and high severity findings
      - Include reproduction steps
      - Suggest remediation approaches
      - Provide evidence for each finding
```

---

## Expert Prompts (Enterprise)

Expert prompts are available in SuperQode Enterprise. OSS ignores these fields.

---

## Cross-Model Validation

Run roles with multiple models for higher confidence:

```yaml
roles:
  security_tester:
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    enabled: true
    cross_validation:
      enabled: true
      exclude_same_model: true
```

When enabled:
- The role runs with multiple different models
- Findings are cross-validated
- Only findings confirmed by multiple models are reported
- Confidence scores are adjusted based on agreement

---

## MCP Server Integration

Connect roles to MCP servers:

```yaml
roles:
  security_tester:
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    enabled: true
    mcp_servers:
      - filesystem
      - github
```

---

## Mode-Specific Models

Use different models for different roles:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          provider: anthropic
          model: claude-sonnet-4  # Best for security analysis

        api_tester:
          provider: anthropic
          model: claude-sonnet-4

        performance_tester:
          provider: openai
          model: gpt-4o  # Good for performance analysis

        unit_tester:
          mode: local
          provider: ollama
          model: qwen3:8b  # Cost-effective for unit tests
```

---

## Mixed Execution Modes

Combine BYOK, ACP, and local modes:

```yaml
team:
  modes:
    qe:
      roles:
        # Cloud model for critical analysis
        security_tester:
          mode: byok
          provider: anthropic
          model: claude-sonnet-4

        # ACP agent for comprehensive testing
        fullstack:
          mode: acp
          coding_agent: opencode

        # Local model for high-volume tasks
        unit_tester:
          mode: local
          provider: ollama
          model: qwen3:8b
```

---

## QE Role Types

### Execution Roles

Deterministic roles that run existing tests:

```yaml
roles:
  smoke_tester:
    description: "Fast critical path validation"
    enabled: true
    # No AI model needed - runs existing tests

  sanity_tester:
    description: "Quick core functionality verification"
    enabled: true

  regression_tester:
    description: "Full test suite execution"
    enabled: true

  lint_tester:
    description: "Fast static linting across languages"
    enabled: true
```

### Detection Roles

AI-powered issue discovery:

```yaml
roles:
  security_tester:
    description: "Security vulnerability detection"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    job_description: |
      Focus on OWASP Top 10, injection attacks,
      authentication flaws, and sensitive data exposure.

  api_tester:
    description: "API contract and security testing"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    job_description: |
      Test API endpoints for schema compliance,
      input validation, rate limiting, and error handling.

  unit_tester:
    description: "Test coverage and unit test gaps"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4

  e2e_tester:
    description: "End-to-end workflow testing"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4

  performance_tester:
    description: "Performance bottleneck detection"
    mode: byok
    provider: openai
    model: gpt-4o
```

### Heuristic Role

Senior QE comprehensive review:

```yaml
roles:
  fullstack:
    description: "Senior QE comprehensive review"
    mode: byok
    provider: anthropic
    model: claude-sonnet-4
    job_description: |
      Provide a comprehensive quality assessment:
      - Cross-cutting concerns
      - Architecture issues
      - Trade-off awareness
      - Risk prioritization
      - Production readiness verdict
```

---

## Managing Roles via CLI

### Enable/Disable Roles

```bash
# Enable a role
superqode config enable-role qe.performance_tester

# Disable a role
superqode config disable-role qe.e2e_tester
```

### View Role Configuration

```bash
superqode roles info qe.security_tester
```

### Change Role Model

```bash
superqode config set-model qe.security_tester claude-opus-4-5
```

---

## Complete Example

```yaml
team:
  modes:
    qe:
      description: "Quality engineering team"
      enabled: true
      roles:
        # Execution roles (no AI)
        smoke_tester:
          description: "Critical path validation"
          enabled: true

        sanity_tester:
          description: "Core functionality check"
          enabled: true

        regression_tester:
          description: "Full test suite"
          enabled: true

        lint_tester:
          description: "Fast static linting"
          enabled: true

        # Detection roles (AI-powered)
        security_tester:
          description: "Security vulnerability detection"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
          job_description: |
            Focus on OWASP Top 10 vulnerabilities,
            injection attacks, and authentication flaws.
          expert_prompt_enabled: false  # Enterprise
          cross_validation:
            enabled: true
            exclude_same_model: true

        api_tester:
          description: "API contract testing"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
          job_description: |
            Test API endpoints for schema compliance,
            input validation, and error handling.

        unit_tester:
          description: "Unit test coverage"
          mode: local
          provider: ollama
          model: qwen3:8b
          enabled: true

        performance_tester:
          description: "Performance analysis"
          mode: byok
          provider: openai
          model: gpt-4o
          enabled: true

        e2e_tester:
          description: "End-to-end testing"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: false  # Disabled by default

        # Heuristic role
        fullstack:
          description: "Senior QE comprehensive review"
          mode: byok
          provider: anthropic
          model: claude-sonnet-4
          enabled: true
          job_description: |
            Provide comprehensive quality assessment
            with production readiness verdict.
```

---

## Next Steps

- [Provider Configuration](../providers/index.md) - Provider-specific settings
- [QE Settings](yaml-reference.md) - Quality engineering options
- [Role Configuration](yaml-reference.md) - Role configuration reference
