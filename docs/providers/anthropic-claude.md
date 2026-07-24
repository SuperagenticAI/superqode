# Anthropic Claude

SuperQode connects to Claude through the Claude Agent SDK, Claude Code over
ACP, or the Anthropic BYOK provider. Select the route based on which harness
should own the agent loop.

## Connection routes

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Claude Agent SDK | `:connect claude` | `ANTHROPIC_API_KEY` | Claude Agent SDK |
| Claude Code ACP | `:connect acp claude` | Local Claude Code login | Claude Code |
| Anthropic BYOK | `:connect byok anthropic <model>` | `ANTHROPIC_API_KEY` | SuperQode |

## Claude Agent SDK route

Install the optional runtime and set the Anthropic API key:

```bash
uv tool install "superqode[claude-agent-sdk]"
export ANTHROPIC_API_KEY="your-key"
```

Connect in the TUI:

```text
:connect claude
```

Run a headless task:

```bash
superqode --connect claude --print "review the current changes"
```

SuperQode selects the `claude-agent-sdk` runtime automatically. The SDK owns
the inner agent loop. SuperQode supplies the terminal, HarnessSpec context,
policy, evidence, evaluation, WorkOrder, and session controls supported by the
runtime adapter.

## Claude Code over ACP

Use a locally authenticated Claude Code installation as an external ACP agent:

```text
:connect acp claude
```

This route preserves the Claude Code harness, tools, commands, and model access.
It does not require SuperQode to handle the Claude Code authentication token.

## SuperQode harness with Anthropic models

Use the Anthropic BYOK route when SuperQode should own the harness:

```text
:connect byok anthropic <model>
:harness core
```

The active HarnessSpec controls tools, memory, approvals, sandbox policy,
workflow, evidence, and evaluation.

## Troubleshooting

Check the SDK and API key:

```bash
superqode runtime doctor claude-agent-sdk
superqode providers doctor anthropic
```

Check the ACP agent:

```bash
superqode agents show claude
superqode agents doctor claude --live
```

## Related references

- [Connection overview](../concepts/modes.md)
- [ACP agents](acp.md)
- [BYOK providers](byok.md)
- [Harness system](../advanced/harness-system.md)
