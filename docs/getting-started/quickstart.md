# Quick Start

This guide installs SuperQode and starts a coding harness.

SuperQode is your portable coding agent harness. A harness defines the run contract: model policy, runtime backend, tool access, sandbox policy, workflow shape, events, and output handling.

!!! note "Safe first run"
    Start in a low-risk repository, throwaway branch, sandbox, or VM. Coding harnesses can read files, edit files, and run shell commands when policy allows it.

---

## 1. Install

```bash
uv tool install superqode
```

Optional runtime backends are installed only when you need them:

```bash
uv tool install "superqode[openai-agents]"
uv tool install "superqode[pydanticai]"
uv tool install "superqode[deepagents]"
uv tool install "superqode[adk]"
```

For Codex, GitHub Copilot SDK, Claude Agent SDK, and Antigravity SDK support, install one runtime
or the optional bundle:

```bash
uv tool install "superqode[codex-sdk]"
uv tool install "superqode[copilot-sdk]"
uv tool install "superqode[claude-agent-sdk]"
uv tool install "superqode[antigravity-sdk]"
# Or install the complete vendor SDK bundle:
uv tool install "superqode[vendor-sdks]"
```

The bundle does not include the Grok or `agy` subscription CLIs. Run
`superqode runtime setup` for installation and authentication guidance.

---

## 2. Prerequisites

Before starting the TUI, make sure you have one of these ready:

- **API key** for a cloud provider (set as env var like `ANTHROPIC_API_KEY`)
- **Local model server** running (e.g., `ollama serve`, `mlx_lm.server`)

See [BYOK providers](../providers/byok.md) or [Local providers](../providers/local.md) for setup guides.

!!! tip "No config file needed"
    SuperQode runs without a `superqode.yaml`. Connect a model to start a session.
    Project defaults and MCP servers live in `superqode.yaml`. Repeatable run
    behavior lives in a HarnessSpec such as `harness.yaml` or
    `superqode.local.yaml`. Add them when you need durable project configuration
    or a run contract you can inspect, version, and reuse.

---

## 3. Run The TUI

For interactive coding work:

```bash
cd /path/to/your/project
superqode
```

Once the TUI starts, connect a provider or agent:

```text
:connect
```

Choose BYOK (cloud API key), Local (self-hosted model), ACP (coding agent), or
an available SDK product profile from the picker. See
[Connection Methods and Vendors](../concepts/modes.md) for the full connection
and interoperability inventory.

For ACP coding agents, `:connect acp` shows installed and featured runtimes.
Use `:connect acp all` to search the complete catalog or `:connect acp refresh`
to update the cached official registry.

Useful TUI commands after connecting:

| Command | Purpose |
| --- | --- |
| `:status` | Show current provider, runtime, mode, and harness state |
| `:harness wizard` | Create and optionally load a starter HarnessSpec step by step |
| `:harness harness.yaml` | Load a HarnessSpec into the session |
| `:runtime list` | Show runtime backends |
| `:runtime setup` | Show optional vendor SDK and authentication setup |
| `:runtime pydanticai` | Switch runtime where available |
| `:providers` | Inspect provider setup |
| `:providers free` | Find free/local inference setup paths |
| `:providers free --live openrouter` | Scan current zero-price model routes |
| `:sandbox` | Show or set the local command sandbox mode |
| `:theme` | Pick an accent theme |
| `:compare <models>` | Re-run your last message across several models |
| `:export` | Export the conversation to HTML |
| `:rewind` | Rewind the conversation to an earlier message |
| `:help` | Show available commands |

For local models, the fastest path to a harness you own is:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

`local init` detects the machine, writes `superqode.local.yaml`, and runs a
non-destructive smoke check when a local server is available. Use `:local build`
or `superqode local build` when you already know the model, endpoint, or pack
you want to target. The pack is only the starting point; inspect the generated
YAML and customize model policy, memory, tools, and approvals for your project.

`superqode.local.yaml` is a harness file, not project configuration. Load it
with `superqode --harness superqode.local.yaml` or `:harness
superqode.local.yaml`. Use `superqode config init` separately when you want a
project-level `superqode.yaml`.

You can also ask directly in natural language:

```text
Summarize this repository and suggest the smallest safe improvement.
```

---

## 4. Run One Headless Task

For a quick terminal task:

```bash
superqode --print "summarize this repository"
```

For JSON output:

```bash
superqode --mode json --print "summarize this repository"
```

---

## 5. Create A Harness

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

## 6. Inspect What Happened

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

## 7. Pick The Right Template

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

## 8. Choose A Runtime

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

## 9. Common Commands

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

## 10. Harness Checks

Project checks are part of a harness. Add commands under `checks.custom_steps`, then run the harness or inspect it with `doctor`.

```yaml
checks:
  enabled: true
  fail_on_error: false
  timeout_seconds: 300
  custom_steps:
    - name: tests
      command: uv run pytest
      enabled: true
      timeout: 300
```

```bash
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "make the smallest safe fix and run the configured check"
```

Use this path for repeatable project checks. For day-to-day coding, start with the TUI and focused prompts.

---

## Next Steps

1. [Your First Session](first-session.md)
2. [Harness System](../advanced/harness-system.md)
3. [Runtime Backends](../runtimes.md)
4. [Configuration Guide](configuration.md)
5. [Connection Methods and Vendors](../concepts/modes.md)

---

## Tips

!!! tip "Run doctor first"
    `superqode harness doctor --spec harness.yaml` catches missing optional runtimes, incompatible no-tool/coding settings, sandbox policy issues, and event-store problems.

!!! tip "Use no-tool for pure reasoning"
    The `no-tool` template intentionally removes filesystem, shell, network, and repository access.

!!! tip "Use the graph when debugging"
    `superqode harness graph <run-id> --json` is the best way to see what a backend actually emitted.
