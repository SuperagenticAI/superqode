# Local Agentic Coding

**Local Agentic Coding** is agentic software engineering on open models running
on your own hardware: an agent that reads, edits, tests, and ships code, where
the model weights, the context, and the transcript never leave your machine.

SuperQode is built to be the first choice for it. Cloud-first harnesses treat
local models as a degraded fallback. SuperQode treats them as the design
center, and treats the cloud as the thing you connect to when you choose to.

---

## Why local, and why now

Three things changed:

1. **Open models got serious.** Current open-weight coders solve a majority of
   real software engineering benchmark tasks on hardware a developer can own.
   MoE architectures deliver large-model quality at small-model decode cost.
2. **Local serving got fast.** MLX on Apple Silicon, continuous batching,
   prefix caching, and accelerator-aware runtimes turned local inference from
   a demo into a daily driver.
3. **The privacy and cost math flipped.** An agent loop resends a growing
   context every turn. On metered APIs that compounds; on your own hardware it
   is free, and the code never leaves the building.

What did not change: local models are less forgiving than frontier APIs. They
have smaller loaded context windows, weaker tool-calling heads, tighter prompt
budgets, and wildly different sweet spots per family. A harness that ignores
this produces a bad agent. SuperQode is engineered for exactly these realities.

---

## From zero to a tuned local agent

One command turns "I have this machine" into a working setup:

```bash
superqode local doctor
```

The [Local Stack Doctor](advanced/local-stack.md) detects your hardware tier,
probes seven inference engines, inventories every model you already
downloaded, and recommends the best combination, preferring what is already
installed. Then:

```bash
superqode local doctor --generate harness.yaml
superqode --harness harness.yaml -p "your task"
```

The generated harness routes to the right provider for where the model lives,
references the matching model policy pack, and switches small machines to
prompt-based tool calling. In the TUI, `:local` runs the same doctor.

---

## What SuperQode does differently for local models

Every layer of the harness has a local-first answer:

| Reality of local models | SuperQode's answer |
|---|---|
| The loaded context window is smaller than the model card says | Live window detection from the running server, [adaptive compaction](advanced/local-context.md) sized to it |
| Model families need different prompts, temperatures, and formats | [Model policy packs](advanced/local-stack.md#model-policy-packs): tuned defaults per family, user-overridable |
| Many models have no reliable native tool head | `tool_call_format: prompt` renders tools into the prompt and parses calls from text |
| Tool schemas eat the prompt budget | [Deferred tools](advanced/tools-system.md): heavy schemas hidden until the model activates them via `tool_search` |
| Small models loop and emit malformed calls | Doom-loop guard, tool-argument repair, and dangling tool-call repair in the [agent loop](advanced/agent-loop.md) |
| Engine choice is hardware-dependent and changes monthly | The recommendation matrix ships as updatable data with user overrides |
| Speed claims are unverifiable | `superqode local bench` measures TTFT and decode rate; `--agentic` also scores tool-call, edit-format, shell-call, and context-recall probes |
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

## Local does not mean isolated

Local Agentic Coding is the center, not a wall. The same harness connects
outward when you want it to: BYOK keys for hosted frontier models, ACP for
editor agents, agent SDK runtimes, MCP for tools, and A2A for agent-to-agent
workflows. Your harness spec stays identical; only the route changes. That is
the point of a portable harness: local first, connected to everything.

---

## Start here

1. [Install SuperQode](getting-started/installation.md) and run
   `superqode local doctor`.
2. Follow the verdict: pull the model or start the engine it names.
3. Generate the harness: `superqode local doctor --generate harness.yaml`.
4. Run `superqode --harness harness.yaml` and start coding.
5. When you want numbers, run `superqode local bench`. When you want deeper
   agent-readiness numbers, run `superqode local bench --agentic`. When you have
   multiple local/open candidates, run `superqode local optimize` to generate a
   role-routed harness. For deeper control, read the
   [Local Stack Doctor guide](advanced/local-stack.md) and the
   [harness system](advanced/harness-system.md).
