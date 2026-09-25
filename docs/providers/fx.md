# fx

fx is Vercel Labs' experimental native coding agent. SuperQode connects to its
ACP server, so fx keeps its own loop, tools, permissions, skills, and sessions
while SuperQode provides the terminal, switching, and normalized events.

fx is Apache-2.0 and still experimental. By default, model requests go through
[Vercel AI Gateway](https://vercel.com/ai-gateway) on a Vercel login or
`AI_GATEWAY_API_KEY`. Separately, fx (>= 0.0.11) can use **custom OpenAI Chat
Completions connections** that you configure in Fx itself. SuperQode does not
inject models into Fx's loop and does not write Fx settings.

## Two local paths

| Path | How you connect | Who talks to the model |
| --- | --- | --- |
| **A. SuperQode-native local engines** | `:connect ollama`, `:connect lmstudio`, `:connect mlx`, … or `superqode local …` | SuperQode's loop and gateway |
| **B. Fx ACP with Fx custom connections** | `:connect fx` (or `:connect fx-key` / `:connect acp fx`) after you configure Fx | Fx's loop; endpoint comes from `~/.fx/settings.json` |

Use path A when you want SuperQode discovery, smoke, MLX, airplane mode, and
local doctor tooling. Use path B when you want Fx's agent loop and permissions
against a local or OpenAI-compatible server that **Fx** is configured to call.

Preview note: Fx's configurable model connections are still documented as a
preview. Verify the active endpoint with:

```bash
fx status --json
```

Confirm `provider_endpoint` matches the server you intended. See
[Custom model connections](https://fx.sh/docs/configure-fx/custom-model-connections)
and the [fx changelog](https://fx.sh/changelog) (v0.0.11+).

## Install And Authenticate

```bash
curl -fsSL https://fx.sh/setup.sh | bash
fx login
```

`fx login` opens the Vercel authorization flow and stores the session in
`~/.fx/auth.json`. SuperQode does not copy that token. On a headless machine,
set `FX_NO_OPEN_BROWSER=1` so the authorization URL is printed instead of
opened.

The signed-in Vercel team scopes AI Gateway requests, the model catalog, and
credit checks for Gateway routes. Models on that path are billed as that team's
AI Gateway credits, not as a coding-agent seat.

Verify that SuperQode can discover it:

```bash
superqode agents show fx
superqode agents doctor fx
```

`agents doctor fx` is read-only. When `~/.fx/settings.json` defines custom
`providers` entries, doctor reports their names as a hint. SuperQode never
writes or rewrites that file.

## Configure Fx custom connections (path B)

Put connection definitions in the top level of your private
`~/.fx/settings.json` (not a repository `.fx.json`). Example for Ollama:

```json
{
  "provider": "local",
  "providers": {
    "local": {
      "protocol": "openai-chat-completions",
      "base_url": "http://localhost:11434/v1",
      "auth": { "type": "none" },
      "model_metadata": {
        "qwen2.5:1.5b": {
          "context_window": 32768,
          "max_output_tokens": 2048,
          "supports_tool_use": true
        }
      }
    }
  },
  "models": {
    "local": "qwen2.5:1.5b"
  }
}
```

Select and verify:

```bash
fx provider local
fx status --json
FX_PROVIDER=local fx ask "Read README.md and summarize this project"
```

Or for one process without rewriting the saved selection:

```bash
FX_PROVIDER=local FX_MODEL=qwen2.5:1.5b fx acp
```

Then attach from SuperQode with `:connect fx`. SuperQode still does not open a
local engine picker for this agent; configure the connection in Fx first.

## TUI Commands

| Command | What it does |
| --- | --- |
| `:fx` | Show install and Vercel-login readiness |
| `:fx connect` | Attach fx over ACP (same as `:connect fx`) |
| `:fx login` | Run Vercel's `fx login` after confirmation |
| `:fx status` | Same readiness screen as `:fx` |
| `:fx help` | Usage |

## Connect From The TUI

Use the Subscriptions connection:

```text
:connect fx
```

fx also appears in the unified Harness Switcher:

```text
:harness
:harness switch fx
```

fx manages its own threads. `:harness switch fx --fork` is rejected; connect
and continue inside fx.

The ACP catalog stays available for scripts and the same attach:

```text
:connect acp fx
```

Headless:

```bash
superqode --connect fx --print "summarize this repository"
```

A leftover `AI_GATEWAY_API_KEY` is ignored on the Subscriptions route so the
session stays on `fx login`. Spend that key on the Open row instead:

```text
:connect fx-key
```

`:connect fx-key` asks for `AI_GATEWAY_API_KEY` (or `fx setup`) and injects
it into the `fx acp` child only. It does not open SuperQode's local or BYOK
model picker, and it does not configure Fx custom connections for you.

## Choose The fx Route

| Goal | Route |
| --- | --- |
| Use fx on your Vercel login (Gateway, or Fx custom connection if selected in Fx) | `:connect fx` |
| Use fx with `AI_GATEWAY_API_KEY` | `:connect fx-key` |
| Attach the same ACP server after `fx setup` | `:connect acp fx` |
| Run Ollama/LM Studio/MLX under SuperQode's own loop | `:connect ollama` / `lmstudio` / `mlx` / … (path A) |

fx is not a SuperQode runtime. SuperQode does not replace its loop. For local
or third-party OpenAI-compatible models **through fx**, configure Fx's custom
connections in `~/.fx/settings.json` (path B). For SuperQode-native local
engines, use path A instead of expecting SuperQode to push models into Fx.

## SuperQode engines vs Fx custom connections

| Capability | SuperQode-native engines (path A) | Fx custom connections (path B) |
| --- | --- | --- |
| Discovery | `superqode local …`, engine doctor, live `/v1/models` where supported | You name models in Fx `model_metadata`; Fx does not auto-discover from the endpoint |
| Smoke / warmup | `superqode local smoke`, TUI warmup | Configure and verify with `fx status --json` |
| MLX | First-class `:connect mlx` / `mlx_lm.server` | Any OpenAI Chat Completions server Fx can reach (including a local OpenAI-compatible wrapper) |
| Airplane / offline | SuperQode local airplane tooling | Fx connection with no Gateway requirement when `auth.type` is `none` (or bearer from env) |
| ACP attach | N/A (SuperQode owns the loop) | `:connect fx` / `fx acp`; Fx owns the loop |
| Who configures the endpoint | SuperQode provider env / connect flow | User edits `~/.fx/settings.json`; SuperQode read-only doctor hints only |

See also [Local Providers](local.md).

## Related Documentation

- [Local Providers](local.md)
- [Connection Methods and Vendors](../concepts/modes.md)
- [Agent Runtimes](../runtimes.md)
- [ACP Agents](acp.md)
- [fx documentation](https://fx.sh/docs)
- [fx custom model connections](https://fx.sh/docs/configure-fx/custom-model-connections)
- [fx changelog](https://fx.sh/changelog)
