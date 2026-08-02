---
title: Protocols and Tools
description: Configure ACP, MCP, A2A, semantic search, and execution tools.
---

# Protocols and tools

## Protocols

| Protocol | Dependency | First use | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| Agent Client Protocol, ACP | **Included** | `:connect acp <agent>` | `superqode agents doctor <agent>` | [ACP Coding Agents](../providers/acp.md) |
| Model Context Protocol, MCP | **Included** | Configure a server in `superqode.yaml` | `:mcp doctor` | [MCP Configuration](../configuration/mcp-config.md) |
| Agent2Agent, A2A | `uv tool install "superqode[a2a]"` | `:a2a connect <url>` | `:a2a discover <url>` | [A2A Agents](../providers/a2a.md) |
| Harness Protocol | **Included** | `superqode harness protocol list` | `superqode harness protocol conformance` | [Harness Protocol](../advanced/harness-protocol.md) |

SuperQode can expose a harness as an MCP, ACP, or A2A service. See
[Serve a Harness over ACP](../advanced/acp-agent-server.md), the
[MCP command](../cli-reference/mcp-command.md), and the
[A2A server guide](../providers/a2a.md#expose-a-harness).

## A2A and multiplayer computers

[A2A](../providers/a2a.md) is SuperQode’s primary **harness-to-harness** and
agent-to-agent network surface. Other agents discover SuperQode through a public
[Agent Card](https://super-agentic.ai/.well-known/agent-card.json) and call the
interface URL advertised in that card. Operational calls on the public pilot
require bearer authentication (`SUPERQODE_A2A_TOKEN` when serving remotely).

This is the preferred way to collaborate with **multiplayer agent computers**
such as [YC’s QM](https://github.com/yc-software/qm): keep SuperQode as the
versioned HarnessSpec, kernel, and evidence layer, and keep the multiplayer
system as the org-shared computer. Do not merge runtimes; exchange tasks over
A2A.

An experimental, non-product packaging sketch for running SuperQode as a tool
inside a QM-style deploy directory lives at
[examples/qm-deployment-layer](https://github.com/SuperagenticAI/superqode/tree/main/examples/qm-deployment-layer).
Treat that as compatibility exploration, not official QM support. Independent
TypeScript and Python A2A clients for interop checks are documented under
[A2A Protocol](../providers/a2a.md#interop-clients-in-this-repository).

| First step | Command or URL |
| --- | --- |
| Public Agent Card | `https://super-agentic.ai/.well-known/agent-card.json` |
| Serve a harness over A2A | `superqode serve a2a --spec harness.yaml` |
| Call / discover from the TUI | `:a2a discover <url>` · `:a2a connect <url>` |
| Full guide | [A2A Protocol](../providers/a2a.md) |

## CocoIndex Code semantic search

The `semantic` extra installs the slim CocoIndex Code client. A local Ollama
embedding route avoids adding Torch or sentence-transformers to the SuperQode
environment.

```bash
uv tool install "superqode[semantic]"
ollama pull nomic-embed-text
ccc init --litellm-model ollama/nomic-embed-text
ccc index
```

The `semantic_search` tool registers when CocoIndex Code is importable. Verify
the index directly with `ccc search "<query>"`, then use the tool from a
SuperQode-owned harness. See [Semantic Code Search](../advanced/semantic-search.md).

## Monty Python REPL

Install the sandboxed Python execution tool:

```bash
uv tool install "superqode[monty]"
superqode providers doctor
```

Add the Monty tool to a HarnessSpec when a model needs bounded Python
calculation. See [Monty Python REPL](../advanced/monty-python-repl.md).

## MCP tools and plugins

MCP clients and servers are included. Repository plugins can add tools,
commands, hooks, and integration-specific behavior without changing the core
package:

```text
:mcp doctor
superqode plugins list
superqode plugins doctor
```

See [MCP Configuration](../configuration/mcp-config.md) and
[Plugin Authoring](../advanced/plugin-authoring.md).
