<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Guidance System

Verification-first system prompts that guide QE agents to prevent false positives and time waste.

---

## Overview

The Guidance System provides time-constrained, verification-first prompts for QE agents:

- **Prevents false positives**: Agents must verify before claiming success
- **Reduces time waste**: Guides agents to get quick feedback first
- **Mode-specific**: Different guidance for quick scan vs deep QE
- **Anti-pattern detection**: Identifies common QE anti-patterns

---

## Principles

### Verification First

Agents must **prove** their findings before claiming success:

- Run tests to verify issues
- Provide evidence for claims
- Don't assume without checking

### Time Optimization

Guidance optimizes for time-constrained sessions:

- **Quick Scan**: Fail fast, validate critical paths
- **Deep QE**: Explore thoroughly, test edge cases

### Anti-Pattern Prevention

Guards against common mistakes:

- Skipping verification
- Claiming unconditional success
- Broad exception handling
- Weakening tests

---

## Configuration

### YAML Configuration

```yaml
superqode:
  qe:
    guidance:
      enabled: true
      require_proof: true

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
        forbidden_actions:
          - "Modifying production code"
          - "Committing changes to git"

      anti_patterns:
        enabled: true
        patterns:
          - skip_verification
          - unconditional_success
          - broad_exception_swallow
          - weaken_tests
```

---

## Mode Configurations

### Quick Scan

**Optimized for speed** (60 seconds):

```yaml
quick_scan:
  timeout_seconds: 60
  verification_first: true
  fail_fast: true
  exploration_allowed: false
  destructive_testing: false
```

**Focus Areas**:
- Run smoke tests first
- Validate critical paths
- Check for obvious errors
- Verify basic functionality

**Forbidden**:
- Long-running performance tests
- Extensive code generation
- Deep exploration without feedback

### Deep QE

**Comprehensive analysis** (30 minutes):

```yaml
deep_qe:
  timeout_seconds: 1800
  verification_first: true
  fail_fast: false
  exploration_allowed: true
  destructive_testing: true
```

**Focus Areas**:
- Comprehensive test coverage
- Edge case exploration
- Security vulnerability scanning
- Performance and load testing
- Chaos and stress testing

**Forbidden**:
- Modifying production code
- Committing changes to git
- Accessing external networks without approval

---

## Anti-Pattern Detection

The guidance system detects and prevents common QE anti-patterns that lead to false positives and unreliable results.

### What Are Anti-Patterns?

Anti-patterns are behaviors that undermine QE reliability:

- Claiming success without evidence
- Weakening tests to make them pass
- Ignoring errors silently
- Guessing expected outputs

### Detected Anti-Patterns

#### 1. Skip Verification

**Pattern**: Claiming success without running tests.

```python
# [INCORRECT] Anti-pattern
def check_code():
    return "PASS"  # Never actually runs tests

# [CORRECT] Correct
def check_code():
    result = run_tests()
    return "PASS" if result.success else "FAIL"
```

**Detection**: No test execution recorded before success claim.

#### 2. Unconditional Success

**Pattern**: Always returning success regardless of outcome.

```bash
# [INCORRECT] Anti-pattern
pytest || true  # Always succeeds

# [CORRECT] Correct
pytest  # Fails if tests fail
```

**Detection**: Exit code manipulation, `|| true` patterns.

#### 3. Weaken Tests

**Pattern**: Modifying tests to pass instead of fixing code.

```python
# [INCORRECT] Anti-pattern
def test_auth():
    # Changed from assertEqual to assertTrue
    assert True  # Was: assert response.status == 401

# [CORRECT] Correct
def test_auth():
    assert response.status == 401  # Fix the code, not the test
```

**Detection**: Test file modifications that remove assertions.

#### 4. Broad Exception Swallow

**Pattern**: Catching all exceptions and hiding errors.

```python
# [INCORRECT] Anti-pattern
try:
    risky_operation()
except Exception:
    pass  # Silently ignore all errors

# [CORRECT] Correct
try:
    risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise
```

**Detection**: Bare `except:` or `except Exception:` with no handling.

#### 5. Silent Fallback

**Pattern**: Returning default values when operations fail.

```python
# [INCORRECT] Anti-pattern
def get_user(id):
    try:
        return database.get(id)
    except:
        return None  # Hide the error

# [CORRECT] Correct
def get_user(id):
    try:
        return database.get(id)
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise UserNotFoundError(id)
```

**Detection**: Error suppression with default returns.

#### 6. Guess Expected Output

**Pattern**: Not verifying actual vs expected output.

```python
# [INCORRECT] Anti-pattern
def test_api():
    response = client.get("/users")
    # Just check status, not content
    assert response.status_code == 200

# [CORRECT] Correct
def test_api():
    response = client.get("/users")
    assert response.status_code == 200
    assert "users" in response.json()
    assert len(response.json()["users"]) > 0
```

**Detection**: Assertions that don't verify actual content.

### Configuration

```yaml
anti_patterns:
  enabled: true
  patterns:
    - skip_verification
    - unconditional_success
    - weaken_tests
    - broad_exception_swallow
    - silent_fallback
    - guess_expected_output

  # Enforcement level
  enforcement: "strict"  # or "warn"
```

### Enforcement Levels

| Level | Behavior |
|-------|----------|
| `strict` | Block QR generation if anti-patterns detected |
| `warn` | Include warning in QR |

### Detection in Practice

The guidance system includes anti-pattern warnings in system prompts:

```
ANTI-PATTERNS (FORBIDDEN):
- Skip Verification: Claiming success without running tests
- Unconditional Success: Always passing regardless of outcome
- Weaken Tests: Modifying tests to pass instead of fixing code
- Broad Exception Swallow: Catching all exceptions silently
- Silent Fallback: Hiding errors with default values
- Guess Expected Output: Not verifying actual outputs
```

### Red Flags in Output

The guidance system prompts agents to flag anti-patterns:

```markdown
## Red Flags Detected

- WARNING: No test execution before success claim
- WARNING: Tests modified (3 assertions removed)
- WARNING: Broad exception handler in `src/api.py:42`
```

### Adding Custom Anti-Patterns

```yaml
guidance:
  anti_patterns:
    patterns:
      # Built-in patterns
      - skip_verification
      - unconditional_success

      # Custom patterns (description only)
      - "Hardcoding expected values"
      - "Mocking external services without verification"
      - "Skipping integration tests"
```

---

## System Prompts

### Quick Scan Prompt

Generated from configuration:

```
SYSTEM: SuperQode Quick Scan QE Mode - 60s

FOCUS AREAS:
  - Run smoke tests first
  - Validate critical paths
  - Check for obvious errors

FORBIDDEN ACTIONS:
  - [INCORRECT] Long-running performance tests
  - [INCORRECT] Extensive code generation

ANTI-PATTERNS (FORBIDDEN):
  - Skip Verification
  - Unconditional Success
  ...
```

### Deep QE Prompt

Comprehensive guidance:

```
SYSTEM: SuperQode Deep QE Mode - 1800s

FOCUS AREAS:
  - Comprehensive test coverage
  - Edge case exploration
  - Security vulnerability scanning

FORBIDDEN ACTIONS:
  - [INCORRECT] Modifying production code
  - [INCORRECT] Committing changes to git

ANTI-PATTERNS (FORBIDDEN):
  ...
```

---

## Review Prompts

Guidance includes review prompts for self-checking:

### Verification Checklist

Agents review their work:

- Did I run tests to verify?
- Is there evidence for my claims?
- Did I check for edge cases?
- Are my findings accurate?

---

## Integration

### With QE Sessions

Guidance automatically applied during QE:

```bash
# Quick scan uses quick_scan guidance
superqe run . --mode quick

# Deep QE uses deep_qe guidance
superqe run . --mode deep
```

### With CI/CD

Guidance configured in `superqode.yaml`:

```yaml
# CI uses quick scan guidance
- run: superqe run . --mode quick

# Nightly uses deep QE guidance
- run: superqe run . --mode deep
```

---

## Best Practices

### 1. Enable Verification First

```yaml
guidance:
  require_proof: true
  quick_scan:
    verification_first: true
```

### 2. Configure Focus Areas

Customize for your project:

```yaml
quick_scan:
  focus_areas:
    - "Your specific focus area"
    - "Another important area"
```

### 3. Define Forbidden Actions

Prevent unwanted behavior:

```yaml
deep_qe:
  forbidden_actions:
    - "Modifying production config"
    - "Changing database schema"
```

### 4. Enable Anti-Patterns

```yaml
anti_patterns:
  enabled: true
```

---

## Customization

### Project-Specific Guidance

Adapt guidance to your project:

```yaml
guidance:
  quick_scan:
    focus_areas:
      - "API endpoint validation"
      - "Authentication flow"
      - "Database queries"

    forbidden_actions:
      - "Modifying production database"
      - "Changing authentication logic"
```

### Team Preferences

Adjust based on team needs:

```yaml
deep_qe:
  timeout_seconds: 3600  # Longer for complex projects
  exploration_allowed: true
  destructive_testing: true  # Enable for pre-release
```

---

## Related Features

- [QE Features](../qe-features/index.md) - QE overview
- [Configuration](../configuration/yaml-reference.md) - Config reference
- [Constitution](../qe-features/constitution.md) - Quality rules

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Harness System](harness-system.md) - Patch validation
