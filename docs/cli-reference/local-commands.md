# Local Commands

The `superqode local` command group is the local-first toolkit: detect hardware, find and serve models, generate a transparent starter harness, and check readiness. It is built for Local Agentic Coding (open models on your own hardware, no token bills).

New to local models? Start with the [Local Providers](../providers/local.md) guide, then use this page as the command reference.

```bash
superqode local COMMAND [OPTIONS]
```

## Command Summary

| Command | Purpose |
| --- | --- |
| `setup` | TUI-first guide for model download, serving, context, harness, and smoke |
| `init` | Generate a starter harness for this repo (doctor + smoke + write) |
| `doctor` | Detect hardware/engines/models and recommend a local stack |
| `build` | Guided local harness builder without live model calls |
| `search` | Find a model and how to get it on every engine (size + fit) |
| `labs` | Browse trusted models.dev model labs |
| `migrate` | Dry-run migration plan for prompts, skills, and existing harnesses |
| `pack init` | Create a project-owned model policy pack |
| `packs` | List model-policy packs (per model family) |
| `serve` | Start a local model server as a managed daemon |
| `servers` | Show status of every known local server |
| `stop` | Stop a server SuperQode started |
| `models` | List chat-capable models on running servers |
| `warm` | Preload a model and report first-token latency |
| `smoke` | Non-destructive coding-readiness smoke test |
| `bench` | Measure TTFT and decode speed |
| `optimize` | Benchmark candidates and recommend role routing |
| `guardrails` | Recommend conservative runtime limits for this machine |

---

## Getting Started

### `local setup`

The recommended first command for new local-model users. It does not download
models or start servers; it prints a TUI-first path that tells you what to run:

```bash
superqode local setup qwen3-coder --repo .
```

In the TUI, use:

```text
:local setup qwen3-coder --repo .
```

The guide sequences model search, explicit download, server start, context
choice, harness build, and smoke test. It also repeats the product contract:
packs are starter templates, not a finished harness. Build or bring your own
harness, then tune prompts, skills, memory, routing, and context to your repo.

### `local init`

The one-command path: detect hardware, recommend a trusted model, run a smoke test, and write a starter `superqode.local.yaml` that you own and can edit.

```bash
superqode local init --repo .
superqode local init --repo . --pack minimax-m1 --skip-smoke
superqode --harness superqode.local.yaml
```

| Option | Description |
| --- | --- |
| `--repo DIRECTORY` | Repository to size the harness for (default `.`) |
| `--output FILE` | Harness file to write (default `superqode.local.yaml`) |
| `--engine TEXT` | Local engine to smoke test |
| `--model TEXT` | Model id to smoke test |
| `--pack TEXT` | Model policy pack to write into the harness |
| `--skip-smoke` | Generate the harness without running smoke |
| `-y, --yes` | Overwrite an existing harness file |
| `--json` | Emit summary as JSON |

### `local doctor`

Detect hardware, installed engines, and downloaded models, then recommend the best engine + model for this machine (preferring what you already have).

```bash
superqode local doctor --repo .
superqode local doctor --generate superqode.local.yaml
superqode local doctor --generate superqode.local.yaml --pack minimax-m1
```

| Option | Description |
| --- | --- |
| `--json` | Emit the full report as JSON |
| `--repo DIRECTORY` | Repository to size recommendations for |
| `--guardrails` | Include conservative runtime guardrails |
| `--generate PATH` | Write a starter harness spec for the recommended stack |
| `--name TEXT` | Name for the generated harness (default `local-coder`) |
| `--pack TEXT` | Model policy pack to write into the generated harness |

---

### `local build`

Guided local harness builder. It runs the migration scan, selects or drafts a
model pack, generates a harness with that pack, and prints the final live smoke
commands. It does not call a model. The result is intended to be customized:
shipped packs are starting points, not proof that a model is optimized for your
repo.

```bash
superqode local build --repo . --model MiniMaxAI/MiniMax-M1 --pack minimax-m1
superqode local build --repo . --model MiniMaxAI/MiniMax-M1 --dry-run
```

| Option | Description |
| --- | --- |
| `--repo DIRECTORY` | Repository to analyze and generate for |
| `--model TEXT` | Target model id |
| `--endpoint URL` | Target local/OpenAI-compatible endpoint |
| `--pack TEXT` | Model policy pack to use |
| `--output FILE` | Harness file to write |
| `--write-pack` | Write a generated pack when missing |
| `--dry-run` | Plan only, write nothing |
| `--force` | Overwrite existing harness/pack files |
| `--json` | Emit build report as JSON |

## Finding Models

### `local search`

Find models matching a query in the trusted catalog and show, per model, the real native download command for every engine it can run on (Ollama, llama.cpp, LM Studio, MLX) plus a `superqode models download` alternative, an approximate size, whether you already have it, and a rough memory-fit verdict for your hardware. With `--hub` it also queries the Hugging Face Hub live (trusted publishers only) for the newest releases.

```bash
superqode local search qwen3-coder
superqode local search glm --hub
superqode local search minimax --hub
superqode local search qwen3-coder --hub --gguf
```

| Option | Description |
| --- | --- |
| `--hub` | Also search Hugging Face live (trusted publishers) |
| `--gguf` | With `--hub`: only GGUF (Ollama / llama.cpp) |
| `--mlx` | With `--hub`: only MLX (Apple Silicon) |
| `--json` | Emit results as JSON |

In the TUI this is `:local search <name>`, or enter `:hub` model-search mode and just type names.

### `local labs`

Browse local-friendly model labs from models.dev (GLM, MiniMax, Qwen, Gemma, DeepSeek, Mistral). Use it before downloading weights.

```bash
superqode local labs
superqode local labs minimax
superqode local labs alibaba
```

| Option | Description |
| --- | --- |
| `--limit INTEGER` | Maximum models to show (default `12`) |
| `--refresh` | Refresh the models.dev cache |
| `--json` | Emit labs or models as JSON |

### `local migrate`

Dry-run migration plan for project prompts, skills, role files, existing
harnesses, and config. It does not rewrite files.

```bash
superqode local migrate --repo .
superqode local migrate --repo . --endpoint http://localhost:8000/v1 --model MiniMaxAI/MiniMax-M1
superqode local migrate --repo . --json
```

| Option | Description |
| --- | --- |
| `--repo DIRECTORY` | Repository to analyze (default `.`) |
| `--endpoint URL` | Target local/OpenAI-compatible endpoint |
| `--model TEXT` | Target model id |
| `--json` | Emit the migration plan as JSON |

### `local packs`

List model-policy packs (shipped plus `~/.superqode/model-packs/`). A pack carries starter defaults for one open-model family; reference one from a harness with `model_policy.pack`, then override it in your own harness as you learn what your model and repo need.

```bash
superqode local packs
```

| Option | Description |
| --- | --- |
| `--json` | Emit packs as JSON |

### `local pack init`

Create a user-owned pack without probing a live model. Use `--dry-run` while
planning, then write the pack when you are ready. Later, after a live smoke run,
pass the saved `smoke --json` payload with `--from-smoke` to derive conservative
defaults from measured behavior.

```bash
superqode local pack init --model MiniMaxAI/MiniMax-M1 --dry-run
superqode local pack init --model MiniMaxAI/MiniMax-M1
superqode local pack init --from-smoke smoke.json --output .superqode/model-packs/my-model.yaml
```

| Option | Description |
| --- | --- |
| `NAME` | Optional pack name |
| `--model TEXT` | Target model id to match |
| `--endpoint URL` | Endpoint hint to include in match terms/notes |
| `--from-smoke FILE` | Saved `local smoke --json` payload |
| `--output FILE` | Pack YAML path |
| `--force` | Overwrite an existing pack |
| `--dry-run` | Print the draft without writing |
| `--json` | Emit the draft as JSON |

---

## Servers

MLX and llama.cpp serve one model per process; Ollama and LM Studio run as
background apps. `serve` is an explicit start command: it launches a managed
daemon that survives SuperQode exiting, records pid/log metadata under
`~/.superqode/servers/`, and can be stopped with `superqode local stop
<engine>`. If a server is already answering on the target port, SuperQode
adopts it for status display and does not restart or kill it.

Nothing in `local init`, `local build`, `local migrate`, or `local smoke`
starts a model server for you. They print the command to run. In the TUI, direct
MLX/llama.cpp model selection asks before starting a one-model server; type
`manual` if you prefer to run the command yourself.

### `local serve`

```bash
superqode local serve ollama
superqode local serve ds4 --ctx 32768
superqode local serve mlx --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8090
superqode local serve llama.cpp --model /path/to/model.gguf --ctx 16384
```

| Option | Description |
| --- | --- |
| `-m, --model TEXT` | Model id / weight path (required for `mlx` and `llama.cpp`) |
| `-p, --port INTEGER` | Port (default: engine default) |
| `--host TEXT` | Bind host (default `127.0.0.1`) |
| `--ctx INTEGER` | Context window (where the engine supports it) |
| `--no-wait` | Return immediately, do not wait for readiness |
| `--build` | (ds4) Build the `ds4-server` binary first if missing |
| `--allow-download` | (mlx) Permit downloading the model from Hugging Face if not cached |
| `--extra TEXT` | Extra flag passed to the server (repeatable) |

Engines: `ollama`, `lmstudio`, `mlx`, `ds4`, `llama.cpp`.

For DS4, the managed default is conservative: `--ctx 32768` plus disk KV cache
under `~/.superqode/ds4-kv`. Use `--ctx 100000` for long coding sessions when
memory headroom allows. Think Max needs `--ctx 393216` or higher. New DS4 flags
can be passed with repeated `--extra`, for example:

```bash
superqode local serve ds4 --ctx 32768 \
  --extra=--ssd-streaming \
  --extra=--ssd-streaming-cache-experts \
  --extra=32GB
```

For MLX, SuperQode refuses a missing Hugging Face model by default because
starting `mlx_lm.server` could trigger a multi-GB download. Use
`--allow-download` only when you are comfortable with that.

### `local servers`

Show the status of every known local server (running, managed, pid).

```bash
superqode local servers
```

| Option | Description |
| --- | --- |
| `--json` | Emit status as JSON |

### `local stop`

Stop a server SuperQode started (adopted servers are left untouched).

```bash
superqode local stop mlx
```

### `local models`

List chat-capable models on running local servers (embedding/reranker models are hidden). Omit the engine to scan every running server.

```bash
superqode local models
superqode local models ollama
```

| Option | Description |
| --- | --- |
| `--json` | Emit models as JSON |

---

## Readiness And Performance

### `local warm`

Preload a model and report first-token latency. Run it before a session so the first real prompt does not pay the model-load cost. A high TTFT here usually means the context window is too large for the hardware.

```bash
superqode local warm ollama --model qwen3:8b
```

| Option | Description |
| --- | --- |
| `-m, --model TEXT` | Model id to preload (default: first served model) |
| `--max-tokens INTEGER` | Tokens to generate (default `8`) |

### `local smoke`

Non-destructive coding-readiness check: server reachable, chat model loaded (not embedding-only), context window detected, TTFT/decode measured, and clean tool-call/patch output on a tiny prompt. Never reads or edits your repo.

```bash
superqode local smoke --repo .
```

| Option | Description |
| --- | --- |
| `--engine TEXT` | Local engine id (default: first running server) |
| `--endpoint TEXT` | OpenAI-compatible base URL |
| `--model TEXT` | Model id (default: first served chat model) |
| `--repo DIRECTORY` | Repository to label in the report |
| `--api-key TEXT` | Bearer token if the endpoint needs one |
| `--max-tokens INTEGER` | Tokens to generate (default `384`) |
| `--json` | Emit report as JSON |

### `local bench`

Measure TTFT and decode speed with a coding prompt. Without `--endpoint`, benches the first model of every running engine. TTFT (prefill) matters most for agent loops.

```bash
superqode local bench
superqode local bench --endpoint http://localhost:11434/v1 --agentic
```

| Option | Description |
| --- | --- |
| `--endpoint URL` | OpenAI-compatible base URL (default: every running engine) |
| `--model TEXT` | Model id to bench (repeatable) |
| `--max-tokens INTEGER` | Tokens to generate (default `256`) |
| `--api-key TEXT` | Bearer token if the endpoint needs one |
| `--agentic` | Also probe tool-call, edit-format, shell-call, context-recall |
| `--json` | Emit results as JSON |

### `local optimize`

Benchmark candidate models and recommend role-specific routing (planner / implementer / reviewer / utility), optionally writing a role-routed harness.

```bash
superqode local optimize --repo .
superqode local optimize --generate superqode.local.yaml
```

| Option | Description |
| --- | --- |
| `--endpoint URL` | OpenAI-compatible base URL (default: every running engine) |
| `--model TEXT` | Candidate model id (repeatable) |
| `--role TEXT` | Workflow role to optimize (default: all four roles) |
| `--repo DIRECTORY` | Repository to size when scoring routes |
| `--max-tokens INTEGER` | Tokens to generate (default `384`) |
| `--api-key TEXT` | Bearer token if the endpoint needs one |
| `--generate PATH` | Write a role-routed harness spec |
| `--name TEXT` | Name for the generated harness (default `local-optimized`) |
| `--json` | Emit report as JSON |

### `local guardrails`

Recommend conservative runtime limits (context cap, worker concurrency, memory headroom) for this machine.

```bash
superqode local guardrails --repo .
```

| Option | Description |
| --- | --- |
| `--json` | Emit guardrails as JSON |
| `--repo DIRECTORY` | Repository to include when capping context and concurrency |

---

## Related

- [Local Providers](../providers/local.md): the guided local-coding walkthrough.
- [Local Agentic Coding](../local-agentic-coding.md): the local-first positioning.
- [Local Stack Doctor](../advanced/local-stack.md): how the recommendation matrix works.
- [Harness Commands](harness-commands.md): the `superqode harness` group.
