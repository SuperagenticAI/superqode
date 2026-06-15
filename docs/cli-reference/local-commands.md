# Local Commands

The `superqode local` command group is the local-first toolkit: detect hardware, find and serve models, generate a tuned harness, and check readiness. It is built for Local Agentic Coding (open models on your own hardware, no token bills).

New to local models? Start with the [Local Providers](../providers/local.md) guide, then use this page as the command reference.

```bash
superqode local COMMAND [OPTIONS]
```

## Command Summary

| Command | Purpose |
| --- | --- |
| `init` | Generate a tuned harness for this repo (doctor + smoke + write) |
| `doctor` | Detect hardware/engines/models and recommend a local stack |
| `search` | Find a model and how to get it on every engine (size + fit) |
| `labs` | Browse trusted models.dev model labs |
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

### `local init`

The one-command path: detect hardware, recommend a trusted model, run a smoke test, and write a tuned `superqode.local.yaml`.

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

| Option | Description |
| --- | --- |
| `--repo DIRECTORY` | Repository to tune the harness for (default `.`) |
| `--output FILE` | Harness file to write (default `superqode.local.yaml`) |
| `--engine TEXT` | Local engine to smoke test |
| `--model TEXT` | Model id to smoke test |
| `--skip-smoke` | Generate the harness without running smoke |
| `-y, --yes` | Overwrite an existing harness file |
| `--json` | Emit summary as JSON |

### `local doctor`

Detect hardware, installed engines, and downloaded models, then recommend the best engine + model for this machine (preferring what you already have).

```bash
superqode local doctor --repo .
superqode local doctor --generate superqode.local.yaml
```

| Option | Description |
| --- | --- |
| `--json` | Emit the full report as JSON |
| `--repo DIRECTORY` | Repository to size recommendations for |
| `--guardrails` | Include conservative runtime guardrails |
| `--generate PATH` | Write a tuned harness spec for the recommended stack |
| `--name TEXT` | Name for the generated harness (default `local-coder`) |

---

## Finding Models

### `local search`

Find models matching a query in the trusted catalog and show, per model, the real native download command for every engine it can run on (Ollama, llama.cpp, LM Studio, MLX) plus a `superqode models download` alternative, an approximate size, whether you already have it, and a rough memory-fit verdict for your hardware. With `--hub` it also queries the Hugging Face Hub live (trusted publishers only) for the newest releases.

```bash
superqode local search qwen3-coder
superqode local search glm --hub
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

Browse local-friendly model labs from models.dev (GLM, Qwen, Gemma, DeepSeek, Mistral). Use it before downloading weights.

```bash
superqode local labs
superqode local labs alibaba
```

| Option | Description |
| --- | --- |
| `--limit INTEGER` | Maximum models to show (default `12`) |
| `--refresh` | Refresh the models.dev cache |
| `--json` | Emit labs or models as JSON |

### `local packs`

List model-policy packs (shipped plus `~/.superqode/model-packs/`). A pack carries tuned defaults for one open-model family; reference one from a harness with `model_policy.pack`.

```bash
superqode local packs
```

| Option | Description |
| --- | --- |
| `--json` | Emit packs as JSON |

---

## Servers

MLX and llama.cpp serve one model per process; Ollama and LM Studio run as background apps. `serve` starts a managed daemon that survives SuperQode exiting.

### `local serve`

```bash
superqode local serve ollama
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
