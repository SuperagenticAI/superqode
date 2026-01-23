# QE Commands

Quality Engineering commands for running QE sessions, viewing reports, and managing artifacts.

---

## Overview

The `superqe` command group provides all quality engineering functionality:

```bash
superqe COMMAND [OPTIONS] [ARGS]
```

---

## OSS vs Enterprise

**OSS supports:** `run`, `roles`, `quick`, `deep`.

**Enterprise commands:** `status`, `artifacts`, `show`, `clean`, `report`, `logs`,
`dashboard`, `feedback`, `suppressions`.

**Enterprise options:** `--generate`, `--allow-suggestions`, `--jsonl`, `--junit`.

---

## run

Run a QE session on the specified path.

```bash
superqe run [PATH] [OPTIONS]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `PATH` | Directory to analyze | `.` (current directory) |

### Options

| Option | Description |
|--------|-------------|
| `--mode`, `-m` | QE mode: `quick` (60s) or `deep` (30min) |
| `--role`, `-r` | QE role(s) to run (can specify multiple) |
| `--timeout`, `-t` | Timeout in seconds |
| `--no-revert` | Don't revert changes (for debugging) |
| `--output`, `-o` | Output directory for artifacts |
| `--json` | Output results as JSON |
| `--jsonl` | Stream events as JSONL (Enterprise) |
| `--junit PATH` | Export JUnit XML to file (Enterprise) |
| `--worktree` | Use git worktree isolation (writes `.git/worktrees`) |
| `--generate`, `-g` | Generate tests for detected issues (Enterprise) |
| `--allow-suggestions` | Enable suggestion mode (Enterprise) |
| `--verbose`, `-v` | Show detailed progress |

### Examples

```bash
# Quick scan current directory
superqe run .

# Quick scan with 60s timeout
superqe run . --mode quick

# Deep analysis with verbose output
superqe run . --mode deep --verbose

# Run specific roles
superqe run . -r security_tester -r api_tester

# Run with suggestions enabled
superqe run . --mode deep --allow-suggestions --generate

# Export for CI
superqe run . --junit results.xml

# Stream JSONL events
superqe run . --jsonl

# Use worktree isolation
superqe run . --worktree
```

---

## quick

Alias for `run --mode quick`.

```bash
superqe quick [PATH]
```

Fast, time-boxed QE for pre-commit and developer feedback.

### Example

```bash
superqe quick .
```

---

## deep

Alias for `run --mode deep`.

```bash
superqe deep [PATH]
```

Full investigation for pre-release and nightly CI.

### Example

```bash
superqe deep .
```

---

## roles

List all available QE roles.

```bash
superqe roles
```

### Output

Shows roles grouped by type:

- **Execution Roles**: Run existing tests deterministically
- **Detection Roles**: AI-powered issue discovery
- **Heuristic Roles**: Senior QE comprehensive review

The list is pulled from your `superqode.yaml`. The default template includes a comprehensive role catalog, but only roles with implementations can actually run.

### Example Output

```
Available QE Roles

Execution Roles (run existing tests)
  smoke_tester: Fast critical path validation
  sanity_tester: Quick core functionality verification
  regression_tester: Full test suite execution
  lint_tester: Fast static linting across languages

Detection Roles (AI-powered issue detection)
  security_tester: Security vulnerability detection
    Focus: injection, auth, secrets, OWASP
  api_tester: API contract and security testing
    Focus: schema, validation, rate limiting
  unit_tester: Test coverage and unit test gaps
  e2e_tester: End-to-end workflow testing
  performance_tester: Performance bottleneck detection

Heuristic Roles (senior QE review)
  fullstack: Senior QE comprehensive review
```

---

## status

Show current QE workspace status.

```bash
superqe status [PATH]
```

### Output

Shows:
- Workspace state (idle, active, etc.)
- Current session ID
- Session start time
- Artifact counts
- Recent session history

---

## artifacts

List QE artifacts from previous sessions.

```bash
superqe artifacts [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--type`, `-t` | Filter by type (patch, test_unit, qr, etc.) |

### Example

```bash
# List all artifacts
superqe artifacts

# List only patches
superqe artifacts --type patch
```

---

## show

Show content of a specific artifact.

```bash
superqe show ARTIFACT_ID [PATH]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `ARTIFACT_ID` | The artifact ID to display |

### Example

```bash
superqe show patch-001
```

---

## report

View or export the latest QR.

```bash
superqe report [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--format`, `-f` | Output format: `md`, `json`, `html` |
| `--output`, `-o` | Output file path |

### Examples

```bash
# View latest QR in terminal
superqe report

# Export as JSON
superqe report --format json --output report.json
```

---

## logs

Show detailed agent work logs for QE sessions.

```bash
superqe logs [SESSION_ID] [PATH]
```

Shows the actual agent interaction logs, including:
- Connection attempts and responses
- Prompts sent to the AI agent
- Analysis steps and reasoning
- Tool calls and their results
- Final findings extraction

### Arguments

| Argument | Description |
|----------|-------------|
| `SESSION_ID` | Optional session ID (defaults to latest) |

### Example

```bash
# Show logs for latest session
superqe logs

# Show logs for specific session
superqe logs qe-20240118-143022
```

---

## dashboard

Open QR dashboard in web browser.

```bash
superqe dashboard [PATH] [OPTIONS]
```

Provides an interactive web interface for viewing Quality Reports.

### Options

| Option | Description |
|--------|-------------|
| `--port`, `-p` | Port for web server (default: 8765) |
| `--no-open` | Don't open browser automatically |
| `--export`, `-e` | Export as standalone HTML file |

### Examples

```bash
# Open latest QR in browser
superqe dashboard

# Use custom port
superqe dashboard --port 9000

# Export as HTML file
superqe dashboard --export report.html
```

---

## clean

Clean up QE artifacts.

```bash
superqe clean [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--keep-qrs` | Keep QR files (default: true) |
| `--all` | Remove all including QRs |

### Example

```bash
# Clean artifacts but keep QRs
superqe clean

# Remove everything
superqe clean --all
```

---

## feedback

Provide feedback on a finding to improve future QE runs.

```bash
superqe feedback FINDING_ID [OPTIONS] [PATH]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | The finding ID to provide feedback on |

### Options

| Option | Description |
|--------|-------------|
| `--valid` | Mark finding as valid (true positive) |
| `--false-positive`, `-fp` | Mark as false positive (suppress in future) |
| `--fixed` | Mark finding as fixed |
| `--wont-fix` | Mark finding as won't fix |
| `--reason`, `-r` | Reason for the feedback |
| `--scope`, `-s` | Scope for suppression: `project` or `team` |
| `--expires`, `-e` | Suppression expires in N days |

### Examples

```bash
# Mark as valid
superqe feedback sec-001 --valid

# Mark as false positive
superqe feedback sec-002 --false-positive -r "Intentional for testing"

# Mark as false positive with team scope
superqe feedback sec-003 --false-positive --scope team -r "Known limitation"

# Mark as fixed
superqe feedback perf-001 --fixed -r "Optimized query"
```

---

## suppressions

List or manage finding suppressions.

```bash
superqe suppressions [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--remove`, `-r` | Remove suppression by ID |

### Examples

```bash
# List active suppressions
superqe suppressions

# Remove a suppression
superqe suppressions -r abc123
```

---

## Common Workflows

### Pre-Commit Check

```bash
superqe run . --mode quick -r security_tester
```

### Pre-Release Validation

```bash
superqe run . --mode deep --allow-suggestions --generate
```

### CI/CD Integration

```bash
# JSONL output for streaming
superqe run . --jsonl

# JUnit XML for test reporting
superqe run . --junit results.xml
```

### Review Findings

```bash
# View report
superqe report

# View agent work logs
superqe logs

# Open dashboard
superqe dashboard
```

---

## Next Steps

- [Config Commands](config-commands.md) - Configuration management
- [Provider Commands](provider-commands.md) - Provider management
- [CI/CD Integration](../integration/cicd.md) - Automated quality gates
