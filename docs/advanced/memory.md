<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode Banner" />

# Memory & Learning System

SuperQode learns from your feedback to improve over time. The memory system stores project-specific learnings that persist across QE sessions.

---

## Overview

The Memory & Learning System enables SuperQode to:

- **Remember patterns**: Track recurring issues and fixes
- **Learn from feedback**: Improve based on your corrections
- **Suppress false positives**: Automatically filter known false positives
- **Score file risk**: Identify high-risk files based on history
- **Track role effectiveness**: Measure which QE roles work best for your project

---

## Components

### MemoryStore

Persistent storage for project learnings:

- **User-local memory**: `~/.superqode/memory/project-{hash}.json`
- **Team-shared memory**: `.superqode/memory.json` (in repo)

Memory is merged with user-local taking precedence.

### FeedbackCollector

Collects and processes user feedback on findings:

- Marks findings as valid/false positive
- Records fix patterns
- Updates role metrics
- Integrates with ML predictor

---

## What Gets Remembered

### Issue Patterns

Recurring issues detected across sessions:

```python
{
  "fingerprint": "abc123",
  "title": "SQL injection vulnerability",
  "category": "security",
  "severity": "critical",
  "occurrences": 5,
  "first_seen": "2025-01-10T10:00:00",
  "last_seen": "2025-01-15T14:30:00",
  "files_affected": ["src/api/users.py", "src/api/orders.py"],
  "avg_confidence": 0.85
}
```

### Suppressions

False positive suppression rules:

```python
{
  "pattern": "legacy authentication code",
  "pattern_type": "fingerprint",
  "scope": "project",
  "created_at": "2025-01-10T10:00:00",
  "created_by": "user",
  "expires_in_days": null
}
```

### Fix Patterns

Successful fix patterns:

```python
{
  "finding_type": "sql_injection",
  "fix_approach": "parameterized_queries",
  "success_rate": 0.95,
  "times_used": 10,
  "files_fixed": ["src/api/users.py", ...]
}
```

### File Risk Scores

Risk scores per file based on finding history:

```python
{
  "src/api/users.py": 0.85,
  "src/auth/login.py": 0.92,
  "src/utils/helpers.py": 0.15
}
```

### Role Metrics

Effectiveness tracking per QE role:

```python
{
  "security_tester": {
    "total_findings": 45,
    "confirmed_findings": 40,
    "false_positives": 5,
    "accuracy_rate": 0.89
  }
}
```

---

## Feedback Collection

### Mark Finding as Valid

```bash
superqe feedback finding-001 --valid
```

Updates:
- Role metrics (increases confirmed findings)
- Issue patterns (tracks recurring issues)
- ML training data (if ML enabled)

### Mark as False Positive

```bash
superqe feedback finding-002 --false-positive -r "Intentional for testing"
```

Creates:
- Suppression rule
- Updates role metrics
- Adds to ML training data

### Mark as Fixed

```bash
superqe feedback finding-003 --fixed -r "Applied suggested patch"
```

Records:
- Fix pattern (approach used)
- File risk score adjustment
- Role effectiveness update

---

## Storage Locations

### User-Local Memory

Location: `~/.superqode/memory/project-{hash}.json`

- Per-user, per-project storage
- Not committed to repo
- Takes precedence over team memory

### Team-Shared Memory

Location: `.superqode/memory.json`

- Committed to repository
- Shared across team
- Merged with user-local memory

### Merging Strategy

When both exist:
1. Load user-local memory
2. Load team-shared memory
3. Merge (user-local takes precedence)
4. Use merged result

---

## Automatic Learning

### Pattern Detection

The system automatically detects patterns:

- **Recurring issues**: Same issue in multiple files
- **Common fixes**: Successful fixes applied repeatedly
- **False positive patterns**: Frequently suppressed findings

### Risk Scoring

File risk scores update automatically:

- Finding detected → increase risk
- Fix applied → decrease risk
- Multiple findings → higher risk

### Role Metrics

Role effectiveness tracked automatically:

- Finding confirmed → increase accuracy
- False positive → decrease accuracy
- Tracks over time

---

## API Usage

### Load Memory

```python
from superqode.memory import MemoryStore

store = MemoryStore(project_root)
memory = store.load()

# Access data
issue_patterns = memory.issue_patterns
suppressions = memory.suppressions
file_risk = memory.file_risk_map
```

### Collect Feedback

```python
from superqode.memory import FeedbackCollector

collector = FeedbackCollector(project_root)

# Mark as valid
collector.mark_valid(
    finding_id="sec-001",
    finding_title="SQL injection",
    category="security",
    severity="critical",
    role_name="security_tester"
)

# Mark as false positive
collector.mark_false_positive(
    finding_id="sec-002",
    finding_title="False positive",
    finding_fingerprint="abc123",
    role_name="security_tester",
    reason="Intentional for testing"
)
```

### Update File Risk

```python
memory = store.load()
memory.update_file_risk("src/api/users.py", "critical")
store.save()
```

---

## Use Cases

### 1. Reduce False Positives

```bash
# First time: mark as false positive
superqe feedback finding-001 --false-positive -r "Known pattern"

# Future sessions: automatically suppressed
```

### 2. Track Recurring Issues

The system tracks issues that appear multiple times:

```
Issue Pattern: SQL injection in user input
Occurrences: 5
Files: users.py, orders.py, products.py
```

### 3. Identify High-Risk Files

Files with high risk scores get more attention:

```python
# Check file risk
memory = store.load()
risk = memory.file_risk_map.get("src/api/users.py", 0.0)
if risk > 0.8:
    print("High-risk file - focus testing here")
```

### 4. Measure Role Effectiveness

See which roles work best:

```python
metrics = memory.role_metrics.get("security_tester")
print(f"Accuracy: {metrics.accuracy_rate:.2%}")
print(f"Confirmed: {metrics.confirmed_findings}")
```

---

## Best Practices

### 1. Provide Regular Feedback

```bash
# After each QE session
superqe feedback finding-001 --valid
superqe feedback finding-002 --false-positive -r "reason"
```

### 2. Share Team Memory

Commit `.superqode/memory.json` to repository:

```bash
git add .superqode/memory.json
git commit -m "Update team memory"
```

### 3. Review Suppressions

Periodically review suppressions:

```bash
superqe suppressions
```

### 4. Monitor Role Metrics

Check which roles are most effective:

```python
# High accuracy = role works well for your project
# Low accuracy = may need different approach
```

---

## Troubleshooting

### Memory Not Persisting

**Check storage location**:
- User-local: `~/.superqode/memory/`
- Team-shared: `.superqode/memory.json`

### Suppressions Not Working

**Verify pattern matching**:
- Pattern type (fingerprint vs. title)
- Scope (project vs. file)
- Expiration (if set)

### Risk Scores Not Updating

**Ensure feedback collected**:
```bash
superqe feedback finding-001 --valid
```

---

## Related Features

- [QE Feedback Commands](../cli-reference/qe-commands.md) - Feedback workflow
- [Noise Filtering](../qe-features/noise-filtering.md) - Filtering false positives

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Configuration](../configuration/yaml-reference.md) - Memory configuration
