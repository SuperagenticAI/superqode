# Safety & Permissions

SuperQode implements a comprehensive safety model to ensure secure operation while allowing agents to perform effective tool-based coding tasks. This document describes the security architecture, permission system, and safety guarantees.

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

```text
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

```text
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
| **! (Abort)** | Stop the current session | Immediate |

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
  # Default local-first profile for account-free sandboxing
  profile: local-secure

  # Fallback order for local execution without cloud accounts
  fallback_runtimes:
    - docker
    - podman
    - apple-container
    - local-os

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

## Local-First Sandbox Providers

SuperQode treats account-free local sandboxes as the primary path for agentic
coding. Cloud providers are explicit integrations, not the default.

| Backend | Location | Account | Notes |
|---------|----------|---------|-------|
| `local-os` | local | none | macOS Seatbelt or Linux Bubblewrap command sandbox |
| `docker` | local | none | Recommended local secure default |
| `podman` | local | none | Docker-compatible local alternative, often rootless |
| `apple-container` | local | none | macOS-native container runtime; detected as experimental |
| `e2b` | cloud | required | Popular cloud sandbox integration |
| `daytona` | cloud | required | Popular cloud/dev environment integration |
| `modal` | cloud | required | Popular cloud execution integration |
| `vercel` | cloud | required | Vercel Sandbox CLI integration |

Useful profiles:

| Profile | Fallback order |
|---------|----------------|
| `local-secure` | `docker -> podman -> apple-container -> local-os` |
| `local-fast` | `local-os -> docker -> podman` |
| `cloud-secure` | `e2b -> daytona -> modal -> vercel` |
| `dev` | `local-os -> docker` |

Check the current machine:

```bash
superqode sandbox doctor
superqode sandbox doctor docker
```

Run a one-off command through a provider:

```bash
superqode sandbox run docker pytest -q
superqode sandbox run podman python -V
```

---

## Local Command Sandbox (OS-level)

Beyond the permission gate, SuperQode can confine every shell command using the
operating system's own isolation so that even an auto-approved command cannot
write outside the workspace or reach the network. This is enforced by the OS, not
by string matching.

### Backends

| Platform | Backend | Binary |
|----------|---------|--------|
| macOS | Seatbelt | `sandbox-exec` (built in) |
| Linux | Bubblewrap | `bwrap` |

If no backend is available, commands run unconfined and SuperQode says so.

### Modes

Select a mode with the `SUPERQODE_SANDBOX` environment variable (or the
`:sandbox <mode>` command in the TUI):

| Mode | Filesystem | Network |
|------|-----------|---------|
| `off` *(default)* | unrestricted | unrestricted |
| `workspace-write` | read anywhere, **write only** to the workspace + temp | allowed |
| `read-only` | read anywhere, write only to temp | **denied** |
| `danger-full-access` | unrestricted | unrestricted |

```bash
# Confine writes to the project, keep network for installs
SUPERQODE_SANDBOX=workspace-write superqode

# Strict read-only analysis: no writes, no network
SUPERQODE_SANDBOX=read-only superqode
```

In the TUI, `:sandbox` shows the active mode, backend, and whether a sandbox is
currently applied; `:sandbox workspace-write` switches modes for the session.

---

## Command Safety Classification

Every shell command is classified before it runs, which lets SuperQode auto-run
safe commands (no prompt) while still gating risky ones:

| Class | Examples | Default action |
|-------|----------|----------------|
| **Safe** (read-only) | `ls`, `cat`, `grep`, `git status`, `git diff`, `pip show` | Auto-allow |
| **Write** | `mv`, `mkdir`, `git commit`, `sed -i`, unknown commands | Ask |
| **Network** | `curl`, `git push`, `pip install`, `npm install` | Ask (see allowlist) |
| **Destructive** | `rm -rf`, `sudo`, `dd of=...`, `mkfs`, `curl ... \| sh` | Block |

The classifier is **obfuscation-aware**: commands are canonicalised before
analysis, so `\rm`, `'/bin/rm'`, and `r""m` are still recognised as `rm`, and
dynamic constructs (`$(...)`, backticks, `eval`, pipe-to-shell) can never be
classified Safe.

This is what removes prompt fatigue - you are no longer asked to approve every
`ls` or `git status`, only the operations that actually carry risk.

---

## Network Allowlist Policy

Network commands are checked against a domain allowlist so trusted installs run
without prompts while arbitrary egress is gated:

| Status | Meaning | Default action |
|--------|---------|----------------|
| **Trusted** | every destination is on the allowlist | Auto-allow |
| **Untrusted** | a destination is not on the allowlist | Ask (or deny in strict mode) |
| **Unknown** | no host could be determined (e.g. `git push`) | Ask |

The built-in allowlist covers common registries and source hosts - PyPI, npm,
crates.io, Go/Ruby proxies, GitHub/GitLab/Bitbucket, container registries, and OS
package mirrors. So `pip install requests`, `npm install`, and
`git clone https://github.com/...` run automatically, while `curl https://evil.com`
is gated.

| Environment variable | Effect |
|----------------------|--------|
| `SUPERQODE_NET_ALLOW` | Comma-separated extra domains to trust (e.g. `internal.corp,mirror.local`) |
| `SUPERQODE_NET_STRICT` | When set, untrusted destinations are **denied** instead of prompted |

```bash
# Trust an internal mirror and hard-deny anything else
SUPERQODE_NET_ALLOW=mirror.corp SUPERQODE_NET_STRICT=1 superqode
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
  "session_id": "session-abc123",
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

```text
.superqode/
├── audit/
│   ├── session-abc123.jsonl
│   └── session-def456.jsonl
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

- [Configuration Reference](../configuration/yaml-reference.md) - Full config options
