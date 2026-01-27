<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Noise Filtering

Reduce false positives and focus on important findings with configurable noise controls.

---

## Overview

Noise filtering helps reduce false positives and focus on important findings by applying multiple filtering strategies:

- **Confidence thresholds**: Filter findings below minimum confidence
- **Deduplication**: Remove duplicate or highly similar findings
- **Severity filtering**: Only show findings above minimum severity
- **Known risk suppression**: Suppress acknowledged risks
- **Rule-based adjustments**: Apply severity rules and adjustments
- **Memory-based filtering**: Use user feedback to suppress false positives

---

## Configuration

Configure noise filtering in `superqode.yaml`:

```yaml
qe:
  noise:
    # Minimum confidence threshold (0.0 to 1.0)
    min_confidence: 0.7

    # Enable deduplication
    deduplicate: true

    # Similarity threshold for deduplication (0.0 to 1.0)
    similarity_threshold: 0.8

    # Suppress known/acknowledged risks
    suppress_known_risks: false
    known_risk_patterns:
      - "legacy code pattern"
      - "known false positive"

    # Minimum severity to report
    min_severity: "low"  # low, medium, high, critical

    # Maximum findings per file (0 = unlimited)
    max_findings_per_file: 0

    # Maximum total findings (0 = unlimited)
    max_total_findings: 0

    # Enable rule-based severity adjustments
    apply_severity_rules: true
```

---

## Confidence Threshold

Filter findings below a minimum confidence score.

### Default: 0.7

Only findings with confidence ≥ 0.7 are included.

### Adjusting Threshold

```yaml
qe:
  noise:
    min_confidence: 0.5  # Lower threshold = more findings
```

| Threshold | Effect |
|-----------|--------|
| `0.9` | Very strict - only high-confidence findings |
| `0.7` | Default - balanced |
| `0.5` | Lenient - includes more speculative findings |
| `0.3` | Very lenient - includes most findings |

### Example

```yaml
# Strict filtering
min_confidence: 0.85

# Balanced (default)
min_confidence: 0.7

# Include more findings
min_confidence: 0.5
```

---

## Deduplication

Remove duplicate or highly similar findings to reduce noise.

### How It Works

1. **Fingerprint-based**: Exact duplicates are identified by fingerprint
2. **Similarity-based**: Fuzzy matching identifies similar findings
3. **Highest severity kept**: When duplicates found, keeps highest severity instance

### Fingerprinting

Each finding gets a fingerprint based on:
- Title
- File path
- Line number range
- Finding type
- Evidence snippet

### Similarity Threshold

Controls how similar findings must be to be considered duplicates:

```yaml
qe:
  noise:
    deduplicate: true
    similarity_threshold: 0.8  # 0.0 to 1.0
```

| Threshold | Effect |
|-----------|--------|
| `1.0` | Only exact duplicates removed |
| `0.8` | Default - similar findings merged |
| `0.6` | Aggressive - many similar findings merged |

### Example

```
Finding A: "SQL injection in user input"
Finding B: "SQL injection vulnerability in user input"
Finding C: "Potential SQL injection in query"

With similarity_threshold: 0.8
→ A and B merged (similarity ~0.9)
→ C kept separate (similarity ~0.6)
```

---

## Severity Filtering

Only report findings above a minimum severity level.

### Severity Levels

| Level | Priority | Description |
|-------|----------|-------------|
| `critical` | 4 | Security breaches, data loss risks |
| `high` | 3 | Serious bugs, performance issues |
| `medium` | 2 | Moderate issues, best practice violations |
| `low` | 1 | Minor issues, style inconsistencies |
| `info` | 0 | Informational findings |

### Minimum Severity

```yaml
qe:
  noise:
    min_severity: "medium"  # Only show medium, high, critical
```

### Example

```yaml
# Only critical and high findings
min_severity: "high"

# Include medium and above
min_severity: "medium"

# Include all findings (default)
min_severity: "low"
```

---

## Known Risk Suppression

Suppress findings that match known risk patterns.

### Configuration

```yaml
qe:
  noise:
    suppress_known_risks: true
    known_risk_patterns:
      - "legacy authentication code"
      - "intentional backdoor for testing"
      - "approved security exception"
```

### Pattern Matching

Patterns can be:
- **Exact strings**: Matches if pattern appears in finding title or description
- **Case-insensitive**: Matching is case-insensitive
- **Partial matches**: Matches anywhere in text

### Example

```yaml
known_risk_patterns:
  - "legacy code - do not refactor"
  - "approved exception: SEC-2024-001"
  - "intentional for test harness"
```

---

## Rule-Based Severity Adjustments

Apply severity rules to adjust finding severity based on context.

### Default Rules

Built-in rules adjust severity based on:
- Finding type (security vs. style)
- Context (test code vs. production)
- Evidence strength

### Configuration

```yaml
qe:
  noise:
    apply_severity_rules: true
    # Uses default rules if not specified

    # Custom rules (advanced)
    severity_rules:
      # Custom rule configuration
```

### Example Adjustments

- Security issues in production: `low` → `high`
- Style issues in test code: `medium` → `info`
- Unclear evidence: `high` → `medium`

---

## Memory-Based Filtering

Use feedback from previous sessions to suppress false positives.

### How It Works

When you mark findings as false positives:

```bash
superqe feedback finding-001 --false-positive
```

The system remembers this and suppresses similar findings in future sessions.

### Automatic Application

Memory-based suppressions are automatically applied if:
- Finding matches a previously suppressed pattern
- User feedback indicates false positive
- Pattern is learned from multiple feedback instances

### Disable Memory Filtering

```yaml
qe:
  noise:
    # Memory filtering is enabled by default
    # Controlled by feedback system
```

---

## Finding Limits

Limit the number of findings reported to focus on top issues.

### Per-File Limit

```yaml
qe:
  noise:
    max_findings_per_file: 5  # Max 5 findings per file
```

Useful when files have many issues - focuses on top findings.

### Total Limit

```yaml
qe:
  noise:
    max_total_findings: 50  # Max 50 total findings
```

### Example

```yaml
# Focus on top 10 issues per file, max 100 total
max_findings_per_file: 10
max_total_findings: 100
```

---

## Filtering Order

Noise filters are applied in this order:

1. **Confidence threshold**: Remove low-confidence findings
2. **Memory suppressions**: Remove learned false positives
3. **Known risk patterns**: Suppress configured patterns
4. **Deduplication**: Merge similar findings
5. **Severity filtering**: Remove below minimum severity
6. **Severity rules**: Adjust severity based on rules
7. **Finding limits**: Apply per-file and total limits

---

## Examples

### Strict Filtering

For production code review:

```yaml
qe:
  noise:
    min_confidence: 0.85
    min_severity: "medium"
    deduplicate: true
    similarity_threshold: 0.9
    max_total_findings: 20
```

### Lenient Filtering

For exploratory analysis:

```yaml
qe:
  noise:
    min_confidence: 0.5
    min_severity: "low"
    deduplicate: true
    similarity_threshold: 0.7
    suppress_known_risks: false
```

### Focus on Security

```yaml
qe:
  noise:
    min_confidence: 0.7
    min_severity: "high"  # Only high/critical
    deduplicate: true
    apply_severity_rules: true
```

---

## Monitoring Filtering Effectiveness

### Check Filtered Counts

```bash
# View QR to see filtering stats
superqe report

# Check artifacts for filtering details
cat .superqode/qe-artifacts/qr/qr-*.json | jq '.noise_filtering'
```

### Adjust Based on Results

1. If too many false positives → increase `min_confidence` or `min_severity`
2. If important findings missing → decrease thresholds
3. If too many duplicates → adjust `similarity_threshold`
4. If specific patterns → add to `known_risk_patterns`

---

## Best Practices

### 1. Start Conservative

```yaml
# Start with default settings
min_confidence: 0.7
min_severity: "low"
```

### 2. Tune Based on Feedback

```bash
# Mark false positives
superqe feedback finding-001 --false-positive

# System learns automatically
```

### 3. Use Known Risk Patterns

```yaml
# Document acknowledged risks
known_risk_patterns:
  - "legacy component - refactor planned Q2"
```

### 4. Set Reasonable Limits

```yaml
# Avoid overwhelming reports
max_findings_per_file: 10
max_total_findings: 50
```

---

## Troubleshooting

### Too Many Findings

**Symptom**: Report has hundreds of findings

**Solution**:
```yaml
min_confidence: 0.8
min_severity: "medium"
max_total_findings: 50
```

### Important Findings Filtered

**Symptom**: Critical issues not showing up

**Solution**:
```yaml
min_confidence: 0.6  # Lower threshold
min_severity: "low"   # Include all severities
```

### Duplicate Findings

**Symptom**: Same issue reported multiple times

**Solution**:
```yaml
deduplicate: true
similarity_threshold: 0.7  # More aggressive
```

---

## Related Features

- [Noise Configuration](../configuration/noise-config.md) - Configuration options
- [Feedback System](../advanced/memory.md) - Learn from feedback

---

## Next Steps

- [QE Features Index](index.md) - All QE features
- [Configuration Reference](../configuration/yaml-reference.md) - Full config options
