# GitHub Actions

Ready-to-use GitHub Actions workflows for SuperQode integration.

Note: JSONL streaming and JUnit output are enterprise features. OSS can use `--json` and redirect output to a file.

---

## Quick Start

### Basic Workflow

```yaml
# .github/workflows/qe.yml
name: Quality Engineering

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  qe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install SuperQode
        run: pip install superqode

      - name: Run QE
        run: superqe run . --mode quick --junit results.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload Results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: qe-artifacts
          path: .superqode/qe-artifacts/
```

---

## Workflow Templates

### PR Security Check

Fast security scan on every PR:

```yaml
name: PR Security Check

on:
  pull_request:

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - run: pip install superqode

      - name: Security Scan
        run: superqe run . --mode quick -r security_tester --junit results.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Report Results
        uses: dorny/test-reporter@v1
        if: always()
        with:
          name: Security Findings
          path: results.xml
          reporter: java-junit
```

### Full QE on Push

Comprehensive QE on main branch:

```yaml
name: Full QE

on:
  push:
    branches: [main]

jobs:
  qe:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install superqode

      - name: Run Deep QE
        run: superqe run . --mode deep --junit results.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload Artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: qe-artifacts
          path: .superqode/qe-artifacts/

      - name: Publish Results
        uses: dorny/test-reporter@v1
        if: always()
        with:
          name: QE Findings
          path: results.xml
          reporter: java-junit
```

### Nightly Analysis

Scheduled comprehensive analysis:

```yaml
name: Nightly QE

on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight UTC
  workflow_dispatch:  # Allow manual trigger

jobs:
  deep-qe:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install superqode

      - name: Run Deep QE with Suggestions
        run: |
          superqe run . \
            --mode deep \
            --allow-suggestions \
            --generate \
            --junit results.xml
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload All Artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: qe-artifacts-${{ github.run_id }}
          path: .superqode/qe-artifacts/
          retention-days: 30

      - name: Create Issue if Critical
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: 'QE: Critical Issues Found',
              body: 'Nightly QE found critical issues. Check the workflow artifacts.'
            });
```

### PR Comment with Findings

Post QE summary as PR comment:

```yaml
name: QE with PR Comment

on:
  pull_request:

jobs:
  qe:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install superqode

      - name: Run QE
        id: qe
        run: |
          superqe run . --mode quick --json > qe-output.json
          echo "findings=$(jq '.summary.total_findings' qe-output.json)" >> $GITHUB_OUTPUT
          echo "critical=$(jq '.summary.by_severity.critical' qe-output.json)" >> $GITHUB_OUTPUT
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Comment on PR
        uses: actions/github-script@v7
        with:
          script: |
            const findings = ${{ steps.qe.outputs.findings }};
            const critical = ${{ steps.qe.outputs.critical }};

            let status = '[CORRECT] No issues found';
            if (critical > 0) {
              status = '🚨 Critical issues found';
            } else if (findings > 0) {
              status = 'WARNING: Issues found';
            }

            const body = `## SuperQode QE Results

            ${status}

            | Severity | Count |
            |----------|-------|
            | Total | ${findings} |
            | Critical | ${critical} |

            [View Full Report](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId})
            `;

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });
```

### Quality Gate

Block merge on critical issues:

```yaml
name: Quality Gate

on:
  pull_request:

jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install superqode

      - name: Run QE
        run: superqe run . --mode quick --json > qe-output.json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Check Quality Gate
        run: |
          CRITICAL=$(jq '.summary.by_severity.critical' qe-output.json)
          HIGH=$(jq '.summary.by_severity.high' qe-output.json)

          if [ "$CRITICAL" -gt 0 ]; then
            echo "[INCORRECT] BLOCKED: $CRITICAL critical issues found"
            exit 1
          fi

          if [ "$HIGH" -gt 5 ]; then
            echo "[INCORRECT] BLOCKED: Too many high severity issues ($HIGH)"
            exit 1
          fi

          echo "[CORRECT] Quality gate passed"
```

---

## Secrets Setup

### Required Secrets

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key (optional) |

### Adding Secrets

1. Go to repository **Settings**
2. Click **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add `ANTHROPIC_API_KEY` with your key

---

## Caching

Speed up workflows with caching:

```yaml
- uses: actions/cache@v4
  with:
    path: |
      ~/.cache/pip
      ~/.superqode
    key: ${{ runner.os }}-superqode-${{ hashFiles('**/requirements.txt') }}
    restore-keys: |
      ${{ runner.os }}-superqode-
```

---

## Matrix Testing

Test with multiple providers:

```yaml
jobs:
  qe:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        provider: [anthropic, openai]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install superqode
      - run: superqe run . --mode quick
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

---

## Branch Protection

Configure branch protection rules:

1. Go to repository **Settings** → **Branches**
2. Add rule for `main`
3. Enable **Require status checks to pass**
4. Select your QE workflow

---

## Troubleshooting

### Workflow Timeout

```yaml
jobs:
  qe:
    timeout-minutes: 30  # Adjust as needed
```

### API Key Issues

```yaml
- name: Verify API Key
  run: |
    if [ -z "$ANTHROPIC_API_KEY" ]; then
      echo "ANTHROPIC_API_KEY is not set"
      exit 1
    fi
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Large Repositories

For large repos, focus on changed files:

```yaml
- name: Get changed files
  id: changed
  uses: tj-actions/changed-files@v44

- name: Run QE on changes
  run: superqe run . --mode quick --files ${{ steps.changed.outputs.all_changed_files }}
```

---

## Next Steps

- [CI/CD Integration](cicd.md) - General CI/CD patterns
- [Quality Gates](../qe-features/index.md) - Gate configuration
