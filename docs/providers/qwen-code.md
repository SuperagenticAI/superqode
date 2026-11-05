# Qwen Code

Qwen Code is QwenLM's first-party coding agent. SuperQode connects to its
stable ACP server, so Qwen Code keeps its own agent behavior while SuperQode
provides the terminal, session, harness-switching, and normalized event
surface.

## Install And Authenticate

```bash
npm install -g @qwen-code/qwen-code
qwen
# Inside Qwen Code, enter /auth to configure your provider or plan.
```

Verify that SuperQode can discover it:

```bash
superqode agents show qwen
superqode agents doctor qwen
```

## Connect From The TUI

Use the direct product connection:

```text
:connect qwen-code
```

Qwen Code also appears in the unified Harness Switcher:

```text
:harness
:harness switch qwen-code
:harness switch qwen-code --fork
```

Use `--fork` when you want Qwen Code to start an independent branch instead of
continuing the current harness transition history.

## Choose The Qwen Route

Qwen is available through several distinct paths:

| Goal | Route |
| --- | --- |
| Use the complete first-party Qwen Code agent | `:connect qwen-code` |
| Use an Alibaba-hosted Qwen model inside the SuperQode native harness | `:connect byok alibaba <model>` |
| Use a local Qwen model inside the SuperQode native harness | `:connect local ollama <qwen-model>` |
| Start a repository-owned Qwen coding HarnessSpec | `superqode harness init qwen-coder --template qwen-coding --output harness.yaml` |

A coding-agent connection and a model connection are not interchangeable.
Choose Qwen Code when you want its complete agent loop. Choose BYOK or local
when you want SuperQode's native harness to own tools, approvals, context, and
workflow around a Qwen model.

## Related Documentation

- [Connection Methods and Vendors](../concepts/modes.md)
- [Agent Runtimes](../runtimes.md)
- [ACP Agents](acp.md)
- [Local Providers](local.md)
- [Bring Your Own Harness](../getting-started/bring-your-own-harness.md)
