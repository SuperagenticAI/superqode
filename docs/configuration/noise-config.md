<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Noise Configuration

Configure noise filtering to reduce false positives and focus on actionable findings.

---

## Overview

Noise configuration controls how SuperQode filters and deduplicates QE findings:

- **Confidence Thresholds**: Filter low-confidence findings
- **Deduplication**: Remove similar findings
- **Severity Filtering**: Focus on important issues
- **Known Risk Suppression**: Suppress acknowledged risks
- **Limits**: Control finding volume

---

## Basic Configuration

```yaml
qe:
  noise:
    min_confidence: 0.7
    deduplicate: true
    min_severity: "low"
```

---

## Configuration Options

### Confidence Threshold

Minimum confidence score (0.0 to 1.0) for findings:

```yaml
qe:
  noise:
    min_confidence: 0.7  # Default: 0.7
```

**Recommendations:**

| Use Case | Threshold | Rationale |
|----------|-----------|-----------|
| Strict filtering | `0.9` | Only high-confidence findings |
| Balanced (default) | `0.7` | Good balance of precision/recall |
| More findings | `0.5` | Include more potential issues |

### Deduplication

Remove similar findings:

```yaml
qe:
  noise:
    deduplicate: true  # Default: true
    similarity_threshold: 0.8  # Default: 0.8
```

**Similarity Threshold:** 0.0 (different) to 1.0 (identical)

- `0.8`: Default, removes clearly duplicate findings
- `0.9`: Only removes nearly identical findings
- `0.7`: More aggressive deduplication

### Severity Filtering

Minimum severity to report:

```yaml
qe:
  noise:
    min_severity: "low"  # low, medium, high, critical
```

**Severity Levels:**

- `critical`: Only critical issues
- `high`: Critical and high severity
- `medium`: Critical, high, and medium
- `low`: All findings (default)

### Known Risk Suppression

Suppress findings matching known risk patterns:

```yaml
qe:
  noise:
    suppress_known_risks: true
    known_risk_patterns:
      - "Deprecated API usage"
      - "TODO:.*security"
      - "FIXME:.*vulnerability"
```

**Pattern Types:**

- **Exact match**: Exact string match
- **Regex patterns**: Regular expression patterns (Python regex)

### Finding Limits

Control maximum number of findings:

```yaml
qe:
  noise:
    max_findings_per_file: 10   # 0 = unlimited
    max_total_findings: 100      # 0 = unlimited
```

**Use Cases:**

- **Per-file limit**: Prevent one file from dominating report
- **Total limit**: Cap total findings for review

---

## Complete Configuration Example

```yaml
qe:
  noise:
    # Confidence threshold
    min_confidence: 0.75

    # Deduplication
    deduplicate: true
    similarity_threshold: 0.85

    # Severity filtering
    min_severity: "medium"

    # Known risk suppression
    suppress_known_risks: true
    known_risk_patterns:
      - "Known issue:.*"
      - "Acceptable risk:.*"
      - "TODO.*security.*acknowledged"

    # Finding limits
    max_findings_per_file: 5
    max_total_findings: 50

    # Severity rules
    apply_severity_rules: true
```

---

## Severity Rules

Enable rule-based severity adjustments:

```yaml
qe:
  noise:
    apply_severity_rules: true  # Default: true
    severity_rules:
      # Custom severity rules (optional)
      rules:
        - pattern: "SQL.*injection"
          severity: "critical"
        - pattern: "XSS.*vulnerability"
          severity: "high"
```

**Default Rules:**

SuperQode includes default severity rules for common issues:
- SQL injection → `critical`
- XSS vulnerabilities → `high`
- Hardcoded secrets → `critical`
- And more...

**Custom Rules:**

Define custom patterns:

```yaml
qe:
  noise:
    severity_rules:
      rules:
        - pattern: "authentication.*bypass"
          severity: "critical"
        - pattern: "rate.*limit.*missing"
          severity: "medium"
```

---

## Memory-Based Suppression

SuperQode learns from user feedback and suppresses findings that were previously dismissed:

```yaml
qe:
  noise:
    # Memory-based suppression is automatically enabled
    # when memory.store is configured
    use_memory_suppressions: true  # Default: true if memory enabled
```

**How It Works:**

1. User dismisses a finding
2. Finding pattern stored in memory
3. Future similar findings automatically suppressed

**Configuration:**

```yaml
memory:
  store:
    type: file
    path: .superqode/memory
```

---

## Mode-Specific Configuration

Different noise settings for Quick Scan vs Deep QE:

```yaml
qe:
  modes:
    quick_scan:
      noise:
        min_confidence: 0.8
        min_severity: "medium"
        max_total_findings: 20

    deep_qe:
      noise:
        min_confidence: 0.6
        min_severity: "low"
        max_total_findings: 200
```

**Rationale:**

- **Quick Scan**: Stricter filtering for fast feedback
- **Deep QE**: More permissive to catch edge cases

---

## Advanced Options

### Similarity Calculation

Deduplication uses multiple factors:

- File path
- Line number (nearby lines considered similar)
- Finding title and description
- Evidence content

**Custom Similarity:**

```yaml
qe:
  noise:
    similarity_threshold: 0.8
    # Uses SequenceMatcher for text similarity
```

### Severity Adjustment Logging

Log severity adjustments for debugging:

```yaml
qe:
  noise:
    apply_severity_rules: true
    # Severity adjustments logged at DEBUG level
```

---

## Configuration Priority

Noise configuration is loaded in this order:

1. **Role-specific** (in `team.modes.qe.roles.<role>.noise`)
2. **Mode-specific** (in `qe.modes.<mode>.noise`)
3. **Global** (in `qe.noise`)

**Example:**

```yaml
qe:
  noise:
    min_confidence: 0.7  # Global default

  modes:
    quick_scan:
      noise:
        min_confidence: 0.8  # Override for quick scan

team:
  modes:
    qe:
      roles:
        security_tester:
          noise:
            min_confidence: 0.9  # Stricter for security role
```

---

## Testing Configuration

Test noise configuration:

```bash
# Run QE with verbose output
superqe run . --mode quick -v

# Check filtering stats in QR
cat .superqode/qe-artifacts/qr-*.json | jq '.noise_filter_stats'
```

---

## Best Practices

### 1. Start Conservative

Begin with stricter filtering, then relax:

```yaml
qe:
  noise:
    min_confidence: 0.8
    min_severity: "medium"
```

### 2. Use Known Risk Patterns

Suppress acknowledged risks:

```yaml
qe:
  noise:
    suppress_known_risks: true
    known_risk_patterns:
      - "Acknowledged.*TODO"
      - "Acceptable.*risk"
```

### 3. Set Reasonable Limits

Prevent report bloat:

```yaml
qe:
  noise:
    max_findings_per_file: 10
    max_total_findings: 100
```

### 4. Adjust by Mode

Stricter for Quick Scan, permissive for Deep QE:

```yaml
qe:
  modes:
    quick_scan:
      noise:
        min_confidence: 0.8
        max_total_findings: 20
    deep_qe:
      noise:
        min_confidence: 0.6
        max_total_findings: 200
```

---

## Troubleshooting

### Too Many Findings

**Problem**: Report has too many findings

**Solution**: Increase thresholds and limits:

```yaml
qe:
  noise:
    min_confidence: 0.8
    min_severity: "medium"
    max_total_findings: 50
```

### Missing Important Findings

**Problem**: Important findings filtered out

**Solution**: Lower thresholds:

```yaml
qe:
  noise:
    min_confidence: 0.6
    min_severity: "low"
```

### Duplicate Findings

**Problem**: Same finding appears multiple times

**Solution**: Enable deduplication:

```yaml
qe:
  noise:
    deduplicate: true
    similarity_threshold: 0.85  # Higher = more aggressive
```

---

## Next Steps

- [Noise Filtering](../qe-features/noise-filtering.md) - How noise filtering works
- [YAML Reference](yaml-reference.md) - Complete configuration reference
- [Memory System](../advanced/memory.md) - Memory-based suppression
