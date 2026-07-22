# Local Agentic Coding

**Local Agentic Coding** uses open models on user-controlled hardware to read,
edit, and test code. Model weights, context, and transcripts remain on the
local system.

SuperQode treats local models as a primary execution target. Hosted providers
remain available through explicit configuration.

---

## Local execution characteristics

Three things changed:

1. **Open-weight coding models.** Current models can execute repository tasks on
   developer-managed hardware. Mixture-of-experts architectures reduce active
   parameter and decode requirements.
2. **Local serving infrastructure.** MLX on Apple Silicon, continuous batching,
   prefix caching, and accelerator-aware runtimes improve local inference
   throughput.
3. **Data control and predictable infrastructure cost.** Local execution keeps
   code and context on controlled systems and avoids per-token API billing.

Local models can have smaller loaded context windows, less reliable tool-call
formats, tighter prompt budgets, and model-specific operating constraints.
SuperQode exposes configuration for these constraints in the HarnessSpec.

---

## From zero to a local harness you own

The following commands create and run a local HarnessSpec:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

`local init` runs the [Local Stack Doctor](advanced/local-stack.md), generates
`superqode.local.yaml`, and, when a local server is running, runs the same
non-destructive readiness probe as `superqode local smoke --repo .`.

Use the individual pieces when you want more control:

```bash
superqode local doctor --repo .
superqode local serve ollama
superqode local models
superqode local warm ollama --model qwen3:8b
superqode local smoke --repo .
superqode local doctor --generate harness.yaml
superqode --harness harness.yaml -p "your task"
```

The generated harness routes to the right provider for where the model lives,
references the matching model policy pack when one is available, and switches
small machines to prompt-based tool calling. It is generated as YAML so it can
be reviewed and edited before use.

The smoke test verifies server reachability, chat model availability,
context-window detection, TTFT, read-file tool calls, patch-format behavior,
shell tool calls, and long-context recall.

Treat the generated harness as an editable project file. Select the model
route, memory provider, permissions, search tools, and workflow settings that
match the repository. SuperQode ships starter packs, but they are not final
configurations for every model, quantization, serving engine, hardware tier, or
codebase.

### Add local semantic code search

For larger repositories, add conceptual code search to the same local loop. It
is optional: if the integration is not installed, leave `semantic_search` out of
the harness and the rest of the stack still works.

```bash
uv pip install 'superqode[semantic]'
ollama pull nomic-embed-text
ccc init --litellm-model ollama/nomic-embed-text
ccc index
```

Then add the read-only tool to the local coding agent:

```yaml
execution_policy:
  sandbox: docker        # or local-os / podman / apple-container when available
  allow_network: false
agents:
  - id: local-coder
    tools:
      - read_file
      - grep
      - glob
      - repo_search
      - semantic_search
      - edit_file
      - patch
      - bash
```

Use it explicitly in prompts when the model needs to find code by intent:

```bash
superqode harness run \
  --spec superqode.local.yaml \
  --provider openai-compatible \
  --model qwen3:8b \
  --sandbox docker \
  --prompt "First use semantic_search to find where request retries are implemented, then patch the bug and run the focused tests."
```

The index stays local. With the Ollama embedding path above, code chunks and
embeddings are produced on the same machine as the agent run. Re-run
`ccc index` after a batch of edits, or ask the tool for `refresh=true` when the
agent must search changes it just made.

### Add recursive dynamic workflows

For long logs, dense diffs, traces, and repo-slice audits, use the bundled
local recursive dynamic harness:

```bash
superqode harness eval \
  --spec examples/harnesses/local-recursive-dynamic.yaml \
  --tasks "$(superqode harness eval-packs local-dynamic-workflow-smoke)" \
  --provider ollama \
  --model qwen3:8b \
  --runtime builtin \
  --sandbox docker \
  --live
```

This proves the full local loop: `context_handle` keeps the artifact outside
the prompt, `dynamic_workflow_script` compiles a bounded plan,
`spawn_harness` runs child inspections, and `harness replay` / `harness
evidence` show the resulting tree. See
[Local Recursive Dynamic Coding](local-recursive-dynamic-coding.md).

You own this harness. Build a custom one by answering a few questions with
`superqode harness wizard`, start from a model-family template such as
`qwen-coding` or `glm-coding`, and read exactly what any harness does in plain
English with `superqode harness explain --spec harness.yaml`. The
[Bring Your Own Harness](getting-started/bring-your-own-harness.md) guide walks
the whole flow.

To browse model labs before downloading weights, use the models.dev-backed
Labs view:

```bash
superqode local labs
superqode local labs minimax
superqode local labs zhipuai
superqode local labs alibaba --refresh
```

The Labs view highlights local-friendly families such as GLM, MiniMax, Qwen,
Gemma, DeepSeek, and Devstral, then shows open-weight, tool-capable,
long-context candidates with Hugging Face download hints where models.dev
provides them.
SuperQode's own recommendations are intentionally narrower than generic model
search: they come from curated models.dev Labs or vetted community namespaces
such as `mlx-community`, so random Hub results do not become default guidance.

### Migrate your existing setup

Most teams already have prompts, skills, role files, and an older harness. Do
not throw them away and do not blindly trust a vendor harness. Start with a
dry-run migration plan:

```bash
superqode local migrate \
  --repo . \
  --endpoint http://localhost:8000/v1 \
  --model MiniMaxAI/MiniMax-M1
```

The migration plan inventories `AGENTS.md`, `CLAUDE.md`, `SUPERQODE.md`,
`.agents/skills`, `.agents/roles`, existing harnesses, and project config. It
flags cloud-only assumptions, oversized prompts, web-search assumptions, shell
approval needs, detected model packs, and the next smoke/explain commands. It
does not rewrite files. The output is meant to help you build a local harness
you own, with measured model behavior instead of hidden defaults.

Create a project-owned pack before the live run, then refine it from saved
smoke results at the end:

```bash
:local build --repo . --model MiniMaxAI/MiniMax-M1 --pack minimax-m1 --output superqode.local.yaml
superqode local pack init --model MiniMaxAI/MiniMax-M1 --dry-run
superqode local pack init --model MiniMaxAI/MiniMax-M1
superqode local init --repo . --pack minimax-m1 --skip-smoke
```

`:local build` is the TUI-first path: it inventories prompts and skills, carries
the selected pack into the generated harness, writes `superqode.local.yaml`, and
prints the final live smoke/eval commands. It does not contact the model.
`local pack init` is the lower-level pack-only command.

---

## What SuperQode does differently for local models

Every layer of the harness has a local-first answer:

| Reality of local models | SuperQode's answer |
|---|---|
| The loaded context window is smaller than the model card says | Live window detection from the running server, [adaptive compaction](advanced/local-context.md) sized to it |
| Model families need different prompts, temperatures, and formats | [Model policy packs](advanced/local-stack.md#model-policy-packs): researched starter defaults per family, user-overridable |
| Many models have no reliable native tool head | `tool_call_format: prompt` renders tools into the prompt and parses calls from text |
| Tool schemas eat the prompt budget | [Deferred tools](advanced/tools-system.md): heavy schemas hidden until the model activates them via `tool_search` |
| Keyword search misses conceptual matches | Optional [semantic code search](advanced/semantic-search.md) via `superqode[semantic]`, backed by a local CocoIndex daemon and local Ollama embeddings |
| A simple "hello" should not feel like a repo-sized agent run | Local fast-chat path: obvious greetings/basic non-code questions skip coding history, reminders, context probing, and tool schemas |
| Small models loop and emit malformed calls | Doom-loop guard, tool-argument repair, and dangling tool-call repair in the [agent loop](advanced/agent-loop.md) |
| Engine choice is hardware-dependent and changes monthly | The recommendation matrix ships as updatable data with user overrides |
| Model discovery should not depend on stale README lists | `superqode local labs` reads models.dev Labs metadata and points to Hugging Face artifacts |
| Speed claims are unverifiable | `superqode local warm` preloads one model and reports first-token latency; `superqode local bench` measures TTFT and decode rate; `--agentic` also scores tool-call, edit-format, shell-call, and context-recall probes |
| Even utility calls cost main-model time | [Utility routing](advanced/local-stack.md#utility-model-routing): grading and memory extraction on a small local model or the free on-device Apple model |
| Long runs chain you to the terminal | [Chat channels](advanced/channels.md): `superqode daemon` relays approvals and steering to Telegram, Slack, or Discord |

---

## The local engines SuperQode speaks

| Engine | Best on | SuperQode integration |
|---|---|---|
| Ollama | everywhere, easiest start | provider, window detection, MLX-runtime detection, keep-alive shaping |
| MLX (`mlx_lm.server`) | Apple Silicon, fastest path | `superqode providers mlx server`, HF cache inventory |
| LM Studio | desktop, GUI management | provider, loaded-window detection, model inventory |
| llama.cpp | CPU and constrained hardware | OpenAI-compatible provider, window detection |
| vLLM | NVIDIA, throughput | provider, `max_model_len` detection |
| SGLang | NVIDIA, agentic pipelines | OpenAI-compatible provider, matrix-ranked on CUDA tiers |
| DS4 | DeepSeek V4 Flash | dedicated provider, KV-cache guidance, thinking modes |

All of them are detected by the doctor, benchable with `superqode local
bench`, and usable from the same harness contract.

---

## Fast first response

Local inference has two different first-response costs:

1. The model server may need to page weights into memory on the first request.
2. A coding-agent turn must prefill the system prompt, tool schemas, restored
   session history, and any active repository context.

SuperQode avoids paying the second cost for obvious chat prompts. For local
providers other than DS4, greetings and basic non-code questions such as
`hello` or `what is 2+2?` use a fast-chat path: no tool schemas, no restored
coding history, no reminders, and no live context-window probe. Real coding
requests still use the full harness.

Warm the model before a coding session when you want to remove cold-load from
the first real prompt:

```bash
superqode local warm ollama --model qwen3:8b
superqode local warm lmstudio
superqode local warm mlx --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```

`local warm` sends one tiny streamed request and reports time to first token
(TTFT), decode speed, and total time. If TTFT stays high after warming, reduce
the loaded context (`--ctx` / `num_ctx`) or use a smaller quantized model for
interactive coding.

---

## Local does not mean isolated

Local Agentic Coding is the center, not a wall. The same harness connects
outward when you want it to: BYOK keys for hosted frontier models, ACP for
editor agents, agent SDK runtimes, MCP for tools, and A2A for agent-to-agent
workflows. Your harness spec stays identical; only the route changes. That is
the point of a portable harness: local first, connected to everything.

---

## Start here

1. [Install SuperQode](getting-started/installation.md) and run
   `superqode local init --repo .`.
2. Follow any smoke-test next steps: start the server, load a chat model, or
   reduce context if TTFT is high.
3. Run `superqode --harness superqode.local.yaml` and start coding.
4. When you want numbers, run `superqode local bench`. When you want deeper
   agent-readiness numbers, run `superqode local bench --agentic`. When you have
   multiple local/open candidates, run `superqode local optimize` to generate a
   role-routed harness. For deeper control, read the
   [Local Stack Doctor guide](advanced/local-stack.md) and the
   [harness system](advanced/harness-system.md).
