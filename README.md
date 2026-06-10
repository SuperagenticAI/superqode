<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" width="200">
</p>

<h1 align="center">SuperQode</h1>

<p align="center">
  <strong>Your Portable Universal Coding Agent Harness.</strong><br>
  <em>Define your harness, connect any agent - local, BYOK, ACP, A2A. The only harness supporting ACP + MCP + A2A with local model optimization.</em>
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

---

## What is SuperQode?

SuperQode is the **Portable Universal Coding Agent Harness** - define your own harness, connect any agent: local models, BYOK providers, ACP agents, or A2A workflows. It is the only harness that supports all major protocols (ACP + MCP + A2A) with deep local model optimization.

One TUI and CLI, consistent tool policies, event logging, and session management across every agent type. Define your harness once as a portable spec. Swap runtimes, models, or tools without changing your workflow. Run the same contract locally, on a team machine, or in CI.

```bash
cd your-project && superqode
```

## Core Concepts

SuperQode separates agent systems into interchangeable pieces: the **harness** (run contract: runtime, tools, sandbox, model policy), the **runtime** (execution engine: builtin, ADK, OpenAI Agents SDK, Codex SDK, DeepAgents, or PydanticAI), **tools** (file/search/edit/shell/MCP under policy), and **model policy** (temperature, reasoning, iteration limits). Change any piece without rewriting the rest.

## Demo Video

Watch the demo: [SuperQode Demo](https://www.youtube.com/watch?v=x2V323HgXRk)

<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode TUI">
</p>

## Quick Start

### Installation

**Primary (Recommended)**
```bash
# Using uv (best performance)
uv tool install superqode

# Or using pip
pip install superqode
```

**Alternate (No Python Required, SuperQode TUI Only)**
```bash
# Using Homebrew (macOS/Linux)
brew install SuperagenticAI/superqode/superqode

# Using Curl script
curl -fsSL https://super-agentic.ai/install.sh | bash
```

### Run SuperQode

**Interactive TUI (Explore)**
```bash
cd your-project
superqode
```

**Headless coding harness**
```bash
cd your-project
superqode --print "inspect this repository and suggest the smallest next step"
```

### Your First Harness Run

A harness is the repeatable contract for how an agent run behaves. Start with the default coding harness:

```bash
cd your-project
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize the architecture"
```

Prefer to start from a complete file? See [`examples/harnesses`](examples/harnesses) for ready-to-run specs covering builtin, no-tool, PydanticAI, DeepAgents, OpenAI Agents SDK, Google ADK, Gemma4, and DS4.

After a run, inspect what happened:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

Use `doctor` before sharing a harness with a team. It checks backend availability, spec compatibility, sandbox policy, event-store readiness, approval support, MCP config paths, and rich event graph support.

### Common Harness Choices

| Goal | Start with |
|------|------------|
| Let SuperQode edit, search, and run shell commands under policy | `superqode harness init app --template coding` |
| Bet on model capability without tools or repository access | `superqode harness init reasoner --template no-tool` |
| Optimize for local Gemma4 coding | `superqode harness init local --template gemma4-coding` |
| Optimize for fast DS4 local iteration | `superqode harness init fast --template ds4-fast-local` |

For DeepSeek V4 Flash on local hardware, prefer the DS4 provider over a generic MLX server:

```bash
superqode providers ds4 server
superqode -p --provider ds4 --model deepseek-v4-flash "review this repo"
```

### Optional Runtime Backends

Install only the runtimes you need:

```bash
pip install "superqode[adk]"
pip install "superqode[openai-agents]"
pip install "superqode[codex-sdk]"
pip install "superqode[deepagents]"
pip install "superqode[pydanticai]"
```

Then select a backend in a spec or at run time:

```bash
superqode harness run --spec harness.yaml --runtime pydanticai --prompt "review this design"
superqode harness run --spec harness.yaml --runtime openai-agents --prompt "make the smallest safe fix"
superqode harness run --spec harness.yaml --runtime codex-sdk --prompt "summarize this repository"
```

## Key Features

- **Universal harness** — One portable spec controls runtime, model, tools, sandbox, approvals, and output for any agent
- **Pluggable runtimes** — Swap between builtin, Google ADK, OpenAI Agents SDK, Codex SDK, DeepAgents, or PydanticAI
- **Agent-agnostic TUI** — Same interface for Claude Code, Codex, opencode, local models, or BYOK providers
- **Event graph** — Normalized model, tool, approval, sandbox, and subagent events across all runtimes
- **Sandbox policy** — Granular read/write/shell/command access control per project
- **Harness doctor** — Preflight backend installation, spec compatibility, sandbox policy, MCP config, and graph readiness
- **Portable specs** — Share `harness.yaml` with your team — run the same contract everywhere
- **Headless CLI** — Run coding tasks and provider checks from scripts or CI
- **Developer workflows** — Session tree, share artifacts, project trust, plugins, memory, and transcript export

### Optimized for local models

SuperQode is tuned to get the best out of local models (≈10B–120B), where context is the usual breaking point:

- **Auto context management** — detects each local model's *real loaded* context window (Ollama, llama.cpp, LM Studio, vLLM, DS4) and compacts the conversation before it overflows, automatically. Inspect or pin it with `:context`.
- **Context-economy tools** — reads are bounded and line-numbered with explicit continue-from hints; oversized command output is spilled to disk in full and the model gets a head/tail preview plus the path (nothing is ever lost to truncation); stale tool outputs are pruned for free before any LLM summarization.
- **Multi-repo search** — register repos with `:workspace add` and search across all of them in one fast ripgrep pass; grep/glob use structured output and report truncation. Absolute paths are permission-gated.
- **Post-edit verification** — after the agent edits a file, fast per-file checks (ruff, eslint, gofmt, JSON/YAML) feed findings back so it self-corrects before moving on.
- **Resilient tool calls** — dangling, malformed, or badly-encoded tool calls (common on smaller local models) are repaired; unparseable arguments return corrective feedback instead of executing with empty args; a doom-loop guard blocks repeated identical calls and stops runs that refuse to move on.
- **Native model dialects** — models edit in the format they were trained on: string-replacement edits with 10 fallback strategies, unified diffs, or codex-style `apply_patch` envelopes (GPT-5.x / local gpt-oss) — including `apply_patch` heredocs typed into bash. `shell_session` drives REPLs, dev servers, and interactive prompts across turns; `view_image` feeds screenshots to vision-capable local models like Gemma 4.
- **Safe parallelism** — read-only tool batches run concurrently; anything that mutates (edit, write, shell) runs strictly in call order, so parallel tool calls can never race your files.
- **Calm by default** — `:thinking` (Ctrl+T) folds noisy per-iteration logs into a live status with a tidy per-tool trace; flip to verbose anytime.
- **Harness over MCP** — `superqode mcp` exposes your HarnessSpec workflows as MCP tools for any MCP client, alongside the A2A and ACP servers.

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
:connect antigravity  # local Antigravity CLI handoff
:connect byok         # hosted provider/API-key path
:connect local        # local model provider
:tree                 # saved session branches
:share create         # portable superqode-share-v1 artifact
:export markdown      # copyable transcript export
:trust doctor         # project-local plugins/MCP/hooks audit
:plugins doctor       # plugin manifest validation
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
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference
superqode memory search "package manager"
superqode memory providers  # local default; optional mem0/cognee/supermemory disabled until configured
```

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

- [Local Context & Compaction](docs/advanced/local-context.md) — context-window detection, adaptive compaction, `:context`
- [Multi-Repo Search & Edit Safety](docs/advanced/multi-repo-search.md) — `:workspace`, cross-repo search, post-edit verification
- [Harness System](docs/advanced/harness-system.md) — HarnessSpec, checks, and exposing harnesses over MCP

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/SuperagenticAI/superqode
cd superqode
uv pip install -e ".[dev]"
pytest
```

## License

[Apache-2.0](LICENSE) - Built by [Superagentic AI](https://super-agentic.ai/) for developers who care about code quality.
