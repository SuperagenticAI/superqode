<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode TUI">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" width="200">
</p>

<h1 align="center">SuperQode</h1>

<p align="center">
  <strong>Multi-agent coding harness for local, BYOK, and ACP workflows</strong><br>
  <em>Connect models, run tools, inspect changes, and keep coding sessions readable.</em><br>
  <strong>Build with agents. Validate with evidence. Ship with confidence.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode?style=flat-square&color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/pyversions/superqode?style=flat-square" alt="Python"></a>
  <a href="https://github.com/SuperagenticAI/superqode/actions"><img src="https://img.shields.io/github/actions/workflow/status/SuperagenticAI/superqode/superqe.yml?style=flat-square&label=CI" alt="CI"></a>
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

**SuperQode** is a coding agent harness for interactive development, local model workflows, BYOK providers, ACP coding agents, and tool-based repository work. It provides a TUI and CLI so developers can connect to the model or agent they prefer, run file/search/edit/shell tools, and get concise summaries of what changed.

**SuperQE** is the quality engineering workflow included with SuperQode. Use it when you want agents to stress, validate, and report on code before release. QE is an important workflow, but SuperQode is first a general coding harness.

**Note (Enterprise):** Enterprise adds deeper automation, evaluation testing, and enterprise integrations.

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
> Note: SuperQE (CLI) requires the Python install above (uv or pip).
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

**Automated QE (CI/CD)**
```bash
cd your-project
superqe init
superqe run . --mode quick
```



## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-agent harness** | Use ACP agents, BYOK providers, and local models from one interface |
| **Developer TUI** | Interactive sessions with wrapped prompts, quiet streaming logs, compact tool activity, and readable change summaries |
| **Headless CLI** | Run coding tasks and provider checks from scripts or terminals |
| **Tool system** | File, search, edit, shell, todo, MCP, and optional Monty Python REPL tools |
| **Provider UX** | Provider doctor, model listing, guided local provider selection, and dynamic OpenCode free model discovery |
| **QE workflows** | Optional SuperQE roles, sandboxes, reports, and release validation |

## How It Works

```
QE SESSION LIFECYCLE
━━━━━━━━━━━━━━━━━━━━
1. SNAPSHOT    → Original code preserved
2. QE SANDBOX  → Agents modify, test, break freely
3. REPORT      → Document findings and fixes
4. REVERT      → All changes removed automatically
5. ARTIFACTS   → QRs and patches preserved
```

**Your original code is ALWAYS restored.**

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
