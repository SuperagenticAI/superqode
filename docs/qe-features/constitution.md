<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Constitution System

Define quality principles, rules, and guardrails to enforce project-specific quality standards.

---

## Overview

The Constitution System provides a declarative way to define quality standards for your project:

- **Principles**: High-level quality guidance
- **Rules**: Enforcement mechanisms with actions
- **Metrics**: Measurement definitions
- **Thresholds**: Quality gates and blocking criteria

Constitutions are defined in YAML/JSON and evaluated during QE sessions to ensure code meets your quality standards.

---

## Concepts

### Principles

High-level quality guidance that describes **what** quality means for your project.

```yaml
principles:
  - id: security-first
    name: Security First
    description: Security vulnerabilities must be addressed before release
    priority: critical
    category: security
    mandatory: true
```

### Rules

Concrete enforcement mechanisms that define **how** principles are enforced.

```yaml
rules:
  - id: no-sql-injection
    name: No SQL Injection
    principle_id: security-first
    conditions:
      - type: finding_type
        operator: equals
        value: "sql_injection"
    action:
      type: block
      severity: critical
    enabled: true
```

### Metrics

Measurable quality indicators.

```yaml
metrics:
  - id: test-coverage
    name: Test Coverage
    description: Percentage of code covered by tests
    unit: percent
    aggregation: average
```

### Thresholds

Quality gates that block releases if not met.

```yaml
thresholds:
  - id: min-coverage
    metric_id: test-coverage
    operator: gte
    value: 80.0
    blocking: true
```

---

## Constitution Structure

### Basic Constitution

```yaml
name: "My Project Constitution"
version: "1.0"
description: "Quality standards for My Project"

principles:
  - id: security-first
    name: Security First
    description: Security vulnerabilities must be addressed
    priority: critical
    mandatory: true

rules:
  - id: no-critical-security-issues
    name: No Critical Security Issues
    principle_id: security-first
    conditions:
      - type: severity
        operator: equals
        value: "critical"
      - type: category
        operator: equals
        value: "security"
    action:
      type: block
      severity: critical
    enabled: true

thresholds:
  - id: min-test-coverage
    metric_id: test-coverage
    operator: gte
    value: 80.0
    blocking: true
```

---

## Principles

### Definition

```yaml
principles:
  - id: unique-identifier
    name: Display Name
    description: Detailed description
    priority: critical | high | medium | low
    category: category-name
    mandatory: true | false
    related_principles: [id1, id2]
    tags: [tag1, tag2]
```

### Priority Levels

| Priority | Meaning |
|----------|---------|
| `critical` | Must be enforced, blocks release |
| `high` | Important, should be enforced |
| `medium` | Recommended |
| `low` | Nice to have |

### Example

```yaml
principles:
  - id: maintainability
    name: Code Maintainability
    description: Code must be maintainable and readable
    priority: high
    category: code-quality
    mandatory: false
    tags: [maintainability, readability]
```

---

## Rules

### Definition

```yaml
rules:
  - id: unique-identifier
    name: Rule Name
    description: Rule description
    principle_id: principle-id
    conditions:
      - type: condition-type
        operator: operator
        value: value
    action:
      type: block | warn | adjust_severity | notify
      severity: severity-level
      notify_channels: [channel1]
    enabled: true | false
    severity: error | warning | info
    tags: [tag1, tag2]
    environments: [production, staging]
```

### Condition Types

- `finding_type`: Finding type (e.g., "sql_injection")
- `severity`: Finding severity (e.g., "critical", "high")
- `category`: Finding category (e.g., "security")
- `file_path`: File path pattern
- `confidence`: Confidence threshold

### Operators

- `equals`: Exact match
- `not_equals`: Not equal
- `contains`: Contains substring
- `matches`: Regex match
- `gt`, `gte`, `lt`, `lte`: Numeric comparison

### Actions

| Action Type | Description |
|-------------|-------------|
| `block` | Block release/deployment |
| `warn` | Warning only |
| `adjust_severity` | Change finding severity |
| `notify` | Send notification |

### Example

```yaml
rules:
  - id: block-critical-security
    name: Block Critical Security Issues
    principle_id: security-first
    conditions:
      - type: severity
        operator: equals
        value: "critical"
      - type: category
        operator: equals
        value: "security"
    action:
      type: block
      severity: critical
    enabled: true
    severity: error
```

---

## Metrics

### Definition

```yaml
metrics:
  - id: unique-identifier
    name: Metric Name
    description: Metric description
    unit: unit-name
    aggregation: sum | average | min | max | count
```

### Aggregation Types

| Type | Description |
|------|-------------|
| `sum` | Sum of values |
| `average` | Average value |
| `min` | Minimum value |
| `max` | Maximum value |
| `count` | Count of items |

### Example

```yaml
metrics:
  - id: test-coverage
    name: Test Coverage
    description: Percentage of code covered by tests
    unit: percent
    aggregation: average
```

---

## Thresholds

### Definition

```yaml
thresholds:
  - id: unique-identifier
    metric_id: metric-id
    operator: gte | gt | lte | lt | equals
    value: threshold-value
    blocking: true | false
    period: time-period  # e.g., "7d"
```

### Operators

| Operator | Meaning |
|----------|---------|
| `gte` | Greater than or equal |
| `gt` | Greater than |
| `lte` | Less than or equal |
| `lt` | Less than |
| `equals` | Equal |

### Example

```yaml
thresholds:
  - id: min-coverage
    metric_id: test-coverage
    operator: gte
    value: 80.0
    blocking: true
```

---

## Evaluation

### During QE Sessions

Constitutions are evaluated automatically during QE sessions:

1. **Findings checked**: Each finding checked against rules
2. **Metrics calculated**: Metrics computed from session results
3. **Thresholds evaluated**: Thresholds checked against metrics
4. **Actions taken**: Block, warn, or notify based on rules

### Evaluation Result

```json
{
  "status": "passed" | "failed" | "warning",
  "rules_checked": 15,
  "rules_violated": 2,
  "thresholds_checked": 5,
  "thresholds_violated": 1,
  "blocking_issues": ["no-critical-security-issues"],
  "warnings": ["low-coverage"]
}
```

---

## Configuration

### Loading Constitution

```python
from superqode.superqe.constitution import load_constitution

constitution = load_constitution("constitution.yaml")
```

### Default Constitution

```python
from superqode.superqe.constitution import get_default_constitution

constitution = get_default_constitution()
```

### YAML Configuration

```yaml
# superqode.yaml
qe:
  constitution:
    path: "constitution.yaml"
    enabled: true
```

---

## Example Constitutions

### Security-Focused

```yaml
name: "Security Constitution"
version: "1.0"

principles:
  - id: security-first
    name: Security First
    priority: critical
    mandatory: true

rules:
  - id: no-sql-injection
    principle_id: security-first
    conditions:
      - type: finding_type
        operator: equals
        value: "sql_injection"
    action:
      type: block
      severity: critical

  - id: no-auth-bypass
    principle_id: security-first
    conditions:
      - type: finding_type
        operator: equals
        value: "authentication_bypass"
    action:
      type: block
      severity: critical
```

### Coverage-Focused

```yaml
name: "Coverage Constitution"
version: "1.0"

metrics:
  - id: test-coverage
    name: Test Coverage
    unit: percent

thresholds:
  - id: min-coverage
    metric_id: test-coverage
    operator: gte
    value: 80.0
    blocking: true
```

---

## Inheritance

Constitutions can extend parent constitutions:

```yaml
name: "Project-Specific Constitution"
version: "1.0"
extends: "default-constitution.yaml"

# Add additional rules
rules:
  - id: custom-rule
    name: Custom Rule
    # ...
```

---

## Best Practices

### 1. Start with Principles

Define high-level principles first, then create rules to enforce them.

### 2. Use Clear IDs

Use descriptive IDs like `no-sql-injection` instead of `rule-1`.

### 3. Enable Gradually

Start with warnings, then enable blocking rules once validated.

### 4. Document Intent

Include descriptions explaining why rules exist.

### 5. Version Control

Track constitution versions and changes over time.

---

## Related Features

- [QE Roles](../concepts/roles.md) - Role-based quality engineering
- [Noise Filtering](noise-filtering.md) - Filtering findings

---

## Next Steps

- [QE Features Index](index.md) - All QE features
- [Configuration Reference](../configuration/yaml-reference.md) - Config options
