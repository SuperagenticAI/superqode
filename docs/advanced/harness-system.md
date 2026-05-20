# Harness System

SuperQode separates the harness from the runtime that executes it.

The harness is the product contract. It defines what a run is allowed to do, how model behavior is shaped,
which tools are available, how sessions and events are stored, and what output must be returned.

The runtime is the execution engine behind that contract. It can be the native SuperQode loop, an SDK adapter,
or an external agent framework adapter.

SuperQode uses the word harness in two related ways:

- **Agent harness**: the runtime that turns a request into model calls, tools, sessions, sandbox access,
  events, and validated output.
- **Validation harness**: the patch and project checks that prove generated changes before they are surfaced
  to users or downstream automation.

The production harness now has a v2 foundation: `HarnessSpec`, built-in templates, a kernel, backend
adapters, run storage, typed outputs, sandbox policy, model policy, and workflow execution. The validation
harness remains a lifecycle hook that can be used by coding harnesses.

---

## Production Harness Vision

SuperQode should be a small framework kernel rather than a single agent loop. The kernel owns stable contracts
for sessions, events, tool policy, sandbox access, model policy, skills, roles, typed outputs, validation,
workflows, and backend adapters. Individual harnesses are user-owned specs compiled into that kernel.

This keeps the existing coding harness as the default while making room for other styles.

### Built In Pieces

| Piece | Production role |
| --- | --- |
| `HarnessSpec` | Declarative contract for flavor, runtime, model policy, agents, workflow, context, validation, and observability |
| Templates | Built-in starts for `coding`, `no-tool`, `gemma4-coding`, `gemma4-no-tool`, `ds4-coding`, and `ds4-fast-local` |
| Kernel | Opens sessions, starts runs, emits events, stores records, and dispatches to backends |
| Backend adapters | Native runtime, Google ADK, OpenAI Agents SDK, optional DeepAgents, optional PydanticAI, and future custom runtimes |
| Sandbox contract | Local read, write, shell, grep, glob, edit, and command policy behind a stable backend protocol |
| Typed outputs | Pydantic-backed result parsing with explicit delimiters and validation failure reporting |
| Workflow engine | Single, chain, parallel, router, orchestrator, and evaluator-optimizer execution |
| Model policy | Explicit prompt, tool, reasoning, temperature, history, and iteration defaults per model family |

The harness sandbox contract is the source of truth for capability profiles. Runtime adapters consume that
contract when they need backend-specific execution, including OpenAI Agents SDK SandboxAgent wiring. Legacy
runtime and sandbox modules keep compatibility imports, but policy decisions live with the harness.
`HarnessSandboxBackend` is the file and shell protocol used by local and future remote harness sandboxes.
OpenAI SandboxAgent clients are exposed through the same harness module as SDK execution clients, not as
direct file-protocol implementations.

Backend adapters also advertise a capability matrix. SuperQode uses it to flag unsupported combinations early,
such as a no-tool spec with DeepAgents or a remote sandbox request against a backend that only supports local policy.

Patch validation primitives are exposed through `superqode.patch_harness`. The `superqode.harness` package
keeps compatibility re-exports, but new agent-harness work should use the HarnessSpec types in this module and
new patch-validation work should use `superqode.patch_harness`.

### What Users Configure

Users configure a harness by selecting:

- flavor: `coding` or `no_tool`
- runtime: `builtin`, `adk`, `openai-agents`, `deepagents`, `pydanticai`, or custom
- model policy: hosted model, local model, Gemma4 profile, DS4 profile, fallbacks, and reasoning defaults
- tools: repository tools, shell, MCP, validation, or no tools
- sandbox policy: read, write, shell, command, and network boundaries
- workflow: single step, chain, parallel workers, router, orchestrator, or evaluator-optimizer
- output: plain text, typed result, events, validation state, and run records

This lets the same harness contract run through different engines while preserving the user-facing behavior.

### Harness Flavors

#### Coding Harness

The coding harness is the current SuperQode strength and should remain the default for repository work.

It gives the model controlled capabilities:

- repository context discovery
- file read/search/edit tools
- shell and test execution under policy
- MCP tools when configured
- validation hooks
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
- optional structured output validation
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
  validation:
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
| Validation harness | yes | optional, output-only |
| Multi-agent delegation | yes | optional, model-only |

### Runtime Backends

Runtime backends are interchangeable execution adapters behind the same harness contract.

| Backend | Status | Use when |
| --- | --- | --- |
| `builtin` | default | You want the native SuperQode coding loop, local-model tuning, and the full harness policy surface |
| `adk` | optional | You want to run through Google ADK while keeping SuperQode harness configuration |
| `openai-agents` | optional | You want OpenAI Agents SDK behavior, sessions, and tool plumbing |
| `deepagents` | optional | You want DeepAgents graph, middleware, and subagent behavior for tool-capable coding harnesses |
| `pydanticai` | optional | You want PydanticAI's agent kernel with SuperQode tools and HarnessSpec policy |

The `deepagents` backend is intentionally not used for no-tool harnesses. DeepAgents 0.6 is built around a
tool-capable deep-agent stack, so SuperQode rejects no-tool specs for that backend and directs users to the
native runtime for model-only runs.

The `pydanticai` backend supports tool-capable coding specs through SuperQode's JSON-schema tool bridge.
It also maps PydanticAI deferred approvals into the standard harness approval flow, loads native
PydanticAI MCP toolsets from `runtime.config.pydanticai.mcp_config_path`, uses PydanticAI fallback
models from `model_policy.fallbacks`, and can enable Logfire instrumentation through `observability.traces`
or `runtime.config.pydanticai.logfire`. Prefect and DBOS durable wrappers are available through
`runtime.config.pydanticai.durable`; Temporal still requires an explicit workflow and worker.

### CLI

Harness specs are usable from the command line:

```bash
superqode harness list-templates
superqode harness list-backends
superqode harness init my-coder --template coding --output harness.yaml
superqode harness validate harness.yaml
superqode harness validate harness.yaml --schema
superqode harness inspect --spec harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

Use `--schema` on `harness validate` to print the HarnessSpec JSON Schema for editor integration and CI
validation.

Use `harness list-backends` to see the backend capability snapshot without loading a spec. It reports coding,
no-tool, streaming, approval, sandbox, shell, MCP, typed-output support, dependency availability, and install
hints for optional backends.

Use `harness inspect` to view the resolved backend, model policy, tools, sandbox policy, workflow, and backend
capability warnings before running a spec. Use `--runtime` and `--sandbox` on `inspect` to check overrides.
Inspection also warns when a backend may not honor model-side constraints such as reasoning effort,
temperature, or max iterations.

Use `harness doctor` before sharing or committing a spec. It checks spec loading, backend installation,
backend/spec compatibility, sandbox policy, event-store writability, rich-event graph support, approval
support, and MCP config paths.

Use `--runtime`, `--provider`, `--model`, `--session`, `--working-dir`, and `--sandbox` on `harness run` to
override the spec for one run. Use `--stream` to print normalized stream events and `--json` for machine
readable output.

### Event Graph

Every HarnessSpec run writes normalized events and a graph view of the execution. The graph turns runtime
events into typed nodes such as run, model, tool, approval, sandbox, MCP, subagent, validation, and typed
output nodes. Edges preserve execution order and mark pauses, resumes, and tool-style calls.

Use the graph commands after a run:

```bash
superqode harness events <run-id>
superqode harness events <run-id> --json
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

This is the common inspection layer for builtin, OpenAI Agents SDK, Google ADK, DeepAgents, PydanticAI, and
future custom backends. Runtime-specific adapters can emit richer events, but the stored graph stays stable.
PydanticAI, OpenAI Agents, and DeepAgents are rich-event backends. PydanticAI maps `run_stream_events` into
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

- `FileHarnessStore`: simple JSON files for local development and easy inspection
- `SQLiteHarnessStore`: indexed session, run, and event history for concurrent readers and larger run sets

### Example Specs

Coding harness:

```yaml
harness:
  name: superqode-coder
  flavor: coding
  runtime:
    backend: builtin
  model_policy:
    primary: gpt-5.5
    fallbacks: [gemma4-local, ds4-local]
  execution_policy:
    sandbox: local
    allow_read: true
    allow_write: true
    allow_shell: true
    approval_profile: balanced
  agents:
    - id: coder
      tools: [filesystem, search, edit, shell, validation]
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

### Implementation Notes

- Preserve the current native loop as the `coding` + `builtin` backend.
- Add `no_tool` as a separate profile with its own system prompt and model policy.
- Do not route no-tool runs through empty tool registries only; the prompt, stop conditions, output parsing,
  and evaluation rules should be tuned for tool-free reasoning.
- Keep validation as a lifecycle hook that the coding harness can call after changes.
- Rename the current patch harness internally to validation harness when the broader agent harness lands.
- Gemma4 should get both coding and no-tool templates so local-model behavior is measurable through the harness.
- Keep DeepAgents as an optional peer backend, not as the core harness foundation.
- Prefer explicit rejection over silent degradation when a runtime cannot honor a harness policy.

---

## Validation Harness Overview

Validation is a secondary lifecycle capability inside the broader harness system. A coding harness can call
validation after it edits files, produces a patch, or returns structured suggestions.

Validation can check:

- **Syntactic correctness**: Code parses correctly
- **Type safety**: Type checking passes
- **Style compliance**: Linting rules followed
- **No regressions**: Changes don't break existing code

Validation does not define the product identity and does not replace runtime policy. It is an optional proof
step that can be attached to coding, workflow, or typed-output runs.

---

## Validation Types

### Structural Validation

Parsing validation for structured formats:

- **JSON**: Valid JSON syntax
- **YAML**: Valid YAML syntax
- **TOML**: Valid TOML syntax

**Runs on**: All changes to structured files

### Language Validation

Language-specific validation:

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
    validation:
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

## How It Works

### 1. Change Or Suggestion Generation

The harness produces a file change, patch, or structured suggestion during a coding run.

### 2. Validation Hook

The validation hook checks the affected files or patch:

```python
harness = PatchHarness(project_root)
result = await harness.validate_changes({
    "src/api/users.py": "new code content"
})
```

### 3. Validation Result

Result includes:

- **Success**: All validations passed
- **Findings**: Validation errors/warnings
- **Tools run**: Which validators executed
- **Duration**: Validation time

### 4. Result Inclusion

The final result can include validation state alongside text, typed data, events, and diffs:

```python
if result.success:
    output.add_validation_state(result)
else:
    output.add_validation_failures(result.findings)
```

---

## Validation Categories

### Structural

**Parsing validation** - ensures files are valid:

```python
{
  "tool": "structural-parse",
  "category": "structural",
  "file": "config.json",
  "message": "Invalid JSON: unexpected token",
  "severity": "error"
}
```

### Syntactic

**Syntax validation** - language syntax:

```python
{
  "tool": "mypy",
  "category": "syntactic",
  "file": "src/api/users.py",
  "line": 42,
  "message": "Missing type annotation",
  "severity": "error"
}
```

### Type

**Type checking** - static type analysis:

```python
{
  "tool": "mypy",
  "category": "type",
  "file": "src/api/users.py",
  "line": 45,
  "message": "Incompatible types: int vs str",
  "severity": "error"
}
```

### Stylistic

**Code style** - formatting and style rules:

```python
{
  "tool": "ruff",
  "category": "stylistic",
  "file": "src/api/users.py",
  "line": 50,
  "message": "Line too long (120 > 100)",
  "severity": "warning"
}
```

### Functional

**Runtime validation** - execution checks:

```python
{
  "tool": "harness",
  "category": "functional",
  "file": null,
  "message": "Harness validation timed out",
  "severity": "warning"
}
```

---

## Tool Detection

Harness automatically detects available tools:

```python
# Checks if tool exists
if shutil.which("mypy"):
    # Run mypy validation
    ...
```

### Tool Availability

- **Not found**: Tool skipped, no error
- **Found**: Tool runs validation
- **Timeout**: Validation times out gracefully

---

## Validation Workflow

### Temporary Workspace

Validation happens in isolated temp workspace:

1. Create temporary directory
2. Stage changed files
3. Run validators
4. Collect findings
5. Clean up temp directory

### Parallel Validation

Multiple validators run in parallel when possible:

- Structural validation (instant)
- Language validators (parallel by file)
- Tool execution (timeout-protected)

---

## Results

### HarnessResult

```python
@dataclass
class HarnessResult:
    success: bool
    findings: List[HarnessFinding]
    tools_run: List[str]
    duration_seconds: float
    files_validated: int
```

### HarnessFinding

```python
@dataclass
class HarnessFinding:
    tool: str
    category: ValidationCategory
    file: Optional[Path]
    message: str
    line: Optional[int]
    column: Optional[int]
    severity: str  # "error", "warning", "info"
```

---

## Integration

### With Coding Harness Runs

Validation can run automatically after a coding harness produces a patch:

```python
patch = agent.generate_suggestion()
result = await harness.validate_changes(patch)

if result.success:
    # Include in final output
else:
    # Report validation issues
```

### With Suggestions

All suggestions validated:

```bash
# Suggestions already validated
superqode --print "inspect this package and suggest the smallest safe cleanup"
```

### With Event Output

Harness events can include validation results:

```json
{
  "changes": [
    {
      "patch": "...",
      "validation": {
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

Use `custom_steps` to run project-specific validation commands as part of the harness. Each step runs in the
repo root, uses the shell, and a non-zero exit code is reported as a harness error.

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

Prevent long-running validations:

```yaml
harness:
  timeout_seconds: 30  # Reasonable timeout
```

### 3. Handle Failures Gracefully

```yaml
harness:
  fail_on_error: false  # Report validation failures without failing the whole run
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

**Symptom**: Validation times out

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
