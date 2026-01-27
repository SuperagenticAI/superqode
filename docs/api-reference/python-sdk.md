<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Python SDK Reference

Programmatic API for SuperQode, enabling integration into Python applications, scripts, and CI/CD pipelines.

---

## Overview

The SuperQode Python SDK provides high-level interfaces for:

- **QE Orchestration**: Run Quick Scan and Deep QE sessions
- **Session Management**: Create, manage, and monitor QE sessions
- **Workspace Control**: Manage ephemeral workspaces and snapshots
- **Event Handling**: Subscribe to JSONL events
- **Result Processing**: Access findings, test results, and artifacts

---

## Installation

The SDK is included with SuperQode:

```bash
pip install superqode
```

Import the SDK:

```python
from superqode.superqe import QEOrchestrator, QESession, QESessionConfig
from superqode.workspace import WorkspaceManager, GitWorktreeManager
```

---

## QE Orchestrator

High-level interface for running QE sessions.

### Basic Usage

```python
from pathlib import Path
from superqode.superqe import QEOrchestrator

# Initialize orchestrator
orchestrator = QEOrchestrator(
    project_root=Path("."),
    verbose=True,
    output_format="rich",  # or "json", "jsonl", "plain"
    use_worktree=False,
    allow_suggestions=False
)

# Quick Scan
result = await orchestrator.quick_scan()

# Deep QE
result = await orchestrator.deep_qe()

# Run specific roles
result = await orchestrator.run_roles(["api_tester", "security_tester"])
```

### Quick Scan

Time-boxed, shallow analysis:

```python
result = await orchestrator.quick_scan(
    on_progress=lambda msg: print(f"Progress: {msg}")
)

print(f"Verdict: {result.verdict}")
print(f"Findings: {len(result.findings)}")
print(f"Duration: {result.duration_seconds:.1f}s")
```

**Characteristics:**
- Fast (60 seconds default)
- Shallow exploration
- High-risk paths only
- Minimal QR

**Best for:** Pre-commit, developer laptop, fast CI feedback

### Deep QE

Comprehensive analysis:

```python
result = await orchestrator.deep_qe(
    on_progress=lambda msg: print(f"Progress: {msg}")
)

# Access detailed results
for finding in result.findings:
    print(f"{finding['severity']}: {finding['title']}")
    print(f"  Location: {finding['file_path']}:{finding.get('line_number')}")
```

**Characteristics:**
- Full sandbox
- Destructive testing allowed
- Comprehensive QR
- Multi-agent analysis

**Best for:** Pre-release, nightly CI, compliance evidence

### Custom Configuration

```python
from superqode.superqe import QESessionConfig, QEMode

config = QESessionConfig(
    mode=QEMode.QUICK_SCAN,
    timeout_seconds=120,
    run_smoke=True,
    run_sanity=True,
    run_regression=False,
    run_agent_analysis=True,
    agent_roles=["security_tester", "api_tester"],
    generate_patches=True,
    generate_tests=True,
    generate_qr=True,
    verbose=True
)

result = await orchestrator.run(config)
```

### Running Specific Roles

```python
result = await orchestrator.run_roles(
    role_names=["api_tester", "security_tester"],
    on_progress=lambda msg: print(msg)
)

# Access aggregated results
print(f"Total findings: {len(result.findings)}")
print(f"Tests: {result.tests_passed}/{result.total_tests} passed")
```

---

## QE Session

Lower-level session management for fine-grained control.

### Session Lifecycle

```python
from superqode.superqe import QESession, QESessionConfig, QEMode

config = QESessionConfig(
    mode=QEMode.DEEP_QE,
    timeout_seconds=300,
    run_agent_analysis=True,
    agent_roles=["security_tester"]
)

session = QESession(
    project_root=Path("."),
    config=config
)

# Run session
result = await session.run()

# Access session ID
print(f"Session ID: {session.session_id}")

# Access result
print(f"Status: {result.status}")
print(f"Verdict: {result.verdict}")
```

### Session Result

`QESessionResult` provides comprehensive session data:

```python
result: QESessionResult

# Basic info
result.session_id
result.mode  # QEMode.QUICK_SCAN or QEMode.DEEP_QE
result.status  # QEStatus enum
result.verdict  # "pass", "warning", "fail"
result.duration_seconds

# Test results
result.total_tests
result.tests_passed
result.tests_failed
result.tests_skipped
result.smoke_result  # TestSuiteResult
result.sanity_result  # TestSuiteResult
result.regression_result  # TestSuiteResult

# Findings
result.findings  # List[Dict[str, Any]]

# Artifacts
result.patches_generated
result.tests_generated
result.qr_path  # Path to QR JSON

# Errors
result.errors  # List[str]

# Suggestions (if allow_suggestions enabled)
result.verified_fixes  # List[Dict[str, Any]]
result.allow_suggestions_enabled
```

### Accessing Test Results

```python
# Smoke tests
if result.smoke_result:
    smoke = result.smoke_result
    print(f"Smoke: {smoke.passed}/{smoke.total_tests} passed")

# Sanity tests
if result.sanity_result:
    sanity = result.sanity_result
    print(f"Sanity: {sanity.passed}/{sanity.total_tests} passed")

# Regression tests
if result.regression_result:
    regression = result.regression_result
    print(f"Regression: {regression.passed}/{regression.total_tests} passed")
```

### Accessing Findings

```python
for finding in result.findings:
    print(f"ID: {finding['id']}")
    print(f"Severity: {finding['severity']}")
    print(f"Title: {finding['title']}")
    print(f"Description: {finding.get('description')}")
    print(f"Location: {finding.get('file_path')}:{finding.get('line_number')}")
    print(f"Confidence: {finding.get('confidence', 1.0)}")

    # Suggested fix (if available)
    if finding.get('suggested_fix'):
        print(f"Fix: {finding['suggested_fix']}")

    # Agent info
    if finding.get('agent'):
        print(f"Found by: {finding['agent']}")

    # Tool calls (if available)
    if finding.get('tool_calls'):
        print(f"Tools: {', '.join(finding['tool_calls'])}")
```

---

## Workspace Management

### Workspace Manager

Manage ephemeral workspaces:

```python
from superqode.workspace import WorkspaceManager, WorkspaceState

manager = WorkspaceManager(project_root=Path("."))

# Initialize workspace
manager.initialize()

# Start session
session_id = manager.start_session()

# Check state
print(f"State: {manager.state}")  # WorkspaceState enum
print(f"Active: {manager.is_active}")

# Add findings
manager.add_finding(
    severity="high",
    title="Security issue",
    description="Potential SQL injection",
    file_path="src/api/users.py",
    line_number=42
)

# End session (reverts changes, generates QR)
ws_result = manager.end_session(generate_qr=True)
print(f"Patches: {ws_result.patches_generated}")
print(f"Tests: {ws_result.tests_generated}")
```

### Git Worktree Manager

Create isolated worktrees:

```python
from superqode.workspace import GitWorktreeManager

worktree_manager = GitWorktreeManager(project_root=Path("."))

# Create QE worktree
worktree = await worktree_manager.create_qe_worktree(
    session_id="qe-20250115",
    base_ref="HEAD",
    copy_uncommitted=True,
    keep_gitignored=True
)

print(f"Worktree path: {worktree.path}")
print(f"Base commit: {worktree.base_commit}")

# ... run QE in worktree ...

# Remove worktree
await worktree_manager.remove_worktree(worktree)
```

### Git Snapshot Manager

Create and restore snapshots:

```python
from superqode.workspace import GitSnapshotManager

snapshot_manager = GitSnapshotManager(project_root=Path("."))

# Create snapshot
snapshot_id = await snapshot_manager.create_snapshot(
    message="Before QE session"
)

# ... modify files ...

# Get changes
changes = await snapshot_manager.get_changes(snapshot_id)
for change in changes:
    print(f"{change.status}: {change.path}")

# Restore snapshot
await snapshot_manager.restore_snapshot(snapshot_id)
```

---

## Event Handling

### Event Emitter

Subscribe to JSONL events:

```python
from superqode.superqe.events import QEEventEmitter, EventType
import sys

emitter = QEEventEmitter(sys.stdout)

# Custom handler
def handle_finding(event):
    if event.type == EventType.FINDING_DETECTED.value:
        finding = event.data
        if finding["severity"] == "critical":
            send_alert(finding)

emitter.add_handler(handle_finding)

# Use with orchestrator
# Events will be emitted automatically during QE sessions
```

### Event Collector

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

# Export
jsonl_data = collector.to_jsonl()
collector.save(Path("events.jsonl"))
```

---

## Example: Custom CI Script

```python
import asyncio
from pathlib import Path
from superqode.superqe import QEOrchestrator

async def run_qe_in_ci():
    orchestrator = QEOrchestrator(
        project_root=Path("."),
        verbose=False,
        output_format="plain"
    )

    # Run quick scan
    result = await orchestrator.quick_scan()

    # Check verdict
    if result.verdict == "fail":
        critical = [f for f in result.findings if f["severity"] == "critical"]
        if critical:
            print(f"[INCORRECT] Found {len(critical)} critical findings")
            for f in critical:
                print(f"  - {f['title']} ({f['file_path']})")
            exit(1)

    # Check test failures
    if result.tests_failed > 0:
        print(f"[INCORRECT] {result.tests_failed} tests failed")
        exit(1)

    print("[CORRECT] All checks passed")

if __name__ == "__main__":
    asyncio.run(run_qe_in_ci())
```

---

## Example: Custom QE Workflow

```python
import asyncio
from pathlib import Path
from superqode.superqe import QESession, QESessionConfig, QEMode
from superqode.workspace import GitWorktreeManager

async def custom_qe_workflow():
    project_root = Path(".")

    # Create worktree
    worktree_manager = GitWorktreeManager(project_root)
    worktree = await worktree_manager.create_qe_worktree(
        session_id="custom-qe-001",
        base_ref="HEAD"
    )

    try:
        # Configure session
        config = QESessionConfig(
            mode=QEMode.DEEP_QE,
            run_agent_analysis=True,
            agent_roles=["security_tester"],
            generate_patches=True
        )

        # Run session in worktree
        session = QESession(worktree.path, config)
        result = await session.run()

        # Process results
        for finding in result.findings:
            if finding["severity"] in ["critical", "high"]:
                print(f"WARNING: {finding['severity']}: {finding['title']}")

        # Access QR
        if result.qr_path:
            print(f"QR: {result.qr_path}")

    finally:
        # Cleanup worktree
        await worktree_manager.remove_worktree(worktree)

if __name__ == "__main__":
    asyncio.run(custom_qe_workflow())
```

---

## Example: Event Monitoring

```python
import asyncio
from pathlib import Path
from superqode.superqe import QEOrchestrator
from superqode.superqe.events import QEEventCollector, EventType

async def monitor_qe_session():
    # Create collector
    collector = QEEventCollector()

    # Set up orchestrator with event handler
    orchestrator = QEOrchestrator(Path("."))

    # Register collector (if using global emitter)
    from superqode.superqe.events import get_event_emitter
    emitter = get_event_emitter()
    if emitter:
        emitter.add_handler(collector.collect)

    # Run QE
    result = await orchestrator.quick_scan()

    # Analyze events
    findings = collector.get_findings()
    tests = collector.get_tests()
    summary = collector.get_summary()

    print(f"Events collected: {summary['total_events']}")
    print(f"Findings: {summary['findings']['total']}")
    print(f"Tests: {summary['tests']['total']}")

if __name__ == "__main__":
    asyncio.run(monitor_qe_session())
```

---

## Error Handling

```python
from superqode.superqe import QESession, QEStatus

try:
    session = QESession(Path("."))
    result = await session.run()

    if result.status == QEStatus.FAILED:
        print("QE session failed:")
        for error in result.errors:
            print(f"  - {error}")

    elif result.status == QEStatus.COMPLETED:
        print(f"[CORRECT] Session completed: {result.verdict}")

except Exception as e:
    print(f"Error: {e}")
```

---

## Best Practices

### 1. Use Async/Await

All QE operations are async:

```python
# [CORRECT] Correct
result = await orchestrator.quick_scan()

# [INCORRECT] Incorrect
result = orchestrator.quick_scan()  # Returns coroutine
```

### 2. Handle Errors

Always check result status:

```python
result = await session.run()

if result.status == QEStatus.FAILED:
    handle_failure(result.errors)
elif result.status == QEStatus.COMPLETED:
    process_results(result)
```

### 3. Resource Cleanup

Use context managers or try/finally:

```python
worktree = await worktree_manager.create_qe_worktree(...)
try:
    # ... use worktree ...
finally:
    await worktree_manager.remove_worktree(worktree)
```

### 4. Progress Reporting

Use progress callbacks for long-running operations:

```python
def on_progress(msg: str):
    logger.info(f"QE Progress: {msg}")

result = await orchestrator.deep_qe(on_progress=on_progress)
```

---

## API Reference

### QEOrchestrator

**Methods:**
- `quick_scan(on_progress=None) -> QESessionResult`
- `deep_qe(on_progress=None) -> QESessionResult`
- `run(config, on_progress=None) -> QESessionResult`
- `run_roles(role_names, on_progress=None) -> QESessionResult`

### QESession

**Methods:**
- `run() -> QESessionResult`
- `validate_patches(changes) -> HarnessResult`

**Properties:**
- `session_id: Optional[str]`
- `result: Optional[QESessionResult]`

### QESessionConfig

**Fields:**
- `mode: QEMode`
- `timeout_seconds: int`
- `run_smoke: bool`
- `run_sanity: bool`
- `run_regression: bool`
- `run_agent_analysis: bool`
- `agent_roles: List[str]`
- `generate_patches: bool`
- `generate_tests: bool`
- `generate_qr: bool`
- `verbose: bool`

### WorkspaceManager

**Methods:**
- `initialize() -> None`
- `start_session(config) -> str`
- `end_session(generate_qr=True) -> WorkspaceResult`
- `add_finding(...) -> None`
- `get_findings() -> List[Finding]`

---

## Next Steps

- [JSONL Events](jsonl-events.md) - Event streaming API
- [Workspace Concepts](../concepts/workspace.md) - Workspace details
- [QE Modes](../concepts/modes.md) - Quick Scan vs Deep QE
