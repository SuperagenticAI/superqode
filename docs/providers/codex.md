# OpenAI Codex

SuperQode connects to Codex through the optional Codex SDK runtime, Codex over
ACP, or the OpenAI BYOK provider. The routes differ in authentication and
harness ownership.

## Connection routes

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Codex SDK | `:connect codex` | Local Codex or ChatGPT login | Codex runtime |
| Codex ACP | `:connect acp codex` | Local Codex CLI login | Codex CLI agent |
| OpenAI BYOK | `:connect byok openai <model>` | `OPENAI_API_KEY` | SuperQode |

The SDK and ACP routes use Codex as the executing coding agent. The BYOK route
uses the SuperQode harness and calls an OpenAI model directly.

## Codex SDK route

Install the optional runtime and complete the Codex login:

```bash
uv tool install "superqode[codex-sdk]"
codex login
```

Connect in the TUI:

```text
:connect codex
```

Run a headless task:

```bash
superqode --connect codex --print "review the current repository"
```

SuperQode selects the `codex-sdk` runtime automatically. The profile is ready
when the `openai_codex` package is installed and `~/.codex/auth.json` exists.

## Codex over ACP

Use the Codex CLI as an external ACP coding agent:

```text
:connect acp codex
```

The Codex agent owns its model and tool loop. SuperQode provides the terminal,
session switching, surrounding policy controls, and normalized ACP events
available from the adapter.

## SuperQode harness with OpenAI models

Use an OpenAI API key when the SuperQode harness should own tools, memory,
workflow, approvals, and evaluation:

```text
:connect byok openai <model>
:harness core
```

Set `OPENAI_API_KEY` or use the provider setup flow:

```bash
superqode connect setup openai
superqode providers doctor openai
```

## Troubleshooting

Check the SDK package and local login:

```bash
codex --version
test -f ~/.codex/auth.json
superqode runtime doctor codex-sdk
```

For ACP, inspect the agent definition and readiness:

```bash
superqode agents show codex
superqode agents doctor codex --live
```

## Related references

- [Connection overview](../concepts/modes.md)
- [Runtime backends](../runtimes.md)
- [BYOK providers](byok.md)
- [Harness system](../advanced/harness-system.md)
