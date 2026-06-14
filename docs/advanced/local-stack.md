# Local Stack Doctor

The hardest part of Local Agentic Coding is not the agent. It is choosing the
right engine and the right model for the machine in front of you, out of a
landscape that changes monthly. The **Local Stack Doctor** does that choice for
you: it detects your hardware, inventories your engines and downloaded models,
and recommends a tuned stack. One more flag turns the recommendation into a
ready-to-run harness.

```bash
superqode local init --repo .
superqode local doctor
superqode local doctor --repo .
superqode local doctor --repo . --guardrails
```

---

## What the doctor checks

1. **Hardware**: Apple Silicon chip and unified memory, NVIDIA GPUs and VRAM,
   macOS version, and whether M5 Neural Accelerators are active (M5 or newer on
   macOS 26.2 or newer).
2. **Engines**: Ollama, LM Studio, mlx-lm, llama.cpp, vLLM, SGLang, and DS4.
   For each one: installed, version, and whether a server is answering right now.
3. **Models**: everything already downloaded, across the Ollama library, the
   Hugging Face cache (including mlx-community artifacts), and LM Studio's
   models directory.
4. **The matrix**: a shipped recommendation table maps your hardware tier to
   ranked engines and models. The doctor prefers what you already have: an
   installed engine beats a better-but-missing one, and a downloaded model
   beats a 20GB pull.
5. **Labs discovery**: `superqode local labs` reads models.dev Labs metadata
   and surfaces open-weight, tool-capable families such as GLM, Qwen, Gemma,
   DeepSeek, and Devstral with Hugging Face download hints.

The shipped matrix only recommends models with explicit provenance: a
models.dev Lab entry or a vetted community namespace such as `mlx-community`.
General Hugging Face search remains available, but search results are not
promoted into SuperQode defaults without that source label.

Example output:

```text
SuperQode Local Stack Doctor
============================================================
Hardware   Apple M4 Max, 128GB unified memory (macOS 26.2)
Tier       apple_128: Apple Silicon, 96GB+ unified memory

Engines
    mlx-lm     not installed
  * ollama     running ollama version is 0.30.3
      - MLX runtime available (0.19+, >32GB): fastest Ollama path on Apple Silicon
    ds4        installed
    lmstudio   installed

Recommended models
  + GLM-4.5-Air (bf16 or 8bit) [main]  downloaded (hf:THUDM/GLM-4.5-Air, 32.2GB)  source: models.dev/labs/zhipuai
  - Gemma 4 31B (bf16 or 8bit) [main]  get it: ollama pull gemma4:31b  source: models.dev/labs/google
  - Qwen3-Coder 30B-A3B [main]  get it: ollama pull qwen3-coder:30b-a3b  source: models.dev/labs/alibaba

Verdict
  Engine mlx-lm + GLM-4.5-Air (ready now)
  Generate a tuned harness: superqode local doctor --generate harness.yaml
```

Use `--json` for the full machine-readable report. Add `--repo PATH` to size a
repository at the same time; the doctor will report code-file count, estimated
code tokens, primary languages, largest files, recommended context window,
model-size class, and workflow shape. Add `--guardrails` to include conservative
local runtime limits for battery, memory headroom, context cap, and worker
concurrency.

---

## Generate a tuned harness

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

`local init` is the MVP one-command path. It runs the doctor, writes a tuned
`superqode.local.yaml`, and runs `local smoke` when a local server is available.
If smoke fails, the harness is still written but the output gives exact next
steps before you trust it for a real coding task.

For manual control:

```bash
superqode local doctor --repo . --generate harness.yaml
superqode --harness harness.yaml -p "your task"
```

The generated spec routes to the right provider for where the model actually
lives (an HF cache model is served by `mlx_lm.server`, not Ollama), references
the matching model policy pack, and switches small-hardware tiers to
prompt-based tool calling. When `--repo` is supplied, the generated harness also
sets a repository-sized `model_policy.context_window`, records the model-size
and workflow recommendation in metadata, and uses a workflow preset for larger
repositories. When `--guardrails` is supplied, it also writes
`execution_policy.config.local_guardrails` so workers and launchers can apply
safe local defaults.

---

## Runtime guardrails

```bash
superqode local guardrails
superqode local guardrails --repo . --json
```

Guardrails are conservative operating limits for local models. They do not
replace operating-system thermal controls; they prevent bad harness defaults:
too much worker concurrency, too much context on battery, and too little
memory/VRAM headroom. The report includes recommended worker concurrency,
context cap, memory headroom, power-source state when detectable, current load,
warnings, and notes.

---

## Hardware tiers and the matrix

The matrix is **data, not code**: `stack_matrix.yaml` ships inside SuperQode
and maps eight hardware tiers (`apple_16` through `apple_128`, `nvidia_16`
through `nvidia_48`, and `cpu`) to ranked engines and models.

Override or extend it without waiting for a release:

```yaml
# ~/.superqode/stack_matrix.yaml
tiers:
  - id: apple_128
    description: "My M4 Max"
    engines: [mlx-lm, ollama]
    models:
      - name: "My favorite coder"
        match: [my-favorite]
        pull: "ollama pull my-favorite"
        role: main
        pack: qwen-coder
```

Your tiers replace shipped tiers with the same `id`; everything else is kept.

---

## Model policy packs

A **pack** is one YAML file of tuned defaults for an open-model family:
temperature, system prompt level, tool-call format, and session history
budget. SuperQode ships packs for `gemma4`, `qwen3`, `qwen-coder`, `ds4`,
`devstral`, `gpt-oss`, and `glm`.

```bash
superqode local packs
```

Packs apply in two ways:

1. **Auto-detection**: if your model id matches a pack's `match` substrings,
   the pack's defaults apply. Longest match wins, so `qwen3-coder-next` picks
   the `qwen-coder` pack rather than `qwen3`.
2. **Explicit reference** in a harness spec:

```yaml
model_policy:
  primary: ollama/qwen3-coder:30b-a3b
  pack: qwen-coder
```

Precedence is strict: pack values override profile defaults, explicit spec
fields (`temperature`, `tool_call_format`, `reasoning`) override the pack, and
`model_policy.config` overrides everything.

Add your own packs in `~/.superqode/model-packs/`; a file with the same `name`
replaces the shipped pack:

```yaml
# ~/.superqode/model-packs/gemma4.yaml
name: gemma4
description: "My Gemma tuning"
match: [gemma-4, gemma4]
policy:
  temperature: 0.1
  session_history_limit: 20
```

---

## Benchmark your endpoints

```bash
superqode local smoke --repo .
superqode local warm ollama --model qwen3:8b
superqode local bench
superqode local bench --agentic
superqode local optimize --endpoint http://localhost:8080/v1 --model qwen3-coder --model tiny-coder
superqode local bench --endpoint http://localhost:8080/v1 --model my-model
```

Use `local smoke` before trusting a model on a repository. It is non-destructive:
it probes the endpoint, filters embedding-only models, detects the loaded
context window when the server exposes it, measures TTFT, and checks read-file
tool calls, patch-format output, shell tool calls, and long-context recall.

Use `local warm` before an interactive coding session when you want the first
real prompt to avoid model-load cost. It sends a tiny streamed request to one
running engine, chooses the first served model when `--model` is omitted, and
reports TTFT, decode speed, and total time:

```text
ready: qwen3:8b
  TTFT 0.8s · decode 38.2 tok/s · total 1.2s
```

If warm TTFT is still high, the bottleneck is usually prefill/context pressure:
restart the server with a smaller context window (`--ctx`, `num_ctx`, or the
engine equivalent) or choose a smaller quantized model.

The bench streams one coding-shaped completion and reports **time to first
token** (prefill speed) and **decode tokens per second**. TTFT is the number
that matters: agent loops resend a growing context every turn, so they are
prefill-dominated. Without `--endpoint` it benches the first model of every
engine it finds running.

```text
model                                            TTFT       decode    total
qwen3-coder:30b-a3b                              0.4s   42.0 tok/s     6.5s
```

Use `--agentic` when you want to know whether a local model is ready for a real
coding-agent loop, not just whether it can stream tokens. The agentic bench is
non-mutating: it asks the model to emit a `read_file` tool call, produce an edit
patch/diff, emit a `bash` tool call, and recall a sentinel from a longer
context. The score is the percentage of those four control probes that pass.

```text
model                                   TTFT       decode   score  tool  edit  shell  ctx
qwen3-coder:30b-a3b                     0.4s   42.0 tok/s    100%   yes   yes    yes  yes
```

Use `local optimize` when you have more than one local/open model and want a
role routing plan instead of a flat benchmark table. It runs the agentic probes
for each candidate, then scores models separately for planner, implementer,
reviewer, and utility work. The utility role is biased toward low TTFT and high
decode speed; implementation and review are biased toward tool calls, edit
format, shell calls, and context recall. Add `--repo PATH` to bias scoring for
the current repository's context size, model-size class, and workflow shape.

```bash
superqode local optimize \
  --endpoint http://localhost:8080/v1 \
  --model qwen3-coder:30b-a3b \
  --model tiny-coder:7b \
  --repo . \
  --generate local-optimized.yaml
```

```text
role           model                                  score  reason
planner        qwen3-coder:30b-a3b                    92.4  best role fit: agentic 100.0, speed 62
implementer    qwen3-coder:30b-a3b                    95.2  best role fit: agentic 100.0, speed 62
reviewer       qwen3-coder:30b-a3b                    91.4  best role fit: agentic 100.0, speed 62
utility        tiny-coder:7b                           74.0  fastest useful route: speed 96, agentic 25.0
```

`--generate` writes a chain harness with per-agent model choices, retry policy,
and endpoint metadata so teams can check in the measured routing plan.

---

## Run an MLX server

On Apple Silicon, `mlx_lm.server` is the fastest serving path for models in
your Hugging Face cache:

```bash
uv pip install mlx-lm
superqode providers mlx server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```

Check the install and whether a server is already answering:

```bash
superqode providers mlx doctor
```

The server speaks the OpenAI protocol at `http://127.0.0.1:8080/v1`, so any
SuperQode route can use it. `superqode local doctor` lists the MLX models
already in your cache.

---

## Utility model routing

Some model calls are small, frequent, and quality-tolerant: rubric grading,
automatic memory extraction, summaries. By default they use the session model.
`SUPERQODE_UTILITY_PROVIDER` redirects them to something cheaper:

```bash
# Any gateway route
export SUPERQODE_UTILITY_PROVIDER=ollama/gemma4:e4b

# The on-device Apple Foundation Model (free, instant, no server)
export SUPERQODE_UTILITY_PROVIDER=apple-fm
```

The `apple-fm` route uses the Apple Intelligence on-device model through the
`apple-fm-sdk` Python package. It needs Apple Silicon with Apple Intelligence
enabled; if unavailable, utility calls silently fall back to the session
model. The doctor reports whether `apple-fm` is usable on your machine.

---

## Verify your setup

1. `superqode local doctor` shows your hardware tier and at least one engine.
2. `superqode local packs` lists seven shipped packs.
3. `superqode local doctor --generate h.yaml` writes a spec that
   `superqode --harness h.yaml -p "hello"` can run.
4. With an engine running, `superqode local bench` prints a TTFT and decode rate.

## Related pages

- [Local Agentic Coding](../local-agentic-coding.md) for the full local-first story
- [Local Models](../providers/local.md) for per-provider connection details
- [Local Context & Compaction](local-context.md) for context window handling
- [Harness System](harness-system.md) for everything a harness spec can do
- [Environment Variables](../configuration/environment-variables.md)
