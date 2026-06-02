# SuperQode

<div class="hero-section" markdown>

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" style="margin-bottom: 1.5rem;" />

<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/superqode-logo.png" alt="SuperQode Logo" style="max-height: 150px; margin-bottom: 1.5rem;" />

# **SuperQode**

### Your Portable Coding Agent Harness.

<p class="tagline">Run coding agents with portable specs, controlled tools, and readable sessions.</p>

[:octicons-rocket-24: Get Started](getting-started/installation.md){ .md-button .md-button--primary }
[:octicons-book-24: Learn Concepts](concepts/index.md){ .md-button }
[:octicons-code-24: CLI Reference](cli-reference/index.md){ .md-button }

[Demo video](https://www.youtube.com/watch?v=x2V323HgXRk)

</div>

---

## What Is SuperQode?

SuperQode is your portable coding agent harness. It gives developers one contract for model calls,
tool execution, sessions, sandbox policy, model routing, runtime adapters, workflow execution,
typed outputs, validation, and readable interactive output.

Use one harness spec to choose the runtime, model policy, tools, sandbox rules, approvals, event storage, and output shape for a coding-agent run.

## Core Concepts

SuperQode separates the major pieces of an agent system:

| Concept | Meaning |
| --- | --- |
| Harness | The full contract for a run: flavor, model policy, tools, sandbox, workflow, output, events, and validation |
| Runtime | The engine that executes the harness |
| Runtime adapter | The bridge from the SuperQode harness contract into a native loop, SDK, or agent framework |
| Harness flavor | The operating style, such as tool-rich coding or model-only no-tool |
| Model policy | Prompt, temperature, reasoning, tool surface, history, and iteration defaults for a model family |
| Tool policy | The explicit set of capabilities the model may use |

The harness is the stable product surface. Runtime adapters let teams use their preferred execution engine
without changing that surface.

## Why It Exists

AI coding work is fragmented across local models, cloud APIs, coding agents, provider-specific tools,
runtime SDKs, and project-specific validation scripts. SuperQode gives those pieces one coherent
developer surface.

Use SuperQode when you want to:

- run coding agents interactively in a TUI
- execute headless coding tasks from scripts
- exercise local and hosted models through the same harness contract
- route through different runtimes without rewriting workflows
- keep tool calls, diffs, summaries, and session history readable
- define project-specific harness behavior instead of hardcoding one agent loop

## Harness Flavors

### Coding Harness

The default flavor gives the model controlled access to repository tools:

- file read/write/edit
- grep, glob, and code search
- shell commands under policy
- MCP tools when configured
- session memory and compaction
- validation hooks after changes
- approval gates for risky actions

Use this for implementation, debugging, refactoring, migration work, test repair, and repository triage.

### No-Tool Harness

The no-tool flavor gives the model no tools at all. It uses only the prompt, selected model, and optional
structured output validation.

Use this for pure reasoning, architecture review from supplied context, design critique, planning, and
local-model capability evaluation.

## Runtime Backends

SuperQode keeps the harness contract stable while allowing different runtimes underneath:

| Runtime | Purpose |
| --- | --- |
| `builtin` | SuperQode's native coding loop |
| `openai-agents` | OpenAI Agents SDK adapter |
| `adk` | Google ADK adapter |
| `deepagents` | Optional DeepAgents runtime adapter for graph and middleware-heavy coding harnesses |
| `pydanticai` | Optional PydanticAI runtime with SuperQode tool bridging |
| custom | Bring your own backend behind the same harness contract |

## Harness Lifecycle

```text
1. SPEC       Choose coding, no-tool, or custom harness behavior
2. MODEL      Apply model policy, local hints, fallback rules, and prompt profile
3. RUNTIME    Select builtin, OpenAI Agents, Google ADK, DeepAgents, PydanticAI, or a custom backend
4. TOOLS      Attach repository tools, MCP tools, validation hooks, or no tools
5. SESSION    Persist history, stream events, compact context, store runs, and resume work
6. WORKFLOW   Run single, chain, parallel, router, orchestrator, or evaluator-optimizer flows
7. RESULT     Return text, diffs, typed data, events, and validation state
```

## Quick Start

```bash
pip install superqode
```

```bash
cd your-project
superqode
```

Run a headless task:

```bash
superqode --print "inspect this repository and suggest the smallest safe cleanup"
```

Inspect available profiles:

```bash
superqode profiles list
superqode tools list --profile build
superqode tools list --profile no-tool
```

## Design Principles

- Harness-first, workflow-neutral
- Local models are first-class
- Bring your own runtime and tools
- Tools are policy-controlled capabilities, not assumptions
- No-tool reasoning is a first-class benchmark path
- Runtime adapters are peers, not product centers
- Model policy is explicit for Gemma4, DS4, and hosted models
- Structured results are validated by the harness, not parsed ad hoc by callers
- Validation is reusable infrastructure
- A2A composes higher-level applications outside the core harness

## Next Steps

- [Installation](getting-started/installation.md)
- [First Session](getting-started/first-session.md)
- [Agent Runtimes](runtimes.md)
- [Harness System](advanced/harness-system.md)
- [Tools System](advanced/tools-system.md)
- [Provider Configuration](providers/index.md)
