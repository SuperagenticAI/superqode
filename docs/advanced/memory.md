# Agent Memory Layer

SuperQode memory is now an agent-memory layer, not a rule suppression store.

The goal is to make memory inspectable, configurable, and provider-neutral:

- explicit user/project/team memories
- SpecMem-aware coding memory
- optional Mem0, Cognee, and Supermemory providers
- future MCP memory providers
- vector databases as storage backends, not the product abstraction

## Quick Start

Start with local memory. It needs no extra dependency and is the default:

```bash
superqode memory providers
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference --tag tooling
superqode memory search "package manager"
```

In the TUI:

```text
:memory providers
:memory remember Use pnpm in this repo; do not use npm
:memory search package manager
```

Provider readiness uses these states:

| State | Meaning |
| --- | --- |
| `ready` | Provider can be used now |
| `disabled` | Provider exists but is not enabled in `superqode.yaml` |
| `missing` | Provider is enabled but its SDK, CLI, workspace, or API key is missing |

Memory is currently retrieved only when you ask for it with `memory search` or
`:memory search`. SuperQode does not yet auto-inject memories into every agent
turn.

## Command Reference

TUI:

```text
:memory
:memory status
:memory providers
:memory doctor
:memory remember <text>
:memory search <query>
:memory search specmem <query>
:memory forget <id>
:memory export [local|specmem]
```

CLI:

```bash
superqode memory status
superqode memory providers
superqode memory doctor
superqode memory remember "This repo uses pnpm, never npm" --kind preference --tag package-manager
superqode memory search "package manager"
superqode memory search "auth requirements" --provider specmem
superqode memory search "auth requirements" --provider mem0
superqode memory forget <id>
superqode memory export --provider local -o memory.json
```

## Automatic Capture (Opt-In)

By default, nothing is written to memory unless you ask. Opt in and SuperQode extracts durable knowledge from completed runs automatically:

```bash
export SUPERQODE_AUTO_MEMORY=1
```

After a run completes, a background extraction call distills up to five memories per run, limited to three kinds:

- **preference**: explicit instructions about how to work ("use pnpm, never npm")
- **fact**: non-obvious project knowledge discovered during the work ("tests need the DS4 server running")
- **decision**: choices made and why

Extractions are deduplicated against existing memories, tagged `auto` so you can find or purge them (`superqode memory search auto`), stored in the local provider, and never block the run (extraction happens in the background and fails silently by design). Trivial exchanges are skipped.

## Automatic Recall (Opt-In)

Capture is the write side; recall is the read side. Opt in and SuperQode surfaces relevant saved memories to the agent at the start of each run:

```bash
export SUPERQODE_AUTO_RECALL=1
```

When a run starts, the local memory store is searched with your prompt. The top hits (at most four, above a relevance floor) ride along on the request as a `<system-reminder>` block, clearly labeled as background context the agent should verify before relying on. The reminder is attached to the outgoing request only and is never written into conversation history, so it costs context once per prompt, not per turn.

Two safety properties are deliberate:

- **Only the local provider is read.** It lives under `~/.superqode/memory/` and contains only what you stored (or opt-in capture stored on your behalf), so an untrusted repository can never plant content into your agent's context through recall.
- **The agent is told what it is.** Recalled items are framed as saved notes to verify, not as instructions.

Enable both sides for the full loop: `SUPERQODE_AUTO_MEMORY=1` learns durable facts from completed runs, and `SUPERQODE_AUTO_RECALL=1` brings them back when they matter.

```bash
export SUPERQODE_AUTO_MEMORY=1
export SUPERQODE_AUTO_RECALL=1
superqode memory remember "Tests require the DS4 server on port 8000" --kind fact
superqode -p "run the integration tests"   # the DS4 note rides along automatically
```

Without recall enabled, stored memories surface only through explicit `search`, `export`, and the TUI `:memory` commands, so you always know what the agent is working from.

## Providers

Keep `local` as the default provider unless a project has a clear reason to use
hosted or graph memory:

```yaml
memory:
  default_provider: local
  providers:
    local:
      enabled: true
```

### `local`

Local memory is user-local and project-scoped by default:

```text
~/.superqode/memory/agent-{project_hash}.json
```

It stores explicit memories such as:

- preferences
- project facts
- procedures
- decisions
- repo-specific warnings

Example:

```bash
superqode memory remember "Use pnpm in this repo; do not use npm." --kind preference --tag tooling
superqode memory remember "Auth changes require tests/test_auth.py." --kind procedure --tag auth
```

### `specmem`

SpecMem is treated as a first-class coding-memory provider. SuperQode detects a
project `.specmem/` workspace and searches Agent Experience Pack files directly:

```text
.specmem/agent_memory.json
.specmem/agent_context.md
.specmem/knowledge_index.json
.specmem/impact_graph.json
```

Search SpecMem context:

```bash
superqode memory status --provider specmem
superqode memory search "checkout flow" --provider specmem
```

In the TUI:

```text
:memory search specmem checkout flow
```

SuperQode does not require SpecMem as a dependency. If the `specmem` CLI is
installed, `memory status --provider specmem` reports it.

SpecMem is not the default provider. Use it explicitly with
`--provider specmem` or enable it in config if a project wants it listed as an
active provider:

```yaml
memory:
  default_provider: local
  providers:
    specmem:
      enabled: true
      root: .specmem
```

### `mem0`

Mem0 is available as an optional hosted provider through the current `mem0ai`
SDK.

Install:

```bash
pip install "superqode[mem0]"
```

Configure:

```yaml
memory:
  default_provider: local
  providers:
    mem0:
      enabled: true
      api_key_env: MEM0_API_KEY
      user_id: my-project-or-user
```

Then:

```bash
export MEM0_API_KEY=...
superqode memory status --provider mem0
superqode memory remember "User prefers pytest examples" --kind preference
superqode memory search "pytest examples" --provider mem0
```

### `cognee`

Cognee is available as an optional local or cloud provider through a separately
installed Cognee SDK or `cognee-cli`. SuperQode calls Cognee's `remember` and
`recall` operations when available.

Install Cognee separately in an environment compatible with Cognee's dependency
tree, or expose `cognee-cli` on `PATH`:

```bash
pip install "cognee>=1.1.2,<2.0.0"
```

Current note: Cognee `1.1.2` depends through `instructor` on `rich<15`, while
SuperQode uses `rich>=15`. For that reason SuperQode does not currently ship a
bundled `superqode[cognee]` extra. The adapter remains configurable for
developers who run Cognee separately or resolve that dependency boundary in
their own environment.

Configure local Cognee with the environment variables Cognee expects, for
example `LLM_API_KEY`, or point to Cognee Cloud with `COGNEE_SERVICE_URL` and
`COGNEE_API_KEY`.

```yaml
memory:
  default_provider: local
  providers:
    cognee:
      enabled: true
      session_id: superqode
```

Then:

```bash
superqode memory status --provider cognee
superqode memory search "release checklist" --provider cognee
```

### `supermemory`

Supermemory is available as an optional hosted provider through the current
`supermemory` Python SDK.

Install:

```bash
pip install "superqode[supermemory]"
```

Configure:

```yaml
memory:
  default_provider: local
  providers:
    supermemory:
      enabled: true
      api_key_env: SUPERMEMORY_API_KEY
      container_tags:
        - superqode
        - my-project
```

Then:

```bash
export SUPERMEMORY_API_KEY=...
superqode memory status --provider supermemory
superqode memory search "API contract" --provider supermemory
```

### Install All Optional Providers

```bash
pip install "superqode[memory-providers]"
```

`memory-providers` installs Mem0 and Supermemory. Install Cognee separately
until its dependency tree is compatible with SuperQode's Rich version.

## Memory Is Not A Vector DB

Vector databases are storage backends. The SuperQode memory abstraction is about
what the agent can safely remember and retrieve.

Useful storage backends for future providers:

| Backend | Fit |
| --- | --- |
| LanceDB | Best local-first vector store for coding memory |
| Chroma | Easy local prototyping |
| Qdrant | Local/server production vector search |
| pgvector | Teams already using Postgres |
| SQLite FTS/BM25 | Deterministic local keyword recall |

SuperQode should keep retrieval hybrid:

```text
semantic score + keyword match + recency + path relevance + source trust
```

## Planned Providers

The provider interface is designed to support:

- `mcp`: memory servers exposed through MCP
- `zep` / Graphiti: temporal graph memory

These should be optional extras or MCP connections, not hard dependencies.

## Trust And Privacy

Memory should be visible and controllable:

- no automatic long-term writes by default (automatic capture is strictly opt-in via `SUPERQODE_AUTO_MEMORY=1`, and everything it stores is tagged `auto`)
- no automatic prompt injection
- explicit `remember` for local memory
- source/provider shown in search results
- project/team-shared writes should respect project trust
- secrets should not be stored in memory

Use project trust commands before enabling project-local memory integrations:

```bash
superqode trust doctor
superqode trust yes
```
