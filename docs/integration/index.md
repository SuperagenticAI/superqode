# Integration

Integrate SuperQode into your development workflow, CI/CD pipelines, and toolchain.

---

## Integration Options

<div class="grid cards" markdown>

-   **CI/CD Pipelines**

    ---

    Automate quality gates in your CI/CD pipeline.

    [:octicons-arrow-right-24: CI/CD Integration](cicd.md)

-   **GitHub Actions**

    ---

    Ready-to-use workflows for GitHub.

    [:octicons-arrow-right-24: GitHub Actions](github-actions.md)

-   **GitLab CI**

    ---

    Integration with GitLab CI/CD.

    [:octicons-arrow-right-24: GitLab CI](gitlab-ci.md)

-   **IDE Integration (Enterprise)**

    ---

    LSP server and VSCode extension for editor integration.

    [:octicons-arrow-right-24: IDE Integration](ide.md)

</div>

---

## Quick Start

### Pre-Commit Hook

Add quality checks before commits:

```bash
# .git/hooks/pre-commit
#!/bin/bash
superqe run . --mode quick -r security_tester
if [ $? -ne 0 ]; then
    echo "QE found issues. Fix them before committing."
    exit 1
fi
```

### GitHub Actions

```yaml
# .github/workflows/qe.yml
name: Quality Engineering
on: [push, pull_request]

jobs:
  qe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install superqode
      - run: superqe run . --mode quick --json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Output Formats

SuperQode supports multiple output formats for integration:

| Format | Use Case | Command |
|--------|----------|---------|
| Console | Interactive use | Default |
| JSONL | CI streaming (Enterprise) | `--jsonl` |
| JUnit XML | Test reporting (Enterprise) | `--junit results.xml` |
| JSON | Programmatic access | `--json` |

---

## Quality Gates

### Block on Critical Issues

```bash
superqe run . --mode quick

# Check exit code
if [ $? -eq 1 ]; then
    echo "Critical issues found"
    exit 1
fi
```

### Parse QR for Custom Gates

```bash
CRITICAL=$(cat .superqode/qe-artifacts/qr-*.json | jq '.summary.by_severity.critical')
if [ "$CRITICAL" -gt 0 ]; then
    echo "Critical issues found, blocking merge"
    exit 1
fi
```

---

## Environment Variables

Required for CI environments:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `CI` | Set to `true` in CI environments |

---

## Caching

Cache dependencies for faster CI runs:

### GitHub Actions

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-superqode
```

### GitLab CI

```yaml
cache:
  paths:
    - ~/.cache/pip
```

---

## Artifacts

Preserve QE artifacts in CI:

### GitHub Actions

```yaml
- uses: actions/upload-artifact@v4
  with:
    name: qe-artifacts
    path: .superqode/qe-artifacts/
```

### GitLab CI

```yaml
artifacts:
  paths:
    - .superqode/qe-artifacts/
  when: always
```

---

## Best Practices

### 1. Use Quick Mode in CI

For fast feedback in PRs:

```bash
superqe run . --mode quick
```

### 2. Deep QE on Schedule

Run comprehensive analysis nightly:

```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight
jobs:
  deep-qe:
    runs-on: ubuntu-latest
    steps:
      - run: superqe run . --mode deep
```

### 3. Security Focus on PRs

Focus on security for PRs:

```bash
superqe run . --mode quick -r security_tester
```

### 4. Report to PR Comments

Add findings as PR comments (GitHub Actions):

```yaml
- name: Comment on PR
  uses: actions/github-script@v7
  with:
    script: |
      const fs = require('fs');
      const path = require('path');

      // Pick the most recent QR JSON artifact.
      const qrDir = '.superqode/qe-artifacts/qr';
      const candidates = fs.readdirSync(qrDir)
        .filter((f) => f.startsWith('qr-') && f.endsWith('.json'))
        .map((f) => ({ f, mtime: fs.statSync(path.join(qrDir, f)).mtimeMs }))
        .sort((a, b) => b.mtime - a.mtime);

      if (!candidates.length) {
        throw new Error(`No QR JSON artifacts found in ${qrDir}. Did the QE job generate artifacts?`);
      }

      const qr = JSON.parse(fs.readFileSync(path.join(qrDir, candidates[0].f), 'utf8'));
      github.rest.issues.createComment({
        issue_number: context.issue.number,
        owner: context.repo.owner,
        repo: context.repo.repo,
        body: JSON.stringify(qr.summary ?? qr, null, 2)
      });
```

---

## Next Steps

- [CI/CD Integration](cicd.md) - Detailed CI/CD setup
- [GitHub Actions](github-actions.md) - GitHub workflows
- [IDE Integration](ide.md) - LSP and editor integration
