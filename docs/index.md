# SuperQode

<div class="hero-section" markdown>

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" style="margin-bottom: 1.5rem;" />

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" style="max-height: 150px; margin-bottom: 1.5rem;" />

# **SuperQode**

### Multi-agent coding harness for local, BYOK, and ACP workflows.

Connect coding agents and models, run repository tools, inspect changes, and keep interactive coding sessions readable. SuperQE remains available for teams that want agent-driven quality engineering and release validation.

<p class="tagline">Build with agents. Validate with evidence. Ship with confidence.</p>

[:octicons-rocket-24: Get Started](getting-started/installation.md){ .md-button .md-button--primary }
[:octicons-book-24: Learn Concepts](concepts/index.md){ .md-button }
[:octicons-code-24: CLI Reference](cli-reference/index.md){ .md-button }

[Demo video](https://www.youtube.com/watch?v=x2V323HgXRk)

</div>

---

## What is SuperQode?

**SuperQode** is a coding agent harness for interactive development, headless coding tasks, local model workflows, BYOK providers, and ACP coding agents. It gives developers one place to connect models, execute file/search/edit/shell tools, review concise summaries, and continue work without noisy output.

**SuperQE** is the quality engineering workflow included with SuperQode. Use it when you want coding agents to stress, validate, and report on code before release. QE is a supported workflow, not the only purpose of SuperQode.

**Note (Enterprise):** Enterprise adds deeper automation, evaluation testing, and enterprise integrations.

### Why SuperQode Exists

AI coding agents have changed how software is written, but the developer experience around them is still fragmented. Teams often need one tool for local models, another for cloud APIs, another for ACP agents, and another set of scripts for validation. SuperQode brings those workflows into a single harness.

- Use local, BYOK, and ACP providers from one interface
- Keep tool calls compact by default, with verbose output when needed
- See provider setup hints and model capabilities before connecting
- Run coding sessions interactively or headlessly
- Use SuperQE when release validation needs stronger evidence

SuperQode is designed to be practical first: connect quickly, let the agent use tools, see what happened, and keep control of your repository.

### What Is SuperQE?

SuperQE (Super Quality Engineering) is a quality methodology for agentic software:

- AI agents act as Quality Engineers
- Multiple agent personas attack code from different angles
- Failures are discovered through exploration and adversarial testing
- Fixes are verified with evidence, not assumed correct
- Humans remain the final decision-makers

SuperQE is not test generation. It is adversarial validation with reproducible evidence.

### What SuperQode Provides

- A TUI (`superqode`) for interactive coding-agent sessions
- A headless CLI for coding tasks and provider checks
- ACP, BYOK, and Local provider modes
- Dynamic OpenCode free model discovery instead of hardcoded free model lists
- Optional Monty-backed `python_repl` tool for controlled interpreter-style work
- Compact TUI tool display for search, file, shell, edit, and Python REPL calls
- SuperQE workflows for sandboxed validation, reports, and release checks

One install ships both entrypoints. You can use them together or independently.

### How SuperQode Works (Lifecycle)

1. SNAPSHOT -> preserve original code
2. SANDBOX -> agents attack, test, and experiment freely
3. REPORT -> produce Quality Reports with evidence
4. REVERT -> restore the original repo state
5. ARTIFACTS -> keep QRs, traces, and patches separately

Agents are free to break things - your repo is always restored.

### Design Principles

- Quality-first, not code-first
- Agents break, humans decide
- Safety by default
- Evidence over opinions
- Self-hosted and privacy-first


SuperQode runs interactive and headless coding workflows. SuperQE runs cleanly in CI/CD pipelines when you need release validation.

What you get out of a run:

- A QR with prioritized findings, reproduction steps, and collected evidence
- Optional (Enterprise): verified patch suggestions and generated tests

Safety model: by default, SuperQode does not modify your repo. All exploratory changes happen in a sandbox and are reverted; humans decide what to apply.

```bash
# After install, in your repo:
superqe init

# Start the developer TUI
superqode

# Or run automated QE CLI
superqe run . --mode quick
```

`superqe init` creates a comprehensive role catalog in `superqode.yaml`. Disable or delete roles you do not need.

---

## Quick Install

```bash
pip install superqode
```

Verify installation:

```bash
superqode --version
superqe --version
```

[:octicons-arrow-right-24: Full installation guide](getting-started/installation.md)

---

## Deployment Options

SuperQode OSS is self-hosted. You are responsible for model/API infra costs.
For Enterprise capabilities (including integrations like OpenClaw, with more coming), see
`enterprise/index.md`.

---

## How It Works

SuperQode uses an **ephemeral workspace model** that enables fearless, exhaustive testing while ensuring your original code is always preserved:

```
┌─────────────────────────────────────────────────────────────┐
│                    QE SESSION LIFECYCLE                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. SNAPSHOT         Original code preserved                 │
│        ↓                                                     │
│  2. QE SANDBOX       Agents freely modify, inject tests,    │
│        │             run experiments, break things           │
│        ↓                                                     │
│  3. REPORT           Document what was done, what was found │
│        ↓                                                     │
│  4. REVERT           All changes removed, original restored │
│        ↓                                                     │
│  5. ARTIFACTS        QRs, patches, tests preserved          │
│                      (in .superqode/qe-artifacts/)          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

Within the sandbox, agents may:

- Perform destructive and adversarial testing
- Simulate malicious or edge behaviors
- Stress CPU, memory, I/O, and concurrency
- Run linters, fuzzers, profilers, and analyzers
- Explore undefined and rare failure paths

This enables **fearless, exhaustive testing** - agents explore freely while your original code remains untouched.

[:octicons-arrow-right-24: Learn more about workspaces](concepts/workspace.md)

---

## Who is This For?

<div class="grid cards" markdown>

-   **Startups**

    ---

    Need a practical coding harness for agent-assisted development, provider experimentation, and release checks.

    *Fast-moving teams standardizing agentic development workflows*

-   **SMEs**

    ---

    Need local, BYOK, and cloud model access without building a custom harness.

    *Growing companies using agents while keeping infrastructure flexible*

-   **Teams Using AI Coding Agents**

    ---

    Need a stronger coding loop than a single chat box: tool execution, readable summaries, provider selection, and optional validation.

    *Teams using GitHub Copilot, Cursor, or other AI coding tools*

-   **Engineering Teams**

    ---

    Want one developer-facing interface for coding sessions, provider checks, local models, and SuperQE release validation.

    *Engineering teams adopting Agentic Quality Engineering methodology*

</div>

---

## Key Features

<div class="grid cards" markdown>

-   **Sandbox-First Testing**

    ---

    All testing happens in isolated ephemeral workspaces. Your code is **never modified** without explicit consent. Changes are always reverted.

    [:octicons-arrow-right-24: Learn about workspaces](concepts/workspace.md)

-   **Multi-Agent Orchestration**

    ---

    Multiple AI agents with different roles and perspectives attack your code simultaneously, reducing blind spots and increasing coverage.

    [:octicons-arrow-right-24: Explore QE roles](concepts/roles.md)

-   **Quality Reports (QRs)**

    ---

    Research-grade forensic reports with evidence, reproduction steps, root cause analysis, and verified fix suggestions.

    [:octicons-arrow-right-24: Understand QRs](concepts/qr.md)

-   **Three Connection Modes**

    ---

    Connect via BYOK (100+ providers), ACP (coding agents), or Local models. Use your preferred infrastructure.

    [:octicons-arrow-right-24: See all modes](concepts/modes.md)

-   **Configurable Roles**

    ---

    Define custom QE roles with specific personas, job descriptions, and testing focus areas tailored to your needs.

    [:octicons-arrow-right-24: Configure roles](configuration/team.md)

-   **CI/CD Integration**

    ---

    JSONL streaming, JUnit XML output, and GitHub Actions support for seamless integration into your pipeline.

    [:octicons-arrow-right-24: Integrate with CI](integration/cicd.md)

</div>

---

## Quick Start

=== "Installation"

    ```bash
    # Install from PyPI
    pip install superqode

    # Verify installation
    superqode --version
    ```

=== "Initialize Configuration"

    ```bash
    # Create repo configuration (recommended)
    superqe init
    ```

=== "Interactive TUI"

    ```bash
    # Start the developer TUI
    superqode
    ```

    Follow the on-screen instructions to explore, debug, and run QE sessions interactively.

=== "Automated QE (CLI)"

    ```bash
    # Quick scan (60s timeout)
    superqe run . --mode quick

    # Deep QE with test generation (Enterprise)
    superqe run . --mode deep --generate

    # Specific roles
    superqe run . -r security_tester -r api_tester
    ```

---

## Three Execution Modes

SuperQode supports three distinct modes for connecting to AI models:

| Mode | Description | Use Case |
|------|-------------|----------|
| **ACP** | Agent Client Protocol - Full coding agent integration | OpenCode, Claude Code (advanced capabilities) |
| **BYOK** | Bring Your Own Key - Direct LLM API calls via LiteLLM | Cloud providers (Google Gemini, Anthropic, OpenAI, etc.) |
| **Local** | Local/self-hosted models | Ollama, vLLM, LM Studio (privacy-first) |

[:octicons-arrow-right-24: Learn more about modes](concepts/modes.md)

---

## QE Execution Modes

| Mode | Timeout | Depth | Test Generation | Use Case |
|------|---------|-------|-----------------|----------|
| **Quick Scan** | 60s | Shallow | No | Pre-commit, PR checks |
| **Deep QE** | 30min | Full | Enterprise | Pre-release, audits |

```bash
# Quick scan for fast feedback
superqe run . --mode quick

# Deep QE for thorough analysis (Enterprise)
superqe run . --mode deep --generate --allow-suggestions
```

---

## Code Modification Policy

!!! warning "Default Behavior: Read-Only"
    **SuperQode NEVER modifies user-submitted production code by default.** All fixes are suggested, never auto-applied.

When `allow_suggestions` is enabled, SuperQode follows a strict workflow:

```
1. DETECT BUG      → Agent finds issue in submitted code
2. FIX IN SANDBOX  → Agent modifies code to fix bug
3. VERIFY FIX      → Run tests, validate fix works
4. PROVE BETTER    → Demonstrate improvement with evidence
5. REPORT OUTCOME  → Document findings and observations
6. ADD TO QR      → Record in Quality Report
7. REVERT CHANGES  → Restore original submitted code
8. USER DECIDES    → Accept/reject suggested patches
```

[:octicons-arrow-right-24: Learn about suggestions](concepts/suggestions.md)

---

## Why SuperQode?

### The Problem

1. **Agentic Coding Is Fragmented** - Developers often switch between local model servers, cloud APIs, ACP agents, shell scripts, and separate validation tools.

2. **Tool Output Gets Noisy** - Raw file reads, search output, shell output, and tool traces can bury the useful summary of what the agent actually changed.

3. **Provider Setup Is Hard to Trust** - Model availability, free tier status, tool support, context windows, and API key setup change over time.

4. **Release Validation Still Matters** - AI-assisted code still needs evidence before humans approve production changes.

### The Solution: SuperQode

SuperQode provides a practical coding-agent harness where:

- Developers can connect ACP agents, BYOK providers, and local models
- The TUI shows compact tool activity by default and can expand when needed
- Provider doctor and model pickers show setup status and capability labels
- Dynamic provider discovery avoids stale hardcoded free model lists
- Optional tools such as Monty add controlled interpreter-style execution
- SuperQE remains available for sandboxed quality engineering and release checks

**Build with agents. Validate with evidence. Keep control.**

---

## Key Differentiators

1. **Harness-first** - Coding sessions, provider access, and tools are the primary workflow
2. **Provider-flexible** - ACP agents, BYOK providers, and local models use one interface
3. **Readable by default** - Tool calls and file activity stay compact unless verbose output is requested
4. **Dynamic model discovery** - Free model lists and provider metadata can refresh from source systems
5. **Tool-rich** - File, search, edit, shell, MCP, todo, and optional Monty tools are available
6. **Human-controlled** - Changes and suggestions remain visible for review
7. **Self-hosted and privacy-first** - Your code stays in your environment
8. **QE-ready** - SuperQE workflows add deeper validation when needed

---

## Supported Providers

=== "ACP Agents"

    | Agent | Capabilities | Status |
    |-------|--------------|--------|
    | OpenCode | File editing, shell, MCP, 75+ providers | Supported |
    | Amp | File editing, shell, MCP, multi-turn | Supported |
    | Claude Code | Native Claude integration | Supported |
    | Codex | OpenAI code generation | Supported |
    | Gemini CLI | Google's reference ACP implementation | Supported |

=== "Cloud Providers (BYOK)"

    | Provider | Models | Free Tier |
    |----------|--------|-----------|
    | Google AI | Gemini 3 Pro, Gemini 3, Gemini 2.5 Flash | Yes |
    | Anthropic | Claude Opus 4.5, Sonnet 4.5, Haiku 4.5 | No |
    | OpenAI | GPT-5.4, GPT-4o, o1 | No |
    | Deepseek | Deepseek V3, Deepseek R1 | Yes |
    | Groq | Llama 3.3, Mixtral | Yes |
    | Together AI | 200+ open models | Limited |

=== "Local Providers"

    | Provider | Description |
    |----------|-------------|
    | Ollama | Easy local model deployment |
    | LM Studio | GUI-based local models |
    | vLLM | High-performance inference |
    | DS4 | Local DeepSeek V4 Flash |
    | llama.cpp | C++ inference engine |

[:octicons-arrow-right-24: See all providers](providers/index.md)

---

## Documentation Structure

<div class="grid" markdown>

**[Getting Started](getting-started/index.md)**
Installation, quick start, and first coding session

**[Concepts](concepts/index.md)**
Core concepts: modes, workspace, roles, QRs

**[CLI Reference](cli-reference/index.md)**
Complete command documentation

**[Configuration](configuration/index.md)**
YAML reference and settings

**[QE Features](qe-features/index.md)**
Quality engineering capabilities

**[Providers](providers/index.md)**
BYOK, ACP, Local, and OpenResponses

**[Integration](integration/index.md)**
CI/CD, Docker, GitHub Actions

**[Advanced](advanced/index.md)**
MCP, custom roles, harness validation

**[API Reference](api-reference/index.md)**
JSONL events and Python SDK

</div>

---

## Community & Support

- [:fontawesome-brands-github: GitHub Repository](https://github.com/SuperagenticAI/superqode)

---

## Vision

As software becomes increasingly agent-written, developers need a harness that can connect models, run tools, summarize work clearly, and validate changes when it matters.

**SuperQode** is that harness. It supports daily coding workflows first, then adds SuperQE for teams that need agent-driven quality engineering and release evidence.

---

<div class="footer-tagline" markdown>

**SuperQode: Multi-agent coding harness.**

*Build with agents. Validate with evidence. Ship with confidence.*

*Built for agentic development. Self-hosted. Privacy-first. Human-controlled.*

</div>
