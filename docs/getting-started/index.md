# Getting Started

Welcome to SuperQode, your pluggable multi-agent coding harness. This guide helps you get started with the coding-agent TUI, headless CLI, HarnessSpec workflows, runtime backends, provider setup, local models, and optional validation workflows.

---

## Quick Navigation

<div class="grid cards" markdown>

-   **Installation**

    ---

    Install SuperQode via pip or from source. Set up your environment and verify installation.

    [:octicons-arrow-right-24: Install now](installation.md)

-   **Project Setup**

    ---

    Initialize your project, configure your preferred model, and choose your connection mode.

    [:octicons-arrow-right-24: Setup guide](#project-setup)

-   **TUI Workflow**

    ---

    Interactive Terminal UI for coding-agent sessions, provider selection, tool use, approvals, and harnesses.

    [:octicons-arrow-right-24: TUI guide](#tui-workflow-recommended-for-coding-sessions)

-   **CLI Workflow**

    ---

    Validation commands for automation, CI/CD integration, and batch processing.

    [:octicons-arrow-right-24: CLI guide](#cli-workflow-recommended-for-automation)

-   **Configuration**

    ---

    Configure providers, roles, and settings. Customize SuperQode for your workflow.

    [:octicons-arrow-right-24: Configure](configuration.md)

-   **Troubleshooting**

    ---

    Common issues and solutions. Get help when things go wrong.

    [:octicons-arrow-right-24: Troubleshooting](troubleshooting.md)

</div>

---

## Prerequisites

Before installing SuperQode, ensure you have:

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | Python 3.12 recommended |
| pip | Latest | Or uv for isolated installation |
| Git | 2.25+ | For workspace isolation features |

### Optional Dependencies

| Tool | Purpose |
|------|---------|
| Node.js | JavaScript/TypeScript linting |
| Go | Go project analysis |
| Rust | Rust project analysis |

---

## Installation

=== "uv (Recommended)"

    ```bash
    # Install uv if needed
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Install SuperQode
    uv tool install superqode
    ```

=== "pip"

    ```bash
    pip install superqode
    ```

=== "From Source"

    ```bash
    git clone https://github.com/SuperagenticAI/superqode.git
    cd superqode
    pip install -e .
    ```

### Verify Installation

```bash
# Check version
superqode --version

# View help
superqode --help
```

---

## Project Setup

### Step 1: Initialize Your Project

Navigate to your project directory and initialize SuperQode:

```bash
cd /path/to/your/project
superqode config init
```

This command will:

1. **Create `superqode.yaml`** using the comprehensive role catalog
2. **Enable core, implemented roles** and leave the rest disabled
3. **Let you edit or delete roles** you don’t need

If you want the interactive wizard, use `superqode config init --guided`.

### Step 2: Choose Your Connection Mode

SuperQode supports three connection modes. Choose based on your needs:

#### ACP (Agent Client Protocol) - **Recommended** ⭐

**Best for:** Teams wanting full coding agent capabilities (file editing, shell, MCP tools)

**Why ACP?**
- Full coding agent features (edit files, run shell, use MCP tools)
- Pre-configured agents (Enterprise adds optimized prompt packs)
- No API key management (agents handle it)
- Most powerful for exploratory testing

**Setup:**
```bash
# 1. Install an ACP agent (e.g., OpenCode)
npm i -g opencode-ai

# 2. Edit superqode.yaml to configure
```

**In TUI:**
- Type `:connect` (or `:c` for short) for an interactive picker
- Or directly: `:connect acp opencode`

**In CLI:** `superqode connect acp opencode`

#### BYOK (Bring Your Own Key)

**Best for:** Teams using cloud providers with their own API keys

**Why BYOK?**
- Use your existing API keys (OpenAI, Anthropic, Google, etc.)
- Direct provider integration
- Cost control with your accounts
- Good for automation and CI/CD

**Setup:**
```bash
# 1. Set your API key
export GOOGLE_API_KEY=your-api-key-here
# or
export OPENAI_API_KEY=your-api-key-here
# or
export ANTHROPIC_API_KEY=your-api-key-here

# 2. Edit superqode.yaml to set default provider
```

**In TUI:**
- Type `:connect` (or `:c` for short) for an interactive picker
- Or directly: `:connect byok openai gpt-4o-mini`

**In CLI:** `superqode connect byok openai gpt-4o-mini`

#### Local Models

**Best for:** Privacy-first teams or offline development

**Why Local?**
- Complete privacy (no data leaves your machine)
- No API costs
- Works offline
- Self-hosted infrastructure

**Setup:**
```bash
# 1. Start a local model server (e.g., Ollama)
ollama serve

# 2. Pull a model
ollama pull qwen3:8b

# 3. Edit superqode.yaml to configure
```

**In TUI:**
- Type `:connect` (or `:c` for short) for an interactive picker
- Or directly: `:connect local ollama qwen3:8b`

**In CLI:** `superqode connect local ollama qwen3:8b`

### Step 3: Configure Your Model Choice

Edit `superqode.yaml` to set your preferred connection:

```yaml
superqode:
  version: "2.0"
  team_name: "My validation Team"

# Choose your default mode
default:
  mode: acp  # or "byok" or "local"
  coding_agent: opencode  # for ACP
  # provider: google        # for BYOK
  # model: gpt-4o-mini      # for BYOK
  # provider: ollama         # for Local
  # model: qwen3:8b          # for Local

providers:
  google:
    api_key_env: GOOGLE_API_KEY
  default_model: qwen3:8b
  base_url: http://localhost:11434
```

---

## Understanding the Architecture

### Role-Based Multi-Agent System

SuperQode uses a **role-based multi-agent architecture** where different AI agents specialize in different validation and evaluation tasks:

```
┌─────────────────────────────────────────────────────────┐
│              SuperQode Architecture                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Security   │  │     API      │  │  Performance │ │
│  │   Tester     │  │   Tester     │  │   Tester     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │     Unit     │  │      E2E     │  │  Fullstack   │ │
│  │   Tester     │  │   Tester     │  │  Reviewer    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                          │
│              ↓ Ephemeral Workspace ↓                     │
│                                                          │
│        Original Code → Sandbox → Revert                 │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Key Concepts:**

- **Ephemeral Workspace:** Agents work in isolated worktrees or snapshots. All changes are reverted after the session.
- **Role Specialization:** Each role focuses on specific quality aspects (security, API, performance, etc.)
- **Parallel Execution:** Multiple roles can run simultaneously for comprehensive analysis
- **Artifact Preservation:** Findings, patches, and reports are saved even though code changes are reverted

### Role-Based Workflows Explained

| Role | Purpose | Best For |
|------|---------|----------|
| `security_tester` | Find vulnerabilities (OWASP Top 10, injection, auth) | Pre-deployment security audits |
| `api_tester` | Validate API contracts and endpoints | API-first projects |
| `unit_tester` | Find coverage gaps and edge cases | Code coverage improvement |
| `performance_tester` | Detect bottlenecks (N+1 queries, memory leaks) | Performance-critical apps |
| `e2e_tester` | Test complete user workflows | Frontend/Fullstack apps |
| `fullstack` | Senior validation comprehensive review | Overall quality assessment |

[Learn more about roles →](../concepts/roles.md)

---

## Two Workflows: Choose Your Path

SuperQode offers two distinct workflows designed for different use cases:

---

## TUI Workflow (Recommended For Coding Sessions)

**Best for:** Interactive repository work, focused coding tasks, approvals, and real-time feedback

### Characteristics

- ✅ **Interactive Terminal UI** - Rich, visual interface
- ✅ **Real-time feedback** - See results as they happen
- ✅ **Focused coding** - Ask for small changes and review what happened
- ✅ **Visual navigation** - Browse files, view diffs, explore findings
- ✅ **Session management** - Save and resume sessions
- ✅ **Harness control** - Load reusable specs for tools, runtime, approvals, and events

### Quick Start

```bash
# 1. Launch TUI
superqode

# 2. Connect to your agent (in TUI)
# Option A: Use interactive picker (recommended for first-time users)
:connect
# or type :c for short
# The TUI will guide you through selecting ACP, BYOK, or Local, then show available options

# Option B: Direct connection (if you know exactly what you want)
:connect acp opencode
# or
:connect byok openai gpt-4o-mini
# or
:connect local ollama qwen3:8b

# 3. Load a harness when you want reusable policy
:harness harness.yaml
:status

# 4. Start coding with natural language requests:
# "Summarize this repository and suggest the smallest safe improvement."
# "Find one low-risk cleanup, make the smallest fix, and run the narrowest useful test."
# "Summarize what changed and which tests you ran."

# 5. Approve or reject pending tool calls when policy asks
:approve
:reject

# Note: automated validation sessions are separate CLI workflows:
# superqode qe run . --mode quick   # Quick 60-second scan
# superqode qe run . --mode deep    # Comprehensive 30-minute analysis
```

### TUI Commands Reference

| Command | Description |
|---------|-------------|
| `:connect` or `:c` | Interactive connection picker (recommended) |
| `:connect acp <agent>` | Connect directly to ACP agent |
| `:connect byok <provider> <model>` | Connect directly to BYOK provider |
| `:connect local <provider> <model>` | Connect directly to local model |
| `:harness <path>` | Load a HarnessSpec |
| `:harness status` | Show active harness state |
| `:runtime list` | Show runtime backends |
| `:approve` | Approve a pending tool call |
| `:reject` | Reject a pending tool call |
| `:qe <role>` | Switch to validation role mode (e.g., `:qe security_tester`) |
| `:view <file>` | View file content |
| `:help` | Show all commands |
| `:quit` | Exit TUI |

[Full TUI documentation →](../advanced/tui.md)

---

## CLI Workflow (Recommended for Automation)

**Best for:** CI/CD integration, automated testing, batch processing, and scripting

### Characteristics

- ✅ **Command-line interface** - Easy to script and automate
- ✅ **CI/CD friendly** - JSONL and JUnit XML output
- ✅ **Batch processing** - Run on multiple projects
- ✅ **Non-interactive** - Perfect for scheduled jobs
- ✅ **Configurable** - Everything via config file or flags

### Quick Start

```bash
# 1. Initialize project (first time)
superqode config init

# 2. Edit superqode.yaml with your model choice

# 3. Run validation session
superqode qe run . --mode quick

# 4. Run with specific roles
superqode qe run . --mode deep -r security_tester -r api_tester

# 5. CI/CD output
superqode qe run . --mode quick --jsonl > results.jsonl
superqode qe run . --mode quick --junit results.xml

# 6. View artifacts
superqode qe artifacts .
superqode qe dashboard
```

### Common CLI Commands

```bash
# Quick scan
superqode qe run . --mode quick

# Deep analysis
superqode qe run . --mode deep

# Specific roles
superqode qe run . -r security_tester -r api_tester

# With test generation (Enterprise)
superqode qe run . --mode deep --generate

# With fix suggestions (Enterprise)
superqode qe run . --mode deep --allow-suggestions

# CI-friendly output (Enterprise)
superqode qe run . --mode quick --jsonl
superqode qe run . --mode quick --junit results.xml

# View results (Enterprise)
superqode qe artifacts .
superqode qe dashboard
superqode qe status
```

[Full CLI reference →](../cli-reference/index.md)

---

## When to Use Which Workflow?

### Use TUI When:

- 🎯 Exploring a codebase for the first time
- 🎯 Ad-hoc testing and investigation
- 🎯 Learning how SuperQode works
- 🎯 Need interactive feedback and real-time results
- 🎯 Want to chat with agents and ask questions
- 🎯 Debugging specific issues interactively

### Use CLI When:

- 🤖 Running in CI/CD pipelines
- 🤖 Scheduled quality checks (nightly, weekly)
- 🤖 Batch processing multiple projects
- 🤖 Automated testing workflows
- 🤖 Need structured output (JSONL, JUnit XML)
- 🤖 Scripted or non-interactive environments

---

## Complete Setup Example

Here's a complete example from scratch:

```bash
# 1. Install SuperQode
pip install superqode

# 2. Navigate to your project
cd ~/projects/my-api

# 3. Initialize configuration
superqode config init
# This will:
# - Detect framework (e.g., FastAPI)
# - Create superqode.yaml
# - Suggest recommended roles

# 4. Edit superqode.yaml
nano superqode.yaml
# Set your preferred connection mode and model

# 5. Choose your workflow:

# Option A: TUI (exploratory)
superqode
# Then: :connect acp opencode
# Then: :qe security_tester
# Then: Start asking questions!

# Option B: CLI (automation)
superqode qe run . --mode quick -r security_tester
```

---

## Next Steps

1. **[Project Setup Guide](quickstart.md)** - Detailed step-by-step setup
2. **[Your First Session](first-session.md)** - Complete walkthrough
3. **[Configuration Reference](configuration.md)** - Customize SuperQode
4. **[Understanding Modes](../concepts/modes.md)** - Deep dive into ACP, BYOK, Local
5. **[Role-Based Workflows](../concepts/roles.md)** - Learn about each role
6. **[CI/CD Integration](../integration/cicd.md)** - Add to your pipeline

---

## Getting Help

- Run `superqode --help` for command help
- Use `:help` in the TUI for interactive help
- Check the [CLI Reference](../cli-reference/index.md) for detailed command documentation
