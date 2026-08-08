# Prime Agent Python client

SuperQode includes a native, async Python host for Prime Agent's public RPC
mode. It replaces the application-side TypeScript bridge: Prime Agent remains
the coding runtime, while Python owns process lifecycle, request correlation,
event streaming, cancellation, and SuperQode integration.

The client is maintained independently as
[`prime-agent-python-client`](https://github.com/SuperagenticAI/prime-agent-python-client)
and consumed by SuperQode as a normal dependency. Add it to another Python
project with:

```bash
uv add prime-agent-python-client
```

## Requirements

- Python 3.12 or 3.13
- `prime-agent` 0.7.0 or 0.7.1 on `PATH`
- Credentials required by the selected Prime Agent provider

The client never invokes a shell. A custom executable is represented as an
argument sequence, not a command string.

## Use the client directly

```python
import asyncio

from prime_agent_client import PrimeSession


async def main() -> None:
    async with PrimeSession(
        cwd="/path/to/repository",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
    ) as session:
        async for event in session.prompt_stream("Fix the failing tests"):
            if event.type == "message_update":
                update = event.get("assistantMessageEvent", {})
                if update.get("type") == "text_delta":
                    print(update.get("delta", ""), end="", flush=True)


asyncio.run(main())
```

`PrimeEvent.raw` retains the complete wire payload, including fields and event
types introduced by newer Prime Agent releases. Malformed records are surfaced
as `protocol_error` events rather than disappearing.

The high-level API also exposes `steer`, `follow_up`, `abort`, `state`,
`messages`, `stats`, `set_model`, `available_models`, `compact`, `refine`,
`switch_session`, `fork`, and `clone`. Use `PrimeRpcTransport.request()` for a
new command that has not yet received a convenience method.

## Use Prime Agent from a HarnessSpec

```yaml
name: prime-coder
inherits: coding
runtime:
  backend: prime-agent
  config:
    prime_agent:
      prompt_timeout: 900
      session_dir: .superqode/prime-agent/sessions
model_policy:
  primary: anthropic/claude-sonnet-4-20250514
```

The backend emits SuperQode `model_delta`, `thinking_delta`, `tool_call`,
`tool_update`, `tool_result`, lifecycle, usage, and error events. Every mapped
event includes `prime_event`, the original Prime RPC object.

Configuration keys under `runtime.config.prime_agent`:

| Key | Default | Purpose |
| --- | --- | --- |
| `command` | `["prime-agent"]` | Executable argv prefix; useful for wrappers and tests |
| `args` | `[]` | Additional Prime Agent launch arguments |
| `env` | `{}` | Environment additions for the child process |
| `session_dir` | `.superqode/prime-agent/sessions` | Persistent Prime session directory |
| `resume` | unset | Prime session ID or JSONL path to resume |
| `continue_session` | `false` | Continue Prime's latest session |
| `persist_session` | `true` | Set false to launch with `--no-session` |
| `request_timeout` | `30` | RPC response deadline in seconds |
| `startup_timeout` | `30` | Readiness-probe deadline in seconds |
| `prompt_timeout` | `600` | Whole-run event deadline in seconds |
| `check_version` | `true` | Detect and record compatibility before launch |

Prime Agent executes its own tools with the permissions of the SuperQode
process. The backend therefore advertises shell access but not SuperQode's
approval, sandbox, MCP, or typed-output guarantees. Extension UI requests are
cancelled by default in headless harness runs so they cannot deadlock the host;
direct clients can provide a `ui_handler` for confirmations and input.

## Compatibility policy

The package currently marks Prime Agent 0.7.0 and 0.7.1 as tested. Unknown
versions are allowed because the protocol is additive, but
`session.compatibility.tested` will be false. This makes upgrades observable
without unnecessarily preventing experimentation.
