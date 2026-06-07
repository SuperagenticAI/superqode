# Harness System

SuperQode is your portable coding agent harness.

SuperQode separates the harness you configure from the runtime that executes it. The harness defines what a
run is allowed to do, which model policy to use, which tools are available, how approvals work, where events
are stored, and what output should be returned.

---

## What A Harness Gives You

| Capability | What you control |
| --- | --- |
| Runtime | Use `builtin`, Google ADK, OpenAI Agents SDK, DeepAgents, PydanticAI, or another supported backend |
| Model policy | Pick primary models, fallbacks, reasoning, temperature, history, and iteration limits |
| Tools | Enable repository tools, shell, MCP, checks, or no tools |
| Sandbox policy | Set read, write, shell, command, and network boundaries |
| Approvals | Pause risky tool calls for review before they run |
| Events | Store run timelines and graph views for debugging |
| Output | Return plain text, typed results, checks state, and run records |

### What Users Configure

Users configure a harness by selecting:

- flavor: `coding` or `no_tool`
- runtime: `builtin`, `adk`, `openai-agents`, `deepagents`, `pydanticai`, or custom
- model policy: hosted model, local model, Gemma4 profile, DS4 profile, fallbacks, and reasoning defaults
- tools: repository tools, shell, MCP, checks, or no tools
- sandbox policy: read, write, shell, command, and network boundaries
- workflow: single step, chain, parallel workers, router, orchestrator, or evaluator-optimizer
- output: plain text, typed result, events, checks state, and run records

This lets the same harness contract run through different engines while preserving the user-facing behavior.

### Harness Flavors

#### Coding Harness

The coding harness is the current SuperQode strength and should remain the default for repository work.

It gives the model controlled capabilities:

- repository context discovery
- file read/search/edit tools
- shell and test execution under policy
- MCP tools when configured
- checks hooks
- patch/diff reporting
- session memory and compaction
- approval gates for risky operations

Use it when the model must inspect, change, run, or verify code. This is the right flavor for implementation,
debugging, refactoring, CI triage, and multi-agent coding workflows.

#### No-Tool Harness

The no-tool harness is a separate first-class flavor, not just "coding harness with tools disabled."

It bets on model capability alone:

- no file tools
- no shell tools
- no MCP tools
- no write access
- no implicit repo mutation path
- prompt, context, and model policy only
- optional structured output checks
- optional final-answer scoring/evaluation
- reasoning disabled where provider APIs support it

Use it when the task is reasoning, planning, code review from supplied context, design critique, explanation,
spec generation, or when evaluating whether a model can solve a task without tool scaffolding.

This flavor is especially useful for Gemma4 and other strong local models because it makes model capability
measurable without hiding weaknesses behind tool execution.

### Flavor Contract

Both flavors should compile from the same `HarnessSpec` shape:

```yaml
harness:
  flavor: coding  # coding | no_tool
  runtime:
    backend: builtin
  model_policy:
    primary: gemma4-local
    fallback: ds4-local
  execution_policy:
    approval_profile: balanced
  checks:
    enabled: true
```

The compiler decides what capabilities are legal for each flavor:

| Capability | Coding | No-tool |
| --- | --- | --- |
| Model calls | yes | yes |
| Sessions/history | yes | yes |
| Skills/roles | yes | yes |
| Typed outputs | yes | yes |
| File read/search | yes | no |
| File edit/write | policy-controlled | no |
| Shell/tests | policy-controlled | no |
| MCP tools | policy-controlled | no |
| Checks harness | yes | optional, output-only |
| Multi-agent delegation | yes | optional, model-only |

### Runtime Backends

Runtime backends are interchangeable execution adapters behind the same harness contract.

| Backend | Status | Use when |
| --- | --- | --- |
| `builtin` | default | You want the native SuperQode coding loop, local-model tuning, and the full harness policy surface |
| `adk` | optional | You want to run through Google ADK while keeping SuperQode harness configuration |
| `openai-agents` | optional | You want OpenAI Agents SDK behavior, sessions, and tool plumbing |
| `codex-sdk` | optional | You want official OpenAI Codex SDK behavior through SuperQode runtime and HarnessSpec selection |
| `deepagents` | optional | You want DeepAgents graph, middleware, and subagent behavior for tool-capable coding harnesses |
| `pydanticai` | optional | You want PydanticAI behavior with SuperQode tools and HarnessSpec policy |

The `deepagents` backend is intentionally not used for no-tool harnesses. DeepAgents 0.6 is built around a
tool-capable deep-agent stack, so SuperQode rejects no-tool specs for that backend and directs users to the
native runtime for model-only runs.

The `pydanticai` backend supports tool-capable coding specs through SuperQode's JSON-schema tool bridge.
It also maps PydanticAI deferred approvals into the standard harness approval flow, loads native
PydanticAI MCP toolsets from `runtime.config.pydanticai.mcp_config_path`, uses PydanticAI fallback
models from `model_policy.fallbacks`, and can enable Logfire instrumentation through `observability.traces`
or `runtime.config.pydanticai.logfire`. Prefect and DBOS durable wrappers are available through
`runtime.config.pydanticai.durable`; Temporal still requires an explicit workflow and worker.

The `codex-sdk` backend uses the published `openai-codex` Python package. The local
`reference/codex/sdk/python` checkout is reference material only; SuperQode runtime code must not import
or vendor it. `codex-sdk` streams Codex model, command, file-change, MCP, dynamic-tool, patch, and turn events
into SuperQode's normalized harness events, only reports streamed completion after Codex sends
`turn/completed`, and serializes turns per runtime/thread for deterministic cancellation and approval handling.
MCP servers and trust/policy are resolved through the local Codex configuration (`~/.codex`).
In the TUI, Codex approval callbacks are bridged to SuperQode's inline approval prompt. Outside the TUI,
approval callbacks are rejected by default unless an explicit SuperQode `PermissionManager` or runtime approval
callback allows them non-interactively. The TUI also exposes fast `:codex status` diagnostics plus
`:codex status --probe` for auth/model probing, shows the active Codex thread id and `~/.codex/sessions`
directory when available, reuses warm Codex runtimes in the same working directory, uses the live Codex
model list for the picker, and forwards batched Codex tool events through the existing PureMode tool-card callbacks.

### CLI

Harness specs are usable from the command line:

```bash
superqode harness list-templates
superqode harness list-backends
superqode harness init my-coder --template coding --output harness.yaml
superqode harness validate --spec harness.yaml
superqode harness validate --spec harness.yaml --schema
superqode harness inspect --spec harness.yaml
superqode harness compile --spec harness.yaml --json
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

Use `--schema` on `harness validate` to print the HarnessSpec JSON Schema for editor integration and CI
checks.

Use `harness list-backends` to see the backend capability snapshot without loading a spec. It reports coding,
no-tool, streaming, approval, sandbox, shell, MCP, typed-output support, dependency availability, and install
hints for optional backends.

Use `harness inspect` to view the resolved backend, model policy, tools, sandbox policy, workflow, and backend
capability warnings before running a spec. Use `--runtime` and `--sandbox` on `inspect` to check overrides.
Inspection also warns when a backend may not honor model-side constraints such as reasoning effort,
temperature, or max iterations.

Use `harness compile` to dump the loaded HarnessSpec, effective model policy, and compatibility headless
profile after defaults and policy resolution.

Use `harness diff` to compare two specs before replacing a team harness:

```bash
superqode harness diff old-harness.yaml new-harness.yaml
superqode harness diff old-harness.yaml new-harness.yaml --json
```

Use `harness doctor` before sharing or committing a spec. It checks spec loading, backend installation,
backend/spec compatibility, sandbox policy, event-store writability, rich-event graph support, approval
support, and MCP config paths.

The default `builtin` backend supports approval pauses for ASK-permission tool calls. `pydanticai` and
`openai-agents` also support approval pauses through their runtime adapters. Backends that cannot pause for
approval are reported by `harness doctor`.

Use `--runtime`, `--provider`, `--model`, `--session`, `--working-dir`, and `--sandbox` on `harness run` to
override the spec for one run. Use `--stream` to print normalized stream events and `--json` for machine
readable output.

### Event Graph

Every HarnessSpec run writes normalized events and a graph view of the execution. The graph turns runtime
events into typed nodes such as run, model, tool, approval, sandbox, MCP, subagent, checks, and typed
output nodes. Edges preserve execution order and mark pauses, resumes, and tool-style calls.

Use the graph commands after a run:

```bash
superqode harness events <run-id>
superqode harness events <run-id> --json
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

This is the common inspection layer for builtin, OpenAI Agents SDK, Google ADK, DeepAgents, and PydanticAI.
Runtime-specific adapters can emit richer events, but the stored graph stays stable.
The builtin backend records model, tool, result, and approval events. PydanticAI maps `run_stream_events` into
model, tool, result, and approval nodes. OpenAI Agents maps SDK stream events into model, tool, approval, and
sandbox markers. DeepAgents maps graph streams into model, tool, subagent, memory, sandbox, and result nodes.

The interactive TUI can also run through a harness spec:

```bash
superqode --harness harness.yaml
```

Inside the TUI, use:

```text
:harness harness.yaml
:harness status
:harness templates
:harness off
```

After loading a spec, connect a model with `:connect byok` or `:connect local`. TUI prompts then stream through
the loaded `HarnessSpec` while keeping the normal conversation display.

When a harness-backed runtime pauses for tool approval, SuperQode surfaces the pending tool calls in the same
conversation log:

```text
:approve
:approve 1 always
:reject
:reject 1 "use a safer command"
```

The same commands work for direct runtime sessions and `HarnessSpec` sessions. JSON output from
`superqode harness run` includes `stopped_reason` and `pending_approvals` so automation can detect paused runs.

### Model Policy

Model policy is resolved before backend execution. This keeps local-model behavior explicit and portable across
runtimes.

| Profile | Defaults |
| --- | --- |
| `gemma4-coding` | minimal prompt, compact local tool surface, strict JSON tool-call hints, low temperature, sequential tools |
| `gemma4-no-tool` | model-only prompt, no tools, low temperature, short history, reasoning disabled where supported |
| `ds4-coding` | DS4 prompt path, compact tool surface, low temperature, low reasoning, sequential tools |
| `ds4-fast-local` | DS4 coding with tighter iteration and history budgets for fast local loops |

No-tool policy also sets `reasoning=off`. For Anthropic-shape providers such as DS4, this maps to the provider
thinking-disable field. Providers without that capability ignore the setting safely.

### Workflow Modes

The workflow engine lets a harness describe more than one prompt call without replacing the runtime backend.

| Mode | Behavior |
| --- | --- |
| `single` | Run one step |
| `chain` | Run steps sequentially and pass previous output forward |
| `parallel` | Run independent steps concurrently with bounded parallelism |
| `router` | Choose a route by config or by router output |
| `orchestrator` | Run worker steps then synthesize |
| `evaluator_optimizer` | Generate, evaluate, and optionally optimize |

### Run Storage

Harness sessions can use a file store or SQLite store:

- `file`: simple JSON files for local development and easy inspection
- `sqlite`: indexed session, run, and event history for concurrent readers and larger run sets
- `memory`: temporary run storage for tests and short-lived automation

Set the default in `observability.run_store`, or override a single CLI run:

```bash
superqode harness run --spec harness.yaml --store sqlite --prompt "summarize this repository"
```

### Example Specs

Coding harness:

```yaml
harness:
  name: superqode-coder
  flavor: coding
  runtime:
    backend: builtin
  model_policy:
    primary: gpt-4o-mini
    fallbacks: [gemma4-local, ds4-local]
  execution_policy:
    sandbox: local
    allow_read: true
    allow_write: true
    allow_shell: true
    approval_profile: balanced
  agents:
    - id: coder
      tools: [filesystem, search, edit, shell, checks]
      skills: [repo-navigation, implementation]
```

No-tool harness:

```yaml
harness:
  name: superqode-reasoner
  flavor: no_tool
  runtime:
    backend: builtin
  model_policy:
    primary: gemma4-local
    fallbacks: [ds4-local]
    temperature: 0.2
  execution_policy:
    allow_read: false
    allow_write: false
    allow_shell: false
  agents:
    - id: reasoner
      tools: []
      skills: [architecture-review, code-review-from-context]
  output:
    typed: true
```

### Practical Guidance

- Use `coding` with `builtin` for the default repository workflow.
- Use `no_tool` when you want model-only planning, explanation, or review from supplied context.
- Use `doctor` before sharing a spec, especially when it depends on an optional runtime.
- Use `compile` when you want to see the effective policy after defaults are applied.
- Use `diff` before replacing a shared harness so reviewers can see policy, tool, and agent changes.
- Keep DeepAgents for tool-capable coding harnesses; use `builtin` for no-tool specs.

---

## Checks Harness Overview

Checks is a secondary lifecycle capability inside the broader harness system. A coding harness can call
checks after it edits files, produces a patch, or returns structured suggestions.

Checks can check:

- **Syntactic correctness**: Code parses correctly
- **Type safety**: Type checking passes
- **Style compliance**: Linting rules followed
- **No regressions**: Changes don't break existing code

Checks does not define the product identity and does not replace runtime policy. It is an optional proof
step that can be attached to coding, workflow, or typed-output runs.

---

## Checks Types

### Structural Checks

Parsing checks for structured formats:

- **JSON**: Valid JSON syntax
- **YAML**: Valid YAML syntax
- **TOML**: Valid TOML syntax

**Runs on**: All changes to structured files

### Language Checks

Language-specific checks:

- **Python**: mypy, ruff, pyright
- **JavaScript**: eslint, tsc
- **TypeScript**: tsc, eslint
- **Go**: go vet, golangci-lint
- **Rust**: cargo check
- **Shell**: shellcheck

**Runs on**: Code files matching language patterns

---

## Configuration

### YAML Configuration

```yaml
superqode:
  harness:
    checks:
      enabled: true
      timeout_seconds: 30
      fail_on_error: false

      structural:
        enabled: true
        formats: ["json", "yaml", "toml"]

      python:
        enabled: true
        tools:
          - mypy
          - ruff
          - pyright

      javascript:
        enabled: true
        tools:
          - eslint

      typescript:
        enabled: true
        tools:
          - tsc
          - eslint

      go:
        enabled: true
        tools:
          - go vet
          - golangci-lint

      rust:
        enabled: true
        tools:
          - cargo check

      shell:
        enabled: true
        tools:
          - shellcheck

      custom_steps:
        - name: "project-harness"
          command: "python scripts/harness_check.py"
          timeout: 120
          enabled: true
```

---

## How Checks Work

Harness checks are ordinary commands declared in the HarnessSpec. They run after the workflow completes and
are recorded as `checks.step.*` events plus a `checks` block in the run metadata.

```yaml
checks:
  enabled: true
  fail_on_error: false
  custom_steps:
    - name: lint
      command: uv run ruff check src tests
      timeout: 300
    - name: tests
      command: uv run pytest
      timeout: 600
```

Project checks belong in the HarnessSpec, not in project-level legacy configuration.

Each step:

- runs from the configured working directory
- uses `shlex` command parsing, not a shell string
- records stdout/stderr previews
- reports `passed` or `failed`
- can fail the whole harness run when `checks.fail_on_error` is true

---

## Integration

### With Coding Harness Runs

Checks can run automatically after a coding harness produces a patch:

```python
patch = agent.generate_suggestion()
result = await harness.validate_changes(patch)

if result.success:
    # Include in final output
else:
    # Report checks issues
```

### With Suggestions

All suggestions validated:

```bash
# Suggestions already validated
superqode --print "inspect this package and suggest the smallest safe cleanup"
```

### With Event Output

Harness events can include checks results:

```json
{
  "changes": [
    {
      "patch": "...",
      "checks": {
        "success": true,
        "tools_run": ["mypy", "ruff"],
        "findings": []
      }
    }
  ]
}
```

---

## Configuration Examples

### Python Project

```yaml
harness:
  python:
    enabled: true
    tools:
      - mypy      # Type checking
      - ruff      # Linting
      - pyright   # Type checking (alternative)
```

### TypeScript Project

```yaml
harness:
  typescript:
    enabled: true
    tools:
      - tsc       # Type checking
      - eslint    # Linting
```

### Multi-Language Project

```yaml
harness:
  python:
    enabled: true
    tools: [mypy, ruff]
  javascript:
    enabled: true
    tools: [eslint]
  typescript:
    enabled: true
    tools: [tsc, eslint]
```

### Bring Your Own Harness (BYOH)

Use `custom_steps` to run project-specific checks commands as part of the harness. Each step runs in the
repo root, and a non-zero exit code is reported as a harness error.

```yaml
harness:
  custom_steps:
    - name: "contracts"
      command: "python scripts/check_contracts.py"
      timeout: 180
    - name: "smoke-tests"
      command: "pytest -q tests/smoke"
      enabled: true
```

**Step fields**

- `name`: Display name for reporting
- `command`: Shell command to run
- `enabled`: Toggle the step on/off (default: true)
- `timeout`: Timeout in seconds (default: 300)

---

## Best Practices

### 1. Enable Relevant Validators

Only enable validators for languages in your project:

```yaml
harness:
  python:
    enabled: true  # If you use Python
  go:
    enabled: false  # If you don't use Go
```

### 2. Set Timeouts

Prevent long-running checkss:

```yaml
harness:
  timeout_seconds: 30  # Reasonable timeout
```

### 3. Handle Failures Gracefully

```yaml
harness:
  fail_on_error: false  # Report checks failures without failing the whole run
```

### 4. Tool Installation

Ensure tools are installed:

```bash
# Python tools
pip install mypy ruff pyright

# TypeScript tools
npm install -g typescript eslint

# Go tools
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
```

---

## Troubleshooting

### Tools Not Found

**Symptom**: Validators skipped

**Solution**: Install required tools:

```bash
# Check availability
which mypy
which ruff

# Install if missing
pip install mypy ruff
```

### Timeout Errors

**Symptom**: Checks times out

**Solution**: Increase timeout or optimize validators:

```yaml
harness:
  timeout_seconds: 60  # Increase timeout
```

### False Positives

**Symptom**: Validators report issues that don't matter

**Solution**: Configure validator options or disable specific tools:

```yaml
harness:
  python:
    tools: [ruff]  # Skip mypy if too strict
```

---

## Related Features

- [Suggestions](../concepts/suggestions.md) - Suggestion workflow
- [Configuration](../configuration/yaml-reference.md) - Config reference

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Tools System](tools-system.md) - Tool registry and permissions
