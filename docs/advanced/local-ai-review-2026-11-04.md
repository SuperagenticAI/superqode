# Local AI execution and onboarding review

Research date: 4 November 2026. Baseline: `origin/main` at `23f3cba543cea209ab780ccd22d6020cb240f7fb`, Python 2.31.2 and macOS 0.3.3 build 19. Main was fetched again during this review and remained at that commit.

**SuperQode already has substantial local inference infrastructure. The next product should turn it into one guided path: choose a model that suits this machine, download it, start it, verify it and code.** Qwen and Gemma are good initial recipe families; GLM and DeepSeek should be prominent where the exact checkpoint and runtime fit the hardware.

The existing interface is a capable workbench, but a newcomer still coordinates runtime installation, model files, quantization, context, server startup, model selection and harness selection. Adding another engine alone will not remove that friction. Optimisation also needs dependable memory and performance evidence before defaults are promoted.

## Implemented today

| Area | Current implementation | Practical limit |
| --- | --- | --- |
| Native Local AI | Server cards, recommended/Hugging Face searches, GGUF/MLX choice, size estimates, operations and logs. | It starts with runtime controls and separate operations rather than a single model-to-coding journey. |
| Native server management | Ollama, LM Studio, MLX, llama.cpp and DS4. Runtime installation is reviewed where supported; MLX uses an isolated environment. | Fresh DS4 setup requires a separately built binary and weights. SGLang/vLLM are available elsewhere, but are outside this native managed workbench's five-engine set. |
| Downloads | Ollama pulls; exact Hugging Face revisions/files; GGUF shard grouping; MLX snapshots; progress and cancellation; completed-cache reuse. | Ollama transfer size can be unknown before pulling. Cancellation is not a universal pause/resume promise. Download completion does not automatically finish server/model/harness setup. |
| Storage | Configurable Hugging Face cache, disk preflight, Hub token verification and optional Keychain storage. LM Studio can link imported cached weights. | Download/cache locations and loaded-model identity remain separate concepts. There is no default installed-model-first journey in this view. |
| Hardware | Apple Silicon/RAM and NVIDIA/VRAM detection, tiered model suggestions, weight estimates, separate power/load guardrails. | The workbench fit verdict covers weights, not the complete inference allocation. Aggregate VRAM is not necessarily usable as one pool. |
| Model families | Packs for Qwen/Qwen Coder, GLM, Gemma, DeepSeek/DS4, Kimi, MiniMax and others. Packs auto-detect by model identity or can be explicitly selected. | These are starting policies, not certification of every checkpoint, quantization and server version. |
| Local routing | Advertised local model selection, loopback endpoint bindings, persistence across supported harness switches and no-tool tests. | Binding the primary model does not rewrite fallbacks, delegates, embeddings or network tools into a fully offline system. |
| Readiness | Endpoint, tool-shape, patch-format and context probes; a bounded Core read-tool roundtrip on generated data. | Readiness is not proof of a successful repository edit/test task. The native UI correctly keeps these scopes separate. |
| Local performance helpers | TUI model warmup, context probing, compact family policies, KV controls for Ollama/llama.cpp, benchmarks and role recommendations. | Native setup, request shaping and performance measurements need a more consistent contract. |
| Offline tools | Airplane preparation, local indexing/search and no-network harness settings exist. | A local primary endpoint alone is not an OS-level network boundary. Shell commands and agent adapters need their own enforcement model. |

Relevant implementation: `local/workbench.py`, `local/servers.py`, `local/install.py`, `local/inventory.py`, `local/matrix.py`, `local/packs.py`, `desktop_service/local_models.py`, and native `LocalModelsView.swift`.

## Confirmed findings

### Fixed locally: GGUF quantization names could understate memory

The weight estimator used regular-expression word boundaries. Underscores are word characters, so common suffixes such as `Q8_0`, `Q6_K` and `Q2_K` were missed. A label such as `Qwen-30B-Q8_0` fell back to the default 4-bit estimate:

```text
Before: estimate=17.4 GB; on 32 GB hardware, likely_fits=true
After:  estimate=31.5 GB; on 32 GB hardware, likely_fits=false
```

Parameter counts followed by underscores could also become unknown. The fix recognises separators while rejecting unrelated suffixes such as `Q80` and `Q8custom`. Eight regression cases cover names and the downstream fit decision. Estimates remain approximate; actual artifact sizes should take precedence.

### Fixed locally: failed execution could pass the Core read check

`local/coding_check.py` checked the successful read event and returned marker but did not check the run's final execution state. An offline fixture with matching read evidence and `stopped_reason="error"` was reported as passed.

The check now also requires normal completion without execution or schema errors. The report retains stop reason and completion evidence. Five regression cases cover error, cancellation, iteration exhaustion and error metadata on otherwise complete responses. Existing successful read and path-boundary tests continue to pass.

### Open: the default native recommendation projection drops GLM and DeepSeek

`workbench.search(source="recommended")` only projects catalog commands matching `ollama pull <tag>`. Hugging Face and other server instructions are discarded. An offline probe on a simulated 32 GB Mac returned:

```text
query=glm       -> 0 recommended results
query=deepseek  -> 0 recommended results
query=gemma     -> 5 recommended results
query=qwen      -> 8 recommended results
```

This is a projection gap, not absence of GLM/DeepSeek support. The underlying catalog contains those families, and HF search or explicit setup can find other artifacts. Preserve model families across engines in a real recipe catalog, rather than deriving the Mac model library from executable command strings.

### Open: tier recommendations need artifact-level validation

The shared matrix recommends GLM-4.5-Air at 4-bit for an Apple 32 GB tier and Qwen3-Coder-Next at Q4 for NVIDIA 16 GB. Those are poor unqualified defaults for full-resident inference. The first-party [GLM source](https://github.com/zai-org/GLM-4.5) identifies Air as 106B total parameters, and the [Qwen source](https://github.com/QwenLM/Qwen3-Coder) identifies Coder-Next's base as 80B total parameters. Active MoE parameters reduce computation, not the total weight storage requirement.

Heavy offload or a different quantization may permit an experiment, but that is distinct from a responsive default. Rebuild recommendations around a specific artifact, actual weight bytes, compatible runtime, memory allocation and declared offload. Do not infer hardware fit from the active-parameter count or the word "Air".

The native recommended search also passes an empty installed inventory to the shared search. Although overview collects cached models and GGUF paths, the default library does not use that inventory to offer a clear **Use installed model** path. Reusing a valid existing download should come before suggesting another one.

### Open: benchmark throughput is response-chunk throughput

`local/bench.py::_stream_chat` increments a counter for content or tool deltas and calls `(chunks - 1) / decode_window` tokens per second. `run_bench` also stores the chunk count as `completion_tokens`. Provider-reported usage is not used there.

A controlled stream with the same text, four reported completion tokens and the same timing produced:

```text
1 content chunk: displayed decode_tps=null
3 content chunks: displayed decode_tps=1.0
```

Network/event batching is not tokenization. This affects the evidence used by local smoke reports and role-scoring heuristics. Record chunks separately, use trustworthy server-reported token counts/timings, and leave token throughput unknown when unavailable. TTFT includes loading, queueing, processing and possible reasoning; it is not a direct prefill-speed measurement.

This finding remains open in this review. Do not use the current `tok/s` value to claim one engine or recipe is faster.

### Open: context ownership is split

The native start form defaults to 16,384 tokens. The Ollama gateway independently chooses family request hints such as 32,768 for Qwen/Gemma when the request lacks an explicit override. A direct command/request-shaping probe confirmed those differing values.

There are existing context probes and explicit overrides, so this is not a claim that every native run uses the wrong allocation. Establish one effective configuration across server load, request options and agent compaction. Test that the next turn cannot silently enlarge a user's reviewed memory budget. Existing server adoption must report the actual configuration rather than imply the new requested values took effect.

### Gemma has a specialised harness, with a permission constraint

CodeGem already handles local Gemma, a compact six-tool surface, Gemma-specific tool history, thinking behavior, context and compaction budgets. It is not automatically selectable through the native Local AI binding helper, whose supported set excludes the `codegem` backend.

Do not resolve that by adding it to the allowed list alone. CodeGem currently requires host execution with `approval_profile=none` and rejects approval rules/command allowlists it cannot enforce. Its local provider set also differs from the workbench's engine set. A guided recommendation must preserve normal user permission expectations. Either add the required adapter/permission integration or provide an equally compact Core profile with verified Gemma behavior, then compare outcomes.

## Recommended default experience

Give users **Run a model locally**. Detect hardware and already-running/cached models, then offer three recommendations: **Fast**, **Balanced**, and **More capable**. Show Qwen and Gemma prominently; include eligible smaller GLM/DeepSeek artifacts instead of promoting a flagship merely because the family is popular.

The flow should be:

```text
Choose a recommended model or an installed model
  -> review total download, destination and expected resource use
  -> install a missing runtime and download the selected artifact
  -> start/load with a compatible context and memory budget
  -> run a small bounded verification
  -> open the coding workspace with the model already selected
```

One reviewed setup intent can describe the full chain; each step should retain its own status, cancellation and recoverable evidence. Reuse existing job idempotence, ownership checks, pinned downloads and cache reuse. Remember what succeeded, so a server-start failure does not send the user back to the beginning or redownload weights.

Put engine, GGUF/MLX format, exact quantization, raw paths, context and KV options in Advanced. A user who wants Qwen should not first need to choose between five server implementations. A user who already runs Ollama or LM Studio should be able to reuse it. Keep existing external server ownership intact.

For Gemma on a public Ollama route, no cloud API key is needed. Where a Hugging Face artifact requires accepting model terms or authenticating, explain that at the download step and return directly to the selected recipe afterward. Existing Hub access/Keychain support can be reused.

## Make the harness efficient on small models

Optimise the complete tool loop, not only raw generation:

1. Reuse compact Core/model-family policies and send only relevant tool schemas. Keep rules, tools and stable repository instructions in a consistent prefix to help runtime caching.
2. Use targeted file search and bounded file excerpts instead of repeatedly sending large repository context. Reuse existing local indexes; optional embeddings should not become a prerequisite for the first task.
3. Budget history, tool output and compaction against the effective loaded context. A long advertised model window is not a sensible default on every machine.
4. Verify native tool calls and the matching parser/chat template for the exact model. Use an explicit tested compatibility mode where needed. Reasoning and sampling settings should follow that checkpoint's contract, with conservative output/iteration limits.
5. Begin with one active local coding task. Schedule additional work according to measured memory, power/load and runtime capacity. A model, embedder, reviewer and other applications compete for the same memory on a Mac.
6. Expose simple **Fast**, **Balanced**, **Reason carefully** controls only for settings the selected model supports. Never invent a thinking toggle for a model that has no thinking mode.

The project already has compact packs, context discovery, tool profiles, local search, guardrails and model warmup. Connect and validate those capabilities across native setup and execution rather than building another independent configuration system.

## Engine strategy

| Environment | Initial recommendation | Optional optimisation |
| --- | --- | --- |
| Apple Silicon with a working server | Reuse compatible installed Ollama/LM Studio setup and weights. | Offer an MLX or llama.cpp recipe only when the exact artifact/runtime is supported and measurements justify it. |
| Fresh Apple Silicon setup | Choose one curated runtime/artifact automatically after hardware assessment. Keep small Qwen/Gemma recipes easy. | Add a tested MLX path with isolated installation; avoid making users manage Python environments. |
| NVIDIA development machine | Use a compatible quantized model that fits declared GPU/offload capacity. | vLLM/SGLang for appropriate server workloads; do not make their installation the beginner default. |
| CPU-only machine | Offer a small quantized model and honest expectations about responsiveness. | Measure a bounded task before recommending larger weights. |
| Large GLM/DeepSeek models | Show actual memory/storage requirements and compatible serving options. | Advanced offload, larger-memory machines and specialised DS4 recipes where tested. |

First-party [MLX-LM guidance](https://github.com/ml-explore/mlx-lm#long-prompts-and-generations) describes prompt caching, bounded KV caches and prefill step size. The [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) exposes prompt caching, quantized KV, GPU placement, slots and speculative decoding. These are optimisation candidates, not evidence of a universal speedup. Inspect the installed version's capabilities before exposing flags; measure quality, peak memory and end-to-end latency before promotion. Do not change system memory limits automatically.

## Ordered implementation plan

### 1. Rebuild recommendations and establish reliable measurements

Replace command-string-derived recommendations with curated recipes containing model family, exact artifact/revision/quantization, weight size, runtime/version range, hardware requirements, context/default concurrency, license/access information and validation evidence. Preserve installed models first. Correct infeasible tier entries and the chunk/token measurement contract.

Acceptance: GLM and DeepSeek are discoverable when a compatible recipe exists; unknown sizes remain unknown; MoE recommendations use total weights; quantizations do not share an unqualified memory claim; identical outputs do not acquire different token counts because SSE batching changed.

### 2. Ship one native download-to-coding journey

Reuse existing workbench operations in a durable setup coordinator. Start with a small validated Qwen recipe and a Gemma recipe on common Apple Silicon hardware. Add other recipes only after the same end-to-end checks.

Acceptance: a clean supported Mac reaches its first verified task without Terminal or manual file paths; a working local installation needs no new download; denied access, insufficient storage, interrupted download, failed load, conflicting port and restart each have a specific recovery action. Preserve existing user configuration and completed artifacts.

### 3. Apply one effective resource and harness profile

Calculate a conservative budget for actual weights, runtime buffers, KV/context, concurrency and OS headroom. Use current memory pressure as well as total capacity. Tie the effective context to requests and compaction. Invalidate/review the plan if the artifact or configuration changes. A multi-GPU estimate must match the runtime's placement strategy.

Acceptance: the reviewed context is not silently expanded by the next request; failed loads produce a smaller compatible suggestion; settings unsupported by that engine are hidden; a compact profile retains the expected read/write/shell permissions.

### 4. Verify local coding and offline behavior

Retain readiness checks, then add an isolated bounded fixture that reads code, makes a small edit and executes a known check with explicitly reviewed permissions. Show readiness, tool roundtrip and coding outcome as separate evidence. Keep the generated marker/failed-run regression fixed.

Offer an explicit local-only preset that inventories primary/fallback/delegate/embedding routes and optional external tools. Reuse Airplane helpers, but distinguish application policy from an OS-level guarantee. Remote inference must never be an automatic recovery for a user who selected local-only operation.

Acceptance: the initial task needs no hosted API key; provider failures do not cause cloud billing; advertised offline tests include secondary routes and attempted network access; stale compatibility evidence is invalidated when weights, template, runtime or harness changes.

### 5. Tune against representative machines

Run the same declared tasks on representative 16/24/32/64 GB Macs and appropriate NVIDIA/CPU systems. Choose exact machines and affordable models before benchmarking. Record cold model-load time, warm first-visible-output latency, first-tool latency, total solved-task time, true token usage, peak memory/swap, context and failure/recovery outcomes.

Compare permission-equivalent compact Core/Gemma paths and supported server recipes. Keep unsuccessful trials. A target such as a first verified task within five minutes after the download is a proposed product goal, not a measured current result. Download time should be reported separately.

## Validation and current limitations

Two production fixes were made locally in `local/matrix.py` and `local/coding_check.py`. Thirteen added regression cases cover quantization/fit and failed readiness execution. The selected local, native binding, installation, server, cache, progress, pack, tool, smoke, Airplane, Gemma reliability and TUI latency checks completed with **367 passed**. Ruff lint and formatting passed for the five changed local Python/test files.

Offline probes reproduced the recommendation projection gap, chunk/token throughput mismatch and split context defaults. These remain open. The native guided setup and recipe redesign are proposals in this document, not implemented features.

This Linux environment did not load real model weights, measure a GPU/Apple Silicon speedup or run Swift UI tests. No large model download, runtime installation, paid inference, version bump, push, merge or release was performed. Existing changes from the earlier evaluation/subscription reviews were preserved.

## Implementation follow-up

The subsequent implementation adds **Local Quick Start** to the native Local AI
page. It offers small Qwen/Gemma starting choices based on detected memory and
puts models already advertised by running local servers first, including GLM
and DeepSeek. Project-scoped setup state survives reopening the guide and engine
restart. Each installation, server start, download and bounded Core read check
uses the existing reviewed operation jobs; failed or interrupted steps need an
explicit retry. Successful verification leads to Core with the local model
selected, without automatically sending a coding prompt.

This initial slice guides Ollama downloads and reuses models already served by
other supported engines. Manual-only runtime installations link to the official
installer. Arbitrary cached HF/GGUF setup remains in the existing workbench.
Artifact-level recommendations, true token-throughput measurement and resource
profile unification remain future work. Native build and real-model validation
are still required on macOS.
