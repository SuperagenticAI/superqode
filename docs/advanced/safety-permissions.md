<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Safety & Permissions

SuperQode implements a comprehensive safety model to ensure secure operation while allowing agents to perform effective quality engineering. This document describes the security architecture, permission system, and safety guarantees.

---

## Overview

SuperQode's safety model is built on these principles:

1. **Sandbox-First** - All testing happens in isolated environments
2. **Least Privilege** - Agents only get permissions they need
3. **Human-in-the-Loop** - Dangerous operations require approval
4. **Revert Guarantee** - Original code is always preserved
5. **Audit Trail** - All actions are logged and traceable

---

## Permission Levels

SuperQode defines four permission levels for tool operations:

| Level | Description | Approval Required |
|-------|-------------|-------------------|
| **Safe** | Read-only operations | No |
| **Moderate** | Limited modifications in sandbox | No |
| **Dangerous** | Significant changes or external access | Yes |
| **Blocked** | Never allowed | N/A |

### Safe Operations

Operations that cannot cause harm:

- Reading files
- Searching code
- Listing directories
- Viewing git history
- Running linters (read-only)

### Moderate Operations

Operations limited to the sandbox:

- Editing files (in workspace)
- Creating new files (in workspace)
- Running tests
- Installing dev dependencies

### Dangerous Operations

Operations requiring explicit approval:

- Executing shell commands
- Network requests to external URLs
- Modifying configuration files
- Git operations (commit, push)
- Package installation
- System file access

### Blocked Operations

Operations that are never allowed:

- Accessing credentials/secrets
- Modifying files outside workspace
- Executing as root/admin
- Network access to internal services
- Deleting critical system files

---

## Permission Rules Engine

The permission rules engine (`permissions/rules.py`) evaluates each tool call:

```
Tool Call Request
       │
       ▼
┌──────────────────┐
│ Permission Rules │
│     Engine       │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
 Allowed   Requires
           Approval
              │
              ▼
       ┌──────────────┐
       │ User Prompt  │
       │  (Y/N/Always)│
       └──────────────┘
```

### Rule Configuration

Permission rules can be configured in `superqode.yaml`:

```yaml
permissions:
  # Default permission level
  default_level: moderate

  # Tool-specific overrides
  tools:
    shell:
      level: dangerous
      require_approval: true
      allowed_commands:
        - pytest
        - npm test
        - cargo test
      blocked_commands:
        - rm -rf
        - sudo
        - curl | bash

    file_write:
      level: moderate
      allowed_paths:
        - "**/*.py"
        - "**/*.js"
        - "**/*.ts"
      blocked_paths:
        - ".env*"
        - "**/*.pem"
        - "**/*.key"

    network:
      level: dangerous
      allowed_domains:
        - github.com
        - pypi.org
      blocked_domains:
        - localhost
        - "*.internal"
```

---

## Dangerous Operation Detection

The danger detection system (`danger.py`) identifies potentially harmful operations:

### Detection Categories

| Category | Examples | Action |
|----------|----------|--------|
| **Destructive Commands** | `rm -rf`, `git reset --hard` | Block or warn |
| **Credential Access** | Reading `.env`, `credentials.json` | Block |
| **System Modification** | `/etc/`, `/usr/` access | Block |
| **Network Exfiltration** | POST to unknown domains | Require approval |
| **Privilege Escalation** | `sudo`, `chmod 777` | Block |

### Detection Rules

```python
# Example danger patterns
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",           # Recursive delete from root
    r"sudo\s+",                 # Privilege escalation
    r">\s*/etc/",               # Write to system config
    r"curl.*\|\s*bash",         # Pipe to shell
    r"chmod\s+777",             # World-writable
    r"eval\s*\(",               # Dynamic code execution
]
```

---

## Approval Workflow

When a dangerous operation is detected, SuperQode prompts for approval:

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠️  Dangerous Operation Detected                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Tool: shell                                                 │
│  Command: npm install axios                                  │
│  Reason: Package installation may modify dependencies       │
│                                                              │
│  [Y] Allow once                                             │
│  [A] Always allow for this session                          │
│  [N] Deny                                                    │
│  [?] Show more details                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Approval Options

| Option | Effect | Scope |
|--------|--------|-------|
| **Y (Yes)** | Allow this specific operation | Once |
| **A (Always)** | Allow similar operations | Session |
| **N (No)** | Deny and continue | Once |
| **! (Abort)** | Stop QE session | Immediate |

### Approval Memory

Approved operations are remembered for the session:

```yaml
# Session approval state
approvals:
  shell:
    - pattern: "npm test"
      approved: true
    - pattern: "pytest"
      approved: true
  file_write:
    - pattern: "tests/**/*.py"
      approved: true
```

---

## Sandbox Isolation

The sandbox system (`safety/sandbox.py`) provides isolation:

### Isolation Mechanisms

| Mechanism | Description | Use Case |
|-----------|-------------|----------|
| **Git Worktree** | Separate git working directory | Optional for git repos |
| **File Snapshot** | Copy of files to temp directory | Non-git directories |
| **Docker Container** | Full container isolation | CI/CD environments |

### Sandbox Guarantees

1. **File Isolation** - Changes only affect the sandbox copy
2. **Git Protection** - Cannot commit/push from sandbox
3. **Process Isolation** - Subprocesses inherit restrictions
4. **Network Isolation** - Optional network restrictions

### Sandbox Configuration

```yaml
sandbox:
  # Isolation mode: worktree, snapshot
  mode: snapshot

  # Preserve sandbox on error for debugging
  preserve_on_error: false

  # Network restrictions
  network:
    enabled: true
    allow_localhost: true
    allowed_hosts:
      - "*.github.com"
      - "*.pypi.org"
```

---

## Safety Warnings

The warning system (`safety/warnings.py`) alerts users to potential issues:

### Warning Levels

| Level | Display | Action |
|-------|---------|--------|
| **Info** | Blue message | Continue |
| **Warning** | Yellow banner | Continue with notice |
| **Critical** | Red blocking dialog | Require acknowledgment |

### Common Warnings

- **Large File Changes** - Modifying files over 1000 lines
- **Binary Files** - Attempting to edit binary files
- **Test Failures** - Tests failing after modifications
- **Resource Usage** - High memory/CPU consumption
- **Long Running** - Session exceeding time limits

---

## Audit Trail

All operations are logged for audit:

```json
{
  "timestamp": "2024-01-15T10:30:45Z",
  "session_id": "qe-abc123",
  "operation": "shell",
  "command": "pytest tests/",
  "permission_level": "moderate",
  "approved": true,
  "approved_by": "auto",
  "duration_ms": 1234,
  "result": "success"
}
```

### Audit Log Location

```
.superqode/
├── audit/
│   ├── session-abc123.jsonl
│   └── session-def456.jsonl
└── qe-artifacts/
```

---

## Best Practices

### For Users

1. **Review Approvals** - Don't blindly approve all operations
2. **Use Quick Mode First** - Start with limited scope
3. **Check Artifacts** - Review suggested changes before applying
4. **Set Allowed Lists** - Configure allowed commands/paths

### For CI/CD

1. **Use worktree isolation** - Full isolation in pipelines
2. **Disable Approvals** - Use `--no-interactive` with pre-approved lists
3. **Set Time Limits** - Prevent runaway sessions
4. **Audit Logs** - Archive audit trails for compliance

### Configuration Example

```yaml
# Production-safe configuration
permissions:
  default_level: moderate

  tools:
    shell:
      require_approval: true
      allowed_commands:
        - pytest
        - npm test
        - cargo test
        - go test
      blocked_patterns:
        - "rm -rf"
        - "curl | bash"
        - sudo

    file_write:
      blocked_paths:
        - ".env*"
        - "*.pem"
        - "*.key"
        - "secrets/**"

sandbox:
  mode: worktree
  network:
    enabled: true
    allowed_hosts:
      - "github.com"
      - "pypi.org"
```

---

## Related Documentation

- [Architecture Overview](architecture.md) - System architecture
- [Workspace Internals](workspace-internals.md) - Isolation details
- [Configuration Reference](../configuration/yaml-reference.md) - Full config options
