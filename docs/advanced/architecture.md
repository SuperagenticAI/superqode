# Architecture Overview

SuperQode v2 is organized around a programmable coding-agent harness. The core product is the harness
kernel: sessions, tools, runtimes, model policy, sandbox policy, validation hooks, events, and backend
adapters.

Higher-level applications should compose through A2A later. They should not define the core architecture.

---

## System Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SUPERQODE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │   CLI / TUI     │    │  Headless CLI   │    │  A2A / ACP      │        │
│  │   Interface     │    │  Automation     │    │  Interfaces     │        │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│           └──────────────────────┴──────────────────────┘                  │
│                                  │                                          │
│                    ┌─────────────▼─────────────┐                          │
│                    │       Harness Kernel       │                          │
│                    │ sessions/events/policies   │                          │
│                    └─────────────┬─────────────┘                          │
│                                  │                                          │
│       ┌──────────────────────────┼──────────────────────────┐              │
│       │                          │                          │              │
│       ▼                          ▼                          ▼              │
│ ┌──────────────┐          ┌──────────────┐          ┌──────────────┐       │
│ │ HarnessSpec  │          │ Runtime      │          │ Tool +       │       │
│ │ Compiler     │          │ Backends     │          │ Sandbox      │       │
│ └──────┬───────┘          └──────┬───────┘          └──────┬───────┘       │
│        │                         │                         │               │
│        ▼                         ▼                         ▼               │
│ ┌──────────────┐          ┌──────────────┐          ┌──────────────┐       │
│ │ Model Policy │          │ Provider     │          │ Validation   │       │
│ │ + Profiles   │          │ Gateways     │          │ Hooks        │       │
│ └──────────────┘          └──────────────┘          └──────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Layers

### 1. HarnessSpec

`HarnessSpec` is the user-owned definition of a harness. It describes what should run, not how every
internal call is implemented.

It should cover:

- harness flavor: `coding`, `no_tool`, or custom
- runtime backend: `builtin`, `openai-agents`, `adk`, or custom
- model policy: primary model, fallbacks, local hardware hints, prompt profile, context budgets
- agents: roles, tools, skills, delegation rules
- workflow: single, chain, router, parallel, orchestrator, evaluator-optimizer
- execution policy: sandbox, approvals, allowed commands, blocked operations
- validation hooks: tests, linters, custom commands
- observability: events, traces, session persistence

### 2. Harness Kernel

The kernel is SuperQode-owned. It provides the stable runtime contract used by every flavor and backend.

Responsibilities:

- create and resume sessions
- stream normalized events
- persist history and compact context
- enforce tool and sandbox policy
- dispatch model calls through runtime backends
- expose typed outputs and structured results
- call validation hooks after changes
- provide a backend-neutral API to CLI, TUI, ACP, and A2A surfaces

### 3. Runtime Backends

Backends are adapters behind the same harness contract.

| Backend | Role |
| --- | --- |
| `builtin` | SuperQode native agent loop |
| `openai-agents` | OpenAI Agents SDK runtime |
| `adk` | Google ADK runtime |
| custom | Bring-your-own backend implementation |

No backend should become the product center. SuperQode owns the contract; backends provide execution.

### 4. Tool And Sandbox Layer

Tools are capabilities attached by policy.

The coding harness can expose:

- file read/write/edit
- search and code search
- shell execution
- MCP tools
- todo/task tools
- validation tools
- optional Python REPL

The no-tool harness exposes none of these. That is intentional: it provides a clean model-only path for
reasoning and evaluation.

### 5. Model Policy

Model behavior should be explicit instead of scattered through runtime conditionals.

Policy should include:

- default model and fallback models
- local model hints for MLX, Ollama, llama.cpp, and DS4
- Gemma4 coding and no-tool prompt profiles
- temperature and reasoning defaults
- context limits and compaction thresholds
- tool-call format repair policy

### 6. Validation Hooks

Validation is infrastructure, not the product identity. The harness can run project checks after it produces
changes or structured suggestions.

Examples:

- syntax checks
- type checks
- lint checks
- test commands
- project-specific custom commands

---

## Request Lifecycle

```text
1. REQUEST
   User sends a prompt from TUI, CLI, ACP, A2A, or an embedding API.

2. SPEC RESOLUTION
   SuperQode selects a built-in or user-provided HarnessSpec.

3. POLICY COMPILATION
   The spec resolves model, runtime, tools, sandbox, permissions, and validation.

4. SESSION OPEN
   The kernel creates or resumes session history and loads project instructions.

5. RUNTIME EXECUTION
   The selected backend runs the model loop or model-only call.

6. TOOL / SANDBOX ACCESS
   Tool-capable flavors execute approved tool calls through the sandbox layer.

7. VALIDATION
   If changes or suggestions were produced, configured validation hooks run.

8. RESULT
   The kernel returns text, structured data, diffs, events, and validation state.
```

---

## Module Direction

```text
src/superqode/harness/
  spec.py
  loader.py
  templates.py
  compiler.py
  kernel.py
  session.py
  events.py
  history.py
  sandbox.py
  validation.py
  backends/
    base.py
    builtin.py
    openai_agents.py
    google_adk.py
```

Existing modules map into this structure:

| Current Area | v2 Role |
| --- | --- |
| `agent/loop.py` | `builtin` backend |
| `headless.py` profiles | built-in HarnessSpec templates |
| `tools/*` | tool capability layer |
| `runtime/*` | backend adapters |
| `providers/*` | model/provider gateway |
| `sandbox/*` | execution policy and workspace isolation |
| `harness/validator.py` | validation hook implementation |

---

## Extension Points

| Extension Point | Purpose |
| --- | --- |
| Harness templates | Add reusable coding, no-tool, local-model, or team-specific profiles |
| Runtime backends | Add a new agent runtime behind the stable kernel contract |
| Tool packs | Add domain-specific capabilities |
| Sandbox connectors | Adapt local, remote, or provider-owned workspaces |
| Model profiles | Tune prompts, tool-call behavior, and fallback policy |
| Validation hooks | Add project-specific checks |
| A2A apps | Compose higher-level applications outside the core harness |

---

## Related Documentation

- [Harness System](harness-system.md)
- [Agent Runtimes](../runtimes.md)
- [Tools System](tools-system.md)
- [Workspace Internals](workspace-internals.md)
- [Safety & Permissions](safety-permissions.md)
- [Session Management](session-management.md)
