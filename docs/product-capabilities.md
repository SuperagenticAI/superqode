# Product Capability Reference

This page maps SuperQode product capabilities to their implementation surfaces
and detailed documentation. It tracks the public user-facing surfaces in the
current codebase.

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
| Session sharing | Portable exports, imports, revocation, local artifacts, and switchboard tree sharing | [Session Sharing](advanced/session-sharing.md) |
| Coding-agent connections | Native clients, ACP agents, subscription CLIs, SDK runtimes, BYOK providers, and local servers | [Connection Methods and Vendors](concepts/modes.md) |
| Model connections | Local engines, BYOK providers, subscription runtimes, model profiles, and fallbacks | [Models and Providers](providers/index.md) |
| Agent catalog | Official ACP Registry cache, bundled offline metadata, installation checks, store views, and free-model discovery | [Agents Commands](cli-reference/agents-commands.md) |
| Model catalog and artifacts | models.dev metadata, Hugging Face search, downloads, cached artifacts, MLX conversion, and capability filters | [Model Catalog](advanced/model-catalog.md) |
| Provider diagnostics | Readiness, setup guides, recommendations, smoke tests, live free-route scans, and local server inspection | [Provider Commands](cli-reference/provider-commands.md) |
| Local inference | Ollama, LM Studio, MLX, DwarfStar, llama.cpp, vLLM, SGLang, TGI, and DS4 | [Local Models](providers/local.md) |
| Poolside Laguna S 2.1 | Shared GGUF discovery, DwarfStar and llama.cpp launch paths, model policy, reasoning preservation, and TUI variants | [DwarfStar and Laguna](providers/local.md#dwarfstar-ds4) |
| Harness Protocol | Versioned lifecycle, event envelope, conformance checks, adapters, and session export | [Harness Protocol v1](advanced/harness-protocol.md) |
| Runtime adapters | Builtin, OpenAI Agents, Google ADK, Codex SDK, GitHub Copilot SDK, Claude Agent SDK, Antigravity SDK and CLI, DeepAgents, and PydanticAI | [Runtime Backends](runtimes.md) |
| Harness backends | Native runtime adapters, RLM Code, Google Agent Engine, Anthropic managed agents, and backend capability diagnostics | [Harness System](advanced/harness-system.md) |
| Tool policy | Repository reads, search, edits, shell, MCP, network, diagnostics, image tools, and validation | [Tools Catalog](advanced/tools-catalog.md) |
| Tool profiles | Core, Workbench, no-tool, build, plan, and review registries with per-tool permissions | [Tools Catalog](advanced/tools-catalog.md) |
| Safety and governance | Permissions, sandboxes, trust checks, approvals, contextual policy, budgets, and credential controls | [Safety and Permissions](advanced/safety-permissions.md) |
| Context and memory | Context detection, compaction, local memory, provider adapters, and repository search | [Memory and Learning](advanced/memory.md) |
| Repository workspaces | Git safety, worktrees, multi-repository search, snapshots, diffs, and post-edit verification | [Workspace System](advanced/workspace-system.md) |
| Planning and review | Plan-only execution, shared plan events, TODOs, clarification cards, diff review, rewind, and transcript selection | [TUI](advanced/tui.md) |
| Terminal workflow | Command palette, state notifications, runtime and harness pickers, themes, exports, optional Vim navigation, and keyboard-first operation | [TUI](advanced/tui.md) |
| Evaluation | Harness tests, eval packs, scorecards, benchmarks, evidence, and regression gates | [Harness Optimization](advanced/harness-optimization.md) |
| Structured output | JSON mode, JSON Schema validation, corrective retries, rubric grading, and CI-oriented exit behavior | [Headless and CI](advanced/headless-ci.md) |
| Optimization | Candidate generation, failure mining, Pareto selection, held-out evaluation, promotion, and rollback | [Optimization](advanced/optimization.md) |
| Recursive workflows | RLM Code backend, context handles, spawned harnesses, bounded scripts, and replayable evidence | [RLM Code Integration](advanced/rlm-code.md) |
| Offline operation | Airplane Mode, cached metadata, local search roots, local servers, and denied network tools | [Airplane Mode](advanced/airplane-mode.md) |
| Durable repository delivery | WorkOrders, task dependencies, isolated workers, leases, recovery, checks, reviews, and merge decisions | [WorkOrders](advanced/workorders.md) |
| Code Factory operation | Harnesses, routes, sessions, WorkOrders, evidence, governance, evaluation, and improvement | [Code Factory](advanced/software-factory.md) |
| Skills and recipes | Project skills, reusable instructions, recipe execution, skill checks, and guarded SkillOpt improvements | [Developer Workflows](developer-workflows.md) |
| Extensions | Python tools, TUI commands, skills, hooks, providers, package entry points, trust, and compatibility checks | [Plugin Authoring](advanced/plugin-authoring.md) |
| Protocol integration | MCP tools and servers, ACP clients and server, A2A workflows, and Harness Protocol adapters | [Advanced Workflows](advanced/index.md) |
| Observability | Normalized logs, harness events, run graphs, optional sinks, evidence exports, and replay | [Logging System](advanced/logging-system.md) |
| Automation | Headless execution, structured output, CI gates, persistent workers, and daemon operation | [Headless and CI](advanced/headless-ci.md) |
| Remote access | Telegram, Slack, and Discord control, local companion API, browser TUI, ACP serving, and MCP serving | [Chat Channels](advanced/channels.md) |
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
