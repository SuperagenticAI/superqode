---
title: All Integrations
description: Alphabetical index of systems integrated with SuperQode.
---

# All integrations

This index lists the integration names documented in this section. Installation
commands, authentication requirements, diagnostics, and operational boundaries
are documented on the linked category page.

| Integration | Function | Category |
| --- | --- | --- |
| Agent Client Protocol, ACP | Connect external coding agents and expose normalized sessions | [Protocols and tools](protocols-tools.md) |
| Agent2Agent, A2A | Discover, call, and serve interoperable agents; public Agent Card pilot | [Protocols and tools](protocols-tools.md#a2a-and-multiplayer-computers) |
| QM (YC multiplayer harness) | Experimental peer packaging and A2A collaboration boundary, not product support | [Protocols and tools](protocols-tools.md#a2a-and-multiplayer-computers) · [A2A Protocol](../providers/a2a.md#multiplayer-computers-and-qm-experimental) |
| Amazon Bedrock AgentCore | Experimental remote code-interpreter sandbox | [Sandboxes](sandboxes.md) |
| Anthropic Claude Agent SDK | Run the Claude Agent SDK through a SuperQode runtime adapter | [Coding agents](coding-agents.md) |
| Apple Container | Experimental macOS-native container status integration | [Sandboxes](sandboxes.md) |
| Apple Foundation Models | Route supported utility work to an on-device Apple model | [Models and inference](models-inference.md) |
| Arize Phoenix | Export harness traces through an OTEL collector path | [Observability](observability.md) |
| AutoResearch | Edit and evaluate optimization candidates through Claude Code | [Optimization](optimization.md) |
| Claude Code over ACP | Connect an authenticated Claude Code agent | [Coding agents](coding-agents.md) |
| CocoIndex Code | Add AST-aware semantic code search | [Protocols and tools](protocols-tools.md) |
| Codex over ACP | Connect the Codex CLI as an ACP coding agent | [Coding agents](coding-agents.md) |
| Cognee | Use a separately installed local or cloud memory provider | [Memory](memory.md) |
| Daytona | Execute commands in a remote development sandbox | [Sandboxes](sandboxes.md) |
| DeepAgents | Execute a HarnessSpec through the DeepAgents runtime | [Runtimes and harnesses](runtimes-harnesses.md) |
| Discord | Control the channel daemon through a Discord bot | [Remote interfaces](remote-interfaces.md) |
| Docker | Execute commands in a local container sandbox | [Sandboxes](sandboxes.md) |
| DwarfStar | Connect a compatible local inference server | [Models and inference](models-inference.md) |
| E2B | Execute commands in an E2B cloud sandbox | [Sandboxes](sandboxes.md) |
| Exa | Add the optional Exa search client | [Models and inference](models-inference.md) |
| GEPA | Optimize text artifacts through reflective search | [Optimization](optimization.md) |
| GEPA meta-harness | Maintain and evaluate an optimization candidate frontier | [Optimization](optimization.md) |
| GEPA Omni | Explore with GEPA, AutoResearch, and GEPA meta-harness | [Optimization](optimization.md) |
| GitHub Copilot | Use a Copilot plan through the SDK or official CLI | [Coding agents](coding-agents.md) |
| Google Agent Development Kit | Execute a HarnessSpec through Google ADK | [Runtimes and harnesses](runtimes-harnesses.md) |
| Google Antigravity CLI | Connect the signed-in `agy` coding agent | [Coding agents](coding-agents.md) |
| Google Antigravity SDK | Execute the Antigravity SDK through a runtime adapter | [Coding agents](coding-agents.md) |
| Harness Protocol | Operate native and external harnesses through one lifecycle | [Protocols and tools](protocols-tools.md) |
| Hugging Face Hub | Search and download hosted model artifacts | [Models and inference](models-inference.md) |
| Hugging Face Tau | Connect the Tau harness through a read-only integration | [Runtimes and harnesses](runtimes-harnesses.md) |
| Kimi Code | Connect the Kimi CLI over ACP | [Coding agents](coding-agents.md) |
| LangSmith observability | Export normalized runs as LangSmith run trees | [Observability](observability.md) |
| LangSmith sandbox | Execute commands in an experimental LangSmith sandbox | [Sandboxes](sandboxes.md) |
| LiteLLM | Route model requests across supported providers | [Models and inference](models-inference.md) |
| LM Studio | Connect a local OpenAI-compatible model server | [Models and inference](models-inference.md) |
| Local memory | Store explicit memories in the local SuperQode data directory | [Memory](memory.md) |
| Local OS sandbox | Apply macOS Seatbelt or Linux Bubblewrap isolation | [Sandboxes](sandboxes.md) |
| Logfire | Mirror run summaries and events as spans and logs | [Observability](observability.md) |
| Mem0 | Add the optional Mem0 memory provider | [Memory](memory.md) |
| MetaHarness | Export and optimize a HarnessSpec through Superagentic MetaHarness | [Optimization](optimization.md) |
| Microsoft Model Context Protocol, MCP | Connect tool servers and expose harness tools | [Protocols and tools](protocols-tools.md) |
| MLflow | Export run artifacts and metrics | [Observability](observability.md) |
| MLX and MLX-VLM | Run supported models locally on Apple Silicon | [Models and inference](models-inference.md) |
| Modal | Execute commands in a Modal cloud sandbox | [Sandboxes](sandboxes.md) |
| Monty Python REPL | Add bounded Python calculation to a harness | [Protocols and tools](protocols-tools.md) |
| Ollama | Connect locally served models | [Models and inference](models-inference.md) |
| Omnigent | Import compatible Omnigent agent specifications | [Runtimes and harnesses](runtimes-harnesses.md) |
| OpenAI Agents SDK | Execute a HarnessSpec through OpenAI Agents | [Runtimes and harnesses](runtimes-harnesses.md) |
| OpenAI Codex SDK | Connect the authenticated Codex SDK runtime | [Coding agents](coding-agents.md) |
| OpenResponses | Use the built-in OpenResponses-compatible gateway | [Models and inference](models-inference.md) |
| OpenTelemetry | Export live harness spans to an OTLP collector | [Observability](observability.md) |
| Plugins | Add repository-owned tools, commands, and hooks | [Protocols and tools](protocols-tools.md) |
| Podman | Execute commands in a local container sandbox | [Sandboxes](sandboxes.md) |
| PydanticAI | Execute a HarnessSpec through PydanticAI | [Runtimes and harnesses](runtimes-harnesses.md) |
| Qwen Code | Connect the first-party Qwen Code ACP server | [Coding agents](coding-agents.md) |
| RLM Code | Execute recursive workflows through the RLM Code backend | [Runtimes and harnesses](runtimes-harnesses.md) |
| Runloop | Execute commands in an experimental Runloop devbox | [Sandboxes](sandboxes.md) |
| SGLang | Connect a local SGLang inference endpoint | [Models and inference](models-inference.md) |
| SkillOpt | Coordinate optimization and review of markdown skills | [Optimization](optimization.md) |
| Slack | Control the channel daemon through Slack Socket Mode | [Remote interfaces](remote-interfaces.md) |
| SpecMem | Store project-scoped HarnessSpec memory | [Memory](memory.md) |
| Supermemory | Add the optional Supermemory provider | [Memory](memory.md) |
| Telegram | Control the channel daemon through a Telegram bot | [Remote interfaces](remote-interfaces.md) |
| Text Generation Inference, TGI | Connect a local or remote TGI endpoint | [Models and inference](models-inference.md) |
| Transformers | Run supported Hugging Face models through a local Python stack | [Models and inference](models-inference.md) |
| Unified Harness Protocol, UHP | Run harnesses hosted on a UHP server through one HTTP contract | [Protocols and tools](protocols-tools.md) |
| vLLM | Connect a local or remote vLLM endpoint | [Models and inference](models-inference.md) |
| Vercel Sandbox | Execute commands through the Vercel Sandbox CLI | [Sandboxes](sandboxes.md) |
| Web TUI | Host the terminal interface in a browser | [Remote interfaces](remote-interfaces.md) |
| xAI Grok Build | Connect the authenticated Grok coding agent | [Coding agents](coding-agents.md) |

Provider-specific model routes are maintained in the
[provider catalog](../providers/index.md). ACP agent packages are maintained in
the [ACP catalog](../providers/acp.md). Those dynamic catalogs are not expanded
into separate left-navigation entries.
