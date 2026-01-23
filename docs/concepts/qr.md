# Quality Reports (QRs)

SuperQode produces **Quality Reports (QRs)** instead of traditional bug reports. QRs are research-grade forensic artifacts that document the complete investigation process.

---

## What is a QR?

A QR is a comprehensive quality document that includes:

- **Investigation Summary**: Objective, scope, and methodology
- **What QE Did**: Actions taken, experiments run
- **What Was Found**: Issues discovered with evidence
- **Root Cause Analysis**: Why issues exist
- **Suggested Fixes**: Proposed solutions with validation
- **Production Readiness**: Go/no-go recommendation

```
┌─────────────────────────────────────────────────────────────┐
│                        QUALITY REPORT (QR)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  INVESTIGATION SUMMARY                               │    │
│  │  Objective • Scope • Methodology • Duration          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  FINDINGS                                            │    │
│  │  ID • Title • Severity • Category • Confidence      │    │
│  │  Evidence • Reproduction • Root Cause               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  RECOMMENDATIONS                                     │    │
│  │  Suggested Fixes • Verification Results • Patches   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  VERDICT                                             │    │
│  │  Production Ready? • Blocking Issues • Next Steps   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## QR vs Traditional Bug Reports

| Aspect | Traditional Bug Report | Quality Report |
|--------|------------------------|------------------------------|
| **Content** | Description of issue | Complete investigation |
| **Evidence** | Screenshot/log | Code snippets, test results, diffs |
| **Reproduction** | User steps | Automated test case |
| **Root Cause** | Often missing | Required analysis |
| **Fix** | "Someone should fix this" | Verified patch with proof |
| **Confidence** | Binary (bug/not bug) | 0.0-1.0 confidence score |
| **Actionability** | Needs investigation | Ready to apply |

---

## QR Structure

### Session Metadata

```json
{
  "session": {
    "id": "qe-session-20240118-143022",
    "mode": "deep_qe",
    "duration_seconds": 1247.3,
    "started_at": "2024-01-18T14:30:22Z",
    "completed_at": "2024-01-18T14:51:09Z",
    "roles_executed": [
      "security_tester",
      "api_tester",
      "fullstack"
    ],
    "workspace": {
      "method": "git_worktree",
      "base_commit": "abc123def",
      "reverted": true
    }
  }
}
```

### Findings Array

Each finding contains:

```json
{
  "findings": [
    {
      "id": "finding-001",
      "title": "SQL Injection in User Search",
      "severity": "critical",
      "category": "security",
      "subcategory": "injection",
      "confidence": 0.95,

      "location": {
        "file_path": "src/api/users.py",
        "line_number": 42,
        "function": "search_users"
      },

      "description": "User input is directly interpolated into SQL query without sanitization, allowing arbitrary SQL execution.",

      "evidence": {
        "code_snippet": "query = f\"SELECT * FROM users WHERE name LIKE '%{search}%'\"",
        "test_input": "'; DROP TABLE users; --",
        "test_result": "SQL syntax error returned, confirming injection vulnerability",
        "affected_endpoints": ["/api/users/search"]
      },

      "reproduction": {
        "steps": [
          "1. Send GET request to /api/users?search='; DROP TABLE users; --",
          "2. Observe SQL error in response",
          "3. Note: Actual drop is prevented by read-only transaction"
        ],
        "automated_test": "tests/generated/test_sql_injection.py"
      },

      "root_cause": {
        "analysis": "String interpolation used instead of parameterized queries",
        "contributing_factors": [
          "No input validation layer",
          "Missing security review in code review process"
        ]
      },

      "recommendation": {
        "summary": "Use parameterized queries or ORM methods",
        "fix_patch": "patches/fix-sql-injection.patch",
        "fix_verified": true,
        "verification_result": "All tests pass after fix application"
      },

      "metadata": {
        "detected_by": "security_tester",
        "detected_at": "2024-01-18T14:35:12Z",
        "cwe_id": "CWE-89",
        "owasp_category": "A03:2021 Injection"
      }
    }
  ]
}
```

### Summary Section

```json
{
  "summary": {
    "total_findings": 6,
    "by_severity": {
      "critical": 1,
      "high": 2,
      "medium": 2,
      "low": 1
    },
    "by_category": {
      "security": 3,
      "performance": 2,
      "correctness": 1
    },
    "production_ready": false,
    "blocking_issues": ["finding-001", "finding-002"],
    "recommendation": "Address critical SQL injection and high-severity auth bypass before deployment"
  }
}
```

---

## Severity Levels

| Severity | Description | Action Required |
|----------|-------------|-----------------|
| **Critical** | Security vulnerability, data loss, system crash | Fix immediately, block deployment |
| **High** | Significant bug, security issue, major functionality | Fix before release |
| **Medium** | Bug, code smell, performance issue | Fix soon |
| **Low** | Minor issue, suggestion, optimization | Fix when convenient |

### Severity Criteria

**Critical:**
- SQL injection, RCE, auth bypass
- Data corruption or loss
- System crash or unavailability
- Sensitive data exposure

**High:**
- Security misconfiguration
- Significant functionality broken
- Data integrity issues
- Performance blocking issues

**Medium:**
- Minor security issues
- Non-critical bugs
- Performance concerns
- Code quality issues

**Low:**
- Style issues
- Minor optimizations
- Documentation gaps
- Edge case handling

---

## Confidence Scores

Each finding includes a confidence score (0.0 - 1.0):

| Range | Meaning | Action |
|-------|---------|--------|
| 0.9 - 1.0 | Very high confidence | Verified, actionable |
| 0.7 - 0.9 | High confidence | Likely valid, review recommended |
| 0.5 - 0.7 | Medium confidence | Needs verification |
| < 0.5 | Low confidence | May be false positive |

### Factors Affecting Confidence

- **Evidence quality**: Direct proof vs. inference
- **Reproducibility**: Consistent reproduction
- **Cross-validation**: Multiple roles agree
- **Test coverage**: Automated test confirms

---

## Categories

### Security

| Subcategory | Examples |
|-------------|----------|
| `injection` | SQL, XSS, Command, LDAP |
| `authentication` | Bypass, weak auth |
| `authorization` | Privilege escalation |
| `cryptography` | Weak crypto, key exposure |
| `data_exposure` | PII, secrets, logs |

### Performance

| Subcategory | Examples |
|-------------|----------|
| `query` | N+1, slow queries |
| `memory` | Leaks, excessive allocation |
| `complexity` | O(n²), deep nesting |
| `concurrency` | Race conditions |
| `resource` | File handles, connections |

### Correctness

| Subcategory | Examples |
|-------------|----------|
| `logic` | Business logic errors |
| `validation` | Missing input checks |
| `error_handling` | Unhandled exceptions |
| `state` | State management issues |
| `integration` | Service communication |

### Testing

| Subcategory | Examples |
|-------------|----------|
| `coverage` | Missing tests |
| `quality` | Flaky tests |
| `mocking` | Improper mocking |
| `assertions` | Weak assertions |

---

## Viewing QRs

### Location

QRs are saved to:

```
.superqode/qe-artifacts/
├── manifest.json
└── qr/
    ├── qr-<date>-<session>.md
    └── qr-<date>-<session>.json
```

### View in Terminal

```bash
# View JSON
cat .superqode/qe-artifacts/qr/qr-*.json | jq

# View Markdown
cat .superqode/qe-artifacts/qr/qr-*.md
```

### View in Browser

```bash
superqe dashboard
```

---

## Working with Findings

### Provide Feedback

Help improve accuracy by providing feedback:

```bash
# Mark as valid
superqe feedback finding-001 --valid

# Mark as false positive
superqe feedback finding-002 --false-positive -r "This is expected behavior"
```

### Apply Suggested Fixes

If fix patches are available:

```bash
# List suggestions
superqode suggestions list

# View a patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply a suggestion
superqode suggestions apply finding-001
```

### Export for Tracking

```bash
# Export to JUnit XML
superqe run . --junit results.xml

# Export to JSONL (CI streaming)
superqe run . --jsonl > qe-events.jsonl
```

---

## QR for CI/CD

### Automated Quality Gates

```yaml
# GitHub Actions example
- name: Run QE
  run: superqe run . --mode quick --junit results.xml

- name: Check for critical issues
  run: |
    CRITICAL=$(cat .superqode/qe-artifacts/qr-*.json | jq '.summary.by_severity.critical')
    if [ "$CRITICAL" -gt 0 ]; then
      echo "Critical issues found, blocking merge"
      exit 1
    fi
```

### JSONL Events

For real-time CI streaming:

```bash
superqe run . --jsonl | while read event; do
  TYPE=$(echo $event | jq -r '.type')
  case $TYPE in
    "finding.detected")
      echo "Found: $(echo $event | jq -r '.data.title')"
      ;;
    "qe.completed")
      echo "QE complete"
      ;;
  esac
done
```

---

## Configuration

### Report Format

```yaml
qe:
  output:
    reports_format: markdown  # markdown, html, json
    keep_history: true
```

### Noise Filtering

```yaml
qe:
  noise:
    min_confidence: 0.7      # Filter below this
    min_severity: "low"      # Minimum to report
    deduplicate: true
    max_per_file: 10
    max_total: 100
```

---

## Next Steps

- [Allow Suggestions](suggestions.md) - Fix demonstration workflow
- [Artifacts & Reports](../qe-features/artifacts.md) - Complete artifact reference
- [CI/CD Integration](../integration/cicd.md) - Automated quality gates
