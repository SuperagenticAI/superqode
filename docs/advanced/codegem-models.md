# CodeGem recommended models

This guide helps you choose a Gemini or Gemma model for CodeGem and gives a
starting configuration for each. Every snippet is a `runtime` and
`model_policy` fragment for a CodeGem harness file. Pass the model with
`--model` and the provider with `--provider` when you run it:

```bash
superqode harness run codegem "Fix the failing test in tests/test_parser.py" \
  --provider google --model gemini-3.8-flash --working-dir .
```

All keys below are read by CodeGem from `runtime.config`, except
`model_policy.reasoning`, which picks a thinking level. See
[CodeGem](codegem.md) for installation and the full list of settings.

## Quick guide

| Job | Model | Provider |
| --- | --- | --- |
| Hard, long-horizon coding and large refactors | `gemini-4-argon` | `google` |
| Complex reasoning over large codebases | `gemini-3.1-pro-preview` | `google` |
| Agentic work that leans on custom tools | `gemini-3.1-pro-preview-customtools` | `google` |
| Everyday coding and agentic execution | `gemini-3.8-flash` or `gemini-3.6-flash` | `google` |
| High-volume subagent and quick tasks | `gemini-3.5-flash-lite` or `gemini-3.1-flash-lite` | `google` |
| Trying open Gemma 4 without local hardware | `gemma-4-31b-it` or `gemma-4-26b-a4b-it` | `google` |
| Private, offline coding on your machine | Gemma 4 or Gemma 3 | `ollama`, `vllm`, `llamacpp`, `lmstudio` |

## Defaults that apply to every Gemini model

- `stream` is `true`. Replies arrive through `streamGenerateContent` and text is
  shown live. Set `stream: false` for one `generateContent` request per turn.
- No thinking level is sent unless the model has a required default (Argon
  sends `medium`) or you set `model_policy.reasoning` or `thinking_config`, so
  Google's per-model default applies.
- `max_output_tokens` defaults to 32,768, except Argon while streaming, which
  defaults to 65,536.
- Requests retry HTTP 429, 5xx and network errors up to `max_attempts` (default
  4), with `retry_initial_delay` (default 1 second) and `retry_max_delay`
  (default 60 seconds). Streaming retries happen only before the first chunk.
- Long replies follow continuation tokens for up to `max_continuation_hops`
  (default 64) requests. A dropped stream resumes from its last checkpoint up to
  `max_stream_resumes` (default 8) times.

## Gemini 4 Argon

Pick Argon for the hardest work: multi-file changes, long debugging sessions
and tasks that need sustained reasoning. Access depends on your account.

CodeGem gives Argon a 20 minute `timeout`, a 65,536 token streaming output
default (32,768 with `stream: false`), and resumes a reply that hits
`max_output_tokens` with a doubled limit up to `max_output_tokens_ceiling`
(default 131,072). Google says sampling parameters are ignored for Gemini 4, so
`temperature`, `top_p` and `top_k` are dropped with a warning. Thinking levels
are `low`, `medium` (default) and `high`.

```yaml
runtime:
  backend: codegem
  config:
    stream: true
    max_output_tokens_ceiling: 131072
    timeout: 1200
model_policy:
  reasoning: high
```

Lower `max_output_tokens_ceiling` to cap the spend on a single reply.

## Gemini 3.1 Pro Preview

Use `gemini-3.1-pro-preview` for complex reasoning, research across a large
codebase and careful reviews. It has a 1,048,576 token input limit and a
65,536 token output limit. Its default thinking level is `high`; `low` and
`medium` are also documented.

```yaml
runtime:
  backend: codegem
  config:
    max_output_tokens: 32768
model_policy:
  reasoning: high
```

## Gemini 3.1 Pro Preview for custom tools

`gemini-3.1-pro-preview-customtools` is a separate preview endpoint. Google
describes it as "better at prioritizing" custom tools, which suits CodeGem's
six-tool loop when the standard model reaches for prose instead of a tool call.
It shares Gemini 3.1 Pro's limits, thinking levels and prices.

```yaml
runtime:
  backend: codegem
  config:
    max_output_tokens: 32768
model_policy:
  reasoning: medium
```

## Gemini 3.8 Flash and 3.6 Flash

`gemini-3.8-flash` is the default choice for everyday coding and agentic
execution. `gemini-3.6-flash` is the stable alternative. Both have a default
thinking level of `medium`; 3.8 Flash documents `low`, `medium` and `high`, and
3.6 Flash adds `minimal`. Both keep Google's default temperature of 1.0.

```yaml
runtime:
  backend: codegem
  config:
    stream: true
    max_output_tokens: 32768
model_policy:
  reasoning: medium
```

Saved configurations naming the deprecated `gemini-3.7-flash` or
`gemini-3.5-flash` are mapped to `gemini-3.8-flash` and `gemini-3.6-flash` with
a notice.

## Gemini 3.5 Flash-Lite and 3.1 Flash-Lite

Use the Flash-Lite models for subagents, high-volume and quick tasks.
`gemini-3.5-flash-lite` defaults to `minimal` thinking and documents
`minimal`, `low`, `medium` and `high`.

```yaml
runtime:
  backend: codegem
  config:
    max_output_tokens: 8192
model_policy:
  reasoning: minimal
```

`gemini-3.1-flash-lite` has a 1,048,576 token input limit and a 65,536 token
output limit. CodeGem has no documented thinking levels for it, so leave
thinking at Google's default, or pass a raw value that Google's model page
shows (its example uses `thinking_level = "high"`):

```yaml
runtime:
  backend: codegem
  config:
    max_output_tokens: 8192
    thinking_config:
      thinkingLevel: HIGH
```

## Gemma 4 31B and 26B A4B on the Gemini API

`gemma-4-31b-it` and `gemma-4-26b-a4b-it` run open Gemma 4 weights on Google's
servers. They suit experiments and comparisons with a local setup. CodeGem
accepts only these Gemini API IDs on the `google` provider, not Ollama tags.

Google documents thinking as `"high"` for enabled or `"minimal"` for disabled.
Set `thinking`, or `model_policy.reasoning` to `high` or `minimal`; with
neither, no level is sent. Sampling uses temperature 1.0, top_p 0.95 and top_k
64 unless you set any of them. No output limit is published for these models
on the Gemini API, so `maxOutputTokens` is sent only when you set
`max_output_tokens`.

```yaml
runtime:
  backend: codegem
  config:
    thinking: true
    stream: true
```

## Local Gemma 4 and Gemma 3

Gemma 4 uses native tool calls and a system role. Gemma 3 has no system role
and uses JSON tool mode; CodeGem places the system prompt at the start of the
first user turn. Local defaults:

- `context_window` defaults to at most 32,768 tokens, and `max_output_tokens`
  to the smaller of 8,192 and a quarter of the context.
- Sampling uses temperature 1.0, top_p 0.95 and top_k 64 only when none of the
  three is set. If you set one, only the values you set are sent.
- Thinking is off by default for Gemma 4. Set `thinking: true` (or
  `model_policy.reasoning` to any value other than `off`) to turn it on.
- Gemma 4 tool images stay inside the tool message. Set
  `tool_images_in_tool_message: false` to send them in a following user turn.
- `tool_mode` is `auto`; set `native` or `json` to force one.

### Ollama

```bash
ollama pull gemma4:12b
superqode harness run codegem "Explain this project" \
  --provider ollama --model gemma4:12b --working-dir .
```

```yaml
runtime:
  backend: codegem
  config:
    context_window: 32768
    max_output_tokens: 8192
    thinking: false
    tool_images_in_tool_message: true
```

Ollama context advice: CodeGem sends `context_window` to Ollama as `num_ctx`
on every request, so that value decides the KV cache Ollama allocates. Keep it
at 32,768 on a laptop, and raise it only after checking memory headroom, since
a model's maximum context is not a sensible default allocation. Set
`ollama_base_url` or `OLLAMA_HOST` when Ollama is not on
`http://localhost:11434`. For Gemma 3, use the same keys without `thinking`
and `tool_images_in_tool_message`:

```yaml
runtime:
  backend: codegem
  config:
    context_window: 32768
    tool_mode: json
```

### vLLM

Start vLLM with the Gemma 4 tool and reasoning parsers and an explicit context
size. CodeGem reads that size back from `/v1/models` (`max_model_len`) when
`context_window` is unset:

```bash
vllm serve google/gemma-4-31B-it --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser gemma4 \
  --reasoning-parser gemma4 \
  --chat-template examples/tool_chat_template_gemma4.jinja
superqode harness run codegem "Explain this project" \
  --provider vllm --model google/gemma-4-31B-it --working-dir .
```

```yaml
runtime:
  backend: codegem
  config:
    base_url: http://localhost:8000/v1
    thinking: true
```

Thinking is sent as `chat_template_kwargs.enable_thinking`. Set `VLLM_HOST`
or `base_url` for another address.

### llama.cpp

CodeGem reads the context size from llama.cpp's `/props`
(`default_generation_settings.n_ctx`) when `context_window` is unset, so set
it with `--ctx-size` when you start the server:

```bash
llama-server --model .superqode/models/codegem/gemma-4-26B_q4_0-it.gguf \
  --alias gemma4-codegem-26b-q4 --host 127.0.0.1 --port 8080 \
  --ctx-size 32768 --parallel 1
superqode harness run codegem "Explain this project" \
  --provider llamacpp --model gemma4-codegem-26b-q4 --working-dir .
```

```yaml
runtime:
  backend: codegem
  config:
    base_url: http://localhost:8080/v1
    thinking: false
```

LM Studio works the same way with `--provider lmstudio`, `LMSTUDIO_HOST` and a
default of `http://localhost:1234/v1`. CodeGem does not read a context size from LM Studio, so
set `context_window` to match the loaded model.

## Cost notes

CodeGem estimates cost from the Standard paid-tier prices in its catalog, per
1M tokens, taken from [Google's pricing page](https://ai.google.dev/gemini-api/docs/pricing).
Thinking tokens are billed as output. Estimates are not a billing statement.

| Model | Input | Output | Cached input | Scheduled change |
| --- | --- | --- | --- | --- |
| `gemini-4-argon` | $2.00 | $10.00 | $0.10 | From 1 December 2026: $4.00, $20.00, $0.20 |
| `gemini-3.8-flash` | $0.75 | $3.75 | $0.075 | From 1 January 2027: $1.50, $7.50, $0.15 |
| `gemini-3.6-flash` | $0.75 | $3.75 | $0.075 | From 1 January 2027: $1.50, $7.50, $0.15 |
| `gemini-3.5-flash-lite` | $0.30 | $2.50 | $0.03 | None |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | $0.025 | None |
| `gemini-3.1-pro-preview` | $2.00 | $12.00 | $0.20 | None |
| `gemini-3.1-pro-preview-customtools` | $2.00 | $12.00 | $0.20 | None |
| `gemma-4-31b-it`, `gemma-4-26b-a4b-it` | Free tier only | | | None |

Gemini 3.1 Pro prompts over 200,000 tokens use the long-context prices: $4.00
input, $18.00 output and $0.40 cached input. The 3.1 Flash-Lite input price is
for text, image and video; audio input and context-cache storage are not
included in the estimates. Local Gemma has no API cost.

## Default changes to know about

- Gemini replies stream by default. Set `stream: false` for the previous
  single-request behaviour.
- Argon's default output limit is 65,536 tokens while streaming.
- Local Gemma 4 thinking is off by default, matching the Gemma 4 chat template
  and Ollama. Set `thinking: true` to restore it.
- Gemma 3 uses temperature 1.0 instead of 0.2, and setting any of
  `temperature`, `top_p` or `top_k` now sends only the values you set.
- Gemma 4 tool images stay in the tool message instead of a separate user turn.
- Tool results are paired by `tool_call_id` and sent in call order.
- Cached tokens are charged at the published cache rates, and the
  `gemini-3.6-flash` price is $0.75 input and $3.75 output.
