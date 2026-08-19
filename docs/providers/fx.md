# fx

fx is Vercel Labs' experimental native coding agent. SuperQode connects to its
ACP server, so fx keeps its own loop, tools, permissions, skills, and sessions
while SuperQode provides the terminal, switching, and normalized events.

fx is Apache-2.0 and still experimental. Every model request goes through
[Vercel AI Gateway](https://vercel.com/ai-gateway). There is no local-model
path and no SuperQode BYOK provider picker for this agent. The Open row
accepts only `AI_GATEWAY_API_KEY`.

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
credit checks. Models are billed as that team's AI Gateway credits, not as a
coding-agent seat.

Verify that SuperQode can discover it:

```bash
superqode agents show fx
superqode agents doctor fx
```

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
model picker.

## Choose The fx Route

| Goal | Route |
| --- | --- |
| Use fx on your Vercel login | `:connect fx` |
| Use fx with `AI_GATEWAY_API_KEY` | `:connect fx-key` |
| Attach the same ACP server after `fx setup` | `:connect acp fx` |

fx is not a SuperQode runtime. SuperQode does not replace its loop, and it
does not accept Ollama, vLLM, or a third-party provider API key as a model
source.

## Related Documentation

- [Connection Methods and Vendors](../concepts/modes.md)
- [Agent Runtimes](../runtimes.md)
- [ACP Agents](acp.md)
- [fx documentation](https://fx.sh/docs)
