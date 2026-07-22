<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode" width="220">
</p>

<h1 align="center">SuperQode</h1>

<p align="center">
  <strong>The harness engineering framework for coding agents, optimized for local and open models</strong><br>
  <em>Build your own coding harness. Measure it. Extend it. Optimize it. Use any model, open or closed, small or large, local or remote, without giving up control of the agent loop.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/pyversions/superqode?style=flat-square" alt="Python"></a>
  <a href="https://github.com/SuperagenticAI/superqode/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square" alt="License"></a>
</p>

<p align="center">
  <a href="https://github.com/SuperagenticAI/superqode/stargazers"><img src="https://img.shields.io/github/stars/SuperagenticAI/superqode?style=flat-square" alt="Stars"></a>
  <a href="https://github.com/SuperagenticAI/superqode/network/members"><img src="https://img.shields.io/github/forks/SuperagenticAI/superqode?style=flat-square" alt="Forks"></a>
  <a href="https://github.com/SuperagenticAI/superqode/issues"><img src="https://img.shields.io/github/issues/SuperagenticAI/superqode?style=flat-square" alt="Issues"></a>
  <a href="https://github.com/SuperagenticAI/superqode/pulls"><img src="https://img.shields.io/github/issues-pr/SuperagenticAI/superqode?style=flat-square" alt="PRs"></a>
</p>

<p align="center">
  <a href="https://superagenticai.github.io/superqode/">📚 Documentation</a> •
  <a href="https://github.com/SuperagenticAI/superqode/issues">🐛 Report Bug</a> •
  <a href="https://github.com/SuperagenticAI/superqode/discussions">💬 Discussions</a>
</p>

<p align="center">
  <img src="assets/superqode-hero.png" alt="SuperQode harness engineering workbench" width="920">
</p>

---

## What is SuperQode?

SuperQode is a **harness engineering framework for coding agents**, optimized for local and open models. The harness is the software around the model that decides what it can see, which tools it can call, how it remembers, and how its work is checked. After prompt engineering and context engineering, the harness is the layer that now decides whether a coding agent is reliable.

Most coding products ship a finished harness you cannot see, tuned to keep you on one model. Open Models ship with no harness at all. SuperQode gives you one you own: model routing, tools, memory, context, search, approvals, sandboxing, workflows, evals, and optimization, written as a YAML artifact that lives in your repo.

You do four things with a harness you own:

- **Build** it as a versioned file, with a wizard, model-family templates, and a plain-English `explain`.
- **Measure** it with eval scorecards, agentic benchmarks, and regression gates before you trust it.
- **Extend** it across runtimes, providers, MCP, ACP, and A2A without changing the contract.
- **Optimize** it with staged candidates a human adopts, so a failure gets fixed once instead of retried.

Use SuperQode when you want harness independence: the freedom to inspect, version, measure, and improve the system that makes a model useful on your codebase, with any model you choose, open or closed, small or large, local or remote.

Run `superqode` for the terminal workbench, then `:local init` to detect your hardware, generate a local first starter harness, and run a readiness smoke test. The CLI mirrors the same path with `superqode local init --repo .`. Run `superqode local optimize` to benchmark candidates and generate role specific routing for planner, implementer, reviewer, and utility agents.

One TUI and CLI, consistent tool policies, event logging, and session management across every agent type. Define your harness once as a portable spec. Swap runtimes, models, memory, search, or tools without changing your workflow. Run the same contract locally, on a team machine, through remote runtimes, or in CI.

For work that must reliably finish across several harnesses, use a durable WorkOrder. A WorkOrder adds investigator, implementer, synthesizer, reviewer and tester roles, bounded parallel workers, isolated task worktrees, deterministic patch integration, leases and crash recovery, acceptance commands, typed evidence, and an explicit human decision without requiring a web control plane:

```bash
sq work create "Implement and review the authentication fix" \
  --repo . --harness coding \
  --acceptance-test "uv run pytest -q tests/test_auth.py" \
  --queue
sq work worker --id builder-01 --concurrency 2
sq work watch work_...
sq work check work_...
sq work prepare work_...
sq work diff work_...
sq work approve work_... --actor maintainer
sq work merge work_... --actor maintainer --cleanup
```

This is the durable execution layer inside SuperQode's terminal-first Software Factory. Read the [complete Software Factory guide](https://superagentic.ai/superqode/advanced/software-factory/) for the product architecture and end-to-end builder workflow, or [How SuperQode Relates to Omnigent](https://superagentic.ai/superqode/advanced/superqode-vs-omnigent/) for shared ideas, different priorities, remote access, and interoperability.

For controlled unattended work, `sq policy init` enables layered contextual policy, secret-filtered shells, strict network destinations, and named host-bound HTTP credentials. Use `sq harness bench` to publish a reproducible same-model harness comparison, then deliver an audited improvement through `sq harness promote stage`, `canary`, `activate`, and `rollback`.

```bash
cd your-project && superqode
```

## Core Concepts

SuperQode separates agent systems into interchangeable pieces: the **harness** controls runtime, tools, sandbox, memory, search, workflow, approvals, and model policy; the **runtime** executes the work; **tools** expose file, search, edit, shell, MCP, and verification capabilities under policy; and **model policy** controls routing, temperature, reasoning, context, and iteration limits. Change any piece without rewriting the rest.

## Quick Start

### Installation

**Primary (Recommended)**
```bash
# Using uv (best performance)
uv tool install superqode

# Or run without installing
uvx superqode
```

This installs the latest [SuperQode release](https://pypi.org/project/superqode/) from PyPI.

SuperQode uses [uv](https://docs.astral.sh/uv/) for installs, development, and release checks. If uv is new to you, start with the official uv documentation before installing extras or working from source.

Installed releases provide both `superqode` and the shorter `sq` command. They are
equivalent, so humans can use commands such as `sq`, `sq harness list`, and
`sq --harness workbench`; documentation, scripts, and agents can keep using the
explicit `superqode` name.

### Run SuperQode

**Interactive TUI (Explore)**
```bash
cd your-project
superqode
```

Inside the TUI, the local-first MVP path is:

```text
:local init          # detect hardware, generate superqode.local.yaml, run smoke when possible
:local labs          # browse trusted models.dev Labs recommendations
:connect local       # pick Ollama, LM Studio, MLX, DS4, vLLM, or SGLang
:harness superqode.local.yaml
```

> **Local model safety:** Local inference can use substantial CPU, GPU, memory, battery, and disk bandwidth. Do not run local models on hardware that cannot safely support them. Monitor temperature, memory pressure, fan noise, battery, and system responsiveness. Use smaller models, lower context, or hosted/BYOK providers when your machine is constrained. SuperQode provides hardware checks and guardrails, but you are responsible for running local models responsibly on your own hardware.

`superqode.yaml` and `superqode.local.yaml` have different jobs. `superqode.yaml` is project configuration: provider hints, endpoints, MCP servers, memory providers, aliases, and default connection settings. `superqode.local.yaml` is a HarnessSpec: the repeatable run contract for runtime, model policy, tools, sandbox, approvals, checks, workflow, and events. Generate project config with `superqode config init`; generate a harness with `:local init`, `superqode local init --repo .`, or `superqode harness init ...`.

| File | Purpose | Created by |
| --- | --- | --- |
| `superqode.yaml` | Project configuration: providers, endpoints, MCP, memory, defaults | `superqode config init` or `:init` |
| `harness.yaml` | Portable agent run contract | `:harness wizard`, `superqode harness wizard`, or `superqode harness init ...` |
| `superqode.local.yaml` | Local-first HarnessSpec generated for this machine | `:local init` or `superqode local init --repo .` |
| `superqode.airplane.yaml` | Strict no-network HarnessSpec for offline local work | `:local airplane prepare` or `superqode local airplane prepare` |

**Headless coding harness**
```bash
cd your-project
superqode --print "inspect this repository and suggest the smallest next step"
```

SuperQode starts with the built-in `core` harness: a compact prompt and exactly four
model-facing tools, `read`, `write`, `edit`, and `bash`. The former tool-rich native
behavior remains available as `workbench`.

```bash
superqode harness list
superqode harness show core
superqode --harness workbench --print "inspect this repository"
superqode harness use workbench   # persist the project default in superqode.yaml
```

In the TUI, enter `:harness` for a keyboard-navigable recommended catalog, or use
`:harness use core`, `:harness use workbench`, or a maintained model-family preset
such as `:harness use kimi-coding`. Named harnesses, built-in templates, and
HarnessSpec files use the same `--harness` option. Use `:harness customize <name>`
to create a project-owned editable copy. Enter `:harness all` when you need pinned
compatibility or specialized presets.

### Your First Harness Run

A harness is the repeatable contract for how an agent run behaves. In the TUI, create and load your first harness without writing YAML:

```text
:connect local
:harness wizard
```

Press Enter through the defaults for a runnable local coding harness, choose an output file, and answer `yes` when asked whether to load it. If `harness.yaml` already exists, the wizard uses the next available path such as `harness-2.yaml`.

For the CLI path, start with the interactive wizard or the default coding template:

```bash
cd your-project
superqode harness wizard
superqode harness explain --spec harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize the architecture"
```

Template shortcut:

```bash
cd your-project
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize the architecture"
```

Prefer to start from a complete file? See [`examples/harnesses`](examples/harnesses) for ready-to-run specs covering builtin, no-tool, PydanticAI, DeepAgents, RLM Code, OpenAI Agents SDK, Google ADK, Gemma4, and DS4.

After a run, inspect what happened:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

Harness Protocol v1 provides one versioned session and evidence contract for
native Core, direct Python harnesses, and ACP agents. Inspect the reference
adapters or run the deterministic offline conformance suite:

```bash
superqode harness protocol describe
superqode harness protocol conformance
```

An independently installed Python harness needs only one async function and one
entry point:

```toml
[project.entry-points."superqode.harnesses"]
my-harness = "my_package:run"
```

```bash
pip install -e .
superqode harness list
superqode harness run my-harness "review this diff"
superqode harness protocol conformance my-harness
```

See [Harness Protocol v1](docs/advanced/harness-protocol.md) for the Python API,
capability boundaries, canonical events, and current limits.

Use `doctor` before sharing a harness with a team. It checks backend availability, spec compatibility, sandbox policy, event-store readiness, approval support, MCP config paths, and rich event graph support.

### Common Harness Choices

| Goal | Start with |
|------|------------|
| Let SuperQode edit, search, and run shell commands under policy | `superqode harness init app --template coding` |
| Bet on model capability without tools or repository access | `superqode harness init reasoner --template no-tool` |
| Start from an Open Model family pack | `superqode harness list-templates` |
| Generate a local first harness for this machine | `superqode local init --repo .` |

### Optional Runtime Backends

Install only the runtimes you need:

```bash
uv tool install "superqode[adk]"
uv tool install "superqode[openai-agents]"
uv tool install "superqode[codex-sdk]"
uv tool install "superqode[deepagents]"
uv tool install "superqode[pydanticai]"
uv tool install "superqode[rlm-code]"
```

Then select a backend in a spec or at run time:

```bash
superqode harness run --spec harness.yaml --runtime pydanticai --prompt "review this design"
superqode harness run --spec harness.yaml --runtime openai-agents --prompt "make the smallest safe fix"
superqode harness run --spec harness.yaml --runtime codex-sdk --prompt "summarize this repository"
superqode harness run --spec examples/harnesses/rlm-code-lid.yaml --provider ollama --model qwen3:8b --prompt "map this repository with evidence"
```

## Key Features

- **Harness specification**: One portable spec controls runtime, model policy, tools, memory, search, sandbox, approvals, workflow, and output.
- **Harness independence**: Inspect, version, measure, and improve the agent loop as your own repository artifact instead of depending on a locked product harness.
- **Harness Protocol v1**: Run native Core, package-style Python harnesses, and ACP agents through one versioned lifecycle and durable evidence envelope without pretending their optional capabilities are identical.
- **Extensible minimal Core**: Start with only `read`, `write`, `edit`, and `bash`, then opt into trusted Python packages or project plugins that contribute tools, commands, skills, context, lifecycle hooks, permission rules, and providers.
- **Model routing**: Use Open Models or closed models, local endpoints or remote providers, small utility models or large coding models.
- **Local first Open Model support**: Detect local engines, probe context windows, generate starter harnesses, run smoke checks, and benchmark local candidates.
- **Local dynamic workflows with RLM**: Run recursive local-model analysis over large logs, traces, diffs, and repo slices with `context_handle`, `spawn_harness`, and bounded dynamic workflow scripts.
- **First-class RLM Code backend**: Run RLM Code v0.1.11+ `reference`, `repo_evidence`, or `lid` profiles through HarnessSpec and Harness Protocol while preserving root/submodel usage, exposure metrics, and native JSONL trajectories.
- **Measure and optimize**: Use harness tests, eval scorecards, local route optimization, harness optimization, and skill optimization with regression gates.
- **Local code intelligence**: Use bounded reads, local code search, multi repo search, semantic search, offline indexes, and post edit verification.
- **Configurable memory**: Keep local memory by default, then connect provider neutral memory systems when needed.
- **Pluggable runtimes**: Run the same harness on the builtin engine, ADK, OpenAI Agents SDK, Codex SDK, Claude Agent SDK, DeepAgents, PydanticAI, or RLM Code.
- **Policy and safety**: Gate file access, shell commands, network access, approvals, sandboxing, plugins, MCP, and project trust through explicit policy.
- **Headless and CI ready**: Run coding tasks, provider checks, evals, schema validated outputs, event exports, and change summaries from scripts.

### Built for Open Models and local execution

SuperQode is tuned for local and Open Models, where context, tool calling, memory, and search usually decide whether an agent works:

- **Auto context management**: Detects each local model's real loaded context window and compacts before overflow. Inspect or pin it with `:context`.
- **Context economy tools**: Bounded reads, line numbered output, continue hints, output spill files, stale output pruning, and compact previews for long commands.
- **Local search stack**: Register repos with `:workspace add`, search across repos with ripgrep, add local code search, and enable semantic search when needed.
- **Airplane Mode**: Prepare a strict offline harness with local repositories, local model servers, local indexes, cached metadata, and network tools removed.
- **Post edit verification**: Feed fast per file checks back into the agent so it can correct mistakes before moving on.
- **Resilient tool calls**: Repair malformed tool calls, return corrective argument feedback, and block repeated no progress loops.
- **Model aware edit formats**: Support string replacement edits, unified diffs, patch envelopes, shell sessions, and vision attachments where the selected model supports them.
- **Safe parallelism**: Run read only tool batches concurrently while preserving strict order for edits, writes, and shell commands.
- **Harness over MCP**: Expose your HarnessSpec workflows as MCP tools for any MCP client, alongside A2A and ACP servers.

## Developer Workflows

Use SuperQode as a daily coding-agent harness from the TUI or CLI:

```bash
superqode --tui
superqode --print "fix the failing test and summarize the change"
superqode --runtime codex-sdk --print "review this repo"
superqode --connect claude --print "summarize the last change"
```

Inside the TUI, start with `:help` and these commands:

```text
:connect codex        # Codex SDK with local Codex login
:connect claude       # Claude Code through ACP
:connect antigravity  # signed-in Antigravity CLI (Google OAuth/keyring)
:connect byok google  # Google API key path
:connect grok         # Grok Build, xAI's own agent over ACP
:grok api             # SuperQode core/workbench harness on the same subscription
:connect byok         # hosted provider/API-key path
:connect local        # local model provider
:tree                 # saved session branches
:share create         # portable superqode-share-v1 artifact
:export markdown      # copyable transcript export
:trust doctor         # project-local plugins/MCP/hooks audit
:plugins doctor       # non-executing plugin manifest validation
:plan fix the tests   # planning-only review before tools run
:plan approve         # execute the last planned request
:plan edit ...        # adjust the pending request before execution
:memory providers     # local and SpecMem-aware memory status
:memory remember ...  # explicit local project memory
```

CLI equivalents:

```bash
superqode sessions tree
superqode share create <session-id>
superqode share import <artifact.superqode-share.json> --session-id imported
superqode trust doctor
superqode trust yes
superqode plugins add ./my-plugin
superqode plugins doctor
superqode plugins doctor --runtime  # trust-gated import and activation check
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference
superqode memory search "package manager"
superqode memory providers  # local default; optional mem0/cognee/supermemory disabled until configured
```

Find free/local inference paths and current zero-price model routes:

```bash
superqode providers scan-free
superqode providers scan-free --live --source openrouter --limit 20
```

Inside the TUI, use `:providers free` for setup hints or `:providers free --live openrouter` for live zero-price model routes.

See [Developer Workflows](docs/developer-workflows.md) for the full command set.

## How It Works

```
HARNESS LIFECYCLE
━━━━━━━━━━━━━━━━━
1. SPEC       Choose coding, no-tool, local-model, or custom harness behavior
2. MODEL      Resolve policy for Gemma4, DS4, hosted models, or model-only runs
3. RUNTIME    Run on builtin, OpenAI Agents, Google ADK, DeepAgents, or another backend
4. TOOLS      Attach file, search, edit, shell, MCP, or no tools
5. SESSION    Stream events, persist history, compact context, and store runs
6. OUTPUT     Return text, typed data, workflow results, and validation state
```

The default coding harness keeps repository work practical. The no-tool harness lets you bet directly on model capability. Optional runtimes let teams bring their preferred agent framework without replacing the SuperQode harness contract.

## Rich Runtime Observability

SuperQode normalizes runtime-specific streams into one harness event graph:

| Backend | Rich graph events |
|---------|-------------------|
| `builtin` | Model requests, model deltas, tool calls, tool results, approval pauses, final results |
| `pydanticai` | Model deltas, tool calls, tool results, final results, approval pauses |
| `openai-agents` | Model deltas, tool calls, tool results, approval pauses, sandbox markers |
| `codex-sdk` | Model deltas, command output, patch updates, command/file-change results, turn completion |
| `deepagents` | Model deltas, tool calls, subagent activity, memory reads/writes, sandbox file/command events, final results |
| `adk` | Run and stream events with the same graph storage contract |

This gives teams one way to debug runs even when they use different agent frameworks.

## Documentation

For complete guides, configuration options, and API reference:

**[📚 View Full Documentation →](https://superagenticai.github.io/superqode/)**

Highlights:

- [Local Context & Compaction](docs/advanced/local-context.md): context-window detection, adaptive compaction, `:context`
- [Multi-Repo Search & Edit Safety](docs/advanced/multi-repo-search.md): `:workspace`, cross-repo search, post-edit verification
- [Harness System](docs/advanced/harness-system.md): HarnessSpec, checks, and exposing harnesses over MCP

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
Development uses [uv](https://docs.astral.sh/uv/) for dependency management and command execution.

```bash
git clone https://github.com/SuperagenticAI/superqode
cd superqode
uv sync --extra dev --extra docs
uv run pytest
```

## License

[Apache-2.0](LICENSE) - Built by [Superagentic AI](https://super-agentic.ai/) for developers who care about code quality.
