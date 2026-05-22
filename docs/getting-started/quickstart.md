# Quick Start

Get a SuperQode harness running in a few minutes.

SuperQode is your pluggable multi-agent coding harness. A harness defines the run contract: model policy, runtime backend, tool access, sandbox policy, workflow shape, events, and output handling.

!!! note "Safe first run"
    Start in a low-risk repository, throwaway branch, sandbox, or VM. Coding harnesses can read files, edit files, and run shell commands when policy allows it.

---

## 1. Install

```bash
pip install superqode
```

Or with `uv`:

```bash
uv tool install superqode
```

Optional runtime backends are installed only when you need them:

```bash
pip install "superqode[openai-agents]"
pip install "superqode[pydanticai]"
pip install "superqode[deepagents]"
pip install "superqode[adk]"
```

---

## 2. Run The TUI

For interactive coding work:

```bash
cd /path/to/your/project
superqode
```

Useful TUI commands:

| Command | Purpose |
| --- | --- |
| `:status` | Show current provider, runtime, mode, and harness state |
| `:harness harness.yaml` | Load a HarnessSpec into the session |
| `:runtime list` | Show runtime backends |
| `:runtime pydanticai` | Switch runtime where available |
| `:providers` | Inspect provider setup |
| `:sandbox` | Inspect sandbox policy |
| `:help` | Show available commands |

You can also ask directly in natural language:

```text
Summarize this repository and suggest the smallest safe improvement.
```

---

## 3. Run One Headless Task

For a quick terminal task:

```bash
superqode --print "summarize this repository"
```

For JSON output:

```bash
superqode --mode json --print "summarize this repository"
```

---

## 4. Create A Harness

Create a reusable coding harness:

```bash
superqode harness init my-coder --template coding --output harness.yaml
```

Check it before running:

```bash
superqode harness doctor --spec harness.yaml
```

Run it:

```bash
superqode harness run --spec harness.yaml --prompt "summarize the architecture"
```

For complete starting points, use the repository examples in `examples/harnesses/`. They cover the builtin coding harness, no-tool reasoning, PydanticAI, DeepAgents, OpenAI Agents SDK, Google ADK, Gemma4, and DS4.

The JSON form includes the `run_id`:

```bash
superqode harness run --spec harness.yaml --prompt "summarize the architecture" --json
```

---

## 5. Inspect What Happened

Every HarnessSpec run writes normalized events and a graph view.

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

Use this when a run behaves unexpectedly. The graph gives one inspection model across backends.

| Backend | Rich graph events |
| --- | --- |
| `builtin` | Model requests, model deltas, tools, results, approvals |
| `pydanticai` | Model deltas, tools, results, approvals |
| `openai-agents` | Model deltas, tools, approvals, sandbox markers |
| `deepagents` | Model deltas, tools, subagents, memory, sandbox activity, results |
| `adk` | Run and stream events |

---

## 6. Pick The Right Template

| Template | Use when |
| --- | --- |
| `coding` | You want repository-aware coding with file/search/edit/shell tools under policy |
| `no-tool` | You want model-only reasoning with no tools, shell, or repository access |
| `gemma4-coding` | You want a Gemma4 local coding starting point |
| `gemma4-no-tool` | You want Gemma4 model-only reasoning |
| `ds4-coding` | You want a DS4 local coding starting point |
| `ds4-fast-local` | You want lower-latency local DS4 iteration |

List templates:

```bash
superqode harness list-templates
```

---

## 7. Choose A Runtime

List backends:

```bash
superqode harness list-backends
```

Run with a backend override:

```bash
superqode harness run --spec harness.yaml --runtime pydanticai --prompt "review this design"
superqode harness run --spec harness.yaml --runtime openai-agents --prompt "make the smallest safe fix"
superqode harness run --spec harness.yaml --runtime deepagents --prompt "prototype the implementation"
```

Use `doctor` with the same override before a team run:

```bash
superqode harness doctor --spec harness.yaml --runtime pydanticai
```

---

## 8. Common Commands

| Command | Purpose |
| --- | --- |
| `superqode` | Launch the interactive TUI |
| `superqode --print "..."` | Run one headless task |
| `superqode harness init ...` | Create a HarnessSpec |
| `superqode harness validate --spec harness.yaml` | Validate spec syntax |
| `superqode harness doctor --spec harness.yaml` | Preflight a spec and backend |
| `superqode harness inspect --spec harness.yaml` | Show resolved policy and compatibility |
| `superqode harness compile --spec harness.yaml --json` | Show effective spec and model policy |
| `superqode harness diff old.yaml new.yaml` | Compare two harness specs |
| `superqode harness run --spec harness.yaml --prompt "..."` | Run a harness task |
| `superqode harness events <run-id>` | Show normalized run events |
| `superqode harness graph <run-id>` | Show the persisted event graph |
| `superqode providers doctor openai` | Check provider setup |
| `superqode runtime list` | List runtime backends |

---

## 9. Validation Workflows

Validation and evaluation are available as secondary workflows behind the main SuperQode CLI:

```bash
superqode qe run . --mode quick
superqode qe run . --mode deep
```

Use these when you want role-based project checks, reports, generated tests, or release validation. For day-to-day coding, start with the harness commands above.

---

## Next Steps

1. [Your First Session](first-session.md)
2. [Harness System](../advanced/harness-system.md)
3. [Runtime Backends](../runtimes.md)
4. [Configuration Guide](configuration.md)
5. [Three Modes](../concepts/modes.md)
6. [CI/CD Integration](../integration/cicd.md)

---

## Tips

!!! tip "Run doctor first"
    `superqode harness doctor --spec harness.yaml` catches missing optional runtimes, incompatible no-tool/coding settings, sandbox policy issues, and event-store problems.

!!! tip "Use no-tool for pure reasoning"
    The `no-tool` template intentionally removes filesystem, shell, network, and repository access.

!!! tip "Use the graph when debugging"
    `superqode harness graph <run-id> --json` is the best way to see what a backend actually emitted.
