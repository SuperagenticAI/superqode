# Sandbox Commands

Manage sandbox execution providers for isolated agent operations.

---

## sandbox doctor

Show sandbox provider setup status.

```bash
superqode sandbox doctor [backend] [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `backend` | Check a specific backend (checks all if omitted) |

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

Checks CLI availability, SDK installation, and authentication for each sandbox backend. Reports `ready`, `missing`, or `unauthenticated` per backend.

---

## sandbox run

Run a command in a sandbox backend.

```bash
superqode sandbox run <backend> [OPTIONS] -- <command>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `backend` | Sandbox backend identifier |
| `command` | Command to execute (after `--`) |

### Options

| Option | Description |
|--------|-------------|
| `--image` | Container image for backends that support it (e.g., `docker`) |

### Examples

```bash
superqode sandbox run docker --image python:3.12 -- pytest -q
superqode sandbox run e2b -- "pytest -q"
```

---

## --sandbox Global Flag

Use `--sandbox` with headless runs to enforce execution capability profiles:

```bash
superqode -p --sandbox <mode> "task"
```

### Sandbox Modes

| Mode | Description |
|------|-------------|
| `read-only` | No filesystem or shell access |
| `no-shell` | Filesystem access, no shell execution |
| `git-worktree` | Isolated git worktree for side effects |
| `docker` | Local Docker container isolation |
| `e2b` | Remote E2B sandbox |
| `daytona` | Remote Daytona workspace |
| `modal` | Modal cloud sandbox |
| `vercel` | Vercel Sandbox CLI |
| `runloop` | Runloop devbox |
| `agentcore` | AgentCore Code Interpreter |
| `langsmith` | LangSmith sandbox |

`docker` uses the local Docker CLI. `e2b`, `daytona`, `modal`, `runloop`, `agentcore`, and `langsmith` use optional Python SDKs. `vercel` uses the Vercel Sandbox CLI with token or OIDC authentication.
