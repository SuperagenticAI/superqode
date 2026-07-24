# xAI Grok

SuperQode supports Grok through three distinct routes. Grok Build is xAI's
coding-agent harness. The subscription and BYOK model routes can instead run a
SuperQode-owned harness.

## Connection routes

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Grok Build | `:connect grok` | `grok login` | xAI Grok Build |
| Grok subscription model route | `:grok api [model]` | Local Grok CLI session | SuperQode |
| xAI BYOK | `:connect byok xai <model>` | `XAI_API_KEY` | SuperQode |

These routes use the same vendor account family but provide different agent
behavior. Select the route based on the harness required for the task.

## Grok Build

Install the official Grok CLI and complete its login:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
grok login
```

For a headless host, use the device authentication flow:

```bash
grok login --device-auth
```

Connect Grok Build in the TUI:

```text
:connect grok
```

SuperQode starts `grok agent stdio` over ACP. Grok Build owns the model,
context, tools, and inner agent loop. SuperQode provides the terminal,
session-switching surface, surrounding policy controls, and ACP events exposed
by the agent.

Inspect the ACP route:

```bash
superqode agents show grok
superqode agents doctor grok --live
```

## SuperQode harness on a Grok subscription

Use the authenticated Grok CLI session while keeping the SuperQode harness:

```text
:grok status
:grok models
:grok model <model>
:grok api [model]
:harness core
```

The `:grok api` command imports the CLI session into SuperQode's local auth
store and selects the `grok-cli` provider. The active SuperQode HarnessSpec
owns tools, context, memory, approvals, workflow, evidence, and evaluation.

The installed CLI's model catalog is authoritative:

```text
:grok models
```

## SuperQode harness with an xAI API key

Set an xAI API key and connect through BYOK:

```bash
export XAI_API_KEY="your-key"
superqode providers doctor xai
```

```text
:connect byok xai <model>
:harness core
```

This route does not use the local Grok CLI login.

## Harness selection

SuperQode does not currently ship a `grok-coding` preset. Use `core`,
`workbench`, or a repository-owned HarnessSpec with `:grok api` or the xAI
BYOK route.

Do not describe Grok Build as a SuperQode preset. It is an external xAI harness
connected through ACP.

## Troubleshooting

Check the CLI and login:

```bash
grok --version
test -f ~/.grok/auth.json
```

Then inspect the SuperQode route:

```text
:grok status
:log verbose
```

If Grok Build is unavailable, run `grok login` again and verify that
`grok agent stdio` is supported by the installed CLI.

## Related references

- [Connection overview](../concepts/modes.md)
- [ACP agents](acp.md)
- [BYOK providers](byok.md)
- [Harness system](../advanced/harness-system.md)
