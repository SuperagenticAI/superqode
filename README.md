<p align="center">
   <img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/docs/assets/superqode.png" alt="SuperQode Logo" width="200">
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

## Quick Start

SuperQode: A TUI and coding agent harness for interactive exploration

```bash
# Install
uv tool install superqode

# Initialize & run
cd your-project
superqode
```
Follow the TUI help commands

SuperQE : A CLI for automated QE in CI/CD

```bash
# Install
uv tool install superqode

# Initialize & run
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

[AGPL-3.0](LICENSE) — Built with ❤️ for developers who care about code quality.
