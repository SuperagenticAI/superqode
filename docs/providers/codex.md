# OpenAI Codex

SuperQode connects to Codex through the installed Codex CLI, the optional Codex SDK,
Codex over ACP, or the OpenAI BYOK provider. The routes differ in authentication and
harness ownership.

## Connection routes

For the audited command mapping and supported controls, see
[Codex command coverage](codex-commands.md). Enter `:codex help` in the TUI for
the shared command list.

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

Selecting Codex CLI or Codex SDK bypasses the active SuperQode harness selection
without changing the saved choice. Returning to `:runtime builtin` restores it.
A repository's `harness.yaml` or saved default does not wrap or override this
connection. The Harness sidebar shows Codex as the owner. Keep the YAML file in
place; use `:harness <path>` to explicitly select it again. Headless Codex routes
also ignore project defaults; passing `--harness <path>` explicitly opts into
that harness instead.

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
reported, installed schema capabilities, human approval reviewer, run state,
context-window usage, and measured startup/RPC/first-text/turn timings. Model and service
latency still apply; using native stdio is not a guarantee of faster inference.
Failed or timed-out turns are never replayed automatically.

Native thread IDs and their connection settings are saved in the project's
session index. `:sessions` lists these sessions and `:resume <id>` reconnects
to the same Codex thread without requiring an OpenAI API key. Reconnecting the
CLI route selects the most recent unarchived native session for that project,
Codex home and billing route. Use `:codex new` for a fresh thread. Codex verifies
the saved thread on the next request; an unavailable thread produces an error
instead of silently starting another. Codex retains the full tool history;
SuperQode stores the user/assistant text observed through this connection.

Codex owns execution policy. SuperQode checks the command and file approval
requests Codex sends, including every reported file path, but does not receive
an approval request for every tool call. `:codex status` shows the policy owner,
approval policy and sandbox reported by Codex. Project or organization deny,
approval, network or credential restrictions that require host interception
block native execution before a task starts. Use a SuperQode-governed runtime
for those restrictions, or configure enforcement with Codex managed requirements.
Codex settings such as `never` or full access do not turn approval forwarding
into host policy enforcement.

Turn usage includes the reported cumulative changes across model/tool iterations.
Missing token counts and costs remain unknown; subscription usage is not converted
into an estimated API charge.

Approval requests offer the decisions advertised by Codex, including cancel
and session consent. Session consent binds the exact action, arguments and
policy revision; it does not become a blanket tool permission. Persistent
Codex rule amendments require a second explicit confirmation. SuperQode pins
the human reviewer on threads, turns and configured apps; it refuses a thread
that reports a different reviewer. Status distinguishes the requested reviewer
from a reviewer confirmed by a thread response. Session consent ignores RPC ids
and timestamps while retaining the command, destination, paths and permissions.

MCP elicitation supports validated JSON forms and manually completed URL flows.
Use `:codex mcp login <server>` for Codex-owned MCP OAuth. Codex stores the login;
SuperQode displays the authorization URL. Additional permission requests require
explicit consent for that turn. Unknown server requests return an explicit error.
SDK handler failures cancel the individual request without terminating the reader.

The installed executable's generated schema gates experimental features at
connect time. An unavailable schema disables experimental controls. A supported
schema still does not guarantee that a feature is enabled by Codex configuration
or managed requirements. Read-only sandboxing permits Codex read tools, so this
backend does not claim support for a strict no-tool spec.

## Native tools and controls

```text
:codex tools
:codex history
:codex permissions untrusted
:codex permissions mediated
:codex turn-options {"summary":"concise","outputSchema":{"type":"object"}}
:codex permissions profile <id>
:codex permissions granular {"sandbox_approval":true,"rules":false,"mcp_elicitations":true}
:codex mcp login <server>
:codex review --detached --base main
```

Codex can call SuperQode project memory, read WorkOrders and access SuperQode
MCP tools through dynamic tools. These calls use SuperQode's existing executor,
permission checks, extension hooks and invocation receipts. Writes are blocked
in Plan/read-only turns. Named Codex profiles conservatively limit host tools
to reads because their filesystem permissions do not describe host memory or
MCP services. Git and WorkOrder delivery remain owned by SuperQode.

Existing threads restore their persisted dynamic tool definitions. Start a
fresh thread with `:codex new` to advertise tools added after that thread was
created. `:codex history` pages earlier messages and tool calls when implemented
by the server. Codex 0.160 advertises paging but returns "not supported yet";
SuperQode falls back to `thread/read`, without pagination. Explicit resume also
displays recent stored turns. Detached review forks saved conversations into a
separate read-only thread. For a fresh, unsaved conversation it starts a separate
read-only thread instead, and preserves the original conversation's unsaved state.

The `mediated` preset selects `on-request`, `workspace-write` and the human
reviewer. It does not expose native actions that Codex executes without approval.
`:codex turn-options <JSON>` sets `outputSchema`, `summary`, `serviceTier` and/or
`clientUserMessageId` on the next ordinary turn; fields must be supported by the
installed schema. Use `:codex turn-options reset` to clear pending options.
Codex may retain summary and service-tier choices for subsequent turns.
Native `sessionId`, `forkedFromId` and account rate-limit pools are retained and
shown in status when reported.

Use `$skill-name` to invoke an enabled skill returned by `:codex skills`.
Use `$app-slug` or `@app-slug` for an accessible, enabled app from `:codex apps`.
SuperQode resolves the catalog entry and sends Codex a typed skill/app input.
Unknown names remain ordinary text; ambiguous names produce an error.
Catalog results are cached for up to 60 seconds. Lookup failures leave the
original text intact; `:codex skills --reload` or `:codex apps --reload` clears
the mention cache after a successful refresh.

## User-owned local app-server

Start a local listener yourself using the same executable selected by SuperQode:

```bash
codex app-server --listen ws://127.0.0.1:4500
```

Then attach from the native CLI connection:

```text
:codex attach ws://127.0.0.1:4500
:codex attach stdio
```

`SUPERQODE_CODEX_SERVER` selects the listener at initial connection. Only literal
loopback addresses are accepted, and the listener version must match the schema
generated by the installed CLI. SuperQode closes its connection on detach and
leaves the user-owned listener running. It does not provide daemon startup,
remote pairing or a hosted subscription proxy. A lost connection never replays
a turn; inspect the saved thread before continuing.

Unattended native goals need a separate continuation lifecycle. SuperQode-owned
processes disable that feature, and shared listener attachment refuses to resume
a thread reporting an active goal. Pause the goal in Codex before attaching it.

Subscription connections are for a local user-run client and that user's Codex
login. For API billing with the native harness, use `:runtime codex-cli` and
configure API authentication in Codex yourself. SuperQode does not collect keys
or transform subscription login into an API credential service.

## Optional SDK route

Choose **Codex SDK** in Subscriptions, or run `:connect codex-sdk` directly.
The native CLI route is the primary integration. The SDK route retains legacy
session controls and shares approval, user-input, MCP elicitation and policy
preflight handling with it; newer native controls require the CLI route.
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
