---
title: SuperQode
hide:
  - navigation
  - toc
---

<div class="sq-hero" markdown>

<img src="assets/superqode-logo.png" alt="SuperQode" class="sq-hero-logo" />

# SuperQode

<p class="sq-kicker">The harness engineering framework for coding agents, optimized for local and open models</p>

<p class="sq-tagline">Build your own coding harness. Measure it. Extend it. Optimize it. Use any model, open or closed, small or large, local or remote, without giving up control of the agent loop.</p>

<p class="sq-badges">
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/v/superqode?style=flat-square&color=7c3aed" alt="PyPI version"></a>
  <a href="https://pypi.org/project/superqode/"><img src="https://img.shields.io/pypi/pyversions/superqode?style=flat-square" alt="Python versions"></a>
  <a href="https://github.com/SuperagenticAI/superqode/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square" alt="License"></a>
  <a href="https://github.com/SuperagenticAI/superqode"><img src="https://img.shields.io/github/stars/SuperagenticAI/superqode?style=flat-square&color=64748b" alt="GitHub stars"></a>
</p>

[Build Your First Harness](getting-started/bring-your-own-harness.md){ .md-button .md-button--primary }
[Optimize Local Models](local-agentic-coding.md){ .md-button }
[Read Harness Engineering](harness-engineering.md){ .md-button }

</div>

---

## Up and running in 60 seconds

```bash
uv tool install superqode    # or run without installing: uvx superqode
cd your-project
superqode
```

That launches the interactive TUI. Connect a model, then start working:

```text
:connect local ollama <open-model>      # a local server you run
:connect byok <provider> <model>        # a hosted provider with an API key
:connect acp <agent>                    # an installed ACP coding agent
```

Prefer scripts and CI? See the headless examples below.

For local and Open Model work, generate a starter harness that belongs to your
repo:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

Use `local init` for the fastest owned-harness path. Use `local build` when you
want the guided builder for a specific model, endpoint, or model pack.

---

## Overview

SuperQode is a harness engineering framework for coding agents, optimized for local and open models. It turns the harness around a coding agent into a repository artifact: model routing, tools, memory, context, search, approvals, sandboxing, workflows, evals, and optimization.

Most coding products ship a finished agent loop. SuperQode gives teams the framework to define that loop, run it local first, and connect any model route without giving up the harness. Harness engineering is the practice. Harness independence is the outcome.

---

## Build. Measure. Extend. Optimize.

Harness engineering is the discipline after prompt engineering and context engineering: design the system around the model so it works reliably. SuperQode gives you four moves on a harness you own.

<div class="grid cards" markdown>

-   :octicons-tools-16:{ .lg .middle } **Build**

    ---

    Author a harness as a versioned `harness.yaml`. Use the wizard, start from a model-family template, and read what it does in plain English with `harness explain`.

    [:octicons-arrow-right-24: Bring Your Own Harness](getting-started/bring-your-own-harness.md)

-   :octicons-graph-16:{ .lg .middle } **Measure**

    ---

    Prove behavior before you trust it: eval scorecards, agentic benchmarks, and regression gates that fail a candidate which breaks a task the baseline solved.

    [:octicons-arrow-right-24: Run, Measure, Optimize](advanced/harness-optimization.md)

-   :octicons-plug-16:{ .lg .middle } **Extend**

    ---

    Run the same contract across runtimes, providers, MCP, ACP, and A2A. Swap models, memory, search, or tools without rewriting the workflow.

    [:octicons-arrow-right-24: Runtime Backends](runtimes.md)

-   :octicons-rocket-16:{ .lg .middle } **Optimize**

    ---

    Improve model routes, harnesses, and skills with staged candidates a human adopts, so a failure gets fixed once instead of retried.

    [:octicons-arrow-right-24: Optimization Story](advanced/optimization.md)

</div>

---

## Main Capabilities

<div class="grid cards" markdown>

-   :octicons-package-16:{ .lg .middle } **Harness specification**

    ---

    Write a `harness.yaml` that pins runtime, model policy, tools, memory, search, sandbox, approvals, and workflow. Validate it with `harness doctor`, commit it, and run the same contract anywhere.

    [:octicons-arrow-right-24: Bring Your Own Harness](getting-started/bring-your-own-harness.md)

-   :octicons-cpu-16:{ .lg .middle } **Model routing**

    ---

    Use Open Models or closed models, local endpoints or remote providers, small utility models or large coding models. The harness remains the portable configuration layer.

    [:octicons-arrow-right-24: Runtime Backends](runtimes.md)

-   :octicons-cpu-16:{ .lg .middle } **Local first Open Model support**

    ---

    Detect local engines, probe real context windows, generate starter harnesses, smoke test readiness, repair weak tool calls, and benchmark local candidates.

    [:octicons-arrow-right-24: Local Agentic Coding](local-agentic-coding.md)

-   :octicons-graph-16:{ .lg .middle } **Evaluation and optimization**

    ---

    Use harness tests, eval scorecards, local route optimization, harness optimization, and skill optimization. Stage changes and adopt them only after regression gates pass.

    [:octicons-arrow-right-24: Optimization Story](advanced/optimization.md)

-   :octicons-search-16:{ .lg .middle } **Local code intelligence**

    ---

    Give models the right context with bounded reads, local code search, multi repo search, semantic search, offline indexes, and post edit verification.

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

    [:octicons-arrow-right-24: Connection Modes](concepts/modes.md)

</div>

---

## See it work

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

## Learn it in order

Each step builds on the previous one.

1. **Install and run**: [Installation](getting-started/installation.md), then [Your First Session](getting-started/first-session.md)
2. **Connect your models**: [Providers](providers/index.md) for hosted APIs, [Local Models](providers/local.md) for Ollama, LM Studio, MLX, vLLM, and DS4
3. **Understand the engine**: [Inside the Agent Loop](advanced/agent-loop.md) and the [Tools Catalog](advanced/tools-catalog.md)
4. **Make it yours**: [Harness System](advanced/harness-system.md) for portable run contracts, [Policies & Safety](advanced/policies.md) for guardrails
5. **Automate**: [Headless & CI](advanced/headless-ci.md) for scripts, pipelines, and schema-validated output
6. **Go further**: [Developer Workflows](developer-workflows.md), [Multi-Agent Workflows](advanced/multi-agent.md), [Runtime Backends](runtimes.md), [Plugin Authoring](advanced/plugin-authoring.md)

---

<div class="sq-footer-cta" markdown>

**Ready?** [Install SuperQode](getting-started/installation.md){ .md-button .md-button--primary } or start with the [Harness Guide](getting-started/bring-your-own-harness.md).

</div>
