# Harness System

SuperQode is your portable coding agent harness.

SuperQode separates the harness you configure from the runtime that executes it. The harness defines what a
run is allowed to do, which model policy to use, which tools are available, how approvals work, where events
are stored, and what output should be returned.

---

## What A Harness Gives You

| Capability | What you control |
| --- | --- |
| Runtime | Use `builtin`, Google ADK, OpenAI Agents SDK, Codex SDK, Claude Agent SDK, DeepAgents, PydanticAI, or another supported backend |
| Model policy | Pick primary models, fallbacks, reasoning, temperature, history, and iteration limits |
| Tools | Enable repository tools, shell, MCP, checks, or no tools |
| Sandbox policy | Set read, write, shell, command, and network boundaries |
| Approvals | Pause risky tool calls for review before they run |
| Events | Store run timelines and graph views for debugging |
| Output | Return plain text, typed results, checks state, and run records |
| Context | Instruction files, skills directories, session storage, compaction, and memory settings |
| Observability | Events, traces, run store backend, and instrumentation configuration |
| Hooks | Custom lifecycle callbacks at defined harness execution points |

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

Both flavors compile from the same `HarnessSpec` shape:

```yaml
version: 1
name: superqode-coder
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: gemma4-local
  fallbacks:
    - ds4-local
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
| Skills | yes | yes |
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
| `claude-agent-sdk` | optional | You want Anthropic Claude Agent SDK runtime with SuperQode harness configuration and policy |
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
superqode harness diff old-harness.yaml new-harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
superqode harness runs
superqode harness events <run-id>
superqode harness evidence <run-id>
superqode harness replay <run-id>
superqode harness fork <run-id> <new-name>
superqode harness graph <run-id>
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
version: 1
name: superqode-coder
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: gpt-4o-mini
  fallbacks:
    - gemma4-local
    - ds4-local
execution_policy:
  sandbox: local
  allow_read: true
  allow_write: true
  allow_shell: true
  approval_profile: balanced
agents:
  - id: coder
    tools:
      - read_file
      - edit_file
      - grep
      - glob
      - bash
      - todo_write
      - todo_read
    skills:
      - repo-navigation
      - implementation
```

No-tool harness:

```yaml
version: 1
name: superqode-reasoner
flavor: no_tool
runtime:
  backend: builtin
model_policy:
  primary: gemma4-local
  fallbacks:
    - ds4-local
  temperature: 0.2
execution_policy:
  allow_read: false
  allow_write: false
  allow_shell: false
agents:
  - id: reasoner
    tools: []
    skills:
      - architecture-review
      - code-review-from-context
```

### Practical Guidance

- Use `coding` with `builtin` for the default repository workflow.
- Use `no_tool` when you want model-only planning, explanation, or review from supplied context.
- Use `doctor` before sharing a spec, especially when it depends on an optional runtime.
- Use `compile` when you want to see the effective policy after defaults are applied.
- Use `diff` before replacing a shared harness so reviewers can see policy, tool, and agent changes.
- Keep DeepAgents for tool-capable coding harnesses; use `builtin` for no-tool specs.

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

### Event Output

Harness events can include checks results. The actual checks result block from a harness run:

```json
{
  "enabled": true,
  "status": "passed",
  "steps": [
    {
      "name": "lint",
      "command": "uv run ruff check src tests",
      "timeout": 300,
      "status": "passed",
      "returncode": 0,
      "stdout": "",
      "stderr": ""
    }
  ]
}
```

---

## Custom Check Examples

Use `custom_steps` to run project-specific checks commands as part of the harness. Each step runs in the
configured working directory, and a non-zero exit code is reported as a harness error.

```yaml
checks:
  enabled: true
  fail_on_error: false
  custom_steps:
    - name: contracts
      command: python scripts/check_contracts.py
      timeout: 180
      enabled: true
    - name: smoke-tests
      command: pytest -q tests/smoke
      timeout: 300
      enabled: true
```

**Step fields**

- `name`: Display name for reporting
- `command`: Shell command to run
- `enabled`: Toggle the step on or off. The default is true.
- `timeout`: Timeout in seconds. The default is 300.

---

## Best Practices

### Set Timeouts

Prevent long-running checks:

```yaml
checks:
  timeout_seconds: 300
```

### Handle Failures Gracefully

```yaml
checks:
  fail_on_error: false
```

### Keep Tools Installed

Ensure tools are installed:

```bash
# Python tools
pip install mypy ruff pyright

# TypeScript tools
npm install -g typescript eslint

# Go tools
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
```

## Expose Harnesses Over MCP

A harness isn't only runnable from the TUI — you can expose your HarnessSpec
workflows as **MCP tools** so any MCP client (Claude Desktop, IDEs, other agents)
can discover and run them. This complements the A2A and ACP servers.

```bash
superqode mcp                      # stdio (for Claude Desktop, etc.)
superqode mcp --http --port 8765   # streamable HTTP
superqode mcp --dir ./harnesses    # point at a specific spec directory
```

It exposes three tools:

- `list_harnesses` — the HarnessSpec files it found.
- `describe_harness(harness)` — a spec's workflow mode, runtime, and agents.
- `run_harness(harness, task, provider?, model?)` — run the workflow, return the result.

Specs are discovered under `.superqode/harness/`, `.superqode/harnesses/`,
`harness/`, or `harnesses/` (or `--dir`). The provider/model resolve from the
tool arguments → `SUPERQODE_MCP_PROVIDER` / `SUPERQODE_MCP_MODEL` →
the spec's `model_policy.primary`.

---

## Related Features

- [Configuration](../configuration/yaml-reference.md) - Project config reference
- [Examples](../examples.md) - Ready-to-run harness examples
- [Safety & Permissions](safety-permissions.md) - Sandbox and approval policy
- [Local Context & Compaction](local-context.md) - Context detection for local models
- [Multi-Repo Search & Edit Safety](multi-repo-search.md) - Cross-repo search

---

## Next Steps

- [Advanced Features Index](index.md) - All advanced features
- [Tools System](tools-system.md) - Tool registry and permissions
