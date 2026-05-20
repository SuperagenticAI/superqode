# Validation Commands

validation and evaluation commands for running validation sessions, viewing reports, and managing artifacts.

---

## Overview

The `superqode qe` command group provides all validation and evaluation functionality:

```bash
superqode qe COMMAND [OPTIONS] [ARGS]
```

---

## OSS vs Enterprise

**OSS supports:** `run`, `roles`, `quick`, `deep`, JSON output, JSONL event
streaming, and JUnit export.

**Enterprise commands:** `status`, `artifacts`, `show`, `clean`, `report`, `logs`,
`dashboard`, `feedback`, `suppressions`.

**Enterprise options:** `--generate`, `--allow-suggestions`.

---

## run

Run a validation session on the specified path.

```bash
superqode qe run [PATH] [OPTIONS]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `PATH` | Directory to analyze | `.` (current directory) |

### Options

| Option | Description |
|--------|-------------|
| `--mode`, `-m` | validation mode: `quick` (60s) or `deep` (30min) |
| `--role`, `-r` | validation role(s) to run (can specify multiple) |
| `--timeout`, `-t` | Timeout in seconds |
| `--no-revert` | Don't revert changes (for debugging) |
| `--output`, `-o` | Output directory for artifacts |
| `--json` | Output results as JSON |
| `--jsonl` | Stream events as JSONL |
| `--junit PATH` | Export JUnit XML to file |
| `--worktree` | Use git worktree isolation (writes `.git/worktrees`) |
| `--generate`, `-g` | Generate tests for detected issues (Enterprise) |
| `--allow-suggestions` | Enable suggestion mode (Enterprise) |
| `--verbose`, `-v` | Show detailed progress |

### Examples

```bash
# Quick scan current directory
superqode qe run .

# Quick scan with 60s timeout
superqode qe run . --mode quick

# Deep analysis with verbose output
superqode qe run . --mode deep --verbose

# Run specific roles
superqode qe run . -r security_tester -r api_tester

# Run with suggestions enabled
superqode qe run . --mode deep --allow-suggestions --generate

# Export for CI
superqode qe run . --junit results.xml

# Stream JSONL events
superqode qe run . --jsonl

# Use worktree isolation
superqode qe run . --worktree
```

---

## quick

Alias for `run --mode quick`.

```bash
superqode qe quick [PATH]
```

Fast, time-boxed validation for pre-commit and developer feedback.

### Example

```bash
superqode qe quick .
```

---

## deep

Alias for `run --mode deep`.

```bash
superqode qe deep [PATH]
```

Full investigation for pre-release and nightly CI.

### Example

```bash
superqode qe deep .
```

---

## roles

List all available validation roles.

```bash
superqode qe roles
```

### Output

Shows roles grouped by type:

- **Execution Roles**: Run existing tests deterministically
- **Detection Roles**: AI-powered issue discovery
- **Heuristic Roles**: Senior validation comprehensive review

The list is pulled from your `superqode.yaml`. The default template includes a comprehensive role catalog, but only roles with implementations can actually run.

### Example Output

```
Available Role-Based Workflows

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

Heuristic Roles (senior validation review)
  fullstack: Senior validation comprehensive review
```

---

## status

Show current validation workspace status.

```bash
superqode qe status [PATH]
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

List validation artifacts from previous sessions.

```bash
superqode qe artifacts [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--type`, `-t` | Filter by type (patch, test_unit, qr, etc.) |

### Example

```bash
# List all artifacts
superqode qe artifacts

# List only patches
superqode qe artifacts --type patch
```

---

## show

Show content of a specific artifact.

```bash
superqode qe show ARTIFACT_ID [PATH]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `ARTIFACT_ID` | The artifact ID to display |

### Example

```bash
superqode qe show patch-001
```

---

## report

View or export the latest report.

```bash
superqode qe report [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--format`, `-f` | Output format: `md`, `json`, `html` |
| `--output`, `-o` | Output file path |

### Examples

```bash
# View latest report in terminal
superqode qe report

# Export as JSON
superqode qe report --format json --output report.json
```

---

## logs

Show detailed agent work logs for validation sessions.

```bash
superqode qe logs [SESSION_ID] [PATH]
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
superqode qe logs

# Show logs for specific session
superqode qe logs qe-20240118-143022
```

---

## dashboard

Open report dashboard in web browser.

```bash
superqode qe dashboard [PATH] [OPTIONS]
```

Provides an interactive web interface for viewing Validation Reports.

### Options

| Option | Description |
|--------|-------------|
| `--port`, `-p` | Port for web server (default: 8765) |
| `--no-open` | Don't open browser automatically |
| `--export`, `-e` | Export as standalone HTML file |

### Examples

```bash
# Open latest report in browser
superqode qe dashboard

# Use custom port
superqode qe dashboard --port 9000

# Export as HTML file
superqode qe dashboard --export report.html
```

---

## clean

Clean up validation artifacts.

```bash
superqode qe clean [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--keep-qrs` | Keep report files (default: true) |
| `--all` | Remove all including reports |

### Example

```bash
# Clean artifacts but keep reports
superqode qe clean

# Remove everything
superqode qe clean --all
```

---

## feedback

Provide feedback on a finding to improve future validation runs.

```bash
superqode qe feedback FINDING_ID [OPTIONS] [PATH]
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
superqode qe feedback sec-001 --valid

# Mark as false positive
superqode qe feedback sec-002 --false-positive -r "Intentional for testing"

# Mark as false positive with team scope
superqode qe feedback sec-003 --false-positive --scope team -r "Known limitation"

# Mark as fixed
superqode qe feedback perf-001 --fixed -r "Optimized query"
```

---

## suppressions

List or manage finding suppressions.

```bash
superqode qe suppressions [PATH] [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--remove`, `-r` | Remove suppression by ID |

### Examples

```bash
# List active suppressions
superqode qe suppressions

# Remove a suppression
superqode qe suppressions -r abc123
```

---

## Common Workflows

### Pre-Commit Check

```bash
superqode qe run . --mode quick -r security_tester
```

### Pre-Release Validation

```bash
superqode qe run . --mode deep --allow-suggestions --generate
```

### CI/CD Integration

```bash
# JSONL output for streaming
superqode qe run . --jsonl

# JUnit XML for test reporting
superqode qe run . --junit results.xml
```

### Review Findings

```bash
# View report
superqode qe report

# View agent work logs
superqode qe logs

# Open dashboard
superqode qe dashboard
```

---

## Next Steps

- [Config Commands](config-commands.md) - Configuration management
- [Provider Commands](provider-commands.md) - Provider management
- [CI/CD Integration](../integration/cicd.md) - Automated quality gates
