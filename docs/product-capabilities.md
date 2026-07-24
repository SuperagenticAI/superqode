# Product Capability Reference

This page maps SuperQode product capabilities to their implementation surfaces and detailed documentation. It covers the public capabilities present in the codebase as of version 0.2.35.

## Product scope

SuperQode is a terminal-first Agent Engineering framework for code factories. It supports organization-owned HarnessSpecs, established coding agents, local and hosted models, persistent sessions, repository delivery, evaluation, governance, and guarded optimization.

The primary interfaces are the CLI and TUI. Headless commands, local APIs, browser rendering, and chat channels provide automation and remote access without replacing the terminal workflow.

## Capability matrix

| Capability | Implementation surface | Documentation |
| --- | --- | --- |
| Harness authoring | `harness init`, wizard, templates, inheritance, compile, explain, and doctor | [Harness System](advanced/harness-system.md) |
| Native harnesses | Core, Workbench, coding, no-tool, and model-family policy profiles | [Harness Engineering](harness-engineering.md) |
| Harness ownership | Repository-owned YAML, version control, inspectable policy, and portable execution | [Bring Your Own Harness](getting-started/bring-your-own-harness.md) |
| Harness selection | Built-in catalog, local registry, Python packages, imported agents, and TUI switcher | [Harness Commands](cli-reference/harness-commands.md) |
| Session continuity | Persistent sessions, same-session harness switching, forks, handoffs, and lineage | [Session Management](advanced/session-management.md) |
| Coding-agent connections | Native clients, ACP agents, subscription CLIs, SDK runtimes, BYOK providers, and local servers | [Connection Methods and Vendors](concepts/modes.md) |
| Model connections | Local engines, BYOK providers, subscription runtimes, model profiles, and fallbacks | [Models and Providers](providers/index.md) |
| Local inference | Ollama, LM Studio, MLX, DwarfStar, llama.cpp, vLLM, SGLang, TGI, and DS4 | [Local Models](providers/local.md) |
| Poolside Laguna S 2.1 | Shared GGUF discovery, DwarfStar and llama.cpp launch paths, model policy, reasoning preservation, and TUI variants | [DwarfStar and Laguna](providers/local.md#dwarfstar-ds4) |
| Harness Protocol | Versioned lifecycle, event envelope, conformance checks, adapters, and session export | [Harness Protocol v1](advanced/harness-protocol.md) |
| Runtime adapters | Builtin, OpenAI Agents, Google ADK, Codex SDK, GitHub Copilot SDK, Claude Agent SDK, DeepAgents, PydanticAI, and RLM Code | [Runtime Backends](runtimes.md) |
| Tool policy | Repository reads, search, edits, shell, MCP, network, diagnostics, image tools, and validation | [Tools Catalog](advanced/tools-catalog.md) |
| Safety and governance | Permissions, sandboxes, trust checks, approvals, contextual policy, budgets, and credential controls | [Safety and Permissions](advanced/safety-permissions.md) |
| Context and memory | Context detection, compaction, local memory, provider adapters, and repository search | [Memory and Learning](advanced/memory.md) |
| Evaluation | Harness tests, eval packs, scorecards, benchmarks, evidence, and regression gates | [Harness Optimization](advanced/harness-optimization.md) |
| Optimization | Candidate generation, failure mining, Pareto selection, held-out evaluation, promotion, and rollback | [Optimization](advanced/optimization.md) |
| Recursive workflows | RLM Code backend, context handles, spawned harnesses, bounded scripts, and replayable evidence | [RLM Code Integration](advanced/rlm-code.md) |
| Offline operation | Airplane Mode, cached metadata, local search roots, local servers, and denied network tools | [Airplane Mode](advanced/airplane-mode.md) |
| Durable repository delivery | WorkOrders, task dependencies, isolated workers, leases, recovery, checks, reviews, and merge decisions | [WorkOrders](advanced/workorders.md) |
| Code Factory operation | Harnesses, routes, sessions, WorkOrders, evidence, governance, evaluation, and improvement | [Code Factory](advanced/software-factory.md) |
| Extensions | Python tools, commands, skills, hooks, providers, package entry points, trust, and compatibility checks | [Plugin Authoring](advanced/plugin-authoring.md) |
| Protocol integration | MCP tools and servers, ACP clients and server, A2A workflows, and Harness Protocol adapters | [Advanced Workflows](advanced/index.md) |
| Automation | Headless execution, structured output, CI gates, workers, daemon, APIs, and channels | [Headless and CI](advanced/headless-ci.md) |
| Omnigent interoperability | Agent-spec import, portable conversion, shared multi-harness concepts, and different interface priorities | [SuperQode and Omnigent](advanced/superqode-vs-omnigent.md) |

## Configuration artifacts

| Artifact | Responsibility |
| --- | --- |
| `superqode.yaml` | Project providers, endpoints, aliases, MCP servers, memory providers, and connection defaults |
| `harness.yaml` | Runtime, model policy, tools, context, memory, sandbox, approvals, checks, workflow, events, and output |
| `superqode.local.yaml` | Hardware-aware local HarnessSpec generated for the current machine |
| `superqode.airplane.yaml` | Local HarnessSpec with network tools removed |
| Session store | Conversation, provider, model, runtime, harness, fork, handoff, and transition state |
| WorkOrder store | Goals, task dependencies, workers, leases, budgets, artifacts, reviews, checks, and delivery decisions |
| Evidence and candidate stores | Run events, scorecards, failed candidates, held-out results, promotion records, and rollback state |

See [Configuration File Responsibilities](getting-started/configuration.md#configuration-file-responsibilities) for the boundary between project configuration and HarnessSpec files.

## Documentation coverage controls

The CI suite checks that every public top-level command group is represented in the CLI reference and navigation. The public documentation style check rejects em dashes, en dashes, and selected formulaic marketing phrases. Strict MkDocs builds validate navigation and internal links.

When a public command group or product capability is added, update this matrix, its dedicated guide, the CLI reference, and the changelog in the same release.
