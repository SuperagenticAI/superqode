# JSONL Events API

SuperQode emits structured JSONL (JSON Lines) events during QE sessions for CI/CD integration, real-time monitoring, and programmatic access to QE results.

---

## Overview

JSONL events provide a machine-readable stream of all QE activities:

- **CI-friendly**: Pipe directly to CI/CD pipelines
- **Real-time**: Stream events as they occur
- **Structured**: Consistent JSON format for easy parsing
- **Complete**: Covers all aspects of QE sessions

---

## Event Format

Each event is a single JSON object on one line:

```json
{"type":"qe.started","session_id":"qe-20250115-143022","mode":"quick","timestamp":"2025-01-15T14:30:22Z","project_root":"/path/to/project","roles":["api_tester"]}
```

**Structure:**
- `type`: Event type identifier
- `timestamp`: ISO 8601 timestamp
- Additional fields depend on event type

---

## Event Types

### Session Lifecycle

#### `qe.started`

QE session started.

```json
{
  "type": "qe.started",
  "timestamp": "2025-01-15T14:30:22Z",
  "session_id": "qe-20250115-143022",
  "mode": "quick",
  "project_root": "/path/to/project",
  "roles": ["api_tester", "security_tester"]
}
```

#### `qe.completed`

QE session completed successfully.

```json
{
  "type": "qe.completed",
  "timestamp": "2025-01-15T14:31:45Z",
  "session_id": "qe-20250115-143022",
  "verdict": "pass",
  "findings_count": 3,
  "duration_seconds": 83.5,
  "tests_generated": 2,
  "patches_generated": 1
}
```

**Verdicts:**
- `pass`: No critical findings
- `warning`: Medium/low severity findings
- `fail`: Critical/high severity findings

#### `qe.failed`

QE session failed with error.

```json
{
  "type": "qe.failed",
  "timestamp": "2025-01-15T14:32:10Z",
  "session_id": "qe-20250115-143022",
  "error": "Timeout after 60 seconds",
  "duration_seconds": 60.0
}
```

---

### Turn/Phase Events

#### `turn.started`

A new turn/phase started.

```json
{
  "type": "turn.started",
  "timestamp": "2025-01-15T14:30:25Z",
  "turn_number": 1,
  "phase": "test_execution"
}
```

#### `turn.completed`

Turn/phase completed.

```json
{
  "type": "turn.completed",
  "timestamp": "2025-01-15T14:30:45Z",
  "turn_number": 1,
  "phase": "test_execution",
  "duration_seconds": 20.5
}
```

---

### Test Events

#### `test.suite.started`

Test suite execution started.

```json
{
  "type": "test.suite.started",
  "timestamp": "2025-01-15T14:30:30Z",
  "suite": "smoke",
  "test_count": 15
}
```

**Suite types:**
- `smoke`: Smoke tests
- `sanity`: Sanity tests
- `regression`: Regression tests

#### `test.suite.completed`

Test suite completed.

```json
{
  "type": "test.suite.completed",
  "timestamp": "2025-01-15T14:30:50Z",
  "suite": "smoke",
  "passed": 14,
  "failed": 1,
  "skipped": 0,
  "duration_seconds": 20.0
}
```

#### `test.started`

Individual test started.

```json
{
  "type": "test.started",
  "timestamp": "2025-01-15T14:30:35Z",
  "name": "test_user_authentication",
  "suite": "smoke"
}
```

#### `test.completed`

Test passed.

```json
{
  "type": "test.completed",
  "timestamp": "2025-01-15T14:30:36Z",
  "name": "test_user_authentication",
  "status": "passed",
  "duration_seconds": 1.2
}
```

#### `test.failed`

Test failed.

```json
{
  "type": "test.failed",
  "timestamp": "2025-01-15T14:30:38Z",
  "name": "test_payment_processing",
  "status": "failed",
  "duration_seconds": 0.8,
  "message": "AssertionError: Payment failed"
}
```

#### `test.skipped`

Test skipped.

```json
{
  "type": "test.skipped",
  "timestamp": "2025-01-15T14:30:40Z",
  "name": "test_integration_api",
  "status": "skipped",
  "message": "Integration API not available"
}
```

---

### Finding Events

#### `finding.detected`

Quality finding detected.

```json
{
  "type": "finding.detected",
  "timestamp": "2025-01-15T14:31:00Z",
  "id": "F001",
  "severity": "high",
  "priority": 1,
  "title": "SQL Injection Vulnerability",
  "location": "src/api/users.py:42",
  "confidence_score": 0.95,
  "category": "security",
  "found_by": "security_tester"
}
```

**Severities:**
- `critical`: Immediate security or data loss risk
- `high`: Significant security or correctness issue
- `medium`: Moderate issue requiring attention
- `low`: Minor issue or code quality concern
- `info`: Informational finding

#### `finding.updated`

Finding updated (e.g., merged duplicates).

```json
{
  "type": "finding.updated",
  "timestamp": "2025-01-15T14:31:05Z",
  "id": "F001",
  "severity": "high",
  "merged_with": ["F002"],
  "confidence_score": 0.98
}
```

---

### Artifact Events

#### `artifact.generated`

Artifact generated.

```json
{
  "type": "artifact.generated",
  "timestamp": "2025-01-15T14:31:40Z",
  "artifact_type": "qr",
  "filename": "qr-20250115-143022.json",
  "description": "Quality Report"
}
```

**Artifact types:**
- `qr`: Quality Report
- `patch`: Unified diff patch
- `test`: Generated test file
- `log`: Session log

#### `patch.created`

Patch file created.

```json
{
  "type": "patch.created",
  "timestamp": "2025-01-15T14:31:30Z",
  "patch_id": "patch-001",
  "filename": "fix-sql-injection.patch",
  "target_file": "src/api/users.py",
  "lines_added": 5,
  "lines_removed": 3
}
```

#### `test.generated`

Test file generated.

```json
{
  "type": "test.generated",
  "timestamp": "2025-01-15T14:31:35Z",
  "test_id": "test-001",
  "filename": "test_sql_injection_fix.py",
  "test_type": "unit",
  "target_file": "src/api/users.py"
}
```

---

### Agent Events

#### `agent.started`

QE agent started.

```json
{
  "type": "agent.started",
  "timestamp": "2025-01-15T14:31:10Z",
  "agent_id": "agent-001",
  "role": "security_tester",
  "model": "gpt-4"
}
```

#### `agent.completed`

QE agent completed.

```json
{
  "type": "agent.completed",
  "timestamp": "2025-01-15T14:31:35Z",
  "agent_id": "agent-001",
  "role": "security_tester",
  "findings_count": 3,
  "duration_seconds": 25.0
}
```

#### `agent.failed`

QE agent failed.

```json
{
  "type": "agent.failed",
  "timestamp": "2025-01-15T14:31:20Z",
  "agent_id": "agent-001",
  "role": "security_tester",
  "error": "Model timeout"
}
```

---

### Workspace Events

#### `workspace.snapshot`

Workspace snapshot created.

```json
{
  "type": "workspace.snapshot",
  "timestamp": "2025-01-15T14:30:22Z",
  "session_id": "qe-20250115-143022",
  "files_count": 142,
  "snapshot_type": "full"
}
```

#### `workspace.reverted`

Workspace reverted to original state.

```json
{
  "type": "workspace.reverted",
  "timestamp": "2025-01-15T14:31:45Z",
  "session_id": "qe-20250115-143022",
  "files_restored": 12,
  "files_deleted": 2
}
```

#### `workspace.change`

File change detected in workspace.

```json
{
  "type": "workspace.change",
  "timestamp": "2025-01-15T14:31:15Z",
  "file_path": "src/api/users.py",
  "change_type": "modified"
}
```

---

### Git Events

#### `git.blocked`

Git operation blocked by Git Guard.

```json
{
  "type": "git.blocked",
  "timestamp": "2025-01-15T14:31:12Z",
  "command": "git commit -m 'test'",
  "reason": "Commits would permanently alter the repository history"
}
```

---

### Progress Events

#### `progress`

Progress update.

```json
{
  "type": "progress",
  "timestamp": "2025-01-15T14:31:00Z",
  "phase": "agent_analysis",
  "current": 2,
  "total": 5,
  "percentage": 40.0,
  "message": "Running security_tester agent"
}
```

#### `message`

Log message event.

```json
{
  "type": "message",
  "timestamp": "2025-01-15T14:31:05Z",
  "level": "info",
  "message": "Completed smoke test suite",
  "context": {
    "suite": "smoke",
    "tests_run": 15
  }
}
```

**Levels:**
- `debug`: Debug information
- `info`: Informational message
- `warning`: Warning message
- `error`: Error message

---

## Usage

### Basic Streaming

Stream events to stdout:

```bash
superqe run . --jsonl
```

Stream to file:

```bash
superqe run . --jsonl > events.jsonl
```

### Programmatic Usage

```python
from superqode.superqe.events import QEEventEmitter
import sys

# Stream to stdout
emitter = QEEventEmitter(sys.stdout)

emitter.emit_qe_started(
    session_id="qe-001",
    mode="quick",
    project_root="/path/to/project",
    roles=["api_tester"]
)
```

### Collecting Events

Collect events in memory:

```python
from superqode.superqe.events import QEEventCollector

collector = QEEventCollector()

# Register with emitter
emitter.add_handler(collector.collect)

# After QE session
findings = collector.get_findings()
tests = collector.get_tests()
summary = collector.get_summary()

# Export to JSONL
jsonl_data = collector.to_jsonl()
collector.save(Path("events.jsonl"))
```

### Event Handlers

Register custom event handlers:

```python
def handle_finding(event: QEEvent):
    if event.type == "finding.detected":
        finding = event.data
        if finding["severity"] == "critical":
            send_alert(finding)

emitter.add_handler(handle_finding)
```

---

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run SuperQode
  run: |
    superqe run . --jsonl > qe-events.jsonl

- name: Parse Results
  run: |
    # Count critical findings
    critical_count=$(jq -r 'select(.type=="finding.detected" and .severity=="critical") | .id' qe-events.jsonl | wc -l)
    if [ "$critical_count" -gt 0 ]; then
      echo "[INCORRECT] Found $critical_count critical findings"
      exit 1
    fi
```

### GitLab CI

```yaml
qe:
  script:
    - superqe run . --jsonl > qe-events.jsonl
    - |
      # Parse findings
      jq -r 'select(.type=="finding.detected") | "\(.severity): \(.title)"' qe-events.jsonl
  artifacts:
    paths:
      - qe-events.jsonl
```

### Jenkins

```groovy
stage('Quality Engineering') {
    sh 'superqe run . --jsonl > qe-events.jsonl'

    def events = readJSON file: 'qe-events.jsonl'
    def findings = events.findAll { it.type == 'finding.detected' }

    if (findings.any { it.severity == 'critical' }) {
        error('Critical findings detected')
    }
}
```

---

## Parsing Events

### Python

```python
import json
from pathlib import Path

def parse_events(jsonl_path: Path):
    findings = []
    tests = []

    with open(jsonl_path) as f:
        for line in f:
            event = json.loads(line)

            if event["type"] == "finding.detected":
                findings.append(event)
            elif event["type"] in ["test.completed", "test.failed"]:
                tests.append(event)

    return findings, tests
```

### JavaScript/Node.js

```javascript
const fs = require('fs');

function parseEvents(jsonlPath) {
    const events = fs.readFileSync(jsonlPath, 'utf-8')
        .split('\n')
        .filter(line => line.trim())
        .map(line => JSON.parse(line));

    const findings = events.filter(e => e.type === 'finding.detected');
    const tests = events.filter(e =>
        ['test.completed', 'test.failed'].includes(e.type)
    );

    return { findings, tests };
}
```

### jq (Command-line)

```bash
# Get all critical findings
jq -r 'select(.type=="finding.detected" and .severity=="critical")' events.jsonl

# Get test summary
jq -r 'select(.type=="test.suite.completed") | "\(.suite): \(.passed)/\(.total) passed"' events.jsonl

# Get session summary
jq -r 'select(.type=="qe.completed") | "Verdict: \(.verdict), Findings: \(.findings_count)"' events.jsonl
```

---

## Best Practices

### 1. Filter by Event Type

Only process relevant events:

```python
relevant_types = {
    "finding.detected",
    "test.failed",
    "qe.completed"
}

for event in events:
    if event["type"] in relevant_types:
        process(event)
```

### 2. Handle Timestamps

Parse ISO 8601 timestamps:

```python
from datetime import datetime

timestamp = datetime.fromisoformat(event["timestamp"].replace('Z', '+00:00'))
```

### 3. Aggregate Results

Build summary from events:

```python
def summarize_events(events):
    summary = {
        "findings": {"critical": 0, "high": 0, "medium": 0},
        "tests": {"passed": 0, "failed": 0, "total": 0},
        "duration": 0
    }

    for event in events:
        if event["type"] == "finding.detected":
            severity = event["severity"]
            summary["findings"][severity] = summary["findings"].get(severity, 0) + 1
        elif event["type"] == "test.completed":
            summary["tests"]["passed"] += 1
            summary["tests"]["total"] += 1
        elif event["type"] == "qe.completed":
            summary["duration"] = event["duration_seconds"]

    return summary
```

---

## Event Flow Example

Typical event sequence for a QE session:

```
qe.started
  ├─ workspace.snapshot
  ├─ test.suite.started (smoke)
  │   ├─ test.started
  │   ├─ test.completed
  │   └─ test.suite.completed
  ├─ turn.started (agent_analysis)
  │   ├─ agent.started
  │   ├─ finding.detected (multiple)
  │   └─ agent.completed
  ├─ artifact.generated (patches)
  ├─ workspace.reverted
  └─ qe.completed
```

---

## Global Event Emitter

Access the global event emitter:

```python
from superqode.superqe.events import (
    get_event_emitter,
    set_event_emitter,
    emit_event,
    EventType
)

# Set custom emitter
emitter = QEEventEmitter(custom_output)
set_event_emitter(emitter)

# Emit event globally
emit_event(EventType.FINDING_DETECTED, id="F001", severity="high", ...)
```

---

## Troubleshooting

### Events Not Appearing

1. Check emitter is enabled:
   ```python
   emitter = QEEventEmitter(enabled=True)
   ```

2. Verify output stream:
   ```python
   emitter = QEEventEmitter(sys.stdout)  # Or file handle
   ```

### Parsing Errors

Ensure valid JSONL format:

```bash
# Validate JSONL
while IFS= read -r line; do
    echo "$line" | jq . > /dev/null || echo "Invalid JSON: $line"
done < events.jsonl
```

---

## Next Steps

- [Python SDK](python-sdk.md) - Programmatic API access
- [CI/CD Integration](../integration/cicd.md) - CI/CD workflows
- [QE Commands](../cli-reference/qe-commands.md) - CLI options
