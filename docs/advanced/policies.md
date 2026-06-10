# Policies & Safety

Four layers decide what the agent may do, evaluated in a fixed order for every tool call. This page shows each layer procedurally: what to write, where to put it, and what happens at runtime.

## Order of authority

```
1. permission_request hooks      (harness policies / plugins — can veto anything)
2. exec-policy rules             (your YAML: allow / deny / ask for shell commands)
3. permission manager            (built-in: dangerous-command guards, tool config)
4. ask flow                      (TUI prompt, or pause in harness runs)
```

Two invariants no layer can break:

- A **hard deny** (dangerous-command guard like `rm -rf`, deny pattern, explicit DENY config) always wins — a permissive hook, rule, or session grant cannot override it.
- A user **`ask`** rule always forces a prompt, even for commands that would auto-allow.

## Exec policy: your allow/deny/ask rules

Write declarative rules for shell commands. Project rules take precedence over user rules:

```yaml
# .superqode/execpolicy.yaml  (project)   or   ~/.superqode/execpolicy.yaml  (user)
rules:
  - pattern: "pytest*"            # glob against the full command
    action: allow                  # skip the prompt
  - pattern: "git push*"
    action: ask                    # always confirm, even if auto-allowed
  - pattern: "re:^rm\\s+-rf\\s+/"  # 're:' prefix = regex
    action: deny
    reason: "refuse rm -rf on absolute paths"
  - pattern: "npm publish*"
    action: deny
    reason: "no publishing from agents"
```

First matching rule decides; no match means no opinion. `SUPERQODE_EXEC_POLICY=<path>` prepends an explicit file (CI, tests). A denied command returns `Command blocked by exec policy: <reason>` to the model.

Try it:

```bash
mkdir -p .superqode
cat > .superqode/execpolicy.yaml <<'EOF'
rules:
  - pattern: "pytest*"
    action: allow
EOF
superqode -p "run the test suite"   # pytest now runs without a prompt
```

## Shell env policy: keep secrets out of spawned commands

By default spawned commands inherit your full environment. Opt in to secret filtering and a prompt-injected `printenv` exfiltrates nothing:

```bash
export SUPERQODE_SHELL_ENV_POLICY=filter-secrets
export SUPERQODE_SHELL_ENV_ALLOW=OPENAI_API_KEY   # exceptions, comma-separated
```

Variables whose names match `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`, `*AUTH*` are dropped from `bash` and `shell_session` children. `SSH_AUTH_SOCK` is always kept (it's a socket path, not a secret).

## `request_permissions`: escalation with consent

When the agent keeps hitting ask-prompts for the same tool, it can make **one explicit, justified request**:

```text
agent → request_permissions(tools=["web_fetch"],
        justification="need to read the upstream changelog for the fix")
you   → approve / decline (normal approval prompt, justification shown)
```

Approval upgrades those tools from ask-each-time to allowed *for this session only*; `:permissions` state resets with the session, and explicit denies remain unbreakable. A declined request tells the model not to retry.

## The built-in permission manager

Configure per-tool and per-group permissions in `superqode.yaml` (see [Safety & Permissions](safety-permissions.md) for the full schema):

```yaml
permissions:
  default: ask
  tools:
    read_file: allow
    bash: ask
  deny_patterns: ["bash:sudo *"]
```

The manager also auto-allows known read-only commands (`ls`, `git status`, …) and trusted-registry network commands when the policy would otherwise prompt — cutting prompt fatigue without weakening safety — and hard-denies dangerous commands regardless of any other setting.

## OS sandbox

With `SUPERQODE_SANDBOX` set, even auto-approved commands are confined by the OS — macOS Seatbelt (`sandbox-exec`) or Linux Bubblewrap (`bwrap`) — so they cannot write outside the project. Harness specs select sandbox modes per run (`execution_policy.sandbox`); `superqode harness doctor` verifies the backend is available.

## Loop-level guards

Two more protections live in the agent loop itself, documented in [Inside the Agent Loop](agent-loop.md):

- the **doom-loop guard** (repeated identical tool calls intercepted, runs that refuse to move on are stopped), and
- **mutation-safe parallelism** (concurrent execution only for all-read-only batches).
