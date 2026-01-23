# QE Features

SuperQode provides comprehensive quality engineering features for AI-assisted code analysis and testing.

---

## Feature Overview

SuperQode OSS ships the core agentic scan + QR workflow. Enterprise adds automated fixes, verified patches,
test generation, CI-grade outputs, and curated prompt packs. Contact us for access.

<div class="grid cards" markdown>

-   **Artifacts & Reports**

    ---

    QRs, patches, generated tests, and other outputs from QE sessions.

    [:octicons-arrow-right-24: Artifacts](artifacts.md)

-   **Test Generation (Enterprise)**

    ---

    Automatic generation of regression tests for detected issues.

    [:octicons-arrow-right-24: Test Generation](test-generation.md)

-   **Noise Filtering**

    ---

    Configure thresholds to reduce false positives and focus on important findings.

    [:octicons-arrow-right-24: Noise Filtering](noise-filtering.md)

-   **Natural Language QE (Enterprise)**

    ---

    Describe testing needs in plain English - automatic role and scope selection.

    [:octicons-arrow-right-24: Natural Language QE](natural-language-qe.md)

-   **Constitution System**

    ---

    Define quality principles, rules, and guardrails for your project.

    [:octicons-arrow-right-24: Constitution](constitution.md)

-   **Fix Verifier (Enterprise)**

    ---

    Automatically verify suggested fixes work before presenting them.

    [:octicons-arrow-right-24: Fix Verifier](fix-verifier.md)

</div>

---

## QE Session Lifecycle

Every QE session follows this lifecycle:

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

## Core Features

### Quality Reports (QRs)

Research-grade forensic artifacts that document the complete investigation process:

- Investigation summary and methodology
- All findings with evidence
- Root cause analysis
- Suggested fixes with validation
- Production readiness verdict

[Learn more about QRs](../concepts/qr.md)

### Ephemeral Workspace

Safe, isolated testing environment:

- Original code is always preserved
- Agents can test destructively
- Automatic revert after session
- Artifacts preserved for review

[Learn more about Ephemeral Workspace](../concepts/workspace.md)

### Allow Suggestions Mode

Demonstrated fixes in a sandbox:

- Agent creates fix in sandbox
- Runs tests to verify fix works
- Proves improvement with evidence
- Reverts all changes
- User decides to apply or reject

[Learn more about Suggestions](../concepts/suggestions.md)

---

## QE Modes

### Quick Scan

Fast, time-boxed analysis for development feedback:

```bash
superqe run . --mode quick
```

- **Duration**: ~60 seconds
- **Use case**: Pre-commit, developer feedback
- **Depth**: Shallow analysis
- **Test generation**: Disabled

### Deep QE

Comprehensive quality investigation:

```bash
superqe run . --mode deep
```

- **Duration**: ~30 minutes
- **Use case**: Pre-release, nightly CI
- **Depth**: Full analysis
- **Test generation**: Available

---

## QE Roles

### Execution Roles

Run existing tests deterministically:

| Role | Purpose |
|------|---------|
| `smoke_tester` | Fast critical path validation |
| `sanity_tester` | Core functionality verification |
| `regression_tester` | Full test suite execution |
| `lint_tester` | Fast static linting across languages |

### Detection Roles

AI-powered issue discovery:

| Role | Focus |
|------|-------|
| `security_tester` | OWASP Top 10, injection, auth |
| `api_tester` | API contracts, validation |
| `unit_tester` | Coverage gaps, edge cases |
| `performance_tester` | Bottlenecks, N+1 queries |
| `e2e_tester` | Workflow integration |

### Heuristic Role

| Role | Purpose |
|------|---------|
| `fullstack` | Senior QE comprehensive review |

---

## Output Formats

### Console Output

Real-time progress and findings in the terminal.

### JSONL Streaming

For CI/CD integration:

```bash
superqe run . --jsonl
```

### JUnit XML

For test reporting integration:

```bash
superqe run . --junit results.xml
```

### Web Dashboard

Interactive HTML report:

```bash
superqe dashboard
```

---

## Configuration

### Output Settings

```yaml
qe:
  output:
    directory: ".superqode"
    reports_format: markdown  # markdown, html, json
    keep_history: true
```

### Mode Settings

```yaml
qe:
  modes:
    quick_scan:
      timeout: 60
      depth: shallow
      generate_tests: false

    deep_qe:
      timeout: 1800
      depth: full
      generate_tests: true
```

---

## Common Workflows

### Pre-Commit Check

```bash
superqe run . --mode quick -r security_tester
```

### Security Audit

```bash
superqe run . --mode deep -r security_tester
```

### Full QE Session

```bash
superqe run . --mode deep --allow-suggestions --generate
```

### CI Integration

```bash
superqe run . --mode quick --jsonl --junit results.xml
```

---

## Next Steps

- [Artifacts](artifacts.md) - QE output artifacts
- [Test Generation](test-generation.md) - Automatic test creation
- [Noise Filtering](noise-filtering.md) - Reduce false positives
- [CI/CD Integration](../integration/cicd.md) - Automated quality gates
