# CodeGem local Gemma study: 13 October 2026

## Scope and machine

This iteration focuses on local Gemma 4 and EmbeddingGemma 2 through Ollama,
LM Studio, and llama.cpp. The development host is an Apple M4 Max with a 40-core
GPU and 128 GB unified memory. It has no discrete GPU VRAM. This allows large
local trials, but the results are not a direct performance prediction for a
32 GB NVIDIA card.

## Model choice for a 32 GB GPU

Google lists Gemma 4 26B-A4B, 31B, and smaller E2B/E4B/12B variants. The 26B-A4B
MoE activates about 3.8B parameters per token, but the full 25.2B parameter model
must stay resident. Google's published Q4_0 loading estimate and the pinned
GGUF file are both about 14.4 GB; the serving process also needs KV-cache and
runtime headroom, which grows with context. The first high-quality 32 GB
candidate is therefore the
Google-published 26B-A4B instruction QAT Q4_0 GGUF. This is a real QAT model,
not an arbitrary post-training quantization. The full instruction checkpoint is
pinned in `scripts/download_codegem_models.py` and SHA-256 checked before use.

This is a throughput-oriented choice for an agent harness, not the top Gemma 4
coding benchmark score. Google's model card reports LiveCodeBench v6 at 80.0%
for 31B and 77.1% for 26B-A4B, with approximate Q4_0 load estimates of 17.5 GB
and 14.4 GB respectively. The 31B QAT GGUF is a sensible next comparison when
quality matters more than speed, but its KV-cache headroom on a 32 GB card was
not measured here. The short local fixtures do not resolve that trade-off.

Start with a 32K context, one active sequence, Flash Attention when supported,
and Q8 KV for K and V. Raise context only after checking actual runtime allocation
on the target machine. Do not set the model's advertised 256K window as the
loaded context by default. llama.cpp warns that very low-bit KV cache can impair
tool use. On Apple Silicon unified memory, the 12B MLX build already present is
the low-friction baseline; Ollama's MLX/MTP path is the first candidate when
interactive speed matters. The 26B QAT GGUF is the quality-focused candidate
when the memory budget allows.

These are candidate starting settings; measured trial results and failures are
recorded in `codegem-validation-2026-10-13.json` as each serving path is tested.

## Harness-specific behavior

CodeGem's existing provider layer supports:

* Ollama's native `/api/chat` tool path and `/api/show` capability probe.
* LM Studio's OpenAI-compatible `/v1/chat/completions` endpoint.
* llama.cpp's OpenAI-compatible endpoint.

The harness keeps Gemma 4's temperature/top-p/top-k defaults, native tool
selection when the server advertises it, the system role, and the thinking switch.
It drops old thinking text on ordinary turns while preserving it between tool
calls, matching Google's multi-turn instructions. The generation loop allows
only the six CodeGem tools and validates calls before execution. This matters
because a server accepting an OpenAI tools payload does not by itself prove that
Gemma 4's special tool-call template and response history are working correctly.

## EmbeddingGemma 2 use in coding

EmbeddingGemma 2 is 740M total parameters, with an independently selectable
270M text tower. Its shared vector space includes text, images, video, and audio,
but this iteration uses only source text. Google reports MTEB Code v1 NDCG@10
of 78.68 at 768 dimensions, 77.24 at 512, 76.18 at 256, and 71.41 at 128. The
local index defaults to 256 dimensions and L2-normalizes after truncation, which
is the documented Matryoshka behavior. Queries use `task: code retrieval | query:`
and each source chunk uses its filename as the document title.

The feature stays inside CodeGem's existing `search` tool. A semantic search
builds or incrementally refreshes a Git-aware local SQLite index, then returns
candidate chunks with file/line references. It ignores Git-ignored files and
private dot directories, caps project size and chunk count, and rejects nonlocal
embedding endpoints. Retrieval is a navigation aid: the agent still reads the
current file and runs tests. The code index does not add a seventh model tool.

## Public X signals

## Local runtime trials

The pinned 26B-A4B instruction QAT Q4_0 GGUF passed the same isolated repair
and creation tasks at 32K context on all three local serving paths: Ollama
(19.62s and 16.48s), LM Studio (5.67s and 10.40s), and llama.cpp (17.50s and
16.98s). Protected tests stayed unchanged in every run. These are single-host
smoke timings, not throughput comparisons: each backend has its own warm-up,
scheduling and implementation. The M4 Max has unified memory, not 32 GB of
discrete VRAM. LM Studio's direct imported GGUF failed when its native tool
template was rendered; CodeGem's narrow auto-retry switched that model/backend
pair to strict JSON-schema tool responses, after which both tasks passed.
Ollama and llama.cpp handled native tool calls.

The same two fixtures passed on the existing Ollama `gemma4:12b-mlx`
(54.94s and 40.09s), also with protected tests unchanged. That result cannot
establish that 26B is faster or better: the models used different runtimes and
this tiny set is not a quality ranking.

EmbeddingGemma 2's pinned 558 MB text GGUF downloaded and passed SHA-256
verification. The installed llama.cpp 10360 build rejected its
`gemma-embedding2` architecture; installed Ollama 0.32.7 refused the published
package because it requires a newer Ollama. Those were runtime-version errors,
not a broken model file. The model's official Hugging Face/Sentence Transformers
path did work locally after including Pillow and torchvision, which the Gemma 4
processor imports even for text-only embedding calls. A 256-dimensional MPS run
indexed 1,789 CodeGem/harness chunks, then reached Recall@5 6/6 and MRR@5 1.0
on six hand-labeled natural-language queries. All six expected files ranked
first. One formal adapter-resume wording initially ranked sixth; the ordinary
user phrasing “how does CodeGem resume an existing session” ranked the expected
adapter first. This small smoke evaluation is not a general quality claim. The
result list returns one best chunk per file so a large module cannot consume all
five slots with duplicates. The whole repository exceeds the 10,000-chunk
safety budget, so the initial scope remains targeted.

The reliable local setup is the optional `semantic-local` dependency extra with
`provider: sentence-transformers`, `model: google/embeddinggemma-2`, and
`device: auto` (CUDA, MPS, then CPU). Set `local_files_only: true` after the
model has been cached to guarantee offline inference. The Ollama and GGUF
routes remain supported for runtimes that have added this newer architecture.
Use the new Google model ID rather than the older unqualified Ollama tag when
running through Sentence Transformers.

Public X posts on Gemma 4 show users wiring the models through Ollama into local
agent applications and emphasize offline execution. These posts are useful for
finding common workflows, not for ranking model quality. For example, [AYi's
post](https://x.com/AYi_AInotes/status/2042292538342850921) describes Ollama plus
OpenClaw and points readers toward the E2B/E4B laptop tiers; [Andy O'Donoghue's
post](https://x.com/ADODonoghue/status/2040031009115197774) summarizes the family
and 26B-A4B MoE. X search did not yield a reproducible CodeGem-like coding-agent
benchmark or convincing independent EmbeddingGemma 2 code-search evaluation.
Promotional posts and unverified token/speed numbers were not treated as evidence.

## Sources

* [Google Gemma 4 model card and QAT repository](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf)
* [Google Gemma 4 overview and memory estimates](https://ai.google.dev/gemma/docs/core)
* [Google Gemma 4 prompt formatting and thought-history rules](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4)
* [Google Gemma 4 function-calling guide](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
* [Ollama Gemma 4 MTP report](https://registry.ollama.com/blog/faster-gemma-4-mlx-mtp)
* [Ollama EmbeddingGemma 2 model page](https://ollama.com/library/embeddinggemma-2)
* [Google EmbeddingGemma 2 model card and retrieval prompts](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2)
* [Google EmbeddingGemma 2 multimodal/local guide](https://ai.google.dev/gemma/docs/embeddinggemma/multimodal-embeddinggemma-with-sentence-transformers)
* [llama.cpp function-calling documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
* [llama.cpp Gemma 4 history/parser implementation](https://github.com/ggml-org/llama.cpp/blob/master/common/parsers/gemma4.cpp)
* [X posts by local Gemma users](https://x.com/AYi_AInotes/status/2042292538342850921), [Gemma family note](https://x.com/ADODonoghue/status/2040031009115197774)
