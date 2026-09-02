---
title: SuperQode
hide:
  - navigation
  - toc
---

<div class="sq-hero" markdown>

<img src="assets/superqode-logo.png" alt="SuperQode" class="sq-hero-logo" />

# SuperQode

<p class="sq-kicker"><span class="sq-gradient-text">The Harness Layer</span> for Coding Agents</p>

<p class="sq-tagline">Discover, build, run, evaluate and optimize coding-agent harnesses from one terminal. Interoperable over ACP, A2A, MCP and UHP: drive any coding agent, and be called as one.</p>

<p>Terminal-first · Any agent · Any model · Local or cloud · Open source</p>

<p class="sq-badges">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode?style=flat-square&color=7c3aed" alt="PyPI version"></a>
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/pyversions/superqode?style=flat-square" alt="Python versions"></a>
  <a href="https://github.com/SuperagenticAI/superqode/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square" alt="License"></a>
  <a href="https://github.com/SuperagenticAI/superqode"><img src="https://img.shields.io/github/stars/SuperagenticAI/superqode?style=flat-square&color=64748b" alt="GitHub stars"></a>
  <a href="https://superqode.dev"><img src="https://img.shields.io/badge/website-superqode.dev-7c3aed?style=flat-square" alt="Website"></a>
</p>

[Start Coding](getting-started/first-session.md){ .md-button .md-button--primary }
[Explore the Harness Hub](harness-hub.md){ .md-button }
[A2A Agent](https://a2a.superqode.dev){ .md-button }
[What's new](https://superqode.dev/v2){ .md-button }
[Choose an Agent, Model, or Harness](concepts/modes.md){ .md-button }
[Build Your First Harness](getting-started/bring-your-own-harness.md){ .md-button }
[Optimize Local Models](local-agentic-coding.md){ .md-button }
[SuperQode Website](https://superqode.dev){ .md-button }

</div>

---

## Installation and first run

```bash
curl -fsSL https://superqode.dev/install.sh | sh
cd your-project
superqode
```

The installer adds `uv` when needed, installs the latest
[SuperQode release](https://pypi.org/project/superqode/) from PyPI in an
isolated environment, and verifies the command. It does not use `sudo`.

Already have [uv](https://docs.astral.sh/uv/)? Install it yourself instead:

```bash
uv tool install superqode      # persistent install
uvx superqode                  # run once without installing
```

The command starts the interactive TUI. Connect the coding agent or model you
already use:

```text
:connect                               # open the complete connection picker
:connect codex                         # Codex subscription
:connect copilot                       # GitHub Copilot plan (SDK or CLI)
:connect kimi-code                     # Kimi Code through its official ACP server
:connect qwen-code                     # Qwen Code through its official ACP server
:connect fx                            # Vercel fx through fx acp after fx login
:connect acp <agent>                   # any installed ACP coding agent
:connect local ollama <open-model>     # a local server you run
:connect byok <provider> <model>       # a hosted provider with an API key
:connect uhp --base-url <url>          # harnesses on a UHP server
:connect a2a --url <url>               # an A2A agent from its Agent Card
```

Ask for repository work as you would in another coding agent:

```text
Summarize this repository and identify the smallest safe improvement.
```

Open the Harness Hub to browse, inspect, and switch the complete harness
without leaving the session:

```text
:hub
:harness
:harness switch
:harness switch qwen-code --fork
```

The mouse- and keyboard-enabled Hub includes SuperQode's native harnesses,
project HarnessSpecs, vendor and ACP coding agents, model presets, installed
and registry harnesses, and optional integrations such as Hugging Face Tau.
It uses focused details and a session Activity screen so important outcomes do
not disappear below the transcript.

For noninteractive execution and CI, see the headless examples below. Build a
repository-owned HarnessSpec only when you want to make the working behavior
repeatable and reviewable.

For local and open models, generate a repository-owned starter harness:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

Use `local init` to detect the current system and generate a default HarnessSpec.
Use `local build` to select a specific model, endpoint, or model pack.

---

## A progressive way to adopt SuperQode

| Stage | Developer outcome | Documentation |
| --- | --- | --- |
| Use | Work in a repository with a familiar coding-agent experience | [Your First Session](getting-started/first-session.md) |
| Choose and switch | Select any supported agent, model, provider, or harness and switch during the session | [All Connections](concepts/modes.md) |
| Build | Create a repository-owned HarnessSpec for repeatable behavior | [Bring Your Own Harness](getting-started/bring-your-own-harness.md) |
| Evaluate | Measure behavior with tasks, scorecards, and regression gates | [Run, Measure, Optimize](advanced/harness-optimization.md) |
| Optimize | Generate staged candidates only after the evaluation contract is useful | [Optimization Story](advanced/optimization.md) |
| Promote | Canary, activate, and roll back a proven harness | [Harness Promotion](advanced/harness-promotion.md) |

---

## Overview

SuperQode is the open-source, terminal-first harness layer for coding agents. Build repository-owned harnesses, run SuperQode's native harnesses, or connect established coding agents through native integrations, SDK runtimes, RPC, and ACP.

[Agent Engineering](https://agentengineering.world/) is the broader discipline of designing, building, evaluating, governing, and operating agents as reliable systems. SuperQode focuses that work on the harness layer: the model routing, context, memory, tools, policies, execution, evidence, and evaluation around a coding agent.

The repository-owned `HarnessSpec` makes that layer portable and reviewable across native, open-source, and proprietary agents. A code factory is the larger system that uses those harnesses to turn intent into verified code changes.

SuperQode is **terminal-first by design**. The CLI and TUI are the complete primary product surfaces for building harnesses, coordinating sessions and WorkOrders, reviewing evidence, and approving delivery. Browser rendering, the local companion API, and chat channels provide optional remote access without creating a separate web or mobile product direction.

---

## The problem SuperQode solves

Selecting a capable model does not give an organization a reliable code production system. The harness still decides what the agent sees, which tools it can use, how it remembers, what it may change, and how its work is verified.

Teams commonly face several related problems:

- established coding agents provide useful but vendor-owned harnesses that cannot always be inspected, moved, or evaluated independently
- open and local models provide model capability without a complete repository coding harness
- different agents keep separate sessions, context, tools, permissions, and evidence
- session orchestration alone does not ensure that repository work finishes, passes checks, or produces an exact candidate a human can approve
- harness changes are difficult to compare when quality, cost, latency, regressions, and failed candidates are not recorded together

SuperQode makes the harness a repository-owned engineering artifact, connects existing agents through native runtimes and ACP, and applies a consistent lifecycle for execution, evaluation, governance, evidence, delivery, and optimization.

---

## Where SuperQode fits

Two ownership boundaries distinguish coding-agent products: control of the
model and control of the harness. The harness is the complete agent loop,
including prompts, context strategy, tools, memory, permissions, workflow, and
verification behavior.

| Ecosystem pattern | Model choice | Harness ownership | Typical examples | Practical result |
| --- | --- | --- | --- | --- |
| **Closed model, closed harness** | Primarily the vendor's models | The vendor owns and evolves the agent loop | Vendor coding agents such as [Claude Code with Claude](https://docs.anthropic.com/en/docs/claude-code/getting-started) | The vendor manages model access and agent-loop changes as one product |
| **Open or selectable models, closed harness** | Several providers or model families may be available | The product vendor still controls the complete loop | Multi-model products such as [Cursor](https://docs.cursor.com/models/) | The team can select models, while the complete harness remains product-controlled |
| **Open models, open harness** | Hosted, open-weight, or local models | The agent implementation is open source and configurable | [Cline](https://github.com/cline/cline), [OpenCode](https://github.com/anomalyco/opencode), and [Aider](https://aider.chat/docs/llms.html) | The source and model routes are inspectable; execution generally follows the framework's established loop |

These categories describe control boundaries and can overlap. SuperQode
classifies an integration by whether the complete working contract can be
stored in a repository, executed across agents and models, evaluated
independently, and promoted as a reviewed revision.

### Coding agents, static harnesses, meta-harnesses, and SuperQode

| Layer | Primary purpose | What it provides | Relationship to SuperQode |
| --- | --- | --- | --- |
| **Coding agent** | Complete coding sessions | An interactive product with a built-in agent loop | SuperQode can connect supported coding agents and switch between them during a session |
| **Static agent harness** | Run a configurable agent loop | An implementation with prompts, tools, and model settings defined by that product or framework | SuperQode can run its own native harness or connect external harnesses while keeping a common session, policy, and evidence layer |
| **Meta-harness or optimizer** | Search for better prompts, code, configuration, or agent structure | Candidate generation and selection around an evaluator | SuperQode uses optimizers such as [MetaHarness and GEPA Omni](advanced/harness-optimization.md) as optional stages in a guarded lifecycle |
| **SuperQode** | Engineer and operate the complete coding-agent lifecycle | Coding sessions, agent and model switching, repository-owned HarnessSpecs, evaluation, governance, optimization, and promotion | A terminal interface and versioned lifecycle for execution through approved harness revisions |

Existing coding agents can remain part of the workflow. SuperQode can first
operate as the coding interface and connection layer. A repository-owned
HarnessSpec can be introduced when the team requires repeatable behavior and
control of the agent loop. Evaluation, optimization, and promotion require a
defined task contract.

## Build your code factory

Build an organization-owned harness, select one from the catalog, or connect an existing coding agent through a native runtime or ACP. SuperQode operates them through one consistent system for orchestration, evaluation, governance, and optimization.

<div class="sq-doc-cta" markdown>

[Understand Code Factories](concepts/code-factory.md){ .md-button .md-button--primary }
[Read Harness Engineering](harness-engineering.md){ .md-button }

</div>

---

## Harness lifecycle

SuperQode provides five connected capabilities for a coding harness you own or an established agent you connect.

<div class="grid cards" markdown>

-   :octicons-tools-16:{ .lg .middle } **Build**

    ---

    Author a harness as a versioned `harness.yaml`. Use the wizard, start from a model-family template, and read what it does in plain English with `harness explain`.

    [:octicons-arrow-right-24: Bring Your Own Harness](getting-started/bring-your-own-harness.md)

-   :octicons-plug-16:{ .lg .middle } **Run**

    ---

    Execute the same contract across runtimes, providers, MCP, ACP, and A2A. Swap models, memory, search, or tools without rewriting the workflow.

    [:octicons-arrow-right-24: Runtime Backends](runtimes.md)

-   :octicons-graph-16:{ .lg .middle } **Evaluate**

    ---

    Measure behavior with eval scorecards, agentic benchmarks, and regression gates that reject candidates which break tasks the baseline solved.

    [:octicons-arrow-right-24: Run, Measure, Optimize](advanced/harness-optimization.md)

-   :octicons-shield-lock-16:{ .lg .middle } **Govern**

    ---

    Control permissions, sandbox policy, budgets, credentials, approvals, and delivery gates with explicit, reviewable rules.

    [:octicons-arrow-right-24: Policies & Safety](advanced/policies.md)

-   :octicons-rocket-16:{ .lg .middle } **Optimize**

    ---

    Improve model routes, harnesses, and skills through staged candidates, held-out evaluation, recorded negative evidence, and explicit human adoption.

    [:octicons-arrow-right-24: Optimization Story](advanced/optimization.md)

</div>

---

## Main Capabilities

<div class="grid cards" markdown>

-   :octicons-package-16:{ .lg .middle } **Harness specification**

    ---

    Write a `harness.yaml` that pins runtime, model policy, tools, memory, search, sandbox, approvals, and workflow. Validate it with `harness doctor`, commit it, and run the same contract anywhere.

    [:octicons-arrow-right-24: Bring Your Own Harness](getting-started/bring-your-own-harness.md)

-   :octicons-git-branch-16:{ .lg .middle } **Harness independence**

    ---

    Keep the agent loop inspectable and versioned in your repo. SuperQode lets teams measure, change, and improve the harness itself instead of depending on a locked product harness.

    [:octicons-arrow-right-24: What Is Harness Engineering](harness-engineering.md)

-   :octicons-cpu-16:{ .lg .middle } **Model routing**

    ---

    Use Open Models or closed models, local endpoints or remote providers, small utility models or large coding models. The harness remains the portable configuration layer.

    [:octicons-arrow-right-24: Runtime Backends](runtimes.md)

-   :octicons-cpu-16:{ .lg .middle } **Local first Open Model support**

    ---

    Detect local engines, probe real context windows, generate starter harnesses, smoke test readiness, repair weak tool calls, and benchmark local candidates.

    [:octicons-arrow-right-24: Local Agentic Coding](local-agentic-coding.md)

-   :octicons-workflow-16:{ .lg .middle } **Local dynamic workflows with RLM**

    ---

    Use local recursive language-model runs for large logs, traces, diffs, and repo-slice audits. `context_handle`, `spawn_harness`, and bounded dynamic workflow scripts keep evidence outside the prompt while preserving replayable lineage.

    [:octicons-arrow-right-24: Local Recursive Dynamic Coding](local-recursive-dynamic-coding.md)

-   :octicons-graph-16:{ .lg .middle } **Evaluation and optimization**

    ---

    Use harness tests, eval scorecards, local route optimization, harness optimization, and skill optimization. Stage changes and adopt them only after regression gates pass.

    [:octicons-arrow-right-24: Optimization Story](advanced/optimization.md)

-   :octicons-workflow-16:{ .lg .middle } **Terminal-first Code Factory**

    ---

    Move from a repo-owned HarnessSpec to durable role-aware WorkOrders, isolated workers, terminal operations, verified delivery, and evidence-backed harness improvement.

    [:octicons-arrow-right-24: Code Factory](advanced/software-factory.md)

-   :octicons-search-16:{ .lg .middle } **Local code intelligence**

    ---

    Provide bounded repository context through local code search, multi repo search, semantic search, offline indexes, and post edit verification.

    [:octicons-arrow-right-24: Multi-Repo Search & Edit Safety](advanced/multi-repo-search.md)

-   :octicons-shield-lock-16:{ .lg .middle } **Airplane Mode**

    ---

    Prepare a strict offline harness with local repositories, local model servers, local indexes, cached metadata, and network tools removed.

    [:octicons-arrow-right-24: Airplane Mode](advanced/airplane-mode.md)

-   :octicons-database-16:{ .lg .middle } **Configurable memory**

    ---

    Local first agent memory supports remember, search, forget, and export operations. Connect provider neutral memory systems when needed.

    [:octicons-arrow-right-24: Memory & Learning](advanced/memory.md)

-   :octicons-tools-16:{ .lg .middle } **Policy controlled tools**

    ---

    Bounded reads, shell sessions, patch edits, vision attachments, MCP tools, web tools, and verification hooks are gated by explicit permissions and sandbox policy.

    [:octicons-arrow-right-24: Tools Catalog](advanced/tools-catalog.md)

-   :octicons-plug-16:{ .lg .middle } **Runtime and protocol integrations**

    ---

    Connect to existing runtimes, SDKs, MCP tools, ACP agents, and A2A workflows while keeping the harness as the portable contract.

    [:octicons-arrow-right-24: Connection Methods and Vendors](concepts/modes.md)

</div>

---

## Feature Reference Map

Every major product surface has a dedicated reference page. Start with the area
you are changing, then use the CLI reference when you need exact flags.

| Area | Documentation |
| --- | --- |
| Product capability coverage | [Product Capability Reference](product-capabilities.md) |
| CLI commands | [CLI Reference](cli-reference/index.md) |
| TUI commands | [TUI Reference](advanced/tui.md) |
| Harness specs, workflows, evals, and events | [Harness System](advanced/harness-system.md) |
| Runtime backends and SDK adapters | [Runtime Backends](runtimes.md) |
| Providers, model catalog, and connection profiles | [Models & Providers](providers/index.md) |
| Local and Open Model workflows | [Local Agentic Coding](local-agentic-coding.md) |
| Tools, search, MCP, and permissions | [Tools Catalog](advanced/tools-catalog.md) |
| Safety, sandboxing, and approvals | [Safety & Permissions](advanced/safety-permissions.md) |
| Sessions, sharing, memory, and logging | [Session Management](advanced/session-management.md) |
| Code Factory, WorkOrders, workers, and delivery gates | [Building a Code Factory with SuperQode](advanced/software-factory.md) |
| Omnigent similarities, differences, and interoperability | [How SuperQode Relates to Omnigent](advanced/superqode-vs-omnigent.md) |
| Plugins, skills, and optimization | [Plugin Authoring](advanced/plugin-authoring.md) |
| Automation, channels, MCP, ACP, and A2A | [Advanced Workflows](advanced/index.md) |
| Environment variables and YAML config | [Configuration](configuration/index.md) |

The release checks include a CLI documentation coverage test so new command
groups are not added without a reference page.

---

## Capability demonstrations

=== "Interactive TUI"

    ```text
    :connect local          # pick a local model server
    :plan fix the tests     # review the plan before tools run
    :plan approve           # execute it
    :context                # check the detected context window
    :local optimize         # benchmark candidates and generate role routes
    ```

    Type while the agent works and your message steers the current run between tool calls.

=== "Headless"

    ```bash
    superqode -p --mode json "summarize the architecture" | jq .success
    superqode -p --resume 4f2a "continue where we left off"
    superqode sessions export 4f2a --format html -o run.html
    ```

=== "Harness contract"

    ```yaml
    # harness.yaml: the portable run contract
    name: my-coder
    flavor: coding
    runtime:
      backend: builtin
    model_policy:
      primary: ollama/gemma4
      tool_call_format: prompt    # for models without a native tool head
    execution_policy:
      sandbox: docker
      approval_profile: ask
    ```

    ```bash
    superqode harness run --spec harness.yaml --prompt "make the smallest safe fix"
    superqode harness events <run-id>
    ```

=== "CI quality gate"

    ```bash
    superqode -p \
      --sandbox git-worktree \
      --rubric "the full test suite passes; the diff is minimal" \
      --output-schema fix-report.schema.json \
      "find one failing test and fix it properly" > report.json

    jq -e '.schema_valid and .success' report.json
    ```

---

## How a run works

```text
1. SPEC       Choose coding, no-tool, or custom harness behavior
2. MODEL      Apply model policy, local hints, fallback rules, and prompt profile
3. RUNTIME    Select builtin, OpenAI Agents, ADK, Codex SDK, Claude Agent SDK, DeepAgents, or PydanticAI
4. TOOLS      Attach repository tools, MCP tools, validation hooks, or no tools
5. SESSION    Persist history, stream events, compact context, store runs, resume work
6. WORKFLOW   Run single, chain, parallel, router, orchestrator, or evaluator-optimizer flows
7. RESULT     Return text, diffs, typed data, events, and validation state
```

Every stage is observable: `superqode harness events <run-id>` shows the normalized event graph regardless of which runtime executed the work.

---

## Recommended documentation sequence

Each step builds on the previous one.

1. **Install and run**: [Installation](getting-started/installation.md), then [Your First Session](getting-started/first-session.md)
2. **Connect your models**: [Providers](providers/index.md) for hosted APIs, [Local Models](providers/local.md) for Ollama, LM Studio, MLX, vLLM, and DS4
3. **Understand the engine**: [Inside the Agent Loop](advanced/agent-loop.md) and the [Tools Catalog](advanced/tools-catalog.md)
4. **Make it yours**: [Harness System](advanced/harness-system.md) for portable run contracts, [Policies & Safety](advanced/policies.md) for guardrails
5. **Build the factory**: [Building a Code Factory with SuperQode](advanced/software-factory.md) for WorkOrders, workers, evidence, delivery, and improvement
6. **Automate**: [Headless & CI](advanced/headless-ci.md) for scripts, pipelines, and schema-validated output
7. **Go further**: [Developer Workflows](developer-workflows.md), [Multi-Agent Workflows](advanced/multi-agent.md), [Runtime Backends](runtimes.md), [Plugin Authoring](advanced/plugin-authoring.md)

---

<div class="sq-footer-cta" markdown>

[Install SuperQode](getting-started/installation.md){ .md-button .md-button--primary } or open the [Harness Guide](getting-started/bring-your-own-harness.md).

</div>
