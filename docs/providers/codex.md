# OpenAI Codex

SuperQode connects to Codex through the installed Codex CLI, the optional Codex SDK,
Codex over ACP, or the OpenAI BYOK provider. The routes differ in authentication and
harness ownership.

## Connection routes

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Codex CLI | `:connect codex` | ChatGPT login through `codex login` | Installed Codex harness |
| Codex SDK | `:connect codex-sdk` | ChatGPT login through Codex | Codex runtime |
| Codex ACP | `:connect acp codex` | Local Codex CLI login | Codex CLI agent |
| OpenAI BYOK | `:connect byok openai <model>` | `OPENAI_API_KEY` | SuperQode |

The CLI, SDK and ACP routes use Codex as the executing coding agent. The BYOK
route uses the SuperQode harness and calls an OpenAI model directly.

## Installed CLI route

Install Codex CLI if needed and sign in with your ChatGPT account:

```bash
npm install -g @openai/codex
codex login
```

In the TUI, choose `:connect` → **Connect to an existing harness** →
**Subscriptions** → **Codex CLI** or **Codex SDK**. The CLI route connects
directly to your installed executable; the SDK route requires the optional
Python package. Both subscription choices verify your ChatGPT login.

Connect to the CLI directly:

```text
:connect codex
:codex status --probe
```

Run a headless task:

```bash
superqode --connect codex --print "review the current repository"
```

`:connect codex` and `:codex` select `codex-cli`. No Python SDK extra is needed.
SuperQode launches the selected CLI's `app-server --listen stdio://` and keeps
one asynchronous connection and Codex thread for the connected TUI session.
Codex owns the model loop, built-in tools, sandbox, skills, MCP configuration,
and credential storage. The app-server is the supported integration boundary
for displaying that harness in a custom client.

The profile is ready when the executable is present. Actual ChatGPT login is
verified before thread creation and before each prompt. API-key authentication,
a signed-out account, or a different resolved model provider stops the request;
there is no automatic API billing fallback. Codex handles keyring storage and
custom `CODEX_HOME`. SuperQode does not read or copy the login tokens.

Set `SUPERQODE_CODEX_BIN` to use a specific executable. An invalid explicit path
reports an error. `:runtime codex-cli` uses agent-managed authentication and its
billing follows the user's Codex configuration; use `:connect codex` for the
guarded ChatGPT subscription route.

The TUI displays model text, public reasoning summaries, command output, file
changes, plans, MCP and collaborator tool activity, token usage, and reported
rate limits. Command/file approvals and user questions use SuperQode prompts.
Model, effort, account, and session commands perform RPCs asynchronously.
Cancellation interrupts the active turn; steering sends `turn/steer`.
`:codex review` uses Codex's native `review/start` operation.

Useful commands:

```text
:codex models
:codex model
:codex effort
:codex sessions
:codex resume <id>
:codex fork <id>
:codex compact
:codex account
:codex review
:codex status
```

Status reports the executable, thread, account verification, rate limits when
reported, and measured startup/RPC/first-text/turn timings. Model and service
latency still apply; using native stdio is not a guarantee of faster inference.
Failed or timed-out turns are never replayed automatically.

Some Codex UI features need additional client integration. MCP elicitation
forms and URL flows currently cancel with a visible message; additional
permission-profile requests decline. Unknown server requests return an explicit
error. Read-only sandboxing still permits Codex read tools. The harness backend
therefore does not claim support for a strict no-tool spec. Use a current Codex
CLI; incompatible protocol errors require updating or selecting a compatible
executable.

## Optional SDK route

Choose **Codex SDK** in Subscriptions, or run `:connect codex-sdk` directly.
Install its optional package first:

```bash
uv tool install "superqode[codex-sdk]"
superqode --connect codex-sdk --print "review the current repository"
```

`:connect codex-sdk` uses guarded ChatGPT subscription authentication.
`:runtime codex-sdk` uses agent-managed authentication. Programmatic helpers in
`superqode.codex` continue to wrap this SDK route.

The runtime already drives the official Codex app-server lifecycle through the
Python SDK. For applications that supply their own experimental app-server
`dynamicTools`, SuperQode also provides `CodexDynamicToolsAdapter`:

```python
from superqode.jev_tools import CodexDynamicToolsAdapter, JevToolRouting

adapter = CodexDynamicToolsAdapter(JevToolRouting())
params, decision = await adapter.thread_start_params(
    task,
    dynamic_tools,
    base={"cwd": project_dir},
)
```

Pass `adapter.initialize_capabilities()` as the app-server initialize
capabilities and use `params` for `thread/start`. This routes client-owned
dynamic tools only. Codex app-server does not expose a supported client hook to
replace the built-in tool catalogue, so SuperQode does not claim savings for
those hidden built-ins.

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

Check the CLI and local login:

```bash
codex --version
codex login status
superqode runtime doctor codex-cli
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
