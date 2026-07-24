# Google Antigravity

SuperQode supports Google Antigravity through three distinct routes. The routes
differ in authentication, harness ownership, event support, and configuration.
Users should select a route based on the harness behavior they need.

## Harness ownership

A harness owns the agent loop. It decides how prompts are processed, how tools
are selected and executed, how conversation state is maintained, and how safety
policies are applied.

| Route | Authentication | Harness owner | Runtime |
| --- | --- | --- | --- |
| `:connect antigravity` | Google Sign-In through `agy` | Google Antigravity | `antigravity-cli` |
| `:antigravity sdk` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Antigravity | `antigravity-sdk` |
| `:antigravity superqode` | Google API key through BYOK | SuperQode | `builtin` |

The signed-in CLI route and the SDK route both use the Antigravity harness.
SuperQode supplies the user interface and runtime adapter, but it does not own
the agent loop in either route.

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
Antigravity CLI or SDK when the Antigravity harness is required.

## Status and diagnostics

```text
:antigravity status
:runtime list
:connect
```

The Antigravity status command reports the installed CLI path, version, settings
location, and authentication ownership. Run `agy` directly if Google Sign-In
must be renewed.
