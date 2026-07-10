# Local Context & Compaction

SuperQode is tuned to get the best out of **local models** (approximately 10B-120B), where the
single biggest failure mode is **running out of context**. It solves this
automatically: it detects each model's *real loaded* context window and compacts
the conversation before it overflows: no configuration required.

---

## Why this matters for local models

A local model "supports 128K context" on its model card, but the server may have
**loaded it with a much smaller window** (e.g. Ollama `num_ctx=4096`). The
*loaded* window is the only number that's true: and on a large model (120B)
there's less VRAM for the KV cache, so the practical window is often *smaller*
than on a 10B model. Overflowing it produces garbage output or hard errors.

SuperQode reads the loaded window directly from the server and sizes everything
to it.

---

## Automatic: detection + adaptive compaction

On the first coding-agent message of a session, SuperQode:

1. **Detects the loaded window** from the live server (per backend):

    | Backend | Endpoint | Field |
    |---|---|---|
    | Ollama | `GET /api/ps` | `context_length` (loaded `num_ctx`) |
    | llama.cpp | `GET /props` | `n_ctx` |
    | LM Studio | `GET /api/v1/models` | `loaded_context_length` |
    | vLLM / DS4 / OpenAI-compatible | `GET /v1/models` | `max_model_len` / `context_length` |

    Server URLs come from each provider's env override (`OLLAMA_HOST`,
    `LMSTUDIO_HOST`, `DS4_HOST`, ...) or its default port. If the window can't be
    read, SuperQode stays **conservative (8K)** rather than risk an overflow: it
    never assumes the model-card maximum for a local model.

2. **Compacts adaptively** as the conversation grows. Compaction triggers at
   `window − reserve` and keeps a **token-budgeted** tail of recent turns,
   replacing older turns with a structured summary. Both the threshold and the
   kept-recent budget scale to the model's window, so a 4K model and a 200K model
   each behave sensibly.

This runs for **local and BYOK** models, on both streaming and non-streaming
paths.

---

## Simple local chat skips context work

For local providers other than DS4, obvious chat prompts such as `hello`, `hi`,
or basic non-code questions use a fast-chat path. SuperQode sends a tiny direct
request and skips the expensive coding-agent scaffolding for that turn:

- no live context-window probe
- no restored session history
- no reminder messages
- no tool schemas

This is intentionally narrow. Any prompt that mentions files, code, the repo,
or a concrete development task uses the normal coding harness and context
management. DS4 is excluded because it benefits from a stable rendered prefix
for KV-cache reuse.

---

## Inspect and override: `:context`

```text
:context              # show detected window, source, and compaction budgets
:context 8192         # pin the window (also accepts 16k)
:context auto         # clear the override and re-detect from the server
```

Example:

```text
🪟 Context window

    Window:      16,384 tokens  (loaded (/api/ps))
    Compact at:  13,108 tokens
    Keep recent: ~6,553 tokens
    Auto-compact: ON
```

The `source` tells you where the number came from: `loaded (<endpoint>)`,
`configured` (you pinned it), `local-fallback` (couldn't detect → conservative),
or `model-info` (BYOK catalog). The live status-bar meter shows fill % against
this window as you work.

---

## Environment variables

| Variable | Effect |
|---|---|
| `SUPERQODE_AUTO_COMPACT=0` | Disable adaptive auto-compaction (on by default) |
| `OLLAMA_HOST` / `LMSTUDIO_HOST` / `DS4_HOST` / ... | Where to probe for the loaded window |

You can also set the window per session in code via `AgentConfig.context_window`
(0 = auto-detect), with `compaction_reserve_tokens` and `keep_recent_tokens` for
fine control (0 = auto).

---

## Choosing a good `num_ctx`

If you're picking a context size when loading a local model:

- **8K-16K** is the practical range for most local coding models: enough for
  real work, small enough to stay fast and fit in VRAM.
- Going larger only helps if the machine has the VRAM. If the KV cache spills to
  CPU RAM, inference can drop 20-50x (for example, from 50-100 tok/s to
  2-5 tok/s).
- K/V cache quantization (q8/q4) lets you fit a larger window in the same VRAM.

SuperQode detects the configured context size and adjusts its context-management limits automatically.

---

## Controlling what local models show: `:thinking`

Local models can be noisy. The thinking-log detail is a three-way toggle
(**Ctrl+T** cycles, or use the command):

```text
:thinking            # show current detail + how to change it
:thinking normal     # default: iterations fold into a live status, reasoning trimmed
:thinking verbose    # full per-iteration reasoning + tool detail
:thinking off        # only tool calls and the final answer
```

In **normal** mode the agent loop's bookkeeping and raw reasoning are folded into
a single live throbber with a tidy per-tool trace: calm by default, full detail
on demand.
