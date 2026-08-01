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
