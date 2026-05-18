# Harness System

SuperQode uses the word harness in two related ways:

- **Agent harness**: the runtime that turns a request into model calls, tools, sessions, sandbox access,
  events, and validated output.
- **Validation harness**: the patch and project checks that prove generated changes before they are surfaced
  to users or downstream automation.

The validation harness exists today. The agent harness is the direction for the next SuperQode runtime layer:
keep the current coding-agent harness intact, then add explicit harness flavors that can be selected,
composed, and optimized.

---

## Agent Harness Direction

The SuperQode agent harness should be a small framework kernel rather than a single agent loop. The kernel owns
stable contracts for sessions, events, tool policy, sandbox access, model policy, skills, roles, validation, and
backend adapters. Individual harnesses are user-owned specs compiled into that kernel.

This keeps the existing coding harness as the default while making room for other styles.

### Harness Flavors

#### Coding Harness

The coding harness is the current SuperQode strength and should remain the default for repository work.

It gives the model controlled capabilities:

- repository context discovery
- file read/search/edit tools
- shell and test execution under policy
- MCP tools when configured
- validation hooks
- patch/diff reporting
- session memory and compaction
- approval gates for risky operations

Use it when the model must inspect, change, run, or verify code. This is the right flavor for implementation,
debugging, refactoring, CI triage, and multi-agent coding workflows.

#### No-Tool Harness

The no-tool harness is a separate first-class flavor, not just "coding harness with tools disabled."

It bets on model capability alone:

- no file tools
- no shell tools
- no MCP tools
- no write access
- no implicit repo mutation path
- prompt, context, and model policy only
- optional structured output validation
- optional final-answer scoring/evaluation

Use it when the task is reasoning, planning, code review from supplied context, design critique, explanation,
spec generation, or when evaluating whether a model can solve a task without tool scaffolding.

This flavor is especially useful for Gemma4 and other strong local models because it makes model capability
measurable without hiding weaknesses behind tool execution.

### Flavor Contract

Both flavors should compile from the same `HarnessSpec` shape:

```yaml
harness:
  flavor: coding  # coding | no_tool
  runtime:
    backend: builtin
  model_policy:
    primary: gemma4-local
    fallback: ds4-local
  execution_policy:
    approval_profile: balanced
  validation:
    enabled: true
```

The compiler decides what capabilities are legal for each flavor:

| Capability | Coding | No-tool |
| --- | --- | --- |
| Model calls | yes | yes |
| Sessions/history | yes | yes |
| Skills/roles | yes | yes |
| Typed outputs | yes | yes |
| File read/search | yes | no |
| File edit/write | policy-controlled | no |
| Shell/tests | policy-controlled | no |
| MCP tools | policy-controlled | no |
| Validation harness | yes | optional, output-only |
| Multi-agent delegation | yes | optional, model-only |

### Example Specs

Coding harness:

```yaml
harness:
  name: superqode-coder
  flavor: coding
  runtime:
    backend: builtin
  model_policy:
    primary: gpt-5.5
    fallbacks: [gemma4-local, ds4-local]
  execution_policy:
    sandbox: local
    allow_read: true
    allow_write: true
    allow_shell: true
    approval_profile: balanced
  agents:
    - id: coder
      tools: [filesystem, search, edit, shell, validation]
      skills: [repo-navigation, implementation]
```

No-tool harness:

```yaml
harness:
  name: superqode-reasoner
  flavor: no_tool
  runtime:
    backend: builtin
  model_policy:
    primary: gemma4-local
    fallbacks: [ds4-local]
    temperature: 0.2
  execution_policy:
    allow_read: false
    allow_write: false
    allow_shell: false
  agents:
    - id: reasoner
      tools: []
      skills: [architecture-review, code-review-from-context]
  output:
    typed: true
```

### Implementation Notes

- Preserve the current native loop as the `coding` + `builtin` backend.
- Add `no_tool` as a separate profile with its own system prompt and model policy.
- Do not route no-tool runs through empty tool registries only; the prompt, stop conditions, output parsing,
  and evaluation rules should be tuned for tool-free reasoning.
- Keep validation as a lifecycle hook that the coding harness can call after changes.
- Rename the current patch harness internally to validation harness when the broader agent harness lands.
- Gemma4 should get both coding and no-tool templates so local-model behavior can be compared cleanly.

---

## Validation Harness Overview

The Harness System validates patches and changes to ensure:

- **Syntactic correctness**: Code parses correctly
- **Type safety**: Type checking passes
- **Style compliance**: Linting rules followed
- **No regressions**: Changes don't break existing code

All validation happens before suggestions are surfaced to users or downstream automation.

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
  harness:
    validation:
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

      custom_steps:
        - name: "project-harness"
          command: "python scripts/harness_check.py"
          timeout: 120
          enabled: true
```

---

## How It Works

### 1. Patch Generation

Agent generates a patch or suggestion during a coding harness run.

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

### 4. Result Inclusion

Only validated patches are included in the final result or downstream event stream:

```python
if result.success:
    output.add_suggestion(patch, result)
else:
    output.add_validation_failures(result.findings)
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

### With Coding Harness Runs

Validation can run automatically after a coding harness produces a patch:

```python
patch = agent.generate_suggestion()
result = await harness.validate_changes(patch)

if result.success:
    # Include in final output
else:
    # Report validation issues
```

### With Suggestions

All suggestions validated:

```bash
# Suggestions already validated
superqode --print "inspect this package and suggest the smallest safe cleanup"
```

### With Event Output

Harness events can include validation results:

```json
{
  "changes": [
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
  fail_on_error: false  # Report validation failures without failing the whole run
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

- [Suggestions](../concepts/suggestions.md) - Suggestion workflow
- [Configuration](../configuration/yaml-reference.md) - Config reference

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Tools System](tools-system.md) - Tool registry and permissions
