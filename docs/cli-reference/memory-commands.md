# Memory Commands

Manage agent memory across providers. Memory stores facts, preferences, and project context that persists across sessions.

---

## memory providers

List available memory providers.

```bash
superqode memory providers
```

### Output

```text
Provider       Status    Type
local          ready     file-based
specmem        ready     project .specmem/
mem0           disabled  hosted (superqode[mem0])
cognee         missing   local/cloud
supermemory    disabled  hosted (superqode[supermemory])
```

---

## memory status

Show memory provider status with readiness state.

```bash
superqode memory status
```

Displays each provider's readiness: `ready`, `disabled`, or `missing`. Shows configuration details and connection status for each provider.

---

## memory doctor

Check provider readiness and diagnose issues.

```bash
superqode memory doctor
```

Probes each configured provider, checks storage paths, credentials, and returns a readiness report with actionable hints for any provider in `missing` or `disabled` state.

---

## memory remember

Store an explicit memory entry.

```bash
superqode memory remember "text" [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `"text"` | Memory content (quote the text) |

### Options

| Option | Description |
|--------|-------------|
| `--kind` | Memory type (e.g., `preference`, `fact`, `instruction`) |
| `--tag` | Tag for filtering and search (e.g., `tooling`, `auth`) |

### Examples

```bash
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference --tag tooling
superqode memory remember "API keys go in .env" --kind fact --tag auth
```

---

## memory search

Search memory across providers.

```bash
superqode memory search "query" [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--provider` | Search a specific provider (searches all if omitted) |

### Examples

```bash
superqode memory search "package manager"
superqode memory search "auth requirements" --provider specmem
```

---

## memory forget

Delete a memory entry.

```bash
superqode memory forget <id>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `id` | Memory entry ID |

Removes the specified memory entry from its provider.

---

## memory export

Export memory as JSON.

```bash
superqode memory export [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--provider` | Export from a specific provider (default: all) |
| `--output`, `-o` | Output file path (prints to stdout if omitted) |

### Examples

```bash
superqode memory export --provider local --output memory.json
```

---

## Providers

| Provider | Type | Storage | Setup |
|----------|------|---------|-------|
| `local` | file-based | `~/.superqode/memory/` | Built-in, always available |
| `specmem` | project | `.superqode/memory/` | Built-in, per-project scope |
| `mem0` | hosted | superqode[mem0] | Install `superqode[mem0]`, configure in `superqode.yaml` |
| `cognee` | local/cloud | install separately | Install `superqode[cognee]` and Cognee |
| `supermemory` | hosted | superqode[supermemory] | Install `superqode[supermemory]`, configure in `superqode.yaml` |

`local` is the default provider. `specmem`, `mem0`, `cognee`, and `supermemory` are opt-in providers configured under `memory.providers` in `superqode.yaml`.
