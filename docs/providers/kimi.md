# Kimi K3

SuperQode supports **Kimi K3** through Moonshot AI's first-party, global,
OpenAI-compatible API. SuperQode owns the coding harness, tools, approvals,
workspace access, and session history; Moonshot provides model inference.

This page documents both the K3 API and the exact subset exposed by SuperQode.
It also separates the pay-as-you-go Moonshot API from the Kimi Code subscription
route, because their endpoints, credentials, and model IDs are not interchangeable.

## Choose the correct route

| Route | Endpoint | K3 model ID | Billing | Who owns the agent loop? |
|-------|----------|-------------|---------|--------------------------|
| SuperQode + Moonshot API | `https://api.moonshot.ai/v1` | `kimi-k3` | Moonshot platform pay-as-you-go | SuperQode |
| Kimi Code subscription, OpenAI-compatible | `https://api.kimi.com/coding/v1` | `k3` | Kimi Code membership quota | Kimi CLI or another supported coding client |
| Kimi Code subscription, Anthropic-compatible | `https://api.kimi.com/coding/` | `k3` | Kimi Code membership quota | The connected coding client |
| Kimi CLI over ACP | Local process: `kimi acp` | Chosen by Kimi CLI | Kimi CLI configuration | Kimi CLI |

The built-in `moonshot` provider and `kimi-coding` family harness use the first row.
Do not put a Kimi Code membership token in `MOONSHOT_API_KEY` or change
`MOONSHOT_API_BASE` to the subscription endpoint: the subscription service uses a
different model namespace and client contract.

## Setup

Create a key in the [Moonshot AI platform](https://platform.kimi.ai/), then set
either supported environment variable:

```bash
export MOONSHOT_API_KEY=your-platform-api-key
# Equivalent alias:
# export KIMI_API_KEY=your-platform-api-key
```

Inspect the configuration without spending model quota, then connect:

```bash
superqode connect setup moonshot
superqode connect byok moonshot kimi-k3
```

In the TUI:

```text
:connect moonshot
:connect moonshot/kimi-k3
```

An approved enterprise proxy can override the endpoint:

```bash
export MOONSHOT_API_BASE=https://your-approved-proxy.example/v1
```

The default is `https://api.moonshot.ai/v1`. The provider uses the standard
`/chat/completions` request shape through SuperQode's OpenAI-compatible gateway.

## Kimi family coding harness

Run the maintained family preset directly. It currently resolves its explicit
stable channel to K3, so no duplicate `--provider` or `--model` flags are needed:

```bash
superqode --harness kimi-coding -p "Review this repository and fix the failing tests"
```

In the TUI, enter `:harness` to browse maintained families with the arrow keys, or
activate it directly:

```text
:harness use kimi-coding
```

Or create a project-owned harness file that can be inspected and versioned:

```bash
superqode harness init kimi-project --template kimi-coding --output harness.yaml
superqode harness inspect --spec harness.yaml --json
superqode --harness harness.yaml -p "Implement the requested feature"
```

The generated file freezes the current exact route. Use `kimi-k3-coding` when you
explicitly want the built-in K3-pinned compatibility preset. When Moonshot ships a
later model, SuperQode can promote the validated `kimi-coding` stable route without
renaming the harness or changing the pinned K3 preset. Pinned presets remain
directly resolvable and appear under `:harness all`, but stay out of the recommended
default picker.

The preset provides:

| Setting | Value |
|---------|-------|
| Primary model | `moonshot/kimi-k3` |
| Fallback 1 | `moonshot/kimi-k2.7-code-highspeed` |
| Fallback 2 | `moonshot/kimi-k2.7-code` |
| Context window | 1,048,576 tokens |
| Reasoning | `max` |
| Parallel tools | Enabled |
| Session history limit | 40 turns |
| Temperature | Omitted; K3 applies its fixed value |
| Cache strategy | Stable harness prefix and reasoning level |

Fallback occurs only for retryable model-availability failures. It does not make
requests free, and a fallback model may have a smaller context window.

## Feature support matrix

The status column describes the current SuperQode integration, not merely what the
upstream API advertises.

| K3 capability | Moonshot API | SuperQode status | Notes |
|---------------|--------------|------------------|-------|
| Text chat | Yes | **Supported** | Non-streaming and streaming paths are covered. |
| 1M-token context | Yes | **Supported** | Catalog and K3 harness use 1,048,576 tokens. Actual usable input is reduced by output, system prompt, tools, and history. |
| Always-on reasoning | Yes | **Supported** | SuperQode maps any requested K3 reasoning level to the only current API value, `max`. |
| Streamed reasoning | Yes | **Supported** | `reasoning_content` is kept separate from final answer text. |
| Multi-turn reasoning replay | Required for tool conversations | **Supported** | Assistant reasoning and tool calls are preserved when tool results are sent back. |
| Custom function tools | Yes | **Supported** | SuperQode exposes its native workspace/tool registry. |
| `tool_choice` | Yes | **Gateway supported** | Normal harness runs let the model choose tools; lower-level callers can pass an explicit choice. |
| Parallel tool calls | Yes | **Supported** | Enabled by the K3 harness. Permission and sandbox rules still apply. |
| Image input | Yes | **Supported for local images** | `view_image` supplies a base64 data URL. K3's API does not accept a public image URL directly. |
| Video input | Yes | **Not first-class** | SuperQode does not currently provide a K3 video upload or `ms://` file workflow. |
| JSON object output | Yes | **Prompt/validation supported** | Headless `--output-schema` validates and retries. It does not yet use K3's native strict `json_schema` response format. |
| Strict JSON Schema | Yes | **Not mapped end-to-end** | Available in the upstream API, but the high-level SuperQode output-schema path is provider-neutral and prompt based. |
| Partial Mode | Yes | **No dedicated surface** | SuperQode does not currently set the K3 assistant message field `partial: true`. |
| Dynamic tool loading | Yes | **Not integrated** | The K3 harness sends the selected SuperQode tool definitions rather than Moonshot's dynamic tool catalog protocol. |
| Automatic context caching | Yes | **Transparent** | Moonshot caches stable prefixes automatically; no cache ID is required. |
| Kimi Formula tools | Yes, subject to availability | **Not integrated** | SuperQode uses its own tools. Moonshot currently advises against relying on its Formula web-search tool while it is being updated. |
| Low/high/max effort selection | Subscription route offers multiple levels | **API K3: max only** | The pay-as-you-go `kimi-k3` API currently accepts only `max`. |
| Open weights | Announced | **Not a local preset yet** | Moonshot says full K3 weights will be released by July 27, 2026. A hosted API preset must not be treated as a local-serving recipe. |

## Reasoning, streaming, and tool history

K3 is always a thinking model on the Moonshot platform API. The current request
contract is:

```json
{
  "model": "kimi-k3",
  "reasoning_effort": "max"
}
```

Do not send the older K2-style `thinking` field. SuperQode normalizes `low`,
`medium`, `high`, or `max` to K3's currently supported `max`, which lets a shared
harness run without producing an invalid K3 request.

During streaming, K3 returns chain-of-thought data in `reasoning_content` and the
answer in `content`. SuperQode preserves that separation. When K3 calls a tool,
SuperQode also replays the complete assistant turn, including reasoning and tool
calls, before the tool-result message. This is required for reliable multi-turn K3
tool use.

Reasoning content is model-generated data. Do not treat it as an audit log, a
security boundary, or a guaranteed explanation of how the answer was produced.

## Fixed sampling and output limits

Moonshot currently fixes the K3 sampling contract:

| Parameter | K3 value |
|-----------|----------|
| `temperature` | `1.0` |
| `top_p` | `0.95` |
| `n` | `1` |
| `presence_penalty` | `0` or omitted |
| `frequency_penalty` | `0` or omitted |
| `max_completion_tokens` default | 131,072 |
| `max_completion_tokens` maximum | 1,048,576 |

The K3 request shaper removes conflicting sampling overrides and translates
SuperQode's neutral `max_tokens` value to `max_completion_tokens`. This is why the
K3 harness intentionally leaves temperature unset.

Very large completion budgets can be expensive and leave less space for input in
the overall context window. Set the smallest practical task budget for unattended
runs.

## Context caching

Moonshot automatically caches matching prompt prefixes. There is no explicit cache
creation call. Cache hits are most likely when all of the following remain stable:

- The system prompt and harness
- Tool definitions and their order
- Earlier conversation messages
- Model and reasoning effort

Changing the model or reasoning effort invalidates the relevant cache prefix. The
K3 harness's extended history is designed to keep a stable session prefix, but
Moonshot, not SuperQode, decides whether any request receives cached pricing.

## Vision and video details

The upstream K3 API accepts text, images, and video. Image data can be supplied as
base64 or through Moonshot's `ms://` file mechanism; a public HTTP image URL is not
supported by K3's documented request contract.

SuperQode's `view_image` tool converts a local image into a base64 multimodal user
message, so local screenshots and repository images work with K3. There is no
first-class SuperQode video attachment or Moonshot file-upload command yet. Use a
direct Moonshot API client when a task requires native video input.

## Structured output and Partial Mode

Moonshot supports strict JSON Schema output with an OpenAI-style
`response_format` object. That upstream capability is represented in the model
catalog, but it is not yet wired to SuperQode's provider-neutral output-schema
shortcut.

SuperQode headless runs can still request, parse, validate, and retry JSON output:

```bash
superqode --provider moonshot --model kimi-k3 \
  --output-schema result.schema.json \
  -p "Inspect the repository and return the requested result"
```

That workflow uses prompt instructions plus local validation. It must not be
described as native K3 constrained decoding.

K3 Partial Mode lets a direct API caller prefill an assistant message and ask the
model to continue it by setting `partial: true`. SuperQode does not expose a
dedicated Partial Mode setting. Ordinary streamed partial chunks in the TUI are a
different concept.

## Tools and dynamic tool loading

K3 supports ordinary custom function tools and required `tool_choice` requests.
The K3 harness uses SuperQode's own tools so that filesystem access, shell commands,
approvals, and sandbox behavior remain under SuperQode policy.

Moonshot also documents dynamic tool loading, where tool descriptions are supplied
through its system-message protocol only when needed. SuperQode currently sends the
tools selected by the harness in the normal request tool array. Keep a harness's
tool set focused if prefix size or cache stability matters.

Moonshot's Formula environment is a separate hosted tool system. Formula tools are
not aliases for SuperQode tools and are not enabled by the K3 preset.

## Model catalog

| Model | Context | Uncached input / output per 1M tokens | Typical use |
|-------|---------|---------------------------------------|-------------|
| `kimi-k3` | 1,048,576 | $3.00 / $15.00 | Long-horizon coding, vision, large repositories, agent workflows |
| `kimi-k2.7-code-highspeed` | 262,144 | $0.95 / $4.00 | Faster iterative coding loops |
| `kimi-k2.7-code` | 262,144 | $0.95 / $4.00 | Stable repository coding |
| `kimi-k2.6` | 262,144 | $0.95 / $4.00 | General multimodal and coding tasks |

K3 cached input is listed by Moonshot at **$0.30 per 1M tokens**. Prices can change;
check the [official pricing page](https://platform.kimi.ai/docs/pricing/chat) before
a large or unattended run. SuperQode's catalog records the uncached input price.

Moonshot's model list says the original K2 model is discontinued, and K2.5 and
`moonshot-v1` are unavailable to new users with sunset scheduled for August 31,
2026. New integrations should use the IDs above instead of legacy examples found
in older tutorials.

## Kimi Code subscription and ACP

Kimi Code membership is separate from Moonshot platform API billing. On that route,
the K3 model ID is `k3`, not `kimi-k3`. Available context and reasoning levels can
also depend on the membership tier: Kimi's documentation lists 256K for Moderato
and 1M for Allegretto and above, with `low`, `high`, and `max` K3 effort choices.
Selecting no thinking routes subscription traffic to K2.6 rather than disabling
thinking in K3.

If Kimi CLI is installed and configured, SuperQode can act as its ACP client:

```bash
uv tool install kimi-cli --no-cache
superqode connect acp kimi
```

Or from the TUI:

```text
:connect acp kimi
```

This starts `kimi acp`. Kimi CLI then owns model selection, tools, authentication,
and its agent loop. The `kimi-coding` SuperQode harness is not applied to an ACP
session.

See the [Kimi Code documentation](https://www.kimi.com/code/docs/en/) for current
membership setup and the [ACP provider guide](acp.md) for SuperQode's ACP boundary.

## Open weights and local serving

Moonshot announced that full K3 model weights will be available by July 27, 2026.
It also describes K3 as a 2.8-trillion-parameter mixture-of-experts model and
indicates that production deployment is a multi-node, data-center-scale task.

SuperQode does not currently ship an Ollama, vLLM, SGLang, or local K3 preset. The
`kimi-coding` and `kimi-k3-coding` target Moonshot's hosted global API. Add a local preset
only after weights, a compatible serving stack, supported request semantics, and a
realistic hardware topology are published and verified.

## Benchmark claims

K3 is a frontier-class model, but the launch material does **not** establish that it
beats every closed model on every benchmark. Moonshot's own aggregate comparison
places it behind the named Fable 5 and GPT 5.6 Sol systems overall while showing
strong results on several coding, agentic, and visual tasks. Compare individual
benchmarks, tool settings, reasoning budgets, and evaluation dates instead of
turning a mixed benchmark table into a universal ranking.

## Troubleshooting

### Authentication fails

- Confirm that the credential is a Moonshot **platform API** key.
- Use `MOONSHOT_API_KEY` or `KIMI_API_KEY` for the SuperQode provider.
- Do not use a Kimi Code membership token with `api.moonshot.ai`.
- If both variables are set, remove stale values and keep one source of truth.

### Model not found

- The pay-as-you-go model is `kimi-k3`.
- The Kimi Code subscription model is `k3`.
- Confirm that a proxy preserves the `/v1` base path.

### Invalid reasoning or sampling parameter

- K3 platform API reasoning is currently `max` only.
- Remove the legacy `thinking` field.
- Let the K3 harness omit temperature and penalties.
- Upgrade SuperQode if an older installation still forwards incompatible sampling
  values.

### Image request fails

- Use a local image through `view_image` so SuperQode sends base64 data.
- Do not pass a public image URL directly to K3.
- Native video and `ms://` uploads require a direct API workflow for now.

### Cache usage is lower than expected

- Keep the same model, reasoning level, system prompt, harness, and tool ordering.
- Avoid rewriting early conversation turns.
- Remember that cache admission and reporting are controlled by Moonshot.

### Output is too long or costly

- Lower the task or completion budget rather than changing K3's fixed sampling.
- Split independent work into smaller sessions only when losing the shared prefix is
  worth the cache tradeoff.
- Check platform usage and current pricing before unattended runs.

## Official references

- [Kimi K3 technical report and launch post](https://www.kimi.com/fr-fr/blog/kimi-k3)
- [Kimi K3 API quickstart](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart)
- [Moonshot model list](https://platform.kimi.ai/docs/models)
- [Moonshot chat pricing](https://platform.kimi.ai/docs/pricing/chat)
- [Kimi Code documentation](https://www.kimi.com/code/docs/en/)
- [Kimi Code model configuration](https://www.kimi.com/code/docs/en/kimi-code/models.html)
