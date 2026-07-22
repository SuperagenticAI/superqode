# Harness System

SuperQode is your portable coding agent harness.

SuperQode separates the harness you configure from the runtime that executes it. The harness defines what a
run is allowed to do, which model policy to use, which tools are available, how approvals work, where events
are stored, and what output should be returned.

!!! tip "Harness overview"
    [Bring Your Own Harness](../getting-started/bring-your-own-harness.md) is the friendly, step-by-step guide: create a harness, read it in plain English with `harness explain`, edit it, verify it, and run it against a local model. [Configuration vs Harness](../concepts/configuration-vs-harness.md) explains how `harness.yaml` differs from `superqode.yaml`, walks the full lifecycle from `harness init` to `harness events`, and lists every surface a harness runs on (CLI, TUI, workflows, MCP, A2A, Python). This page is the detailed spec reference.

!!! tip "Harness explanation"
    `superqode harness explain --spec harness.yaml` reads the resolved policy (the same one the runtime enforces) and describes, in words, which tools the model gets, what it may read/write/run, how approvals work, and why a given tool-call format was chosen.

!!! tip "Execution, measurement, and optimization"
    SuperQode runs a harness and measures it (`harness test` / `eval` / `auto-bench`). Improving the harness over many iterations is a separate, optional job: `superqode harness optimize` bridges to the optional [metaharness](harness-optimization.md) tool, while `superqode harness improve` adds failure mining, logbook memory, candidate audit gates, and accepted/rejected candidate history. See [Running, Measuring, and Optimizing a Harness](harness-optimization.md) and [Self-Improving Harnesses](self-improving-harness.md) for the distinction.

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
| Optimization | Self-improvement boundaries: editable surfaces, protected surfaces, held-out split, and human-apply policy |

### What Users Configure

Users configure a harness by selecting:

- flavor: `coding` or `no_tool`
- runtime: `builtin`, `adk`, `openai-agents`, `deepagents`, `pydanticai`, or custom
- model policy: hosted model, local model, Gemma4 profile, DS4 profile, fallbacks, and reasoning defaults
- tools: repository tools, shell, MCP, checks, or no tools
- sandbox policy: read, write, shell, command, and network boundaries
- workflow: single step, chain, parallel workers, router, orchestrator, or evaluator-optimizer
- output: plain text, typed result, events, checks state, and run records
- optimization: whether self-improvement is enabled, what surfaces can be edited, and what surfaces are protected

This lets the same harness contract run through different engines while preserving the user-facing behavior.

### Nine Behavioral Dimensions

A harness behaves along nine orthogonal dimensions. SuperQode uses them to tag a failure with *where* in the spec to look: `harness test` reports a `dimension: {id, label, field}` on the failing check (see [Run, Measure, Optimize](harness-optimization.md)).

| ID | Dimension | Spec field |
| --- | --- | --- |
| D1 | model selection | `model_policy` |
| D2 | context assembly | `context` |
| D3 | memory management | `context.memory` |
| D4 | tool ecosystem | `agents.tools` |
| D5 | execution environment | `execution_policy.sandbox` |
| D6 | evaluation and reward | `checks` |
| D7 | control and safety | `execution_policy` |
| D8 | observability | `observability` |
| D9 | training bridge | `metadata` |

For example, a `model_endpoint_error` is tagged **D1** (`model_policy`); a `tool_or_permission_error` is tagged **D7** (`execution_policy`). The mapping mirrors the HarnessX taxonomy; see [Run, Measure, Optimize](harness-optimization.md).

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
| `rlm-code` | optional | You want RLM Code v0.1.11+ recursive REPL execution, LID context isolation, and native trajectory evidence behind a HarnessSpec |

The `rlm-code` backend delegates recursive execution to RLM Code and maps its context record, steps,
root/submodel usage, harness-exposure metrics, and native JSONL trajectory into SuperQode events and evidence.
Install it with `uv tool install "superqode[rlm-code]"`; see [RLM Code Integration](rlm-code.md) for the
configuration and safety boundary.

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
superqode harness init my-coder --template coding --minimal --output harness.yaml
superqode harness import-omnigent path/to/agent.yaml --output harness.yaml
superqode harness validate --spec harness.yaml
superqode harness validate --spec harness.yaml --schema
superqode harness inspect --spec harness.yaml
superqode harness compile --spec harness.yaml --json
superqode harness diff old-harness.yaml new-harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness test --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml
superqode harness auto-bench --spec harness.yaml --tasks eval-tasks.yaml
superqode harness optimize --spec harness.yaml --tasks eval-tasks.yaml --export-only
superqode harness registry publish harness.yaml
superqode harness registry list
superqode harness registry install my-coder --output harness.yaml
superqode harness inbox add --session my-session --prompt "fix auth bug"
superqode harness inbox list --session my-session
superqode harness inbox recover --session my-session
superqode harness drain --spec harness.yaml --session my-session
superqode harness worker --spec harness.yaml --session my-session --concurrency 2
superqode harness runs
superqode harness events <run-id>
superqode harness evidence <run-id>
superqode harness replay <run-id>
superqode harness fork <run-id> <new-name>
superqode harness graph <run-id>
```

Use `--schema` on `harness validate` to print the HarnessSpec JSON Schema for editor integration and CI
checks.

Use `inherits` to compose a harness from a built-in template or another YAML file:

```yaml
version: 1
name: team-coder
inherits: coding
model_policy:
  primary: ollama/qwen3-coder
```

Inheritance is resolved when the spec loads. Mapping fields are deep-merged, child scalar values override the
base, and list fields such as agents and permission rules replace the base list. Relative inherited files are
resolved from the child spec's directory, and cycles are rejected.

Use `harness import-omnigent` to convert an Omnigent `agent.yaml` into a SuperQode
`HarnessSpec` without making Omnigent the controlling runtime. The importer maps
executor, model, prompt, instruction file, OS access, tools, and sub-agent fields
into SuperQode's spec, then preserves Omnigent-only fields under `metadata.omnigent`.
See [Omnigent Compatibility](omnigent-compat.md).

Use `harness import-agent` when you want that concise authoring style without
depending on Omnigent. It compiles a SuperQode `agent.yaml` with `executor`,
`tools`, `skills`, `os_env`, policies, and agent-valued tools into a normal
`HarnessSpec`, preserving source details under `metadata.agent`.

Harness-local MCP servers can be declared directly under
`runtime.config.mcp_servers` or via `import-agent` tool declarations. During a
harness run, SuperQode connects those inline MCP servers, exposes discovered
tools as `mcp_<server>_<tool>`, and records MCP list/error events in the run
ledger.

Harness child agents declared with Omnigent-style `tools.<name>.type: agent`
compile into delegated `AgentSpec`s. The builtin runtime exposes them through
`agent_session`, which starts persistent named child sessions, sends follow-up
input, resumes saved child context by `session_id`, waits for results, lists
active sessions, approves or rejects pending child tool approvals, and closes
them. Child sessions use the declared child agent's prompt, model, tool filter,
and iteration limit.

Use `harness inbox` when you want durable prompt admission before execution. Inputs are written to the
harness store first, then `harness drain` claims pending `queue` inputs for one session and marks each input
`done` or `failed` with the resulting run id. `--delivery admit-only` stages an input without letting a drain
claim it yet, which is useful for exact retry, review, or external schedulers.

Drains claim inputs with an owner id and lease. Use `harness drain --owner-id worker-a --lease-seconds 300`
when you run multiple workers, and use `harness inbox recover --stale-after 300` to move stale `running`
inputs back to `pending` after an interrupted worker.

Use `harness worker` for long-running local execution. It recovers stale inputs on startup, claims pending
inputs with an owner lease, renews the lease while a run is active, and can process more than one input with
`--concurrency`. For CI or scripts, use `--max-runs N` or `--once` so the worker exits after bounded work.

Use `harness list-backends` to see the backend capability snapshot without loading a spec. It reports coding,
no-tool, streaming, approval, sandbox, shell, MCP, typed-output, workflow-child support, event detail,
dependency availability, and install hints for optional backends.

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

Use `harness doctor` before sharing or committing a spec. It checks spec loading, workflow topology,
agent IDs and per-agent policy, requested tools, backend installation, backend/spec compatibility, local
endpoint/model routing, sandbox policy, event-store writability, rich-event graph support, approval
support, checks commands, hooks, skills, and MCP config paths.

Use `harness test` for a quick end-to-end readiness probe. Without `--live` it validates load, doctor, and
kernel initialization paths without calling a model. With `--live` it also sends a small prompt and emits a
compact failure digest that points at likely components such as `model_policy`, `execution_policy`, tools, or
runtime setup.

Use `harness eval` to run one or more specs against a task file and produce a scorecard. Pass extra variants
with repeated `--variant` options to keep task-specific harnesses isolated instead of forcing one global spec
to fit every workflow. Use `--live` when you want to execute tasks against the configured model endpoint.

Use `harness auto-bench` as the quick model-facing wrapper around `harness test` or `harness eval`. It keeps
the output focused on the next recommended action so first-run local model setup has a single obvious command.

Use `harness optimize` to export a HarnessSpec and eval task file into a `superagentic-metaharness` project,
then optionally run a meta-harness backend such as Codex, Gemini, Omnigent, or the fake backend. The command
keeps meta-harness optional: `--export-only` creates the project without requiring the external tool, and
`--apply` copies the best candidate `harness.yaml` back only after an explicit request.

The exporter also writes `trace-evidence.md` when you do not pass your own evidence file. That evidence captures
the current harness snapshot, model policy, permission posture, workflow, and eval task prompts. Pass
`--test-result` with JSON from `harness test --json` or `--eval-result` with JSON from `harness eval --json`
to carry previous failures, scorecards, and regressions into the optimizer evidence. After a run,
`harness optimize-inspect RUN_DIR` summarizes the best candidate and `harness optimize-ledger RUN_DIR` renders
the candidate ledger from the meta-harness artifacts. Both commands have `--json` for CI and release evidence.
The TUI harness sidebar shows the latest local meta-harness ledger when run artifacts exist.

Use `harness registry` for local sharing before publishing specs to a remote hub. `publish` validates and
copies a spec into `~/.superqode/harness-registry`, `list` shows available entries, and `install` copies one
into the current project.

The default `builtin` backend supports approval pauses for ASK-permission tool calls. `pydanticai` and
`openai-agents` also support approval pauses through their runtime adapters. Backends that cannot pause for
approval are reported by `harness doctor`.

Use `--runtime`, `--provider`, `--model`, `--session`, `--working-dir`, and `--sandbox` on `harness run` to
override the spec for one run. Use `--stream` to print normalized stream events and `--json` for machine
readable output.

`harness run` honors the workflow topology in the spec. A `single` workflow runs
one prompt through the harness kernel. `chain`, `parallel`, `router`,
`orchestrator`, and `evaluator_optimizer` run through the workflow engine,
persisting a parent workflow run plus child result run IDs. Use `--single-step`
to force the old one-prompt path, and use `--stream` only with single-step runs.

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
| `qwen-coding` | Qwen Coder pack: low temperature, native tools, long agentic sessions, sequential tools |
| `glm-coding` | GLM pack: native tools, longer history budget, sequential tools |
| `glm52-coding` | Z.AI GLM-5.2: native tools, 1M context, max reasoning, longer history |
| `gemma4-coding` | minimal prompt, compact local tool surface, strict JSON tool-call hints, low temperature, sequential tools |
| `gemma4-no-tool` | model-only prompt, no tools, low temperature, short history, reasoning disabled where supported |
| `ds4-coding` | DS4 prompt path, compact tool surface, low temperature, low reasoning, sequential tools |
| `ds4-fast-local` | DS4 coding with tighter iteration and history budgets for fast local loops |

The `qwen-coding`, `glm-coding`, and `glm52-coding` templates set `model_policy.pack`, so the matching model-policy pack (temperature, parallel-tools, history budget) is layered on automatically. `glm52-coding` explicitly uses the Z.AI general API route. List every built-in template with `superqode harness list-templates`.

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

Workflow steps inherit the top-level `--provider`, `--model`, and `--runtime`
unless the matching `agents:` entry overrides them. Agent-level `model` may be a
plain model id (`<openai-model>`) or a provider-qualified id (`ollama/qwen3:4b`).
Hugging Face Inference Provider routes may also use the shorthand
`hf.zai-org/GLM-5.2:fireworks-ai`; SuperQode resolves that to provider
`huggingface` and model `zai-org/GLM-5.2:fireworks-ai` for the step.
Agent `config.provider`, `config.runtime`, `tools`, and `max_iterations` are
honored for that step by the runtime-backed harness path, so one workflow can
route planning to a small local model, implementation to a coding model, and
review to a different runtime without changing the harness contract.

Workflow failure policy is configured under `workflow.config`:

```yaml
workflow:
  mode: chain
  config:
    max_retries: 1
    continue_on_error: true
    fallback_prompt: "Recover with a simpler answer and preserve useful context."
    fallback_step_id: recover
```

Defaults are fail-fast with no retries. `max_retries` retries the same step
before it is considered failed. `fallback_prompt` runs one fallback step after
retry exhaustion. `continue_on_error` lets chain/parallel-style workflows keep
going while the parent run records `failures` and ends with failed status, so CI
and automation can detect partial success.

### Run Storage

Harness sessions can use a file store or SQLite store:

- `file`: simple JSON files for local development and easy inspection
- `sqlite`: indexed session, run, and event history for concurrent readers and larger run sets
- `memory`: temporary run storage for tests and short-lived automation

Set the default in `observability.run_store`, or override a single CLI run:

```bash
superqode harness run --spec harness.yaml --store sqlite --prompt "summarize this repository"
```

### Observability Export

Replay and evidence are local-first. External observability is an optional
mirror over the same stored run graph:

```bash
uv sync --extra observability
```

```yaml
observability:
  events: true
  traces: true
  local: true
  run_store: file
  exporters:
    - type: opentelemetry
      enabled: false
      endpoint: http://localhost:4317
    - type: mlflow
      enabled: true
    - type: langsmith
      enabled: false
    - type: logfire
      enabled: false
    - type: arize
      enabled: false
```

Check sink status:

```bash
superqode harness observability status --spec harness.yaml
```

Export a root run and its recursive child runs:

```bash
superqode harness observability export <run-id> --spec harness.yaml
```

The local export writes `trace.json`, `runs.jsonl`, `events.jsonl`,
`otel_spans.jsonl`, and `overview.md`. MLflow can optionally log those files as
artifacts and metrics. LangSmith creates a child run tree, Logfire mirrors the
run as spans and log events, and Arize/Phoenix uses the OTEL collector path.
Availability checks stay separate from run execution, so missing credentials
never block the harness.

### Example Specs

Coding harness:

```yaml
version: 1
name: superqode-coder
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: <openai-model>
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
uv pip install mypy ruff pyright

# TypeScript tools
npm install -g typescript eslint

# Go tools
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
```

## Expose Harnesses Over MCP

A HarnessSpec can also be exposed outside the TUI
workflows as **MCP tools** so any MCP client (Claude Desktop, IDEs, other agents)
can discover and run them. This complements the A2A and ACP servers.

```bash
superqode mcp                      # stdio (for Claude Desktop, etc.)
superqode mcp --http --port 8765   # streamable HTTP
superqode mcp --dir ./harnesses    # point at a specific spec directory
```

It exposes three tools:

- `list_harnesses`: the HarnessSpec files it found.
- `describe_harness(harness)`: a spec's workflow mode, runtime, and agents.
- `run_harness(harness, task, provider?, model?)`: run the workflow, return the result.

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
