---
title: Integrations
description: Reference for SuperQode integration dependencies, configuration, diagnostics, and commands.
---

# Integrations

The integration catalog is organized by technical function. Each category
provides the required dependency, authentication method, initial command,
diagnostic command, and link to the detailed feature guide.

The [Connect guide](../concepts/modes.md) explains how to select an active
coding agent, model, provider, or harness. The pages in this section cover
installation and operation of the systems connected to those execution paths.
The [Harness Hub](../harness-hub.md) presents the usable coding-agent and
harness inventory as one searchable terminal product surface, including local
readiness, provenance, setup guidance, and project-owned HarnessSpecs.

## Integration categories

| Category | Included systems |
| --- | --- |
| [Coding agents](coding-agents.md) | Codex, Claude Code, GitHub Copilot, Antigravity, Grok, Kimi Code, Qwen Code, and ACP agents |
| [Models and inference](models-inference.md) | LiteLLM, OpenResponses, hosted providers, Ollama, LM Studio, vLLM, SGLang, TGI, MLX, DwarfStar, and Hugging Face |
| [Runtimes and harnesses](runtimes-harnesses.md) | Google ADK, OpenAI Agents SDK, PydanticAI, DeepAgents, RLM Code, Hugging Face Tau, and Omnigent |
| [Protocols and tools](protocols-tools.md) | ACP, MCP, A2A (public Agent Card, multiplayer peers such as QM), Harness Protocol, CocoIndex Code, Monty, and plugins |
| [Optimization](optimization.md) | GEPA, GEPA Omni, AutoResearch, MetaHarness, and SkillOpt |
| [Memory](memory.md) | Local memory, SpecMem, Mem0, Cognee, and Supermemory |
| [Sandboxes](sandboxes.md) | Local OS isolation, containers, E2B, Daytona, Modal, Vercel, Runloop, AgentCore, and LangSmith |
| [Observability](observability.md) | OpenTelemetry, MLflow, LangSmith, Logfire, and Arize Phoenix |
| [Remote interfaces](remote-interfaces.md) | Telegram, Slack, Discord, and the browser-hosted TUI |
| [Dependency compatibility](dependency-compatibility.md) | Optional-extra conflicts and environment isolation requirements |

## Integration status

| Status | Meaning |
| --- | --- |
| **Included** | Available in the standard SuperQode installation |
| **Optional extra** | Install a named `superqode[...]` dependency group |
| **External application** | Install and authenticate a separate CLI or local server |
| **External service** | Configure an account, credential, or service endpoint |
| **Compatibility adapter** | Import or operate another harness through a defined boundary |
| **Experimental** | Available for evaluation, with a narrower support or safety boundary |

## Install an optional extra

The product-facing setup command is stable:

| SuperQode environment | Command |
| --- | --- |
| Installed as a `uv` tool | `uv tool install "superqode[<extra>]"` |
| Running from this source repository (contributors) | `uv sync --extra <extra>` |

SuperQode does not install optional packages automatically and does not ask
users to modify an unrelated project's dependency manifest.

## Diagnose an integration

Select the most specific available diagnostic command before running a paid or
mutating task:

```text
superqode doctor
superqode providers doctor <provider>
superqode runtime doctor <runtime>
superqode agents doctor <agent>
:mcp doctor
:a2a discover <url>
superqode sandbox doctor <backend>
superqode memory status
superqode harness observability status
superqode harness doctor --spec harness.yaml
```

Diagnostic commands report missing dependencies, unavailable executables,
missing credentials, and incompatible configuration without starting the full
coding task.
