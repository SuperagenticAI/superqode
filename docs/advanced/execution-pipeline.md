<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode Banner" />

# Execution Pipeline

This document explains how SuperQode executes QE sessions, from receiving a user request to generating the final Quality Report.

---

## Overview

The execution pipeline orchestrates the entire QE session lifecycle:

```
┌─────────────────────────────────────────────────────────────┐
│                    EXECUTION PIPELINE                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  User Request                                                │
│       │                                                      │
│       ▼                                                      │
│  ┌─────────────┐                                            │
│  │ Request Parse│ ─── Parse options, extract targets        │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │  Resolver   │ ─── Select roles, resolve configuration    │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │  Workspace  │ ─── Create isolated environment            │
│  │   Setup     │                                            │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │   Runner    │ ─── Execute agent loop with tools          │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │  Verifier   │ ─── Verify findings, filter noise          │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │ QR Generator│ ─── Generate Quality Report                │
│  └──────┬──────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │  Cleanup    │ ─── Revert changes, store artifacts        │
│  └─────────────┘                                            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

### 1. Request Parsing

The request parser interprets CLI options and config:

**Input Examples:**
```bash
superqe run . --mode quick -r security_tester
superqe run src/ -r api_tester -r unit_tester
superqe run . --mode deep
```

**Parser Output:**
```python
ParsedRequest(
    target_path=".",
    mode="quick",
    roles=["security_tester"],
    options={
        "generate_tests": False,
        "allow_suggestions": False,
        "timeout": 60
    }
)
```

### 2. Resolution

The resolver (`execution/resolver.py`) resolves roles and configuration:

| Resolution Step | Description |
|-----------------|-------------|
| **Role Lookup** | Find role definitions from registry |
| **Provider Selection** | Choose BYOK/ACP/Local provider |
| **Config Merge** | Merge project + user + CLI config |
| **Validation** | Validate all settings |

**Output:**
```python
ResolvedExecution(
    roles=[RoleDefinition(...)],
    provider=ProviderConfig(...),
    workspace_mode="worktree",
    timeout=60,
    harness=HarnessConfig(...)
)
```

### 3. Workspace Setup

The workspace manager creates an isolated environment:

```python
# Workspace creation
workspace = workspace_manager.create(
    source_path="/path/to/project",
    mode="worktree"
)

# Enter workspace context
with workspace.activate():
    # All operations happen in isolated workspace
    run_qe_session()
# Automatic cleanup on exit
```

**Setup Steps:**
1. Create worktree/snapshot
2. Install git guard hooks
3. Initialize diff tracker
4. Set up file watcher

### 4. Execution Runner

The runner (`execution/runner.py`) executes the QE session:

```
For each role in roles:
    │
    ├──► Load role prompts
    │
    ├──► Connect to provider
    │
    ├──► Start agent loop
    │       │
    │       ├──► Send system prompt
    │       │
    │       ├──► Process tool calls
    │       │       │
    │       │       ├──► Validate permissions
    │       │       │
    │       │       ├──► Execute tool
    │       │       │
    │       │       └──► Return result
    │       │
    │       └──► Continue until complete
    │
    └──► Collect findings
```

### 5. Execution Modes

Two execution modes are available (`execution/modes.py`):

| Mode | Timeout | Depth | Features |
|------|---------|-------|----------|
| **Quick** | 60s | Surface scan | Fast feedback, pre-commit |
| **Deep** | 30min | Full analysis | Test generation, fix suggestions |

**Quick Mode:**
- Single-pass analysis
- Focus on critical issues
- No test generation
- Minimal tool usage

**Deep Mode:**
- Multiple-pass analysis
- Comprehensive coverage
- Test generation enabled
- Fix suggestions with verification

### 6. Agent Loop

The agent loop (`agent/loop.py`) manages AI interactions:

```python
class AgentLoop:
    async def run(self, prompt: str) -> AgentResult:
        # Send to LLM
        response = await self.provider.chat(
            messages=self.messages,
            tools=self.tools
        )

        # Process tool calls
        while response.has_tool_calls:
            for tool_call in response.tool_calls:
                result = await self.execute_tool(tool_call)
                self.messages.append(tool_result(result))

            response = await self.provider.chat(
                messages=self.messages,
                tools=self.tools
            )

        return AgentResult(response)
```

### 7. Tool Execution

Tools are executed with permission checks:

```
Tool Call
    │
    ▼
Permission Check
    │
    ├──► Allowed ──► Execute ──► Return Result
    │
    ├──► Needs Approval ──► Prompt User ──► Execute/Deny
    │
    └──► Blocked ──► Return Error
```

**Available Tools:**
- `read_file` - Read file contents
- `write_file` - Write/create files
- `edit_file` - Edit existing files
- `search` - Search codebase
- `shell` - Execute commands
- `web_fetch` - Fetch web content

### 8. Verification

The verifier (`superqe/verifier.py`) validates findings:

| Verification Step | Description |
|-------------------|-------------|
| **Reproduce** | Confirm issue can be reproduced |
| **Validate Fix** | If fix suggested, verify it works |
| **Run Tests** | Execute test suite |
| **Check Regression** | Ensure no new issues introduced |

### 9. Noise Filtering

The noise filter (`superqe/noise.py`) removes false positives:

```python
class NoiseFilter:
    def filter(self, findings: list[Finding]) -> list[Finding]:
        filtered = []
        for finding in findings:
            if self.is_valid(finding):
                filtered.append(finding)
        return filtered

    def is_valid(self, finding: Finding) -> bool:
        # Check against known false positive patterns
        # Verify with secondary analysis
        # Apply confidence threshold
        return confidence > 0.7
```

### 10. Report Generation

The QR generator (`qr/generator.py`) creates reports:

**Report Structure:**
```json
{
  "session_id": "qe-abc123",
  "timestamp": "2024-01-15T10:30:45Z",
  "summary": {
    "total_findings": 5,
    "critical": 1,
    "high": 2,
    "medium": 2,
    "low": 0
  },
  "findings": [...],
  "suggested_fixes": [...],
  "generated_tests": [...],
  "execution_log": [...]
}
```

### 11. Cleanup

Cleanup restores the original state:

```python
def cleanup(session: QESession):
    # Save artifacts
    save_artifacts(session.artifacts)

    # Revert workspace changes
    session.workspace.revert()

    # Remove temporary files
    session.workspace.cleanup()

    # Log completion
    log_session_complete(session)
```

---

## Event Streaming

The pipeline emits JSONL events (`superqe/events.py`):

```jsonl
{"event": "session_start", "session_id": "qe-abc123", "timestamp": "..."}
{"event": "role_start", "role": "security_tester", "timestamp": "..."}
{"event": "tool_call", "tool": "read_file", "args": {"path": "..."}, "timestamp": "..."}
{"event": "finding", "severity": "high", "message": "...", "timestamp": "..."}
{"event": "role_complete", "role": "security_tester", "timestamp": "..."}
{"event": "session_complete", "summary": {...}, "timestamp": "..."}
```

---

## Error Handling

The pipeline handles errors gracefully:

| Error Type | Handling |
|------------|----------|
| **Provider Error** | Retry with backoff, fallback provider |
| **Tool Error** | Log error, continue execution |
| **Timeout** | Save partial results, cleanup |
| **Workspace Error** | Attempt recovery, preserve for debug |
| **User Cancel** | Clean shutdown, save artifacts |

```python
try:
    await run_qe_session()
except ProviderError as e:
    await handle_provider_error(e)
except TimeoutError:
    save_partial_results()
finally:
    cleanup_workspace()
```

---

## Configuration

```yaml
execution:
  # Default mode
  default_mode: quick

  # Timeouts
  quick_timeout: 60
  deep_timeout: 1800

  # Parallelism
  max_parallel_roles: 3

  # Retry settings
  max_retries: 3
  retry_delay: 5

  # Event streaming
  emit_events: true
  event_format: jsonl
```

---

## Monitoring

### Session Status

```bash
superqe status

# Output:
# Session: qe-abc123
# Status: running
# Role: security_tester (2/3)
# Duration: 45s
# Findings: 3
```

### Live Events

```bash
superqe run . --jsonl | jq .
```

---

## Related Documentation

- [Architecture Overview](architecture.md) - System architecture
- [Workspace Internals](workspace-internals.md) - Isolation details
- [Tools System](tools-system.md) - Available tools
- [QE Commands](../cli-reference/qe-commands.md) - CLI reference
- [JSONL Events](../api-reference/jsonl-events.md) - Event format
