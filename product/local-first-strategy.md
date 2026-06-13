# SuperQode Local-First Strategy

Status: implementation in progress. The core Local Stack Doctor, shipped
recommendation matrix, model policy packs, MLX/DS4 local providers, and local
benchmark command are now implemented. The remaining items below are roadmap
work for making SuperQode the strongest Local Agentic Coding Harness.

Goal: make SuperQode the best coding agent harness for open models running locally, by recommending the right model, engine, and harness configuration for the hardware a developer actually has, and by squeezing the most agentic performance out of every layer.

---

## 1. The landscape, as of this week

### Open models worth optimizing for

| Family | License | Local-relevant sizes | Why it matters for coding agents |
| --- | --- | --- | --- |
| Gemma 4 (Google) | Apache 2.0 | E2B, E4B, 12B (unified multimodal), 26B MoE, 31B dense | Native function calling, structured JSON, system instructions, thinking modes. 31B is the #3 open model on Arena. The 12B brings agentic multimodal to laptops. |
| Qwen 3.5 / 3.6 (Alibaba) | Apache 2.0 | 0.8B to 397B-A17B; the sweet spots are 3.6-27B dense and 3.6-35B-A3B MoE | The open-source workhorse family of 2026. MoE A3B variants give large-model quality at small-model decode cost, ideal for unified memory. |
| Qwen3-Coder / Coder-Next | Apache 2.0 | 30B-A3B, Coder-Next (ultra-sparse), 480B-A35B | Coder-Next scores 58.7 percent SWE-bench Verified on a single 24GB GPU with 256K context. Qwen2.5-Coder remains the best fill-in-the-middle model at every tier. |
| DeepSeek V4 Flash | MIT | 284B total / 13B active, 1M context | Three local tiers: ~33GB heavily quantized, ~80GB FP8, ~170GB full. The DS4 engine (already integrated in SuperQode) is purpose-built for it on Metal, CUDA, and ROCm. |
| GLM-5.1 (Z.ai) | MIT | 754B MoE | #1 on SWE-Bench Pro, 8-hour autonomous runs. Server-class only; relevant for teams with GPU clusters, not laptops. |
| Devstral 2 Small (Mistral) | open | small | 68 percent SWE-bench Verified, runs on consumer hardware. |
| gpt-oss (OpenAI) | open | several | Emits the patch-envelope dialect SuperQode already supports natively. |

### Inference engines

| Engine | Hardware | June 2026 state | Agentic strengths |
| --- | --- | --- | --- |
| MLX stack (`mlx_lm.server`) | Apple Silicon | Apple's WWDC26 session "Run local agentic AI on the Mac using MLX" blesses exactly this stack: MLX, mlx-lm, the OpenAI-compatible server with tool calling and continuous batching, and any agent on top. M5 Neural Accelerators give 4x faster prompt processing (needs macOS 26.2+). Distributed inference across Thunderbolt-connected Macs via RDMA/JACCL: a 4-node cluster reaches ~3x generation rate and can host models up to DeepSeek's 1.6T class. | Continuous batching means concurrent peer agents are genuinely parallel. Prompt processing is the agentic bottleneck, and that is exactly what M5 accelerates. |
| Ollama (now MLX-powered on Apple Silicon, preview) | Apple Silicon, CUDA, CPU | Version 0.19 preview runs on MLX: prefill 1154 to 1810 tok/s and decode 58 to 112 tok/s on the tested config, with int4 coming. New agentic prompt caching with cross-conversation reuse and checkpoints. New `ollama launch <app> --model ...` integration. MLX preview needs more than 32GB unified memory; custom model import not yet supported. | The easiest path for most developers; the MLX runtime may obsolete our Modelfile num_ctx workaround (verify). |
| LM Studio | Apple Silicon, CUDA | 0.4.15+ is the agentic baseline; MLX backend on Mac; mature model catalog including Qwen3-Coder and Devstral 2. | Good GUI on-ramp; OpenAI-compatible server. |
| vLLM | CUDA (server) | The throughput standard. Not for Apple Silicon or CPU. | Best raw throughput at scale. |
| SGLang | CUDA (server) | ~29 percent faster than vLLM on H100; RadixAttention prefix caching gives up to 6.4x on prefix-heavy multi-turn agentic workloads; native structured-output (JSON schema) enforcement without throughput tax. | The best CUDA engine specifically for agent pipelines. |
| llama.cpp (`llama-server`) | everything, incl. CPU | `--tools all` applies model tool templates; PEG-based tool-call parsing with JSON healing; MCP and tool-registry integration in progress. | The universal fallback; only option for CPU-only and odd hardware. |
| DS4 (`antirez/ds4`) | Metal, CUDA, ROCm | Dedicated DeepSeek V4 Flash/Pro engine; includes its own bench and agent harness. Already a first-class SuperQode provider. | The most efficient way to run V4 Flash locally. |
| Emerging: vllm-mlx, Rapid-MLX | Apple Silicon | vllm-mlx: continuous batching, MCP tool calling, multimodal, 400+ tok/s. Rapid-MLX: 0.08s cached TTFT prompt cache, 17 tool parsers, drop-in OpenAI replacement. | Worth tracking as optional engines; both target exactly the agentic gap. |

### Platform signals

- Apple opened the Foundation Models framework to any Hugging Face MLX model behind a `LanguageModel` protocol, will open source it this summer, and shipped Xcode tooling for observing local model runs. Apple is officially in the local-agent business.
- Ollama's `launch` feature starts coding agents directly against local models. Local-first coding agents are becoming a configuration the platforms themselves promote.
- Conclusion: the window where "best harness for local models" is winnable is now, and the differentiator is no longer running models locally (everyone does), it is making the agentic loop excellent per hardware tier.

---

## 2. Strategy: seven pillars

### Pillar 1: the Local Stack Doctor (flagship)

One command that turns "I have this machine" into a working, tuned local agent:

```text
superqode local doctor
  -> detects: chip (Apple Silicon generation, Neural Accelerator support via macOS
     version), unified memory / VRAM (nvidia-smi, ROCm), CPU fallback
  -> inventories: installed engines (Ollama + version + MLX runtime, LM Studio,
     mlx-lm, vLLM, SGLang, llama.cpp, DS4) and already-downloaded models
     (ollama list, LM Studio dir, HF cache, mlx-community artifacts)
  -> recommends: ranked engine + model + quantization for THIS machine, with the
     exact commands to start the server
  -> generates: a tuned harness.yaml (model policy pack applied) ready to run
```

TUI equivalent: `:local doctor` and a first-run hint when no provider is connected. This is the single highest-leverage feature: it converts the research below into a product moment.

### Pillar 2: the hardware-model-engine matrix (data, not code)

Shipped as updatable data consumed by the doctor. Initial matrix:

| Hardware tier | First-choice engine | Models (coding) | Notes |
| --- | --- | --- | --- |
| Apple Silicon 16GB | `mlx_lm.server` or llama.cpp | Gemma 4 E4B, Qwen3.5-4B/9B Q4; Qwen2.5-Coder-7B for FIM | Ollama MLX preview requires >32GB, so plain Ollama or mlx-lm here |
| Apple Silicon 32-48GB | Ollama-MLX (48GB) or `mlx_lm.server` | Qwen3.6-35B-A3B 4bit, Gemma 4 12B, Devstral 2 Small | MoE A3B is the unified-memory sweet spot: big-model quality, 3B-active decode cost |
| Apple Silicon 64GB | Ollama-MLX or `mlx_lm.server` | Gemma 4 26B MoE, Qwen3.6-27B dense, 35B-A3B 8bit | DS4 V4-Flash heavily quantized becomes possible |
| Apple Silicon 128GB+ (M4 Max class) | `mlx_lm.server` + DS4 | Gemma 4 31B bf16, Qwen3-Coder-30B-A3B, DeepSeek V4 Flash quantized | Enough headroom to run a main coder plus a small FIM/utility model concurrently |
| M5 + macOS 26.2 | always prefer MLX path | same as tier | Neural Accelerators give 4x prefill; agentic loops are prefill-dominated |
| Multi-Mac (Thunderbolt) | MLX distributed (JACCL) | 100B+ class, V4 full | Document the cluster recipe; 4 nodes ~3x |
| NVIDIA 8-16GB | Ollama or llama.cpp | Devstral 2 Small, Qwen3-Coder-Next Q4, Gemma 4 12B Q4 | |
| NVIDIA 24GB | SGLang or vLLM (AWQ) | Qwen3-Coder-Next (its design target), Qwen3.6-27B | SGLang preferred for agentic: RadixAttention + structured output |
| NVIDIA 48-96GB+ | SGLang | Qwen3-Coder-30B-A3B FP8, DS4 V4-Flash FP8 | |
| Multi-GPU server | SGLang/vLLM | GLM-5.1, DeepSeek V4 | Team-server scenario; SuperQode connects over OpenAI-compatible API |
| CPU-only | llama.cpp | Gemma 4 E2B/E4B, Qwen3.5-2B | Pair with `tool_call_format: prompt` |

### Pillar 3: deeper engine adapters

- First-class `mlx_lm.server` lifecycle, mirroring the DS4 provider: `superqode providers mlx server --model ...`, health probe, loaded-context detection (already have the /v1/models probe).
- Ollama 0.19 awareness: detect the MLX runtime, re-test the num_ctx behavior (our Modelfile workaround may be obsolete on the MLX runner), and exploit their new agentic prompt caching.
- Engine capability profiles: a table per engine recording tool-calling reliability per model family (native vs our prompt mode), prompt/prefix cache support, continuous batching, structured-output enforcement, embeddings. The loop already adapts per model family; this adds the per-engine dimension.
- Evaluate vllm-mlx and Rapid-MLX as optional engines once they stabilize; their prompt-cache TTFT numbers matter for steering-heavy interactive use.

### Pillar 4: model policy packs (the customization story)

Today gemma4 and ds4 tuning lives in code (`providers/profiles.py`, harness templates). Move it to data:

- A pack is YAML: sampling parameters, `tool_call_format`, tool profile, context strategy (keep-recent sizing, compaction aggressiveness), reasoning/thinking toggles, stop-token quirks, recommended quantizations per RAM tier.
- Ship packs for: gemma4 (per size), qwen3.5, qwen3.6, qwen3-coder(-next), ds4/deepseek-v4, devstral2, gpt-oss (patch envelope default), glm (server tier).
- User packs in `~/.superqode/model-packs/` override shipped ones; harness specs reference them via `model_policy.pack:`. This is exactly "developers define their own harness fully optimized for their models," with the harness file staying portable.

### Pillar 5: agentic performance plumbing

- Prefix-cache discipline audit: the request prefix (system prompt, tool schemas) must stay byte-stable across turns so MLX/Ollama/SGLang caches hit. Tool defs are already sorted; reminders already append at the end. Verify end to end and add a regression test.
- Surface TTFT and tokens/sec per turn in the thinking trace and `:context`, so users see what their stack delivers.
- Peer-agent parallelism hints per engine: on continuous-batching engines (mlx-lm server, vLLM, SGLang), concurrent peers are truly parallel; on single-stream engines they serialize. The doctor should say so, and peer-agent docs should reflect it.
- `superqode local bench`: a standardized agentic micro-benchmark (a short read-edit-bash tool loop) run against each installed engine/model combination, producing measured TTFT, decode rate, and tool-call success rate. Recommendations from measurement beat any static table, and this builds on the existing benchmarks module.

### Pillar 6: model acquisition UX

- `superqode models advise`: given detected hardware, print the exact artifacts to pull (ollama tag vs mlx-community 4bit vs GGUF), with size previews (the HF dry-run download support already exists).
- Post-pull: offer to generate the matching harness from the right pack.

### Pillar 7: Apple-stack alignment (forward-looking)

- Track the Foundation Models framework open sourcing; an `MLXLanguageModel`-style integration could eventually let SuperQode appear inside Apple's own agent tooling.
- Document the multi-Mac distributed recipe for 100B+ models (Thunderbolt RDMA).
- Investigate registering SuperQode as an `ollama launch` target so `ollama launch superqode --model qwen3.6:35b-a3b` works.

---

## 3. Prioritized roadmap

**P0 (build first, highest leverage)**
1. Local Stack Doctor: detection + inventory + recommendation + harness generation.
2. Hardware-model-engine matrix as shipped, updatable data.
3. Model policy packs as user-overridable YAML, wired into harness `model_policy.pack:`.

**P1**
4. `mlx_lm.server` first-class provider lifecycle.
5. Ollama 0.19/MLX detection and num_ctx workaround re-validation.
6. Prefix-cache stability audit + per-turn TTFT/tok-s surfacing.
7. `superqode local bench` measured recommendations.

**P2**
8. Engine capability profiles informing loop behavior per engine.
9. `models advise` acquisition UX.
10. vllm-mlx / Rapid-MLX optional engine evaluation.
11. Multi-Mac distributed recipe documentation; `ollama launch` target.

**Risks and watch items**
- Ollama's MLX runtime is a preview: behavior (num_ctx, model coverage, >32GB requirement) will change; keep detection version-gated.
- The matrix decays: model releases land monthly; that is why it must be data, refreshed independently of releases, with `local bench` as the ground truth on each user's machine.
- macOS version gating for Neural Accelerators (26.2+) must be detected, not assumed from chip generation.

---

## 4. Why this wins

Every harness can call a local OpenAI-compatible endpoint. None of them answer the question developers actually have: "I bought this machine; what is the best coding agent I can run on it, and how do I get it tuned in one command?" SuperQode already owns the hardest parts (the loop hardening, context economy, prompt-mode tool calling, the DS4 integration, loaded-window detection). The doctor, the matrix, and the policy packs turn that engineering into a product answer, and the bench makes the answer provable on the user's own hardware.

---

## 5. Addendum (June 11): Apple fm SDK and MacXie analysis

### Apple fm CLI and Foundation Models Python SDK

What shipped at WWDC26: the `fm` CLI (pre-installed with macOS 27; `respond`, `chat`, `schema` subcommands) and the `apple-fm-sdk` Python package (Apache 2.0, macOS 26+, Apple Silicon, Xcode required). The Python SDK exposes the on-device Apple Intelligence model through a session API with streaming, tool calling, guided generation (`@fm.generable` structured output), and image input. It accesses the system model only; custom and MLX models are not reachable from the Python SDK today. An optional Private Cloud Compute model handles harder prompts but has usage limits, and the on-device model's small context produces generation errors on complex prompts.

Assessment for SuperQode: not a coding engine (the model is too small for agentic coding), but an excellent **utility model**: zero-install, zero-cost, fully private, always present on modern Macs. SuperQode makes many small background LLM calls that currently burn main-model tokens or local-server throughput: the rubric grader, automatic memory extraction, summaries and titles, small structured one-shots. Routing those to the system model is free capacity.

Plan addition (P1):

- New provider `apple-fm` behind an optional extra (`superqode[apple-fm]`), platform-gated, with availability detection (`SystemLanguageModel.is_available()`).
- A "utility model" routing tier in model policy: graders, auto-memory extraction, and title/summary calls prefer the utility model when configured; `apple-fm` becomes its default on capable Macs.
- Doctor integration: report Apple Intelligence availability as a free utility-model slot.
- Watch item: the Foundation Models framework opens sourcing this summer, and WWDC26 session 339 covers bringing third-party LLM providers into the framework; that is a future path for SuperQode to appear inside Apple's own agent tooling.

### MacXie (SiliconClaw) import analysis

MacXie (`/Users/shashi/oss/siliconclaw`, 135 Python files, Apache 2.0, same author) is a local-first personal assistant for Apple Silicon. Deep review verdict: **selective adoption, not wholesale import**. Its harness, agents, daemon, memory, MCP, and sandbox modules are parallel implementations of systems where SuperQode is now substantially ahead; importing those would create dual systems. Three assets are genuinely valuable:

1. **`inference/model_policy.py` is a working prototype of the Local Stack Doctor.** It already implements hardware profiling (unified memory tiers), per-family model maps by tier, preference for already-downloaded models, and model inventory across the Ollama API, the MLX Hugging Face cache, and LM Studio. Port and extend it: more tiers (16 through 128GB plus NVIDIA VRAM tiers), refreshed model map (its gemma-3 and Qwen2.5 entries predate Gemma 4 and Qwen 3.6), engine recommendation, and harness generation. This de-risks P0 significantly.
2. **`inference/vlm_worker.py` solves our known mlx-vlm conflict.** It runs mlx-vlm in an isolated subprocess with JSON-line IPC, sidestepping the starlette/fastapi dependency clash we hit with Gemma 4 multimodal. The same pattern (plus the engine's interrupt and download-progress handling) upgrades SuperQode's in-process MLX path and enables local multimodal inference cleanly.
3. **`channels/` (10.7K lines, tested) is a differentiator for later.** Telegram polling, Slack socket mode, Discord gateway, and iMessage watch. Driving a coding agent from chat (kick off a run from your phone, receive long-run notifications, approve `request_permissions` escalations over Slack) composes perfectly with peer agents and the approval flow. Adopt as an optional extra (`superqode[channels]`) in P2 with an adapter layer; coupling to MacXie internals is moderate (config, response normalization, engine types).

Strategic recommendation (decided June 11): do not release MacXie as a standalone product. Roughly 70 percent of it is a parallel, earlier implementation of subsystems where SuperQode is now ahead; releasing it would split maintenance, community, and positioning against our own product. Fold the valuable 30 percent into SuperQode: model policy into the Doctor (P0), the vlm-worker pattern into the MLX provider (P1), channels as `superqode[channels]` with approval-over-chat (P2), the daemon and jobs scheduler as a `superqode daemon` mode, and the persona templates as harness templates (an `assistant` template alongside `coding` and `no-tool`). Park the MacXie brand: if demand for a packaged consumer assistant emerges later, MacXie returns as a distribution of SuperQode (preset harness, channels pre-wired, native companion), a brand and a default configuration rather than a codebase. Archive the siliconclaw repo once the ports land.

### Revised priority deltas

- P0 gains a head start: port MacXie `model_policy` as the doctor's core.
- P1 adds: `apple-fm` utility provider + utility-model routing tier; mlx-vlm subprocess worker for local multimodal.
- P2 adds: `superqode[channels]` (Telegram/Slack/Discord/iMessage) with approval-over-chat.
