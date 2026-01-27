<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# CI/CD Integration

Automate SuperQode quality gates in your CI/CD pipeline.

---

## Overview

SuperQode integrates with any CI/CD system through:

- **JSONL streaming** for real-time event processing (enterprise feature)
- **JUnit XML** for test reporting (enterprise feature)
- **Exit codes** for simple pass/fail
- **JSON output** for programmatic access

OSS tip: use `superqe run . --json > results.json` when JSONL/JUnit are unavailable.

---

## Output Formats

### JSONL Streaming (Enterprise)

Stream events in real-time:

```bash
superqe run . --jsonl
```

Output:
```jsonl
{"type":"qe.started","timestamp":"2024-01-18T14:30:22Z","data":{"mode":"quick"}}
{"type":"role.started","timestamp":"2024-01-18T14:30:23Z","data":{"role":"security_tester"}}
{"type":"finding.detected","timestamp":"2024-01-18T14:30:45Z","data":{"id":"finding-001","severity":"critical"}}
{"type":"qe.completed","timestamp":"2024-01-18T14:31:22Z","data":{"findings":3}}
```

### JUnit XML (Enterprise)

Export for test reporting tools:

```bash
superqe run . --junit results.xml
```

Compatible with:
- Jenkins
- GitHub Actions
- GitLab CI
- CircleCI
- Azure DevOps

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success, no critical/high findings |
| `1` | Findings detected or error |
| `130` | Interrupted (Ctrl+C) |

---

## Quality Gates

### Basic Gate

```bash
#!/bin/bash
superqe run . --mode quick

if [ $? -ne 0 ]; then
    echo "QE failed, blocking deployment"
    exit 1
fi
```

### Severity-Based Gate

```bash
#!/bin/bash
superqe run . --mode quick --json > results.json

CRITICAL=$(jq '.summary.by_severity.critical' results.json)
HIGH=$(jq '.summary.by_severity.high' results.json)

if [ "$CRITICAL" -gt 0 ]; then
    echo "Critical issues found, blocking deployment"
    exit 1
fi

if [ "$HIGH" -gt 2 ]; then
    echo "Too many high severity issues"
    exit 1
fi

echo "Quality gate passed"
```

### Custom Gate Script

```python
#!/usr/bin/env python3
import json
import sys
import glob

# Find latest QR
qr_files = glob.glob('.superqode/qe-artifacts/qr-*.json')
if not qr_files:
    print("No QR found")
    sys.exit(1)

latest_qr = max(qr_files)
with open(latest_qr) as f:
    qr = json.load(f)

summary = qr['summary']

# Custom rules
if summary['by_severity'].get('critical', 0) > 0:
    print(f"BLOCKED: {summary['by_severity']['critical']} critical issues")
    sys.exit(1)

if not summary.get('production_ready', True):
    print("BLOCKED: Not production ready")
    sys.exit(1)

print("PASSED: Quality gate passed")
sys.exit(0)
```

---

## Event Processing

### JSONL Event Types

| Event Type | Description |
|------------|-------------|
| `qe.started` | QE session started |
| `qe.completed` | QE session completed |
| `role.started` | Role execution started |
| `role.completed` | Role execution completed |
| `finding.detected` | New finding detected |
| `suggestion.created` | Fix suggestion created |
| `error` | Error occurred |

### Processing JSONL

```bash
superqe run . --jsonl | while read event; do
    TYPE=$(echo $event | jq -r '.type')

    case $TYPE in
        "qe.started")
            echo "🚀 QE session started"
            ;;
        "finding.detected")
            TITLE=$(echo $event | jq -r '.data.title')
            SEVERITY=$(echo $event | jq -r '.data.severity')
            echo "🔍 Found: [$SEVERITY] $TITLE"
            ;;
        "qe.completed")
            FINDINGS=$(echo $event | jq -r '.data.total_findings')
            echo "✅ Complete: $FINDINGS findings"
            ;;
    esac
done
```

---

## Pipeline Examples

### Jenkins

```groovy
pipeline {
    agent any

    environment {
        ANTHROPIC_API_KEY = credentials('anthropic-api-key')
    }

    stages {
        stage('Quality Engineering') {
            steps {
                sh 'pip install superqode'
                sh 'superqe run . --mode quick --junit results.xml'
            }
            post {
                always {
                    junit 'results.xml'
                    archiveArtifacts artifacts: '.superqode/qe-artifacts/**/*'
                }
            }
        }
    }
}
```

### GitLab CI

```yaml
# .gitlab-ci.yml
stages:
  - quality

qe:
  stage: quality
  image: python:3.12
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  script:
    - pip install superqode
    - superqe run . --mode quick --junit results.xml
  artifacts:
    reports:
      junit: results.xml
    paths:
      - .superqode/qe-artifacts/
    when: always
```

### CircleCI

```yaml
# .circleci/config.yml
version: 2.1

jobs:
  qe:
    docker:
      - image: python:3.12
    steps:
      - checkout
      - run:
          name: Install SuperQode
          command: pip install superqode
      - run:
          name: Run QE
          command: superqe run . --mode quick --junit results.xml
      - store_test_results:
          path: results.xml
      - store_artifacts:
          path: .superqode/qe-artifacts/

workflows:
  quality:
    jobs:
      - qe
```

### Azure DevOps

```yaml
# azure-pipelines.yml
trigger:
  - main
  - develop

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'

  - script: pip install superqode
    displayName: 'Install SuperQode'

  - script: superqe run . --mode quick --junit results.xml
    displayName: 'Run QE'
    env:
      ANTHROPIC_API_KEY: $(ANTHROPIC_API_KEY)

  - task: PublishTestResults@2
    inputs:
      testResultsFormat: 'JUnit'
      testResultsFiles: 'results.xml'
    condition: always()
```

---

## Strategies

### PR Checks (Quick Mode)

Fast feedback on every PR:

```yaml
on:
  pull_request:

jobs:
  qe-quick:
    runs-on: ubuntu-latest
    steps:
      - run: superqe run . --mode quick -r security_tester
```

### Nightly Deep Analysis

Comprehensive analysis on schedule:

```yaml
on:
  schedule:
    - cron: '0 0 * * *'

jobs:
  qe-deep:
    runs-on: ubuntu-latest
    steps:
      - run: superqe run . --mode deep --allow-suggestions
```

### Release Gate

Block releases on findings:

```yaml
on:
  release:
    types: [created]

jobs:
  qe-release:
    runs-on: ubuntu-latest
    steps:
      - run: superqe run . --mode deep
      - name: Check for blockers
        run: |
          CRITICAL=$(cat .superqode/qe-artifacts/qr-*.json | jq '.summary.by_severity.critical')
          if [ "$CRITICAL" -gt 0 ]; then
            exit 1
          fi
```

---

## Notifications

### Slack Integration

```bash
#!/bin/bash
superqe run . --mode quick --json > results.json

FINDINGS=$(jq '.summary.total_findings' results.json)
CRITICAL=$(jq '.summary.by_severity.critical' results.json)

if [ "$CRITICAL" -gt 0 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"🚨 QE found $CRITICAL critical issues!\"}" \
        $SLACK_WEBHOOK_URL
fi
```

### GitHub PR Comment

See [GitHub Actions](github-actions.md) for PR comment integration.

---

## Caching

### Cache SuperQode

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/.cache/pip
      ~/.superqode
    key: ${{ runner.os }}-superqode-${{ hashFiles('**/requirements.txt') }}
```

### Cache Provider Responses

Some responses can be cached to reduce API costs:

```yaml
qe:
  cache:
    enabled: true
    ttl: 3600  # 1 hour
```

---

## Best Practices

### 1. Use Appropriate Modes

| Trigger | Mode | Roles |
|---------|------|-------|
| PR | quick | security_tester |
| Merge | quick | all |
| Nightly | deep | all |
| Release | deep | all |

### 2. Set Timeouts

```yaml
jobs:
  qe:
    timeout-minutes: 30
    steps:
      - run: superqe run . --mode quick --timeout 300
```

### 3. Handle Failures Gracefully

```yaml
- run: superqe run . --mode quick || true
  continue-on-error: true
- run: cat .superqode/qe-artifacts/qr/qr-*.md
```

### 4. Secure API Keys

Never commit API keys. Use CI secrets:

- GitHub: Repository secrets
- GitLab: CI/CD variables
- Jenkins: Credentials plugin

---

## Next Steps

- [GitHub Actions](github-actions.md) - GitHub-specific workflows
- [Artifacts](../qe-features/artifacts.md) - QE output formats
