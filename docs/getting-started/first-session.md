# Your First QE Session

This guide walks you through a complete Quality Engineering session step-by-step, explaining each phase and output.

---

## Overview

A SuperQode QE session follows this lifecycle:

```
┌─────────────────────────────────────────────────────────────┐
│                    QE SESSION LIFECYCLE                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. SNAPSHOT         Original code preserved                 │
│        ↓                                                     │
│  2. QE SANDBOX       Agents freely modify, inject tests,    │
│        │             run experiments, break things           │
│        ↓                                                     │
│  3. ANALYSIS         Role-specific quality investigation    │
│        ↓                                                     │
│  4. REPORT           Document what was done, what was found │
│        ↓                                                     │
│  5. REVERT           All changes removed, original restored │
│        ↓                                                     │
│  6. ARTIFACTS        Patches, tests, reports preserved      │
│                      (in .superqode/qe-artifacts/)          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

Before starting, ensure you have:

- [x] SuperQode installed (`superqode --version`)
- [x] At least one provider configured (API key or local model)
- [x] A project directory to analyze

---

## Step 1: Navigate to Your Project

```bash
cd /path/to/your/project
```

Ensure you're in a Git repository (recommended for full workspace isolation):

```bash
git status
```

---

## Step 2: Launch SuperQode

=== "Interactive Mode (TUI)"

    ```bash
    superqode
    ```

    The TUI launches with the SuperQode interface.

=== "Direct Command"

    ```bash
    superqe run . --mode quick
    ```

    Runs QE directly without the TUI.

---

## Step 3: Connect to a Provider

In the TUI, connect to your preferred provider:

```
# ACP mode (recommended)
:connect acp opencode

# Or BYOK mode with Google
:connect byok google gemini-3-pro
```

You'll see a connection confirmation:

```
✓ Connected to opencode
  Mode: ACP
  Capabilities: chat, streaming, tools, file_editing, shell
```

---

## Step 4: Start the QE Session

### Quick Scan

For a fast 60-second analysis:

```bash
superqe run . --mode quick
```

**Note:** QE sessions are run via CLI commands. In the TUI, you interact directly with agents by typing natural language requests after switching to a QE role.

### Deep QE

For comprehensive 30-minute analysis:

```bash
superqe run . --mode deep
```

---

## Step 5: Watch the Session Progress

During the session, you'll see real-time progress:

```
╭──────────────────────────────────────────────────────────────╮
│                     QE Session in Progress                    │
├──────────────────────────────────────────────────────────────┤
│ Mode: quick_scan                                              │
│ Started: 2024-01-18 14:30:22                                 │
│ Elapsed: 23.4s / 60s                                         │
├──────────────────────────────────────────────────────────────┤
│ Current Role: security_tester                                │
│ Status: Analyzing authentication patterns...                 │
├──────────────────────────────────────────────────────────────┤
│ Roles Completed: 1/3                                         │
│   ✓ api_tester (15.2s) - 2 findings                         │
│   ◐ security_tester (in progress)                           │
│   ○ fullstack (pending)                                      │
├──────────────────────────────────────────────────────────────┤
│ Findings So Far: 2                                           │
│   • [HIGH] SQL Injection vulnerability in /api/users        │
│   • [MEDIUM] Missing rate limiting on /api/auth             │
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 6: Understanding Role Execution

Each role runs with a specific focus:

### Execution Roles (Deterministic)

These roles run existing tests:

| Role | Focus | Duration |
|------|-------|----------|
| `smoke_tester` | Critical paths | Fast (seconds) |
| `sanity_tester` | Core functionality | Quick (< 1 min) |
| `regression_tester` | Full test suite | Thorough (varies) |
| `lint_tester` | Static lint checks | Fast (seconds) |

### Detection Roles (AI-Powered)

These roles use AI to find issues:

| Role | Focus | Typical Findings |
|------|-------|------------------|
| `security_tester` | Vulnerabilities | Injection, auth bypass, secrets |
| `api_tester` | API contracts | Schema violations, missing validation |
| `unit_tester` | Coverage gaps | Untested paths, edge cases |
| `performance_tester` | Bottlenecks | N+1 queries, memory leaks |
| `e2e_tester` | Workflows | Integration issues |

### Heuristic Role

| Role | Focus |
|------|-------|
| `fullstack` | Senior QE comprehensive review |

---

## Step 7: Session Completion

When the session completes, you'll see a summary:

```
╭──────────────────────────────────────────────────────────────╮
│                    QE Session Complete                        │
├──────────────────────────────────────────────────────────────┤
│ Duration: 58.7s                                               │
│ Mode: quick_scan                                              │
│ Workspace: Reverted to original state                        │
├──────────────────────────────────────────────────────────────┤
│ Roles Executed: 3                                             │
│   ✓ api_tester         15.2s    2 findings                   │
│   ✓ security_tester    28.1s    3 findings                   │
│   ✓ fullstack          15.4s    1 finding                    │
├──────────────────────────────────────────────────────────────┤
│ Total Findings: 6                                             │
│   Critical: 1    High: 2    Medium: 2    Low: 1              │
├──────────────────────────────────────────────────────────────┤
│ Artifacts Generated:                                          │
│   • QR: .superqode/qe-artifacts/qr/qr-2024-01-18-1a2b3c4d.json │
╰──────────────────────────────────────────────────────────────╯
```

---

## Step 8: Review the Quality Report (QR)

The QR is a research-grade forensic report. View it:

```bash
cat .superqode/qe-artifacts/qr/qr-*.json | jq
```

### QR Structure

```json
{
  "session": {
    "id": "qe-session-20240118-143022",
    "mode": "quick_scan",
    "duration_seconds": 58.7,
    "started_at": "2024-01-18T14:30:22Z",
    "completed_at": "2024-01-18T14:31:21Z"
  },
  "findings": [
    {
      "id": "finding-001",
      "title": "SQL Injection in User Search",
      "severity": "critical",
      "category": "security",
      "confidence": 0.95,
      "file_path": "src/api/users.py",
      "line_number": 42,
      "description": "User input is directly interpolated into SQL query without sanitization.",
      "reproduction_steps": [
        "1. Send GET request to /api/users?search='; DROP TABLE users; --",
        "2. Observe SQL error in response"
      ],
      "recommendation": "Use parameterized queries or ORM methods",
      "evidence": {
        "code_snippet": "query = f\"SELECT * FROM users WHERE name LIKE '%{search}%'\"",
        "test_result": "SQL syntax error returned, confirming injection"
      }
    }
  ],
  "summary": {
    "total_findings": 6,
    "by_severity": {
      "critical": 1,
      "high": 2,
      "medium": 2,
      "low": 1
    },
    "production_ready": false,
    "recommendation": "Address critical SQL injection before deployment"
  }
}
```

---

## Step 9: Review Individual Findings

Each finding in the QR contains:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier |
| `title` | Brief description |
| `severity` | critical, high, medium, low |
| `category` | security, performance, correctness, etc. |
| `confidence` | 0.0 - 1.0 confidence score |
| `file_path` | Location of the issue |
| `line_number` | Specific line (if applicable) |
| `description` | Detailed explanation |
| `reproduction_steps` | How to reproduce |
| `recommendation` | Suggested fix |
| `evidence` | Supporting data |

---

## Step 10: Apply Suggested Fixes (Optional, Enterprise)

If you ran with `--allow-suggestions`, patches are available:

```bash
# List available suggestions
superqode suggestions list

# View a specific patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply a suggestion
superqode suggestions apply suggestion-001
```

!!! warning "Review Before Applying"
    Always review patches before applying. SuperQode suggests fixes but you make the final decision.

---

## Step 11: Provide Feedback (Enterprise)

Help improve SuperQode's accuracy by providing feedback:

```bash
# Mark finding as valid
superqe feedback finding-001 --valid

# Mark as false positive
superqe feedback finding-002 --false-positive -r "This is expected behavior"
```

Feedback improves the ML-based severity prediction for future sessions.

---

## Step 12: View Session Artifacts

All artifacts are preserved in `.superqode/qe-artifacts/`:

```
.superqode/qe-artifacts/
├── qr-20240118-143022.json       # Quality Report
├── patches/
│   ├── fix-sql-injection.patch    # Suggested fix patches
│   └── fix-rate-limiting.patch
├── tests/
│   └── generated/
│       ├── test_sql_injection.py  # Generated regression tests
│       └── test_api_security.py
├── reports/
└── qr/
    ├── qr-<date>-<session>.md
    └── qr-<date>-<session>.json
```

---

## Complete Session Example

Here's a complete example from start to finish:

```bash
# 1. Navigate to project
cd ~/projects/my-api

# 2. Run comprehensive QE
superqe run . \
  --mode deep \
  --timeout 1800 \
  --output .superqode/qe-artifacts

# 3. Wait for session to complete...

# 4. Review the QR
cat .superqode/qe-artifacts/qr/qr-*.md

# 5. Provide feedback on findings
superqe feedback finding-001 --valid
superqe feedback finding-003 --false-positive -r "Intentional behavior"
```

---

## Next Steps

Now that you've completed your first session:

1. **[Configure SuperQode](configuration.md)** - Customize roles and settings
2. **[Understand QE Roles](../concepts/roles.md)** - Learn about each role
3. **[Read QR Documentation](../concepts/qr.md)** - Deep dive into reports
4. **[Set Up CI/CD](../integration/cicd.md)** - Automate QE in your pipeline
5. **[Advanced Features](../advanced/index.md)** - Custom roles, MCP, harness

---

## Troubleshooting First Session

??? question "Session times out before completion"

    Increase the timeout or use quick scan mode:

    ```bash
    superqe run . --mode quick --timeout 120
    ```

??? question "No findings detected"

    - Ensure the project has analyzable code
    - Try running specific roles: `-r security_tester -r api_tester`
    - Check that the provider is properly connected

??? question "Too many false positives"

    Configure noise filters:

    ```yaml
    # superqode.yaml
    qe:
      noise:
        min_confidence: 0.8
        min_severity: "medium"
    ```

??? question "Workspace not reverting"

    Check that you're in a Git repository. For non-Git projects, snapshot isolation is used by default (worktree mode requires Git).
