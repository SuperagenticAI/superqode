<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode TUI">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" width="200">
</p>

<h1 align="center">SuperQode</h1>

<p align="center">
  <strong>Production coding harness for local models, BYOK providers, and pluggable agent runtimes</strong><br>
  <em>Define the harness, choose the runtime, control the tools, and keep coding sessions readable.</em><br>
  <strong>Bring your own model, runtime, tools, and harness.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/pyversions/superqode?style=flat-square" alt="Python"></a>
  <a href="https://github.com/SuperagenticAI/superqode/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-green?style=flat-square" alt="License"></a>
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

**SuperQode** is a production coding-agent harness for interactive development, local model workflows, BYOK providers, ACP coding agents, and tool-based repository work. It provides a TUI and CLI so developers can connect to the model or agent runtime they prefer, run file/search/edit/shell tools under policy, and get concise summaries of what changed.

The v2 direction is harness-first: SuperQode owns the kernel for sessions, tools, runtimes, model policies, sandboxing, typed outputs, workflow execution, validation, events, and backend adapters. Higher-level workflows can be built on top through A2A later without changing the core identity.

**Note (Enterprise):** Enterprise adds deeper automation, evaluation testing, and enterprise integrations.

## Core Concepts

SuperQode separates the pieces of an agent system so teams can change one piece without rewriting the rest.

| Concept | What it means in SuperQode |
|---------|----------------------------|
| **Harness** | The full contract for a run: flavor, model policy, tools, sandbox, workflow, output, events, and validation |
| **Runtime** | The engine that executes the harness, such as the native loop, Google ADK, OpenAI Agents SDK, or DeepAgents |
| **Flavor** | The kind of harness being run, such as tool-rich coding or model-only no-tool |
| **Tools** | Capabilities granted by policy, including file, search, edit, shell, MCP, todo, and validation tools |
| **Model policy** | The model-specific behavior for prompt level, temperature, reasoning, tool surface, history, and iteration limits |
| **Framework adapter** | A bridge that lets an external agent framework run behind the SuperQode harness contract |

The harness is the product contract. Runtimes and framework adapters are execution choices behind that contract.

## Demo Video

Watch the demo: [SuperQode Demo](https://www.youtube.com/watch?v=x2V323HgXRk)

<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner">
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



## Key Features

| Feature | Description |
|---------|-------------|
| **HarnessSpec** | Define coding, no-tool, local-model, and custom harness behavior with one declarative contract |
| **Harness kernel** | Run sessions with normalized events, run records, backend dispatch, typed outputs, and workflow execution |
| **Pluggable runtimes** | Swap the agent loop: SuperQode native, Google ADK, OpenAI Agents SDK, or optional DeepAgents |
| **Developer TUI** | Interactive sessions with wrapped prompts, quiet streaming logs, compact tool activity, and readable change summaries |
| **Headless CLI** | Run coding tasks and provider checks from scripts or terminals |
| **Tool system** | File, search, edit, shell, todo, MCP, and optional Monty Python REPL tools |
| **Sandbox contract** | Use local sandbox policy for read, write, shell, command, grep, glob, and edit access |
| **Typed outputs** | Ask a harness run to return validated structured data using explicit result delimiters |
| **Workflow engine** | Run single, chain, parallel, router, orchestrator, and evaluator-optimizer workflows |
| **Model policies** | First-class Gemma4, DS4, coding, and no-tool policy profiles for local and hosted models |
| **Provider UX** | Provider doctor, model listing, guided local provider selection, and dynamic OpenCode free model discovery |
| **Harness flavors** | Tool-rich coding and model-only no-tool profiles, with room for Bring Your Own Harness specs |

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

## Documentation

For complete guides, configuration options, and API reference:

**[📚 View Full Documentation →](https://superagenticai.github.io/superqode/)**

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/SuperagenticAI/superqode
cd superqode
uv pip install -e ".[dev]"
pytest
```

## License

[AGPL-3.0](LICENSE) - Built by [Superagentic AI](https://super-agentic.ai/) for developers who care about code quality.
