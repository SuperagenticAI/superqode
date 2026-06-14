# Configuration vs Harness

SuperQode has two YAML files with very different jobs, and the distinction matters: one describes your environment, the other describes a run.

| | `superqode.yaml` | `harness.yaml` (HarnessSpec) |
| --- | --- | --- |
| **What it is** | Project and machine configuration | A portable, runnable contract for agent runs |
| **Answers** | "What is set up here?" | "What is this run allowed to be?" |
| **Contains** | Providers and key mapping, MCP servers, permission defaults, memory providers, gateway options, team and role settings, cost tracking | Runtime backend, model policy, tool surface, sandbox and approvals, workflow topology, checks, hooks, output contract |
| **How many** | One per project (plus an optional `~/.superqode.yaml`) | As many as you want; one per task shape |
| **Shared how** | Usually stays with the machine or repo | Designed to travel: commit it, send it to a teammate, expose it over MCP or A2A |
| **Required** | No. SuperQode works with zero config | No. The TUI and `--print` use built-in defaults |

A useful analogy: `superqode.yaml` is like your Git configuration, while a `harness.yaml` is like a CI pipeline definition. The first sets up the environment once. The second is an artifact you create, version, share, and execute.

They compose: a harness run executes *inside* the environment your configuration provides. The harness says "use the `ds4` tool profile with a workspace sandbox and ask before shell commands"; your configuration supplies the provider credentials, MCP servers, and permission defaults that environment offers.

---

## The harness lifecycle, end to end

Everything below is a real, runnable path. Try it in any repository.

### 1. Create

Answer a few questions and let the wizard write it (recommended, no YAML editing), start from a built-in template, or write the YAML from scratch:

```bash
superqode harness wizard                                              # interactive builder
superqode harness list-templates
superqode harness init my-coder --template qwen-coding --output harness.yaml
superqode harness init local --template gemma4-coding --output harness.yaml
```

Templates include `coding`, `no-tool`, `qwen-coding`, `glm-coding`, `gemma4-coding`, `gemma4-no-tool`, `ds4-coding`, and `ds4-fast-local`. The model-family templates ship model policies already tuned for those families.

See exactly what any harness will do, in plain English:

```bash
superqode harness explain --spec harness.yaml
```

For the full step-by-step walkthrough, see [Bring Your Own Harness](../getting-started/bring-your-own-harness.md).

### 2. Define

The spec is a complete contract. Every section is optional with sensible defaults:

```yaml
version: 1
name: my-coder
flavor: coding                  # or no_tool

runtime:
  backend: builtin              # adk | openai-agents | codex-sdk | claude-agent-sdk | deepagents | pydanticai
  fallback_backends: []

model_policy:
  primary: ollama/gemma4
  fallbacks: ["lmstudio/qwen3-coder"]
  temperature: 0.2
  context_window: 16384         # pin it, or let live detection decide
  tool_call_format: prompt      # for models without a native tool-calling head

execution_policy:
  sandbox: local                # OS sandbox for shell commands
  approval_profile: balanced
  allow_write: true
  allow_shell: true
  permission_rules:             # first match wins
    - { tool: bash, pattern: "pytest*", action: allow }
    - { tool: bash, pattern: "git push*", action: ask }

workflow:
  mode: single                  # chain | parallel | router | orchestrator | evaluator_optimizer

context:
  instruction_files: ["AGENTS.md"]
  session_storage: .superqode/sessions

checks:                         # commands that verify the work
  steps:
    - { name: tests, run: "pytest -q" }
```

You can go further: an `agents:` section defines named roles with their own model, system prompt, tool list, and delegation graph for multi-agent workflows.

### 3. Validate

```bash
superqode harness validate harness.yaml
superqode harness inspect --spec harness.yaml     # resolved policy, workflow, tools
superqode harness compile --spec harness.yaml     # the exact effective contract
superqode harness doctor --spec harness.yaml      # backend installed? sandbox available? store ready?
superqode harness diff a.yaml b.yaml              # what changed between two specs
```

`doctor` is the share gate: run it before giving a spec to a teammate so missing backends or sandbox tools surface on your machine, not theirs.

### 4. Run

A harness executes anywhere SuperQode runs:

| Surface | Command | Use for |
| --- | --- | --- |
| CLI, task or workflow | `superqode harness run --spec harness.yaml --prompt "..."` | Scripts, CI, repeatable tasks. Non-single workflow specs execute their topology; use `--single-step` to force one prompt. |
| TUI, interactive | `:harness harness.yaml`, then chat normally | Daily coding under the contract; `:harness status` shows what is active |
| TUI, at launch | `superqode --harness harness.yaml` or `SUPERQODE_HARNESS=...` | Make the contract the session default |
| TUI, workflows | `:workflow run <task>` (after `:harness ...`) | Execute the spec's chain, parallel, router, orchestrator, or evaluator-optimizer topology; `:workflow presets` and `:workflow preview <task>` first |
| MCP | `superqode mcp` | Any MCP client discovers `list_harnesses`, `describe_harness`, `run_harness` and runs your workflows |
| A2A | `create_a2a_server()` Python API | Other agents call your harness over the Agent-to-Agent protocol |
| Python | `init_harness()`, `kernel.session()`, `run_workflow()` | Embed harness execution in your own application |

The single-prompt paths (`harness run --single-step`, TUI chat) execute through the harness kernel. Non-single CLI runs, `:workflow run`, the MCP server, and the Python `run_workflow()` API execute the spec's chain, parallel, router, orchestrator, or evaluator-optimizer topology.

### 5. Observe

Every run leaves a normalized event trail, no matter which runtime executed it:

```bash
superqode harness runs                  # recent runs
superqode harness events <run-id>      # model calls, tool calls, approvals, results
superqode harness graph <run-id>       # the event graph (add --json for machines)
superqode harness evidence <run-id>    # checks output and verification evidence
```

### 6. Reuse and share

Commit `harness.yaml` next to your code. A teammate with SuperQode installed runs the same contract with one command, and `harness doctor` tells them if their machine is missing anything. Expose it over MCP and it becomes a tool inside Claude Desktop or any other MCP client. Serve it over A2A and it becomes an agent other agents can call.

---

## Which file do I edit?

| You want to... | Edit |
| --- | --- |
| Add an API key mapping, MCP server, or memory provider | `superqode.yaml` |
| Change default tool permissions for the whole project | `superqode.yaml` |
| Pin which model and runtime a recurring task uses | `harness.yaml` |
| Let a task write files and run tests, but ask before pushing | `harness.yaml` (`execution_policy.permission_rules`) |
| Run the same agent contract on a teammate's machine | `harness.yaml` (share it; they run `harness doctor` first) |
| Tune behavior for a local Gemma or DS4 model | `harness.yaml` (`model_policy`, or start from a local template) |

See [Harness System](../advanced/harness-system.md) for the full spec reference and [superqode.yaml Reference](../configuration/yaml-reference.md) for the configuration schema.
