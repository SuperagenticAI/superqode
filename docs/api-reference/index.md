# API Reference

Programmatic access to SuperQode functionality through Python SDK and JSONL events.

---

## Overview

The SuperQode API provides two main interfaces:

1. **Python SDK**: High-level Python APIs for orchestrating QE sessions
2. **JSONL Events**: Machine-readable event stream for CI/CD integration

---

## Quick Start

### Python SDK

```python
from pathlib import Path
from superqode.superqe import QEOrchestrator

orchestrator = QEOrchestrator(Path("."))
result = await orchestrator.quick_scan()

print(f"Verdict: {result.verdict}")
print(f"Findings: {len(result.findings)}")
```

### JSONL Events

```bash
# Stream events to stdout
superqe run . --jsonl

# Stream to file
superqe run . --jsonl > events.jsonl
```

---

## API Documentation

### [Python SDK](python-sdk.md)

Complete Python API reference:

- **QEOrchestrator**: High-level QE session orchestration
- **QESession**: Lower-level session management
- **WorkspaceManager**: Ephemeral workspace control
- **Event Handling**: Subscribe to QE events

**Use for:**
- Custom Python scripts
- CI/CD integrations
- Automated quality gates
- Programmatic QE workflows

### [JSONL Events](jsonl-events.md)

Event streaming API:

- **Event Types**: Complete event catalog
- **Event Format**: JSON structure and fields
- **CI/CD Integration**: GitHub Actions, GitLab CI, Jenkins
- **Event Parsing**: Python, JavaScript, jq examples

**Use for:**
- CI/CD pipeline integration
- Real-time monitoring
- Custom reporting tools
- Event-driven workflows

---

## Common Use Cases

### CI/CD Quality Gate

```python
from superqode.superqe import QEOrchestrator

orchestrator = QEOrchestrator(Path("."))
result = await orchestrator.quick_scan()

if result.verdict == "fail":
    exit(1)
```

### Custom QE Workflow

```python
from superqode.superqe import QESession, QESessionConfig, QEMode

config = QESessionConfig(
    mode=QEMode.DEEP_QE,
    agent_roles=["security_tester"],
    generate_patches=True
)

session = QESession(Path("."), config)
result = await session.run()
```

### Event Monitoring

```python
from superqode.superqe.events import QEEventCollector

collector = QEEventCollector()
emitter.add_handler(collector.collect)

# After QE
summary = collector.get_summary()
```

---

## Integration Examples

### GitHub Actions

See [JSONL Events - CI/CD Integration](jsonl-events.md#cicd-integration) for complete examples.

### Custom Script

```python
import asyncio
from pathlib import Path
from superqode.superqe import QEOrchestrator

async def main():
    orchestrator = QEOrchestrator(Path("."))
    result = await orchestrator.quick_scan()

    # Process results
    print(f"Verdict: {result.verdict}")
    for finding in result.findings:
        print(f"- {finding['severity']}: {finding['title']}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Related Documentation

- [Concepts](../concepts/index.md) - Core concepts and architecture
- [CLI Reference](../cli-reference/index.md) - Command-line interface
- [Integration](../integration/index.md) - CI/CD and tool integration
