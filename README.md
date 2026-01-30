<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode.png" alt="SuperQode TUI">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" width="200">
</p>

<h1 align="center">SuperQode</h1>

<p align="center">
  <strong>Superior Quality-Oriented Agentic Software Development</strong><br>
  <em>Orchestrate, Validate, and Deploy Agentic Software with Unshakable Confidence.</em><br>
  <strong>Let agents break the code. Prove the fix. Ship with confidence.</strong>
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



## What is SuperQode and SuperQE?

**SuperQE** is the quality paradigm and automation CLI: Super Quality Engineering for Agentic AI. It uses QE coding agents to break and validate code written by coding agents. SuperQE can spawn a team of QE agents with different testing personas in a multi-agent setup to stress your code from many angles.

**SuperQode** is the agentic coding harness designed to drive the SuperQE process. It delivers a Superior and Quality Optimized Developer Experience as a TUI for interactive development, debugging, and exploratory QE. SuperQode can also be used as a general development harness beyond QE.

**Note (Enterprise):** Enterprise adds powerful automation, deep evaluation testing, and enterprise integrations (OpenClaw first; more bot integrations coming).

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
| 🎯 **Quality-First** | Breaks and validates code, not generates it |
| 🛡️ **Sandbox Execution** | Destructive testing without production risk |
| 🤖 **Multi-Agent QE** | Cross-validation from multiple AI perspectives |
| 📋 **Quality Reports** | Forensic artifacts documenting findings |
| 👥 **Human-in-the-Loop** | All fixes are suggestions for human review |
| 🏠 **Self-Hosted** | BYOK, privacy-first, no SaaS dependency |

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

[AGPL-3.0](LICENSE) — Built by [Superagentic AI](https://super-agentic.ai/) for developers who care about code quality.
