# SuperQode

<p align="center">
  <strong>SuperQE: Super Quality Engineering for Agentic AI.</strong><br>
</p>

<p align="center">
  Licensed under the AGPL-3.0
</p>

<p align="center">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode" alt="PyPI version"></a>
  <a href="https://github.com/SuperagenticAI/superqode/actions"><img src="https://img.shields.io/github/actions/workflow/status/SuperagenticAI/superqode/superqe.yml" alt="CI Status"></a>
</p>

---

## What is SuperQode and SuperQE?

SuperQode is a quality-oriented harness and orchestration layer for coding agents. The name stands for
**Superior Quality Oriented Developer Experience**. It can be used for development, quality engineering,
and DevOps tasks, but it is optimized for quality engineering.

SuperQE is the agentic QA paradigm for AI-written software: multiple QE agents attack and validate code
in sandboxes before it ships. It is not test generation; it is adversarial validation with evidence,
where humans remain in control.

**SuperQE** is the quality paradigm and automation CLI: **Super Quality Engineering for Agentic AI**. It uses QE coding agents to break and validate code written by coding agents. SuperQE can spawn a team of QE agents with different testing personas in a multi-agent setup to stress your code from many angles.

**SuperQode** is the agentic coding harness designed to drive the SuperQE process. It delivers a **Superior and Quality Optimized Developer Experience** as a TUI for interactive development, debugging, and exploratory QE. SuperQode can also be used as a general development harness beyond QE.

One install ships both entrypoints: `superqode` (TUI) and `superqe` (CLI).
SuperQE runs cleanly in CI/CD pipelines, while SuperQode drives SuperQE for interactive workflows. You can also use each independently.

```bash
# After install, in your repo:
superqe init
superqe run . --mode quick

# Start the developer TUI (optional, for interactive workflows)
superqode
```

`superqe init` creates a comprehensive role catalog in `superqode.yaml`. Disable or delete roles you don’t need.

**Core Philosophy:** *Let agents break the code. Prove the fix. Ship with confidence.*

!!! warning "Safe Usage"
    Run SuperQode in a **sandboxed or controlled environment** (CI, staging, or isolated worktrees). It **NEVER modifies production code by default**; all changes are suggestions for human review.

### Why SuperQode?

**The Problem:**
- **AI Coding Has Outpaced QA** - Code is written faster than humans can meaningfully test it
- **Existing AI Tools Stop at Code Review** - They don't actively break code, perform destructive testing, or prove production readiness
- **QE Is Treated as Reporting, Not Problem Solving** - Traditional QA optimizes for tickets, not validated fixes or proof of improvement
- **Agentic QE Cannot Be Retrofitted** - Legacy QA systems weren't designed for autonomous agents

**The Solution: SuperQE + SuperQode**
**SuperQE** is the automation engine: AI agents aggressively attack and test code in sandbox environments, propose fixes, prove improvements, and validate production readiness before humans approve release. **SuperQode** is the interactive TUI that drives exploratory workflows and agent orchestration for developers.

Unlike incumbent testing tools that retrofit AI onto legacy architectures, SuperQode is built **from first principles for Agentic QE**.

**Let agents fight agents. Humans decide.**

## ✨ Key Features

### 🎯 **Quality-First, Not Code-First**
SuperQode focuses on **breaking and validating code**, not generating it. All fixes are suggested, validated, and proven—never auto-applied.

### 📋 **Quality Reports (QRs)**
Research-grade forensic artifacts that document **what failed, how it was discovered, why it matters, and whether fixes are provably better**.

### 🛡️ **Sandbox-First Execution**
Agents can perform **destructive testing, chaos experiments, and stress tests** in isolated environments without risk to production.

### 🤖 **Multi-Agent QE Architecture**
Multiple agents with different models **cross-validate findings, compete to surface issues, and prevent blind spots**.

### ⚙️ **User-Defined Harness**
**No opinionated QA workflows**—define testing harnesses, quality gates, and business-specific validation logic.

### 👥 **Human-in-the-Loop**
SuperQode **reports findings only**. Humans approve, reject, or ignore. Zero automated code modification.

### 🏠 **Self-Hosted & Privacy-First**
- Runs in your infrastructure
- BYOK (Bring Your Own Key) model support
- No SaaS dependency
- Your data never leaves your environment

## 🔄 Ephemeral Workspace Model

SuperQode uses **ephemeral workspaces** that snapshot changes and revert them at the end of each session. When enabled, isolation can use git worktrees for deeper sandboxing. Note: worktrees write to `.git/worktrees`, so only opt in if you're comfortable with git metadata changes.

```
QE SESSION LIFECYCLE
━━━━━━━━━━━━━━━━━━━━
1. SNAPSHOT    Original code preserved
2. QE SANDBOX  Agents modify, test, break freely
3. REPORT      Document findings and fixes
4. REVERT      All changes removed automatically
5. ARTIFACTS   QRs and patches preserved
```

**Your original code is ALWAYS restored** - agents explore freely but never permanently modify production code.

### Allow Suggestions Mode (Opt-In)

For advanced usage, you can enable `allow_suggestions` mode where agents demonstrate fixes:

```yaml
qe:
  allow_suggestions: true  # OFF by default
```

When enabled, agents can:
1. **Detect bugs** in sandbox environment
2. **Fix issues** and verify fixes work
3. **Prove improvements** with evidence
4. **Generate patches** for human review
5. **Revert all changes** automatically

**Safety guarantee:** Even with suggestions enabled, your original code is always preserved.

## 🚀 Quick Start

### Prerequisites
- **Python**: 3.12 or higher
- **Git**: 2.30 or higher
- **Installer**: `uv` (recommended) or `pip`

### Installation

#### Recommended: uv (Isolated Tool Install)
```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install SuperQode
uv tool install superqode

# Verify installation
superqode --version
superqe --version
```

#### Alternative: pip (Virtual Environment)
```bash
# Create virtual environment (recommended)
python3 -m venv ~/.superqode-venv
source ~/.superqode-venv/bin/activate

# Install SuperQode
pip install superqode

# Verify installation
superqode --version
superqe --version
```

### Setup API Keys (BYOK Mode)

Set your API keys as environment variables:

```bash
# Anthropic (recommended)
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Google AI
export GOOGLE_API_KEY=...

# Add to your shell profile (~/.bashrc or ~/.zshrc)
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc
```

### First QE Session
```bash
# Navigate to your project
cd /path/to/your/project

# Initialize project configuration
superqe init

# Connect to a provider (choose one):
superqode connect acp opencode          # ACP mode (recommended)
superqode connect byok anthropic         # BYOK with Anthropic
superqode connect local ollama qwen3:8b  # Local models

# Run quick quality scan
superqe run . --mode quick

# Run comprehensive deep analysis
superqe run . --mode deep --verbose

# Start interactive TUI
superqode
```

### Example Output
```
╭─────────────────────────────────────────────────────╮
│                 QE Session Complete                  │
├─────────────────────────────────────────────────────┤
│ Duration: 45.2s                                      │
│ Roles Run: 3 (security_tester, api_tester, fullstack)│
│ Findings: 5 (1 critical, 2 high, 2 medium)          │
├─────────────────────────────────────────────────────┤
│ Artifacts Generated:                                 │
│   • QR: .superqode/qe-artifacts/qr-20240118.json      │
╰─────────────────────────────────────────────────────╯
```

**Artifacts are saved to `.superqode/qe-artifacts/`** containing:
- Quality Reports (QR) with detailed findings
- Evidence and metadata for findings

### Optional Add-ons
SuperQode can be extended with optional add-ons such as suggested fixes, verified patches, test generation, and advanced dashboards. These are designed to layer on without changing the core safety model.

**BYOK Cost Note:** SuperQode is self-hosted. You are responsible for model/API infra costs.

### SuperOpt (Optional, Config-Flagged)

SuperOpt is included as a core dependency but only runs if enabled in `superqode.yaml`:

```yaml
superqode:
  qe:
    optimize:
      enabled: true
      command: "python3.12 -m superqode.integrations.superopt_runner --trace {trace_path} --out .superqode/superopt/env.json"
```

## 👥 Target Users

SuperQode is designed for:

| Segment | Description |
|---------|-------------|
| **Startups** | With CI/CD maturity, need quality without QE headcount |
| **SMEs** | Limited or no dedicated QE team |
| **Teams using AI coding agents** | Need quality validation for generated code |
| **Engineering Teams** | Want to operationalize SuperQE paradigm |

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup
```bash
git clone https://github.com/SuperagenticAI/superqode
cd superqode
uv pip install -e .
```

### Areas for Contribution
- QE role implementations and agent mappings
- TUI improvements and UX enhancements
- Documentation and examples
- Test coverage and validation
- Performance optimizations
- Integration with additional AI providers

### Code of Conduct
See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

### Future Integration Layers (Coming Soon)
- **SuperQode SpecMem**: Agent memory system for QE context persistence
- **SuperQode CodeOptiX**: Agent evaluation and optimization loops
- **Enhanced MCP Support**: Model Context Protocol integrations
- **CI/CD Integrations**: GitHub Actions, GitLab CI, Jenkins plugins


## 🙋 Support & Community

- **Issues**: [GitHub Issues](https://github.com/SuperagenticAI/superqode/issues)
- **Discussions**: [GitHub Discussions](https://github.com/SuperagenticAI/superqode/discussions)
- **Documentation**: [Full Docs](https://superagenticai.github.io/superqode)
- **License**: [AGPL-3.0](LICENSE)

---

<p align="center">
  <em>Built with ❤️ for developers who care about code quality</em>
</p>
