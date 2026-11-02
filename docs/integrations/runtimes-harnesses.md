---
title: Runtimes and Harnesses
description: Install agent framework runtimes and compatibility adapters.
---

# Runtimes and harnesses

SuperQode registers **28 distinct runtime/backend IDs** across two execution
surfaces: 15 direct agent runtimes and 21 HarnessSpec backends, with eight IDs
shared by both. This inventory follows `runtime.registry.known_runtime_names()`
and `harness.backends.registry.known_harness_backend_names()` in this checkout.
Registration does not mean optional dependencies, accounts or remote endpoints
are already configured on your machine.

In the macOS app, open **Harness Hub → Agent runtimes** or search **Agent
Runtimes** in Command-K. The catalog reads both registries and shows every entry,
including missing dependencies and the decision-only SystemOne backend. Coding
HarnessSpec backends offer **Build with this runtime**. Direct runtimes without
a HarnessSpec adapter show their CLI/TUI selection path; their registration does
not imply a dedicated native desktop execution adapter.

## Direct agent runtimes

Choose these using `superqode --runtime <id>` or `:runtime <id>`. Run
`superqode runtime doctor <id>` to inspect the runtime. The HarnessSpec column
indicates whether the same ID also supports `runtime.backend: <id>`.

| Runtime | ID | HarnessSpec | Setup or ownership |
| --- | --- | --- | --- |
| SuperQode Core | `builtin` | Yes | Included native loop |
| Google Agent Development Kit | `adk` | Yes | Optional `superqode[adk]` extra |
| OpenAI Agents SDK | `openai-agents` | Yes | Optional `superqode[openai-agents]` extra |
| Pydantic AI | `pydanticai` | Yes | Optional `superqode[pydanticai]` extra |
| OpenAI Codex CLI | `codex-cli` | Yes | Installed Codex CLI and vendor sign-in |
| OpenAI Codex SDK | `codex-sdk` | Yes | Optional `superqode[codex-sdk]` extra |
| GitHub Copilot SDK | `copilot-sdk` | Yes | Optional `superqode[copilot-sdk]` extra and account/token |
| Anthropic Claude Agent SDK | `claude-agent-sdk` | Yes | Optional `superqode[claude-agent-sdk]` extra and API key |
| Google Antigravity SDK | `antigravity-sdk` | No | Optional `superqode[antigravity-sdk]` extra and Google API key |
| Google Antigravity CLI | `antigravity-cli` | No | Installed `agy` CLI and Google sign-in |
| Google Antigravity Managed | `antigravity-managed` | No | Included remote adapter; Google API key required |
| Cognition Devin CLI | `devin-cli` | No | Installed Devin CLI and vendor sign-in |
| Meta Muse Code | `muse` | No | Installed Muse CLI and vendor sign-in |
| GitHub Copilot CLI | `copilot-cli` | No | Installed Copilot CLI and vendor sign-in |
| Grok CLI | `grok-cli` | No | Installed Grok CLI and vendor sign-in |

For optional extras in a packaged CLI installation, use
`uv tool install "superqode[<extra>]"`. Contributors can use
`uv sync --extra <extra>`. These commands do not install into the macOS app's
bundled engine. The app reports the active engine's setup status; managed setup
support varies by runtime.

See [Agent Runtimes](../runtimes.md) for runtime behavior and account boundaries,
[Python Runtimes](../advanced/python-runtimes.md) for embedding APIs, and
[Runtime Commands](../cli-reference/runtime-commands.md) for selection controls.

## Additional HarnessSpec backends

The following 13 IDs extend the eight shared backends above. Select them using
`runtime.backend: <id>` in a HarnessSpec. Inspect the complete capability catalog
with `superqode harness list-backends`; use
`superqode harness doctor --spec <file>` to check a configured harness.

| Backend | ID | Setup and scope |
| --- | --- | --- |
| AWS Strands Harness | `strands` | Separate managed runtime via `superqode harness strands setup`; [guide](../advanced/strands-harness.md) |
| LangChain DeepAgents | `deepagents` | Optional `superqode[deepagents]` extra; tool-capable coding harnesses; [guide](../providers/deepagents.md) |
| DeepSeek Harness | `deepseek-harness` | Optional `superqode[deepseek-harness]` extra; [guide](../advanced/deepseek-harness.md) |
| Prime Agent | `prime-agent` | External Prime Agent runtime; [guide](../providers/prime-agent.md) |
| SuperQode RLM | `rlm` | Native recursive coding loop; execution-boundary setup depends on the profile; [guide](../advanced/recursive-agent-harness.md) |
| RLM Code | `rlm-code` | Optional `superqode[rlm-code]` extra; [guide](../advanced/rlm-code.md) |
| PiPy | `pipy` | Included Python coding harness with host permissions |
| CodeGem | `codegem` | Included coding loop for Gemini and local Gemma; [guide](../advanced/harness2.md) |
| Hugging Face Tau | `tau` | Optional `superqode[tau]` extra and Tau setup; [guide](../advanced/tau.md) |
| Google Agent Engine | `google-agent-engine` | Remote managed agent; provider credentials and endpoint configuration |
| Anthropic Managed Agents | `anthropic-managed` | Remote managed agent; provider credentials and endpoint configuration |
| Unified Harness Protocol | `uhp` | Remote harness server; [guide](../advanced/harness-protocol.md) |
| SystemOne Decisions | `systemone` | Structured decision-pack evaluation; not a coding loop |

PydanticAI Logfire, Prefect and DBOS integrations are configurations of the
`pydanticai` backend, rather than separate runtime IDs. Harness presets such as
Workbench are definitions over a backend, rather than additional runtime IDs.
ACP and A2A agent connections are separate protocol catalogs; individual agents
in those catalogs are not counted as runtime registrations here.

## Omnigent compatibility

Omnigent support is an included format and execution bridge. It imports a
compatible `agent.yaml` into a repository-owned HarnessSpec; it does not run
the Omnigent server or managed host workflow.

```bash
superqode harness import-omnigent path/to/agent.yaml --output harness.yaml
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
```

See [Omnigent Compatibility](../advanced/omnigent-compat.md) for field mapping
and the interoperability boundary.
