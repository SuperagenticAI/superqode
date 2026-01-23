# Harness System

Fast validation for QE-generated patches and changes before they're suggested in QRs.

---

## Overview

The Harness System validates patches and changes to ensure:

- **Syntactic correctness**: Code parses correctly
- **Type safety**: Type checking passes
- **Style compliance**: Linting rules followed
- **No regressions**: Changes don't break existing code

All validation happens **before** suggestions are included in QRs.

---

## Principle

> "SuperQode never edits, rewrites, or commits code."
> "All fixes are suggested, validated, and proven, never auto-applied."

The harness **VALIDATES** suggestions - it doesn't apply them.

---

## Validation Types

### Structural Validation

Parsing validation for structured formats:

- **JSON**: Valid JSON syntax
- **YAML**: Valid YAML syntax
- **TOML**: Valid TOML syntax

**Runs on**: All changes to structured files

### Language Validation

Language-specific validation:

- **Python**: mypy, ruff, pyright
- **JavaScript**: eslint, tsc
- **TypeScript**: tsc, eslint
- **Go**: go vet, golangci-lint
- **Rust**: cargo check
- **Shell**: shellcheck

**Runs on**: Code files matching language patterns

---

## Configuration

### YAML Configuration

```yaml
superqode:
  qe:
    harness:
      enabled: true
      timeout_seconds: 30
      fail_on_error: false

      structural:
        enabled: true
        formats: ["json", "yaml", "toml"]

      python:
        enabled: true
        tools:
          - mypy
          - ruff
          - pyright

      javascript:
        enabled: true
        tools:
          - eslint

      typescript:
        enabled: true
        tools:
          - tsc
          - eslint

      go:
        enabled: true
        tools:
          - go vet
          - golangci-lint

      rust:
        enabled: true
        tools:
          - cargo check

      shell:
        enabled: true
        tools:
          - shellcheck

      # Bring Your Own Harness (BYOH)
      custom_steps:
        - name: "project-harness"
          command: "python scripts/harness_check.py"
          timeout: 120
          enabled: true
```

---

## How It Works

### 1. Patch Generation

Agent generates a patch/suggestion during QE.

### 2. Harness Validation

Harness validates the patch:

```python
harness = PatchHarness(project_root)
result = await harness.validate_changes({
    "src/api/users.py": "new code content"
})
```

### 3. Validation Result

Result includes:

- **Success**: All validations passed
- **Findings**: Validation errors/warnings
- **Tools run**: Which validators executed
- **Duration**: Validation time

### 4. QR Inclusion

Only validated patches included in QR:

```python
if result.success:
    # Include in QR
    qr.add_suggestion(patch, result)
else:
    # Report validation failures
    qr.add_validation_failures(result.findings)
```

---

## Validation Categories

### Structural

**Parsing validation** - ensures files are valid:

```python
{
  "tool": "structural-parse",
  "category": "structural",
  "file": "config.json",
  "message": "Invalid JSON: unexpected token",
  "severity": "error"
}
```

### Syntactic

**Syntax validation** - language syntax:

```python
{
  "tool": "mypy",
  "category": "syntactic",
  "file": "src/api/users.py",
  "line": 42,
  "message": "Missing type annotation",
  "severity": "error"
}
```

### Type

**Type checking** - static type analysis:

```python
{
  "tool": "mypy",
  "category": "type",
  "file": "src/api/users.py",
  "line": 45,
  "message": "Incompatible types: int vs str",
  "severity": "error"
}
```

### Stylistic

**Code style** - formatting and style rules:

```python
{
  "tool": "ruff",
  "category": "stylistic",
  "file": "src/api/users.py",
  "line": 50,
  "message": "Line too long (120 > 100)",
  "severity": "warning"
}
```

### Functional

**Runtime validation** - execution checks:

```python
{
  "tool": "harness",
  "category": "functional",
  "file": null,
  "message": "Harness validation timed out",
  "severity": "warning"
}
```

---

## Tool Detection

Harness automatically detects available tools:

```python
# Checks if tool exists
if shutil.which("mypy"):
    # Run mypy validation
    ...
```

### Tool Availability

- **Not found**: Tool skipped, no error
- **Found**: Tool runs validation
- **Timeout**: Validation times out gracefully

---

## Validation Workflow

### Temporary Workspace

Validation happens in isolated temp workspace:

1. Create temporary directory
2. Stage changed files
3. Run validators
4. Collect findings
5. Clean up temp directory

### Parallel Validation

Multiple validators run in parallel when possible:

- Structural validation (instant)
- Language validators (parallel by file)
- Tool execution (timeout-protected)

---

## Results

### HarnessResult

```python
@dataclass
class HarnessResult:
    success: bool
    findings: List[HarnessFinding]
    tools_run: List[str]
    duration_seconds: float
    files_validated: int
```

### HarnessFinding

```python
@dataclass
class HarnessFinding:
    tool: str
    category: ValidationCategory
    file: Optional[Path]
    message: str
    line: Optional[int]
    column: Optional[int]
    severity: str  # "error", "warning", "info"
```

---

## Integration

### With QE Sessions

Harness runs automatically during QE:

```python
# During QE session
patch = agent.generate_suggestion()
result = await harness.validate_changes(patch)

if result.success:
    # Include in QR
else:
    # Report validation issues
```

### With Suggestions (Enterprise)

All suggestions validated:

```bash
# Suggestions already validated
superqe run . --mode deep --allow-suggestions
```

### With QR Generation

QR includes validation results:

```json
{
  "suggestions": [
    {
      "patch": "...",
      "validation": {
        "success": true,
        "tools_run": ["mypy", "ruff"],
        "findings": []
      }
    }
  ]
}
```

---

## Configuration Examples

### Python Project

```yaml
harness:
  python:
    enabled: true
    tools:
      - mypy      # Type checking
      - ruff      # Linting
      - pyright   # Type checking (alternative)
```

### TypeScript Project

```yaml
harness:
  typescript:
    enabled: true
    tools:
      - tsc       # Type checking
      - eslint    # Linting
```

### Multi-Language Project

```yaml
harness:
  python:
    enabled: true
    tools: [mypy, ruff]
  javascript:
    enabled: true
    tools: [eslint]
  typescript:
    enabled: true
    tools: [tsc, eslint]
```

### Bring Your Own Harness (BYOH)

Use `custom_steps` to run project-specific validation commands as part of the harness. Each step runs in the
repo root, uses the shell, and a non-zero exit code is reported as a harness error.

```yaml
harness:
  custom_steps:
    - name: "contracts"
      command: "python scripts/check_contracts.py"
      timeout: 180
    - name: "smoke-tests"
      command: "pytest -q tests/smoke"
      enabled: true
```

**Step fields**

- `name`: Display name for reporting
- `command`: Shell command to run
- `enabled`: Toggle the step on/off (default: true)
- `timeout`: Timeout in seconds (default: 300)

---

## Best Practices

### 1. Enable Relevant Validators

Only enable validators for languages in your project:

```yaml
harness:
  python:
    enabled: true  # If you use Python
  go:
    enabled: false  # If you don't use Go
```

### 2. Set Timeouts

Prevent long-running validations:

```yaml
harness:
  timeout_seconds: 30  # Reasonable timeout
```

### 3. Handle Failures Gracefully

```yaml
harness:
  fail_on_error: false  # Report but don't fail QE
```

### 4. Tool Installation

Ensure tools are installed:

```bash
# Python tools
pip install mypy ruff pyright

# TypeScript tools
npm install -g typescript eslint

# Go tools
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
```

---

## Troubleshooting

### Tools Not Found

**Symptom**: Validators skipped

**Solution**: Install required tools:

```bash
# Check availability
which mypy
which ruff

# Install if missing
pip install mypy ruff
```

### Timeout Errors

**Symptom**: Validation times out

**Solution**: Increase timeout or optimize validators:

```yaml
harness:
  timeout_seconds: 60  # Increase timeout
```

### False Positives

**Symptom**: Validators report issues that don't matter

**Solution**: Configure validator options or disable specific tools:

```yaml
harness:
  python:
    tools: [ruff]  # Skip mypy if too strict
```

---

## Related Features

- [Fix Verifier](../qe-features/fix-verifier.md) - Fix verification
- [Suggestions](../concepts/suggestions.md) - Suggestion workflow
- [Configuration](../configuration/yaml-reference.md) - Config reference

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Guidance System](guidance-system.md) - QE guidance
