# GitLab CI Integration

Integrate SuperQode into your GitLab CI/CD pipelines for automated quality gates.

Note: JSONL streaming and JUnit output are enterprise features. OSS can use `--json` and redirect output to a file.

---

## Overview

SuperQode integrates seamlessly with GitLab CI/CD through:

- **JUnit XML reports**: Native test reporting in GitLab
- **Artifacts**: Preserve QE results and QRs
- **Exit codes**: Simple pass/fail for quality gates
- **JSONL streaming**: Real-time event processing

---

## Quick Start

### Basic Workflow

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

---

## Complete Examples

### Quick Scan on Every Push

```yaml
# .gitlab-ci.yml
stages:
  - quality

qe-quick:
  stage: quality
  image: python:3.12
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  before_script:
    - pip install --upgrade pip
    - pip install superqode
  script:
    - superqe run . --mode quick --junit results.xml --jsonl
  artifacts:
    reports:
      junit: results.xml
    paths:
      - .superqode/qe-artifacts/
      - events.jsonl
    expire_in: 30 days
    when: always
  only:
    - merge_requests
    - branches
```

### Deep QE on Schedule

```yaml
# .gitlab-ci.yml
qe-deep:
  stage: quality
  image: python:3.12
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  before_script:
    - pip install --upgrade pip
    - pip install superqode
  script:
    - superqe run . --mode deep --junit results.xml --allow-suggestions
  artifacts:
    reports:
      junit: results.xml
    paths:
      - .superqode/qe-artifacts/
    expire_in: 90 days
    when: always
  only:
    - schedules
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Security-Focused PR Checks

```yaml
# .gitlab-ci.yml
qe-security:
  stage: quality
  image: python:3.12
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  script:
    - pip install superqode
    - superqe run . --mode quick -r security_tester --junit security-results.xml
  artifacts:
    reports:
      junit: security-results.xml
    paths:
      - .superqode/qe-artifacts/
  only:
    - merge_requests
```

---

## Advanced Configuration

### Multi-Stage Workflow

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - quality
  - deploy

build:
  stage: build
  script:
    - npm install
    - npm run build

test:
  stage: test
  script:
    - npm test

quality-engineering:
  stage: quality
  image: python:3.12
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  script:
    - pip install superqode
    - superqe run . --mode quick --junit qe-results.xml
  artifacts:
    reports:
      junit: qe-results.xml
    paths:
      - .superqode/qe-artifacts/
  needs:
    - build
    - test

deploy:
  stage: deploy
  script:
    - echo "Deploy..."
  needs:
    - quality-engineering
  only:
    - main
```


## CI/CD Variables

Configure API keys in GitLab CI/CD settings:

**Settings → CI/CD → Variables**

| Variable | Description | Protected | Masked |
|----------|-------------|-----------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API key | [CORRECT] | [CORRECT] |
| `OPENAI_API_KEY` | OpenAI API key | [CORRECT] | [CORRECT] |
| `GOOGLE_API_KEY` | Google API key | [CORRECT] | [CORRECT] |

**Access in YAML:**

```yaml
variables:
  ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

---

## Quality Gates

### Block Merge on Critical Issues

```yaml
qe-gate:
  stage: quality
  image: python:3.12
  script:
    - pip install superqode jq
    - superqe run . --mode quick --json > results.json
    - |
      CRITICAL=$(jq '.summary.by_severity.critical' results.json)
      if [ "$CRITICAL" -gt 0 ]; then
        echo "Critical issues found, blocking merge"
        exit 1
      fi
  only:
    - merge_requests
```

### Custom Severity Threshold

```yaml
qe-custom:
  stage: quality
  script:
    - pip install superqode jq
    - superqe run . --mode quick --json > results.json
    - |
      CRITICAL=$(jq '.summary.by_severity.critical' results.json)
      HIGH=$(jq '.summary.by_severity.high' results.json)

      if [ "$CRITICAL" -gt 0 ]; then
        echo "[INCORRECT] Critical issues found: $CRITICAL"
        exit 1
      fi

      if [ "$HIGH" -gt 5 ]; then
        echo "WARNING: Too many high severity issues: $HIGH"
        exit 1
      fi

      echo "[CORRECT] Quality gate passed"
```

---

## Artifacts

### Preserve QE Artifacts

```yaml
qe:
  artifacts:
    paths:
      - .superqode/qe-artifacts/
    reports:
      junit: results.xml
    expire_in: 30 days
    when: always  # Preserve even on failure
```

### Artifact Expiration

```yaml
artifacts:
  paths:
    - .superqode/qe-artifacts/
  expire_in: 7 days    # Short-lived for PRs
  # expire_in: 90 days  # Long-lived for releases
```

---

## Caching

### Cache Python Dependencies

```yaml
qe:
  cache:
    key: ${CI_COMMIT_REF_SLUG}-superqode
    paths:
      - ~/.cache/pip
    policy: pull-push
  script:
    - pip install superqode
```

### Cache SuperQode Config

```yaml
qe:
  cache:
    key: superqode-config
    paths:
      - ~/.superqode/
    policy: pull
```

---

## Notifications

### Send Results to Slack

```yaml
qe:
  script:
    - pip install superqode jq curl
    - superqe run . --mode quick --json > results.json
    - |
      CRITICAL=$(jq '.summary.by_severity.critical' results.json)
      if [ "$CRITICAL" -gt 0 ]; then
        curl -X POST -H 'Content-type: application/json' \
          --data "{\"text\":\"🚨 QE found $CRITICAL critical issues in $CI_PROJECT_NAME\"}" \
          $SLACK_WEBHOOK_URL
      fi
  variables:
    SLACK_WEBHOOK_URL: $SLACK_WEBHOOK_URL
```

### Email on Failure

```yaml
qe:
  allow_failure: false
  when: on_failure
  # GitLab will automatically send email on failure
```

---

## Parallel Jobs

### Multiple Roles in Parallel

```yaml
qe-security:
  extends: .qe-base
  script:
    - superqe run . --mode quick -r security_tester --junit security.xml
  artifacts:
    reports:
      junit: security.xml

qe-api:
  extends: .qe-base
  script:
    - superqe run . --mode quick -r api_tester --junit api.xml
  artifacts:
    reports:
      junit: api.xml

.qe-base:
  stage: quality
  image: python:3.12
  before_script:
    - pip install superqode
```

---

## Conditional Execution

### Only on Main Branch

```yaml
qe:
  only:
    - main
```

### Only on Merge Requests

```yaml
qe:
  only:
    - merge_requests
```

### Only on Tags

```yaml
qe-release:
  only:
    - tags
```

### Custom Rules

```yaml
qe:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_COMMIT_TAG
```

---

## Environment-Specific

### Different Modes per Environment

```yaml
qe-staging:
  stage: quality
  environment: staging
  script:
    - superqe run . --mode quick

qe-production:
  stage: quality
  environment: production
  script:
    - superqe run . --mode deep
  only:
    - main
```

---

## Resource Limits

### Timeout Configuration

```yaml
qe:
  timeout: 30m  # Maximum 30 minutes
  script:
    - superqe run . --mode deep --timeout 1800
```

### Resource Allocation

```yaml
qe:
  tags:
    - docker
    - large  # Use runners with more resources
```

---

## Error Handling

### Continue on Failure

```yaml
qe:
  allow_failure: true
  script:
    - superqe run . --mode quick
  # Job won't block pipeline if QE fails
```

### Always Upload Artifacts

```yaml
qe:
  script:
    - superqe run . --mode quick --junit results.xml || true
  artifacts:
    when: always  # Upload even if job fails
    paths:
      - .superqode/qe-artifacts/
```

---

## JSONL Event Processing

### Process Events in Pipeline

```yaml
qe:
  script:
    - pip install superqode jq
    - |
      superqe run . --mode quick --jsonl | tee events.jsonl | while read event; do
        TYPE=$(echo $event | jq -r '.type')
        if [ "$TYPE" = "finding.detected" ]; then
          SEVERITY=$(echo $event | jq -r '.severity')
          TITLE=$(echo $event | jq -r '.title')
          echo "Found: [$SEVERITY] $TITLE"
        fi
      done
  artifacts:
    paths:
      - events.jsonl
```

---

## Integration with GitLab Pages

### Publish QE Reports

```yaml
pages:
  stage: deploy
  dependencies:
    - qe
  script:
    - mkdir -p public
    - cp -r .superqode/qe-artifacts/*.html public/ || true
  artifacts:
    paths:
      - public
  only:
    - main
```

---

## Best Practices

### 1. Use Appropriate Timeouts

```yaml
qe-quick:
  timeout: 10m
  script:
    - superqe run . --mode quick

qe-deep:
  timeout: 60m
  script:
    - superqe run . --mode deep
```

### 2. Cache Dependencies

```yaml
cache:
  key: ${CI_COMMIT_REF_SLUG}
  paths:
    - ~/.cache/pip
```

### 3. Preserve Artifacts

```yaml
artifacts:
  paths:
    - .superqode/qe-artifacts/
  expire_in: 30 days
  when: always
```

### 4. Use Protected Variables

Always mark API keys as **Protected** and **Masked** in GitLab settings.

---

## Troubleshooting

### Job Timeouts

**Problem**: QE job times out

**Solution**: Increase timeout or use quick mode:

```yaml
qe:
  timeout: 30m
  script:
    - superqe run . --mode quick
```

### Missing Artifacts

**Problem**: Artifacts not available

**Solution**: Ensure `when: always`:

```yaml
artifacts:
  when: always
```

### API Key Not Available

**Problem**: `ANTHROPIC_API_KEY` not set

**Solution**: Configure in CI/CD variables:
- Settings → CI/CD → Variables
- Add `ANTHROPIC_API_KEY` with protected/masked enabled

---

## Next Steps

- [CI/CD Integration](cicd.md) - General CI/CD patterns
- [GitHub Actions](github-actions.md) - GitHub-specific examples
