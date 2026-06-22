# Airplane Mode

Airplane Mode prepares a local coding session that keeps working after the
network disappears. It is stricter than ordinary local mode: the generated
harness denies network access, hides web-shaped tools from the agent, and uses
only local repositories, local model servers, local indexes, and cached model
metadata.

Use it before a flight, train ride, locked-down customer site, or any session
where the model must not reach the internet.

```bash
superqode local airplane prepare \
  --repo . \
  --ref ~/src/reference-api \
  --ref ~/src/reference-web \
  --model ollama/qwen3:8b

superqode --harness superqode.airplane.yaml -p "implement the feature"
```

The same setup can run from the TUI command prompt:

```text
:local airplane doctor --repo . --ref ~/src/reference-api
:local airplane prepare --repo . --ref ~/src/reference-api --model ollama/qwen3:8b --force
:local airplane smoke --repo . --ref ~/src/reference-api
:harness superqode.airplane.yaml
```

`prepare` writes two files and, by default, builds one local index:

- `superqode.airplane.yaml`: a strict no-network harness.
- `.superqode/airplane/manifest.json`: the machine-readable preflight report.
- `.superqode/code-search.sqlite3`: a SQLite FTS5 index for fast offline code search.

The active repo remains writable. `--ref` repositories are search/read roots for
context; they should be treated as reference material unless you start a session
inside them.

## Commands

```bash
superqode local airplane doctor --repo . --ref ~/src/reference
superqode local airplane prepare --repo . --ref ~/src/reference
superqode local airplane index --repo . --ref ~/src/reference
superqode local airplane smoke --repo . --ref ~/src/reference
superqode local airplane models
superqode local airplane health
```

TUI equivalents use the same arguments:

```text
:local airplane doctor --repo . --ref ~/src/reference
:local airplane prepare --repo . --ref ~/src/reference
:local airplane index --repo . --ref ~/src/reference
:local airplane smoke --repo . --ref ~/src/reference
:local airplane models
:local airplane health
```

- `doctor` checks local search roots, ripgrep, semantic-search availability,
  model fit, memory warnings, and best-effort health signals.
- `prepare` writes the harness and manifest, and builds the code index unless
  you pass `--no-index`.
- `index` rebuilds the local SQLite code-search index explicitly.
- `smoke` runs a fast offline readiness check without making model calls.
- `models` shows neutral "fits this machine" suggestions from the trusted local
  matrix and cached catalog data. These are not endorsements.
- `health` reports memory, swap, battery, CPU load, and temperature where the OS
  exposes it.

## Search Contract

The default Airplane search stack is local:

1. `local_code_search` for the first broad pass. It prefers the local SQLite
   FTS5 index when it covers the requested roots, and otherwise falls back to
   live filesystem search. It merges file-path, literal content, and
   symbol-definition results across the active repo and any `--ref` roots.
2. `grep` / `glob` through ripgrep for exact text and file discovery.
3. `repo_search` and `code_search` for narrower path/content/symbol lookup.
4. `semantic_search` when `cocoindex-code` is installed and indexed locally.

Exa and other web search tools are intentionally excluded. OpenSearch can be a
future optional backend for workstation/server setups, but it is not the default
laptop path because it brings a service, memory tuning, and operational overhead.

## Hardware Guidance

Airplane Mode allows small local experiments on modest machines, but it warns
below 32 GB RAM/unified memory. For serious local agentic coding, prefer:

- 32 GB+ unified/system memory for Apple Silicon or CPU-only setups.
- 20 GB+ VRAM for NVIDIA local serving.
- Smaller context and lower concurrency on battery or when swap is active.

The model list is deliberately phrased as "likely fits" / "tight" / "likely too
large", not "best". Always validate the actual model with:

```bash
superqode local smoke --repo .
```

## Offline Boundary

The generated harness sets:

```yaml
execution_policy:
  allow_network: false
  blocked_categories:
    - network
    - fetch
    - download
```

During the connected preflight, download models, clone repositories, refresh
catalogs, and build local/semantic indexes. During the offline session,
Airplane Mode should not fetch packages, pull models, call web APIs, or refresh
online model catalogs.
