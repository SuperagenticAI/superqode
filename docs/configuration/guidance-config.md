# Guidance Configuration

Configure QE guidance prompts that control agent behavior, time constraints, and verification requirements.

---

## Overview

Guidance configuration defines how QE agents operate:

- **Time Constraints**: Time limits for different modes
- **Verification Requirements**: Proof before success claims
- **Focus Areas**: What agents should prioritize
- **Forbidden Actions**: What agents should avoid
- **Anti-Pattern Detection**: Prevent common QE mistakes

---

## Basic Configuration

```yaml
qe:
  guidance:
    enabled: true
    require_proof: true
```

---

## Configuration Structure

```yaml
qe:
  guidance:
    enabled: true
    require_proof: true
    qr_format: "markdown"  # markdown, json, both

    # Mode-specific settings
    quick_scan: {}
    deep_qe: {}

    # Anti-pattern detection
    anti_patterns: {}
```

---

## Mode-Specific Configuration

### Quick Scan Configuration

Fast, focused analysis:

```yaml
qe:
  guidance:
    quick_scan:
      timeout_seconds: 60
      verification_first: true
      fail_fast: true
      exploration_allowed: false
      destructive_testing: false
      focus_areas:
        - "Run smoke tests first"
        - "Validate critical paths"
        - "Check for obvious errors"
      forbidden_actions:
        - "Long-running performance tests"
        - "Extensive code generation"
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout_seconds` | number | `60` | Maximum time for quick scan |
| `verification_first` | boolean | `true` | Verify before claiming success |
| `fail_fast` | boolean | `true` | Stop on first failure |
| `exploration_allowed` | boolean | `false` | Allow deep exploration |
| `destructive_testing` | boolean | `false` | Allow destructive tests |
| `focus_areas` | array | (see defaults) | Areas to prioritize |
| `forbidden_actions` | array | (see defaults) | Actions to avoid |

### Deep QE Configuration

Comprehensive analysis:

```yaml
qe:
  guidance:
    deep_qe:
      timeout_seconds: 1800
      verification_first: true
      fail_fast: false
      exploration_allowed: true
      destructive_testing: true
      focus_areas:
        - "Comprehensive test coverage"
        - "Edge case exploration"
        - "Security vulnerability scanning"
        - "Performance and load testing"
      forbidden_actions:
        - "Modifying production code"
        - "Committing changes to git"
        - "Accessing external networks"
```

**Fields:**

Same as `quick_scan`, but with different defaults optimized for thorough analysis.

---

## Complete Configuration Example

```yaml
qe:
  guidance:
    enabled: true
    require_proof: true
    qr_format: "markdown"

    quick_scan:
      timeout_seconds: 60
      verification_first: true
      fail_fast: true
      exploration_allowed: false
      destructive_testing: false
      focus_areas:
        - "Run smoke tests immediately"
        - "Validate authentication flows"
        - "Check for SQL injection patterns"
        - "Verify API endpoints respond"
      forbidden_actions:
        - "Running load tests"
        - "Deep code exploration"
        - "Generating extensive test suites"

    deep_qe:
      timeout_seconds: 1800
      verification_first: true
      fail_fast: false
      exploration_allowed: true
      destructive_testing: true
      focus_areas:
        - "Comprehensive security audit"
        - "Edge case and boundary testing"
        - "Performance profiling"
        - "Chaos engineering scenarios"
        - "Test coverage analysis"
      forbidden_actions:
        - "Committing to git repository"
        - "Modifying production configuration"
        - "Accessing external APIs without approval"

    anti_patterns:
      enabled: true
      patterns:
        - skip_verification
        - unconditional_success
        - broad_exception_swallow
        - weaken_tests
        - silent_fallback
        - guess_expected_output
```

---

## Anti-Pattern Detection

Configure detection of common QE mistakes:

```yaml
qe:
  guidance:
    anti_patterns:
      enabled: true
      patterns:
        - skip_verification      # Claiming success without proof
        - unconditional_success  # Always returning success
        - broad_exception_swallow  # Catching all exceptions
        - weaken_tests           # Making tests less strict
        - silent_fallback        # Hiding failures
        - guess_expected_output  # Guessing instead of checking
```

**Available Patterns:**

| Pattern | Description |
|---------|-------------|
| `skip_verification` | Success claimed without running tests |
| `unconditional_success` | Tests that always pass |
| `broad_exception_swallow` | Catching all exceptions without handling |
| `weaken_tests` | Making assertions less strict |
| `silent_fallback` | Hiding errors with fallback behavior |
| `guess_expected_output` | Guessing expected values instead of computing |

**Custom Patterns:**

Add custom anti-pattern detection (future feature):

```yaml
qe:
  guidance:
    anti_patterns:
      enabled: true
      patterns:
        - skip_verification
        - custom_pattern_name
```

---

## Verification-First Workflow

Require proof before claiming success:

```yaml
qe:
  guidance:
    require_proof: true  # Default: true
    quick_scan:
      verification_first: true  # Verify before success
```

**How It Works:**

1. Agent must run tests/checks
2. Agent must verify results
3. Agent can only claim success with proof

**Example Prompt (automatically added):**

```
VERIFICATION-FIRST REQUIREMENT:
- DO NOT claim success without running tests
- DO NOT assert findings without verification
- ALWAYS provide evidence (test output, logs, etc.)
```

---

## Time Constraints

Set time limits for each mode:

```yaml
qe:
  guidance:
    quick_scan:
      timeout_seconds: 60  # 1 minute

    deep_qe:
      timeout_seconds: 1800  # 30 minutes
```

**Recommendations:**

| Mode | Timeout | Rationale |
|------|---------|-----------|
| Quick Scan | 60s | Fast feedback loop |
| Deep QE | 1800s (30m) | Comprehensive analysis |

---

## Focus Areas

Guide agents on what to prioritize:

```yaml
qe:
  guidance:
    quick_scan:
      focus_areas:
        - "Run smoke tests first"
        - "Validate critical paths"
        - "Check for obvious errors"
        - "Verify basic functionality"
```

**Custom Focus Areas:**

```yaml
qe:
  guidance:
    quick_scan:
      focus_areas:
        - "Authentication and authorization"
        - "Input validation"
        - "Error handling"
        - "API response times"
```

**How Focus Areas Are Used:**

Focus areas are included in system prompts to guide agent behavior:

```
FOCUS AREAS:
1. Run smoke tests first
2. Validate critical paths
3. Check for obvious errors
```

---

## Forbidden Actions

Specify actions agents should avoid:

```yaml
qe:
  guidance:
    quick_scan:
      forbidden_actions:
        - "Long-running performance tests"
        - "Extensive code generation"
        - "Deep exploration without quick feedback"
```

**Custom Forbidden Actions:**

```yaml
qe:
  guidance:
    quick_scan:
      forbidden_actions:
        - "Running database migrations"
        - "Installing system packages"
        - "Modifying .env files"
```

**How Forbidden Actions Are Used:**

Included in system prompts as constraints:

```
FORBIDDEN ACTIONS:
- Long-running performance tests
- Extensive code generation
- Deep exploration without quick feedback
```

---

## QR Format

Control Quality Report format:

```yaml
qe:
  guidance:
    qr_format: "markdown"  # markdown, json, both
```

**Options:**

- `markdown`: Human-readable markdown report
- `json`: Machine-readable JSON report
- `both`: Generate both formats

---

## Role-Specific Guidance

Override guidance per role:

```yaml
team:
  modes:
    qe:
      roles:
        security_tester:
          guidance:
            timeout_seconds: 300
            focus_areas:
              - "OWASP Top 10 vulnerabilities"
              - "Authentication bypasses"
              - "Injection attacks"
```

---

## Advanced Configuration

### Custom Verification Requirements

```yaml
qe:
  guidance:
    require_proof: true
    proof_requirements:
      - "Test output must be shown"
      - "Before/after metrics required"
      - "Logs must be included"
```

### Exploration Control

Control how deeply agents can explore:

```yaml
qe:
  guidance:
    deep_qe:
      exploration_allowed: true
      exploration_depth: "deep"  # shallow, medium, deep
      max_exploration_time: 900  # seconds
```

### Destructive Testing

Allow agents to break things (in sandbox):

```yaml
qe:
  guidance:
    deep_qe:
      destructive_testing: true
      allowed_destructive_tests:
        - "Load testing"
        - "Stress testing"
        - "Chaos scenarios"
```

---

## Configuration Priority

Guidance configuration priority:

1. **Role-specific** (in `team.modes.qe.roles.<role>.guidance`)
2. **Mode-specific** (in `qe.guidance.<mode>`)
3. **Global** (in `qe.guidance`)

**Example:**

```yaml
qe:
  guidance:
    timeout_seconds: 60  # Global default

    quick_scan:
      timeout_seconds: 60  # Mode-specific

team:
  modes:
    qe:
      roles:
        security_tester:
          guidance:
            timeout_seconds: 300  # Role-specific override
```

---

## Best Practices

### 1. Match Timeouts to Use Case

```yaml
qe:
  guidance:
    quick_scan:
      timeout_seconds: 60  # Fast CI feedback
    deep_qe:
      timeout_seconds: 1800  # Comprehensive analysis
```

### 2. Use Verification-First

Always require proof:

```yaml
qe:
  guidance:
    require_proof: true
    quick_scan:
      verification_first: true
```

### 3. Define Clear Focus Areas

Guide agents explicitly:

```yaml
qe:
  guidance:
    quick_scan:
      focus_areas:
        - "Authentication flows"
        - "API endpoint validation"
        - "Error handling"
```

### 4. Enable Anti-Pattern Detection

Prevent common mistakes:

```yaml
qe:
  guidance:
    anti_patterns:
      enabled: true
      patterns:
        - skip_verification
        - unconditional_success
```

---

## Troubleshooting

### Agents Not Following Guidance

**Problem**: Agents ignore focus areas or forbidden actions

**Solution**: Verify guidance is enabled:

```yaml
qe:
  guidance:
    enabled: true  # Must be enabled
```

### Timeouts Too Short

**Problem**: Sessions timing out prematurely

**Solution**: Increase timeout:

```yaml
qe:
  guidance:
    quick_scan:
      timeout_seconds: 120  # Increase from 60
```

### Too Many False Positives

**Problem**: Agents claiming success without proof

**Solution**: Enable verification-first:

```yaml
qe:
  guidance:
    require_proof: true
    quick_scan:
      verification_first: true
```

---

## Next Steps

- [Guidance System](../advanced/guidance-system.md) - How guidance works
- [YAML Reference](yaml-reference.md) - Complete configuration reference
- [QE Modes](../concepts/modes.md) - Quick Scan vs Deep QE
