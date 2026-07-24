# Google Antigravity

SuperQode supports Google Antigravity through four distinct routes. The routes
differ in authentication, harness ownership, event support, and configuration.
Users should select a route based on the harness behavior they need.

## July 2026 ecosystem snapshot

The public Antigravity ecosystem now has four related products:

| Product | Current public line | Important recent capabilities | SuperQode response |
| --- | --- | --- | --- |
| Antigravity CLI | `agy` 1.1.6 | Markdown custom agents, selectable subagents, reasoning effort, stable model slugs, progressive code search, MCP media results, improved print-mode reliability | Preserve workspace-scoped conversations and expose custom-agent and effort selection through the safe `agy --print` adapter |
| Antigravity 2.0 | 2.2.x | Standalone agent command center, asynchronous work, subagents, Chrome, skills/MCP, plans and visual artifacts | SuperQode already supplies multi-agent HarnessSpecs, background work orders, browser/MCP integrations, skills, plans, artifacts, and run observability |
| Antigravity SDK | `google-antigravity` 0.1.8 | Stateful local harness, typed streams, multimodal input, custom tools, MCP, hooks/policies, triggers | Normalize typed events, bridge approvals and cancellation, report exact usage, and pass project skills and MCP servers into the SDK |
| Gemini Managed Agents | preview | Hosted Antigravity sandbox through the Interactions API, persistent conversations and files, streaming steps, saved agents, environments, MCP/functions, triggers, budgets | Add the `antigravity-managed` runtime and correct the existing managed-backend request schema |

This snapshot is based on Google's
[CLI releases](https://github.com/google-antigravity/antigravity-cli/releases),
[SDK repository](https://github.com/google-antigravity/antigravity-sdk-python),
and [Managed Agents documentation](https://ai.google.dev/gemini-api/docs/agents).
Preview identifiers and supported models can change, so the managed runtime
keeps the agent ID configurable.

## Harness ownership

A harness owns the agent loop. It decides how prompts are processed, how tools
are selected and executed, how conversation state is maintained, and how safety
policies are applied.

| Route | Authentication | Harness owner | Runtime |
| --- | --- | --- | --- |
| `:connect antigravity` | Google Sign-In through `agy` | Google Antigravity | `antigravity-cli` |
| `:antigravity sdk` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Antigravity | `antigravity-sdk` |
| `:antigravity managed` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Antigravity, hosted by Google | `antigravity-managed` |
| `:antigravity superqode` | Google API key through BYOK | SuperQode | `builtin` |

The signed-in CLI, local SDK, and managed routes use the Antigravity harness.
SuperQode supplies the user interface and runtime adapter, but it does not own
the agent loop in those routes.

The Google BYOK route uses the SuperQode harness. SuperQode owns the agent loop,
tool registry, approval flow, session policy, and normalized harness events.

## Google Sign-In route

Install Antigravity CLI and complete sign-in once:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
agy
```

Then connect from SuperQode:

```text
:connect antigravity
```

For a headless invocation:

```bash
superqode --connect antigravity --print "Summarize this repository"
```

The `agy` process owns OAuth authentication and retrieves its session from the
operating system keyring. SuperQode does not read, copy, refresh, or persist the
OAuth token.

SuperQode requires Antigravity CLI 1.1.1 or newer. Version 1.1.1 corrected
subprocess hangs and error exit behavior in print mode.

Current CLI controls are available without leaving SuperQode:

```text
:agy help
:agy status
:agy agents
:agy models
:agy changelog
:agy plugin list
:agy plugin import gemini
:agy update
:antigravity agent reviewer
:antigravity model gemini-model-slug
:antigravity effort high
:antigravity agent auto
:antigravity model auto
:antigravity effort auto
```

The `:agy` namespace mirrors the major non-interactive commands in `agy` 1.1.6:
`agents`, `models`, `changelog`, `install`, `update`, and plugin
`list/import/install/uninstall/enable/disable/validate/link`. These commands
run as explicit argument vectors rather than shell text. Commands that consult
the signed-in CLI account run only after the user explicitly enters them;
`:agy help`, completion, and `:agy status` do not query the account.

Use `:agy launch [flags]`, `:agy continue`, or
`:agy resume <conversation-id>` to generate a copyable command for a separate
terminal. Full-screen agy panels such as `/resume`, `/agents`, `/config`,
`/permissions`, `/mcp`, and `/skills` cannot be nested reliably inside
SuperQode's Textual TUI.

The selected custom agent is passed through `agy --agent`, and the selected
model is passed through `agy --model`. Effort is passed through `agy --effort`
and requires CLI 1.1.5 or newer. CLI 1.1.6 accepts `low`, `medium`, or `high`.
The adapter also accepts `SUPERQODE_ANTIGRAVITY_CLI_AGENT` and
`SUPERQODE_ANTIGRAVITY_CLI_EFFORT` for headless runs. Custom-agent discovery,
YAML frontmatter, nested subagents, and command policy remain owned by `agy`;
SuperQode does not copy or reinterpret those definitions.

The CLI provides text output but does not provide a documented structured event
stream. SuperQode cannot display normalized tool calls, tool results, plans, or
interactive approval cards for this route. Configure tool permissions and the
sandbox through Antigravity CLI.

### Workspace and conversation isolation

SuperQode passes the Antigravity project ID that explicitly contains the active
working directory. If the workspace has no Antigravity project mapping, the
runtime asks `agy` to create one for that session.

After the first turn, SuperQode captures the conversation ID mapped to the exact
resolved working directory. Later turns resume that conversation with
`--conversation <id>`. The adapter does not use `agy --continue` because that
option selects global recent state and can resume a conversation from another
repository.

This isolation prevents project context, tool paths, and conversation history
from leaking between repositories. Starting a new SuperQode Antigravity runtime
starts a new conversation in the selected workspace.

## Antigravity SDK route

Install the optional SDK runtime:

```bash
uv tool install "superqode[antigravity-sdk]"
export GEMINI_API_KEY="your-key"
```

Select it in the TUI:

```text
:antigravity sdk
```

The SDK starts Google's bundled `localharness` process. The Antigravity
`Agent`, `Conversation`, and `Connection` components manage orchestration,
conversation history, context compaction, tool dispatch, hooks, and execution
steps. This is an Antigravity harness route.

The SDK is useful when an API key is preferred and the application needs direct
access to the Antigravity agent API. It does not reuse the Google Sign-In token
from `agy`.

SuperQode tracks the current `google-antigravity` 0.1.x SDK line. The SDK
supports multimodal inputs, custom Python tools, MCP servers, hooks and
policies, triggers, typed thought/tool streams, and stateful conversations.
The SuperQode adapter now provides:

- typed text, thought, tool-call, and tool-result events
- exact prompt, response, thought, cached, and total token usage
- backend cancellation through `ChatResponse.cancel()`
- SDK thinking levels through `:antigravity effort <level>`
- model selection through `:antigravity model <model>`
- native SDK capability restriction for model-only and no-tool runs
- stateful SDK conversation IDs in runtime metadata
- automatic skills from `.agents/skills` and `.superqode/skills`
- additional skill roots from `SUPERQODE_ANTIGRAVITY_SKILLS`
- stdio and Streamable HTTP MCP servers from `.superqode/mcp.json` when
  `SUPERQODE_MCP_SEARCH=1`
- workspace-scoped file policy plus SuperQode approval prompts for mutating,
  shell, subagent, and MCP tool calls

Read-only SDK tools are allowed automatically. All other SDK tools use
SuperQode's current approval mode. In non-interactive use without an approval
callback, those tool calls are denied. Legacy SSE MCP transport is not
supported by the SDK; configure stdio or Streamable HTTP instead.

The 0.1.8 wheel contains protobuf 7.35-generated descriptors but publishes a
looser runtime dependency. SuperQode pins protobuf 7.35 or newer for this extra.
Some optional SuperQode extras that currently require protobuf below 7 cannot
be installed in the same environment; uv reports those combinations as
explicit conflicts rather than producing a broken SDK import.

## Google-hosted managed agent route

Google now exposes the Antigravity harness through the Gemini Interactions API.
This is separate from the local SDK: execution happens in a Google-hosted Linux
sandbox rather than the current machine.

```bash
export GEMINI_API_KEY="your-key"
export SUPERQODE_ANTIGRAVITY_MAX_TOTAL_TOKENS=50000  # recommended budget
superqode
```

Then select:

```text
:antigravity managed
```

The runtime uses the preview agent `antigravity-preview-05-2026` by default,
streams typed Interactions API events into SuperQode, and preserves both state
dimensions across turns:

- conversation context through `previous_interaction_id`
- hosted filesystem state through `environment_id`

The managed agent includes hosted code execution, filesystem tools, Google
Search, and URL context. Google's API also supports remote streamable-HTTP MCP
servers, custom functions, environment sources, network allowlists, saved
agents, triggers, background execution, and environment snapshot downloads.

Important boundaries:

- SuperQode never reads the `agy` keyring or Google Sign-In state for this route.
- The current local repository is **not uploaded automatically**. The managed
  sandbox begins as a fresh remote environment. This prevents accidental source
  or secret disclosure.
- `GEMINI_API_KEY` is sent only to the Gemini API in the request header and is
  never included in events or logs.
- The TUI labels this route `MANAGED · HOSTED`: Google owns the remote tool
  execution and its approval behavior, so SuperQode's local `ASK` mode does not
  govern those hosted tools.
- Identity questions are answered from the runtime contract. The managed agent
  should not inspect environment variables or processes merely to determine
  which harness invoked it.
- Managed Agents is a preview API and its schema may change.
- Agentic runs can consume substantial tokens. Set
  `SUPERQODE_ANTIGRAVITY_MAX_TOTAL_TOKENS` before use.

Optional runtime settings:

| Variable | Purpose |
| --- | --- |
| `SUPERQODE_ANTIGRAVITY_AGENT` | Override the managed agent ID |
| `SUPERQODE_ANTIGRAVITY_MODEL` | Set the underlying supported Gemini model |
| `SUPERQODE_ANTIGRAVITY_MAX_TOTAL_TOKENS` | Cap total input, output, and thinking tokens per interaction |

## SuperQode harness with Google models

Select the Google BYOK route:

```text
:antigravity superqode
```

The command opens the Google provider and model flow. It is equivalent to:

```text
:connect byok google
```

In this route, SuperQode owns the harness. Users receive the SuperQode tool
contract, approval handling, HarnessSpec support, normalized events, and session
behavior. Authentication uses `GOOGLE_API_KEY` or `GEMINI_API_KEY`, according to
the selected Google provider configuration.

## SDK and Harness Boundary

The Antigravity SDK is an agent harness SDK rather than a model-only completion
client. Its public API creates an Antigravity `Agent` and connects it to the
bundled local harness. It does not expose a supported model transport intended
for use beneath an independent agent loop.

Placing the Antigravity SDK inside the SuperQode agent loop would create nested
harnesses. Tool policy, conversation state, retries, and approvals would have
two owners. SuperQode does not present this arrangement as a supported mode.

Use the Google BYOK provider when the SuperQode harness is required. Use the
Antigravity CLI, local SDK, or managed route when the Antigravity harness is
required.

## Status and diagnostics

```text
:antigravity status
:runtime list
:connect
```

The Antigravity status command reports the installed CLI path, version, settings
location, and authentication ownership. Run `agy` directly if Google Sign-In
must be renewed.
