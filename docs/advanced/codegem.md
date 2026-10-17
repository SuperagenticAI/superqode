# CodeGem

CodeGem is SuperQode's native Python coding harness for Google's Gemini and
Gemma families. It provides six tools and optional local EmbeddingGemma code
search. Install the released package and run it in your own project; you do
not need to clone or build SuperQode.

## Install and run local Gemma

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Ollama](https://ollama.com), then install SuperQode:

```bash
uv tool install --python 3.13 --upgrade --force superqode
superqode --version
ollama pull gemma4:12b
cd your-project
superqode harness run codegem "Explain this project and suggest one small fix" \
  --provider ollama --model gemma4:12b --working-dir .
```

CodeGem requires SuperQode 2.19.0 or later. `gemma4:12b` is the cross-platform
starting point. Apple Silicon users can substitute `gemma4:12b-mlx` when that
Ollama build is available. Install ripgrep (`rg`) and Bash for the search and
shell tools. See [Installation](../getting-started/installation.md) for the
hosted installer and platform requirements.

For an interactive session, start `superqode` in your project, open `:connect`,
choose **Connect a harness with your model**, then **CodeGem**. Choose **Local**
for Gemma with Ollama, LM Studio or llama.cpp, or **BYOK** for Gemini with your
Google API key. `:connect harness-codegem` opens the same flow directly.
For a small coding demo, ask it to read a failing test, fix the implementation,
and run the test.

Local Gemma sessions default to at most 32,768 context tokens, with smaller
output and compaction budgets for smaller contexts. Set `context_window` in
your harness configuration to use a different budget, and load compatible
servers with the same context size. Local EmbeddingGemma inference runs in a
worker thread so semantic search keeps the terminal responsive.

## Use Gemini through the Google API

Create a Gemini Developer API key in [Google AI Studio](https://aistudio.google.com/apikey).
Set the key and a model ID available to your account:

```bash
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="your-current-gemini-model"
cd your-project
superqode harness run codegem "Explain this project and suggest one small fix" \
  --provider google --model "$GEMINI_MODEL" --working-dir .
```

`GOOGLE_API_KEY` and keys saved through SuperQode's provider connection also
work. Keep keys in your environment rather than project configuration. Begin
with a small task to control usage. CodeGem uses native Gemini GenerateContent
requests and needs no additional Google SDK installation. See
[Google's key guide](https://ai.google.dev/gemini-api/docs/api-key).

## Add local EmbeddingGemma search

The ordinary `search` tool works without embeddings. To add natural-language
code retrieval, install the optional local runtime in the same tool environment:

```bash
uv tool install --python 3.13 --upgrade --force 'superqode[semantic-local]'
cd your-project
superqode-codegem-index . --provider sentence-transformers \
  --model google/embeddinggemma-2 --scope src
superqode-codegem-index . --provider sentence-transformers \
  --model google/embeddinggemma-2 --scope src \
  --query "where are requests authenticated?"
```

Use a directory that exists in your project for `--scope`, or omit it to index
the whole project. Repeat `--scope` for several directories. Indexing requires
a Git working tree, honors Git ignore rules, and stores the local SQLite index
under `.superqode/codegem`. Changed source chunks are refreshed automatically.
The default 256-dimensional vectors reduce storage; the current index cap is
10,000 chunks.

The first run downloads Google's Hugging Face weights. If Hugging Face requests
access, accept the model's terms and authenticate as directed by Hugging Face.
The encoder selects CUDA, Apple Metal (MPS), then CPU. Use `--device cpu`, `mps`,
or `cuda` to choose explicitly. After downloading, `--local-files-only` permits
offline use. This path needs no Google API key.

To use this encoder from the coding agent, save the following as `codegem.yaml`
in your project. The built-in template supplies the six tools and defaults:

```yaml
version: 1
name: codegem-local
inherits: codegem
runtime:
  config:
    embedding:
      provider: sentence-transformers
      model: google/embeddinggemma-2
      device: auto
      dimensions: 256
      scope: [src]
```

Then run:

```bash
superqode harness run codegem.yaml \
  "Use semantic search to find request authentication, then explain its flow" \
  --provider ollama --model gemma4:12b --working-dir .
```

Semantic retrieval uses the existing `search` tool, with no seventh tool.
Keep the provider, model, dimensions, and scope identical between the index
command and harness configuration to reuse the same index. Index contents and
embedding requests stay local. A Gemini coding session still sends its prompt
and selected tool results to Google's API.

### Ollama embeddings

A sufficiently recent Ollama can serve EmbeddingGemma directly, without the
`semantic-local` extra:

```bash
ollama pull embeddinggemma-2
superqode-codegem-index . --provider ollama --model embeddinggemma-2 --scope src
superqode-codegem-index . --provider ollama --model embeddinggemma-2 \
  --scope src --query "where are requests authenticated?"
```

Set `runtime.config.embedding.provider` to `ollama` and its `model` to
`embeddinggemma-2` in the configuration above. If the runtime cannot load the
model architecture, upgrade it or use the Sentence Transformers path.
An OpenAI-compatible embedding server is also supported, restricted to loopback:

```bash
superqode-codegem-index . --provider openai \
  --base-url http://127.0.0.1:8081 --model embeddinggemma-2 --scope src
```

## Use LM Studio or llama.cpp

CodeGem supports local Gemma through both servers' OpenAI-compatible endpoints.
Load your model with a Gemma-identifiable model ID and start the local server:

```bash
superqode harness run codegem "Explain this project and suggest one small fix" \
  --provider lmstudio --model gemma4-codegem-26b-q4 --working-dir .
superqode harness run codegem "Explain this project and suggest one small fix" \
  --provider llamacpp --model gemma4-codegem-26b-q4 --working-dir .
```

Default endpoints are `http://127.0.0.1:1234/v1` for LM Studio and
`http://127.0.0.1:8080/v1` for llama.cpp. Set `LMSTUDIO_HOST` or `LLAMACPP_HOST`
when your server uses another address.

For the same checksum-verified 26B-A4B QAT Q4_0 model tested across all three
runtimes, the installed download command creates the GGUF and an Ollama Modelfile:

```bash
superqode-codegem-download --directory .superqode/models/codegem --models coding
ollama create gemma4-codegem-26b-q4 -f .superqode/models/codegem/Modelfile
```

The coding GGUF is about 14.4 GB; the resumable downloader needs roughly twice
the artifact size plus 2 GB of free disk space while assembling it. Existing
files are reused only after their SHA-256 checksum matches.

For LM Studio, install its `lms` CLI and import the downloaded model:

```bash
lms import .superqode/models/codegem/gemma-4-26B_q4_0-it.gguf \
  --user-repo google/gemma-4-26B-A4B-it-qat-q4_0-gguf --hard-link -y
lms load <imported-model-key> --context-length 32768 --parallel 1 \
  --gpu max --identifier gemma4-codegem-26b-q4 -y
lms server start --port 1234 --bind 127.0.0.1
```

Replace `<imported-model-key>` with the key returned by the import. With a
recent llama.cpp build:

```bash
llama-server --model .superqode/models/codegem/gemma-4-26B_q4_0-it.gguf \
  --alias gemma4-codegem-26b-q4 --host 127.0.0.1 --port 8080 \
  --ctx-size 32768 --flash-attn on --cache-type-k q8_0 \
  --cache-type-v q8_0 --parallel 1 --gpu-layers 999 --no-webui
```

For a 32 GB GPU, start with one session and a 32K context, then measure memory
headroom before increasing context or concurrency. Weights, runtime buffers,
and KV cache all consume memory. The local compatibility tests ran on an
Apple M4 Max with 128 GB unified memory, so their throughput does not predict
performance on a 32 GB CUDA card.

## Tools, configuration, and sessions

| Tool | Purpose |
| --- | --- |
| `read` | Read files with pagination and image support |
| `write` | Write files and create parent directories |
| `edit` | Apply exact text replacements |
| `search` | Ripgrep content search, file discovery, and optional semantic retrieval |
| `python` | Execute Python in a fresh subprocess using SuperQode's interpreter |
| `bash` | Run Bash commands with the same Python environment |

Shell and Python calls default to a 60-second timeout, accept up to 300 seconds,
and return the last 16 KB of output. Larger output is retained in a temporary
file. Calls in a batch execute in order. CodeGem reads `AGENTS.md` and `GEMINI.md`
from ancestors through your working directory, with a 32 KB cap per file.

Generate an editable configuration without downloading example source files:

```bash
superqode harness init my-codegem --template codegem --output codegem.yaml
superqode harness validate codegem.yaml
```

Useful `runtime.config` settings include `tool_mode` (`auto`, `native`, or
`json` for Gemma), `max_turns`, `context_window`, `max_output_tokens`,
`temperature`, `thinking`, and `embedding`. Use `base_url` for LM Studio or
llama.cpp, `ollama_base_url` for Ollama, and native `thinking_config` for Gemini
thinking controls. Start with defaults and tune against your own coding tasks.
New model generations do not inherit guessed thinking controls or context limits.

Gemini requests leave Google's per-model default thinking level in place. Set
`model_policy.reasoning` to `low`, `medium` or `high` (or `minimal` where the
model documents it) to choose a level; unsupported levels are rejected with the
supported list. Gemini 4 Argon requests send its documented `medium` default.
Argon requests omit `temperature`, `top_p`, `top_k` and `candidate_count`,
which Google says are ignored for Gemini 4; configured values are dropped with
a one-time warning. `thinkingBudget` is never sent to Gemini 4 or alongside
`thinkingLevel`; when a raw `thinking_config` has both, the level is kept.
The deprecated `gemini-3.7-flash` and `gemini-3.5-flash` IDs are mapped to
`gemini-3.8-flash` and `gemini-3.6-flash` with a notice.
Gemini requests retry HTTP 429, 5xx and transient network
errors up to `max_attempts` (default 4) with exponential backoff from
`retry_initial_delay` (default 1 second), honouring Google's retry delay up to
`retry_max_delay` (default 60 seconds). Each retry is logged on the
`superqode.codegem` logger. A malformed function call or an empty response is
retried once.

For Gemini 4 Argon, CodeGem defaults to a 20 minute `timeout` and a 32,768
token `max_output_tokens` (the non-streaming per-request cap), and follows long decode continuation tokens. A reply
that reaches `max_output_tokens` with a continuation token resumes with a
doubled limit up to `max_output_tokens_ceiling` (default 131,072 for Argon).
Raise or lower the ceiling to control spend.

Conversations live in `.superqode/codegem/sessions/`. Reuse `--session <id>` to
continue a headless run. Start a fresh session when changing models, especially
with Gemini signed history. Model text is emitted after a complete response;
token-by-token provider streaming is not available in this release.

Tools run with the host process's permissions. CodeGem does not provide OS
isolation or approval prompts, and rejects unsupported sandbox and approval
policies. Review tasks before running them in projects you trust.

## Tested scope and troubleshooting

Local validation covered two coding smoke tasks on the same Gemma 4 26B-A4B
QAT Q4_0 artifact through Ollama, LM Studio, and llama.cpp. EmbeddingGemma retrieval
was checked on six labeled queries. These are compatibility checks, not broad
model rankings. Gemini has request/response contract tests; a successful live
API smoke test is still pending a valid key.

- **Command missing:** upgrade SuperQode to 2.19.0 or later and check that uv's
  tool binary directory is on `PATH`.
- **Embedding runtime missing:** reinstall with `superqode[semantic-local]`
  using the command above; installing it in a separate Python environment will
  not add it to SuperQode's environment.
- **Model architecture unsupported:** update the serving runtime or use the
  direct Sentence Transformers encoder for embeddings.
- **Model or server unavailable:** check the model ID and confirm the local
  server is listening at the configured endpoint.
- **Memory pressure:** reduce context and keep one concurrent session before
  trying a smaller quantized model.

Use the [graded benchmark runner](benchmark-runner.md) to compare coding results
with your models and repositories.
