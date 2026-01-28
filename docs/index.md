# SuperQode

<div class="hero-section" markdown>

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" style="margin-bottom: 1.5rem;" />

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" style="max-height: 150px; margin-bottom: 1.5rem;" />

# **SUPERQODE**

### Superior Quality-Oriented Agentic Software Development.

Orchestrating coding agents as **Super Quality Engineers** using the **SuperQE methodology**. Let agents break the code. Prove the fix. Ship with confidence.

<p class="tagline">Orchestrate, Validate, and Deploy Agentic Software with Unshakable Confidence.</p>

[:octicons-rocket-24: Get Started](getting-started/installation.md){ .md-button .md-button--primary }
[:octicons-book-24: Learn Concepts](concepts/index.md){ .md-button }
[:octicons-code-24: CLI Reference](cli-reference/index.md){ .md-button }

[Demo video](https://www.youtube.com/watch?v=x2V323HgXRk)

</div>

---

## What is SuperQode and SuperQE?

**SuperQE** is the quality paradigm and automation CLI: **Super Quality Engineering for Agentic AI**. It uses QE coding agents to break and validate code written by coding agents. SuperQE can spawn a team of QE agents with different testing personas in a multi-agent setup to stress your code from many angles.

**SuperQode** is the agentic coding harness designed to drive the SuperQE process. It delivers a **Superior and Quality Optimized Developer Experience** as a TUI for interactive development, debugging, and exploratory QE. SuperQode can also be used as a general development harness beyond QE.

**Note (Enterprise):** Enterprise adds powerful automation, deep evaluation testing, and enterprise integrations (Moltbot first; more bot integrations coming).

### Why SuperQode Exists

AI coding agents have changed how software is written, but quality engineering still assumes human
authorship, deterministic behavior, and slow change. That mismatch creates a new risk surface:

- PR review catches syntax but not emergent behavior
- Static analysis misses runtime failure modes
- Human QA cannot keep pace with agent velocity
- "Looks correct" is no longer evidence of safety

SuperQode closes this gap by letting agents fight agents in safe sandboxes and turning the results into
evidence-based decisions.

### What Is SuperQE?

SuperQE (Super Quality Engineering) is a quality methodology for agentic software:

- AI agents act as Quality Engineers
- Multiple agent personas attack code from different angles
- Failures are discovered through exploration and adversarial testing
- Fixes are verified with evidence, not assumed correct
- Humans remain the final decision-makers

SuperQE is not test generation. It is adversarial validation with reproducible evidence.

### What Is SuperQode?

SuperQode is the execution harness for SuperQE:

- A CLI (`superqe`) for automation and CI/CD runs
- A TUI (`superqode`) for interactive, exploratory QE
- A sandboxed workspace model that snapshots, tests, and reverts safely
- A role-based agent system for coverage across security, API, regression, full-stack, and chaos testing

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


SuperQE runs cleanly in CI/CD pipelines, while SuperQode drives SuperQE for interactive workflows. You can also use each independently.

What you get out of a run:

- A QR with prioritized findings, reproduction steps, and collected evidence
- Optional (Enterprise): verified patch suggestions and generated tests

Safety model: by default, SuperQode does not modify your repo. All exploratory changes happen in a sandbox and are reverted; humans decide what to apply.

```bash
# After install, in your repo:
superqe init

# Start the developer TUI (recommended for interactive workflows)
superqode

# Or run automated QE CLI
superqe run . --mode quick
```

`superqe init` creates a comprehensive role catalog in `superqode.yaml`. Disable or delete roles you don’t need.

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
For Enterprise capabilities (including integrations like Moltbot, with more coming), see
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

    CI/CD maturity but need quality assurance without QE headcount. Super Quality Engineers replace or augment human QA teams.

    *Fast-moving teams scaling quality engineering with AI agents*

-   **SMEs**

    ---

    Limited or no dedicated QE team. SuperQE methodology provides add-on-grade quality engineering without add-on costs.

    *Growing companies needing quality validation without hiring QE teams*

-   **Teams Using AI Coding Agents**

    ---

    Need quality validation for AI-generated code. Orchestration of coding agents ensures agent-written code meets production standards.

    *Teams using GitHub Copilot, Cursor, or other AI coding tools*

-   **Engineering Teams**

    ---

    Want to scale QA with code velocity. SuperQE transforms reactive QA into proactive, agentic quality engineering.

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

1. **AI Coding Has Outpaced QA** - Code is now written faster than humans can meaningfully test. Traditional QA processes cannot keep up with the velocity, scale, and complexity of agent-generated software.

2. **Existing Tools Stop at Code Review** - Most incumbent tools focus on PR comments, static analysis, or surface-level reviews. They do not actively break code, perform destructive testing, validate fixes in sandbox environments, or prove production readiness with evidence.

3. **QE Is Treated as Reporting, Not Problem Solving** - Traditional QA workflows optimize for tickets and findings, not for validated fixes, benchmarks, or proof of improvement.

4. **Incumbent QA + "Agentic AI" Falls Short** - Many existing testing platforms attempt to "add agents" to legacy QA systems. This approach fails structurally due to systems not being agent-native by design, mismatch between deterministic QA and probabilistic agents, and single-agent or same-model bias.

### The Solution: SuperQE

SuperQode introduces **SuperQE** through orchestration of coding agents - a new quality paradigm where:

- Coding agents are orchestrated as Super Quality Engineers aggressively attacking code in sandbox
- Multiple agents with different perspectives challenge each other
- Orchestrated agents can inject test code, run experiments, and break things
- All changes are tracked and demonstrated in reports
- Original code is always preserved
- Humans review outcomes and approve/reject fixes

**Let agents fight agents. Humans decide.**

---

## Key Differentiators

1. **Quality-first, not code-first** - Focus on breaking, not building
2. **QRs instead of bug reports** - Research-grade findings with evidence
3. **Sandbox freedom with safety** - Agents explore freely; original preserved
4. **Multi-agent, cross-model** - Diverse perspectives, fewer blind spots
5. **User-defined harness and roles** - No opinionated workflows
6. **Human-in-the-loop by design** - Findings and suggestions, not auto-apply
7. **Self-hosted, privacy-first** - Your code stays in your environment
8. **Prove-then-revert model** - Demonstrate fixes work, then restore original

---

## Supported Providers

=== "ACP Agents"

    | Agent | Capabilities | Status |
    |-------|--------------|--------|
    | OpenCode | File editing, shell, MCP, 75+ providers | Supported |
    | Claude Code | Native Claude integration | Coming Soon |
    | Aider | Git-integrated pair programming | Coming Soon |

=== "Cloud Providers (BYOK)"

    | Provider | Models | Free Tier |
    |----------|--------|-----------|
    | Google AI | Gemini 3 Pro, Gemini 3, Gemini 2.5 Flash | Yes |
    | Anthropic | Claude Opus 4.5, Sonnet 4.5, Haiku 4.5 | No |
    | OpenAI | GPT-5.2, GPT-4o, o1 | No |
    | Deepseek | Deepseek V3, Deepseek R1 | Yes |
    | Groq | Llama 3.3, Mixtral | Yes |
    | Together AI | 200+ open models | Limited |

=== "Local Providers"

    | Provider | Description |
    |----------|-------------|
    | Ollama | Easy local model deployment |
    | LM Studio | GUI-based local models |
    | vLLM | High-performance inference |
    | llama.cpp | C++ inference engine |

[:octicons-arrow-right-24: See all providers](providers/index.md)

---

## Documentation Structure

<div class="grid" markdown>

**[Getting Started](getting-started/index.md)**
Installation, quick start, and first QE session

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

As software becomes increasingly agent-written, **only agentic quality engineering can keep it safe**.

**SuperQode** orchestrates coding agents as Super Quality Engineers and operationalizes SuperQE (Agentic Quality Engineering). Let agents break the code. Prove the fix. Ship with confidence. Validate readiness before humans approve release.

---

<div class="footer-tagline" markdown>

**SuperQode: Superior Quality-Oriented Agentic Software Development.**

*Operationalizing SuperQE (Agentic Quality Engineering) - Let agents break the code. Prove the fix. Ship with confidence.*

*Built from first principles for Agentic QE. Self-hosted. Privacy-first. Human-in-the-loop.*

</div>
