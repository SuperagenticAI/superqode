# Semantic Code Search

Semantic search finds code by intent instead of exact text or symbol names.
For example, a query such as "where is the conversation history compacted" can
return the relevant implementation even when the code uses different wording.

It complements the built-in search tools:

| Tool | Finds | Example |
|---|---|---|
| `grep` | An exact regex or text pattern | `def\s+compact` |
| `code_search` | A symbol by name | `CompactTool` |
| `semantic_search` | Code by intent or description | "how history is trimmed when the window fills" |

SuperQode integrates [cocoindex-code](https://github.com/cocoindex-io/cocoindex-code)
(Apache-2.0). It builds an AST-aware, embedding-backed index and serves queries
from a background daemon. The native SuperQode extra installs the slim client by
default; local embeddings can run through Ollama/LiteLLM without adding
sentence-transformers or torch to the SuperQode environment.

You can use it two ways. They are independent, and you can run both.

## Option A: Native tool (recommended)

This exposes a first-class `semantic_search` tool inside SuperQode's own agent
loop, governed by the same policy and permission system as every other tool.

### 1. Install the integration

```bash
uv pip install 'superqode[semantic]'
```

This pulls in the slim `cocoindex-code` client. It supports LiteLLM embeddings,
including local Ollama models, without installing `sentence-transformers`.

### 2. Index a project once

Run this in the project you want to search. The daemon starts automatically on
first use.

```bash
ollama pull nomic-embed-text
ccc init --litellm-model ollama/nomic-embed-text
ccc index
```

For offline Hugging Face sentence-transformers instead, install the heavier
extra explicitly:

```bash
uv pip install 'cocoindex-code[full]'
ccc init
ccc index
```

### 3. Use it

The tool registers automatically once `cocoindex-code` is importable. Ask the
agent a conceptual question, or invoke the tool directly:

```text
semantic_search(query="logic that decides if a local model gets tools", limit=5)
```

Parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `query` | required | Natural-language description or code snippet. |
| `limit` | `10` | Maximum results (capped at 50). |
| `offset` | `0` | Skip ranked results for pagination. |
| `languages` | all | Filter, for example `["python", "typescript"]`. |
| `paths` | all | Path globs, for example `["src/superqode/tools/*"]`. |
| `refresh` | `false` | Re-index changed files before searching (slower). |

If `cocoindex-code` is not installed, the tool is not registered, so there
is no failure and no hard dependency.

For local-first coding harnesses, prefer an Ollama embedding model such as
`nomic-embed-text` unless you specifically need sentence-transformers. It keeps
SuperQode's Python environment smaller and avoids importing torch in the agent
process.

## Option B: MCP server

This runs cocoindex-code as a standalone MCP server. Pick this when you want one
index shared across multiple agents, such as SuperQode, Claude Code, Codex, or
Cursor, without using SuperQode's native tool integration.

Install `ccc` as a user-level command first:

```bash
uv tool install 'cocoindex-code'
```

For fully offline sentence-transformers embeddings, install the heavier variant
instead:

```bash
uv tool install 'cocoindex-code[full]'
```

Add it to your MCP configuration:

```yaml
mcp_servers:
  cocoindex-code:
    transport: stdio
    command: ccc
    args: ["mcp"]
```

See [MCP Configuration](../configuration/mcp-config.md) for where this file
lives and how servers are connected. The server exposes a `search` tool;
SuperQode reaches it through the standard MCP tool bridge.

The MCP `search` tool accepts:

| Parameter | Default | Meaning |
|---|---|---|
| `query` | required | Natural-language query or code snippet. |
| `limit` | `5` | Maximum results, 1-100. |
| `offset` | `0` | Skip ranked results for pagination. |
| `refresh_index` | `true` | Incrementally update the index before searching. |
| `languages` | all | Language filters such as `["python"]`. |
| `paths` | all | Glob filters such as `["src/utils/*"]`. |

Operationally, the MCP path is the lightest boundary for SuperQode because
`ccc` can be installed with `uv tool` or `pipx` outside SuperQode's environment.
The tradeoff is that `ccc mcp` starts a background index task when the server
starts, and MCP searches refresh the index by default. On laptops or small local
machines, pre-index with `ccc index` and ask the MCP tool to use
`refresh_index=false` for consecutive searches when the code has not changed.

## Which option to pick

| You want | Use |
|---|---|
| A first-class SuperQode tool under harness policy | Option A |
| The lightest SuperQode dependency footprint | Option B |
| One shared index across several different agents | Option B |
| Low-overhead repeated searches on a local laptop | Option A with `refresh=false`, or Option B with `refresh_index=false` |
| Both native SuperQode and external agents | Install Option A, and add the Option B entry too |

## Keeping the index fresh

The daemon re-indexes incrementally and only reprocesses changed files, so
re-running `ccc index` after edits is fast. To reflect uncommitted edits in a
single query without a manual re-index, pass `refresh=true` to the native tool.

For local models, keep routine agent turns low-overhead by leaving
`refresh=false`. Run `ccc index` manually after batches of edits, or use
`refresh=true` only when the agent must search changes made moments ago.
Indexing is the expensive part; normal searches use the existing index and only
embed the query.

## Local Harnesses

Local harnesses can use semantic search like any other read-only search tool
once `superqode[semantic]` is installed. Add it to the agent's tool list when
you want conceptual repo lookup:

```yaml
agents:
  - id: local-coder
    tools:
      - read_file
      - grep
      - glob
      - repo_search
      - code_search
      - semantic_search
      - edit_file
      - patch
      - bash
```

For small local models, keep `parallel_tools: false` and prefer explicit search
requests such as "use semantic_search for the relevant implementation". If the
extra is not installed, leave `semantic_search` out of the harness; SuperQode
registers the tool only when `cocoindex-code` is importable.

## Verifying the setup

```bash
ccc status     # chunk count, file count, language breakdown
ccc doctor     # checks settings, daemon, model, and index health
ccc search "authentication logic"   # confirm results outside the agent
```
